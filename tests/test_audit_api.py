"""
Audit fixes, HTTP layer (backend/app.py, auth.py, security.py). Written
before the fixes; each test names the audit finding it pins.
"""
import os
import subprocess
import sys
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ.setdefault("DXMAP_DB_PATH", _TMP.name)
os.environ["DXMAP_SERVICE_TOKEN"] = "test-service-token"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402
import db  # noqa: E402
import lawref  # noqa: E402
import security  # noqa: E402

db.init_db()
app_module.SERVICE_TOKEN = "test-service-token"

CF_EDGE = "162.158.1.10"
_ip = [0]


def visitor():
    _ip[0] += 1
    return {"X-Forwarded-For": CF_EDGE, "CF-Connecting-IP": f"203.0.113.{_ip[0] % 250 + 1}"}


def new_client():
    return TestClient(app_module.app)


@pytest.fixture(autouse=True)
def _fresh():
    security.limiter.reset()
    if hasattr(security, "reset_login_locks"):
        security.reset_login_locks()
    yield


def make_user(role, tag):
    email = f"{role.lower()}-{tag}@example.org"
    if not db.get_user_by_email(email):
        db.create_user(email, "correct-horse-battery", role)
    return email


def login(client, email, password="correct-horse-battery"):
    return client.post("/api/auth/login", json={"email": email, "password": password}, headers=visitor())


def logged_in(role, tag):
    c = new_client()
    assert login(c, make_user(role, tag)).status_code == 200
    return c


def verified_report(category, lat=52.5200, lon=13.4050, **kw):
    base = dict(source="user", external_id=f"t-{os.urandom(4).hex()}", title="Title", body="b",
                category=category, reason="r", evidence="", law=None, impact="", lat=lat, lon=lon,
                place="x", status="verified")
    base.update(kw)
    rid = db.insert_report(**base)
    assert rid is not None
    return rid


def coords_for(client, rid):
    rows = client.get("/api/reports?limit=5000", headers=visitor()).json()["reports"]
    row = next(r for r in rows if r["id"] == rid)
    return row["lat"], row["lon"]


# ---- AUDIT-01: a self-made account must not unlock exact coordinates --------

def test_signed_in_none_account_still_gets_blurred_sensitive_reports():
    rid = verified_report("harassment")
    anon, none_user, reviewer = new_client(), logged_in("NONE", "a1"), logged_in("VERIFIER", "a1")
    exact = (52.52, 13.405)
    assert coords_for(anon, rid) != exact
    assert coords_for(none_user, rid) != exact
    assert coords_for(reviewer, rid) == exact


# ---- AUDIT-03: sensitive means ANY category token, whatever its spelling ----

@pytest.mark.parametrize("category", [
    "harassment,racism", "racism,sexual_violence", "Harassment", " harassment ", "HARASSMENT|racism",
    "homophobia_transphobia",
])
def test_every_sensitive_spelling_is_blurred(category):
    rid = verified_report(category)
    assert coords_for(new_client(), rid) != (52.52, 13.405)


def test_non_sensitive_verified_report_keeps_its_exact_location():
    rid = verified_report("banned_symbols")
    assert coords_for(new_client(), rid) == (52.52, 13.405)


def test_report_with_an_unknown_category_is_rejected():
    body = {"title": "Graffiti", "reason": "Swastika", "category": "not_a_category", "lat": 52.5, "lon": 13.4}
    assert new_client().post("/api/reports", json=body, headers=visitor()).status_code == 422


def test_report_with_known_categories_is_accepted():
    known = [c for c in lawref.CATEGORIES][:2]
    body = {"title": "Graffiti", "reason": "Swastika", "category": ",".join(known), "lat": 52.5, "lon": 13.4}
    assert new_client().post("/api/reports", json=body, headers=visitor()).status_code == 201


# ---- AUDIT-04: the stored id must not be a request timestamp ----------------

def test_user_reports_get_a_random_external_id():
    import re
    body = {"title": "Graffiti", "reason": "Swastika", "category": "banned_symbols", "lat": 52.5, "lon": 13.4}
    rid = new_client().post("/api/reports", json=body, headers=visitor()).json()["id"]
    ext = db.get_report(rid)["external_id"]
    assert not re.fullmatch(r"user_\d+", ext or "")
    assert len(ext) >= 16


# ---- AUDIT-05: reviewers must not learn who the other volunteers are --------

def test_verifier_cannot_read_moderator_emails_in_history():
    rid = verified_report("banned_symbols")
    db.set_status(rid, "dismissed", edited_by="boss@example.org")
    verifier, admin = logged_in("VERIFIER", "a5"), logged_in("ADMIN", "a5")
    seen = str(verifier.get(f"/api/admin/reports/{rid}/history").json())
    assert "boss@example.org" not in seen and "@" not in seen
    assert "boss@example.org" in str(admin.get(f"/api/admin/reports/{rid}/history").json())


def test_masked_moderator_ids_are_stable_and_opaque():
    assert security.mask_moderator("boss@example.org") == security.mask_moderator("boss@example.org")
    assert security.mask_moderator("boss@example.org") != security.mask_moderator("other@example.org")
    assert "@" not in security.mask_moderator("boss@example.org")
    assert security.mask_moderator("pantheon:vol_" + "a" * 32) == "pantheon:vol_" + "a" * 32


def test_only_admins_can_list_volunteer_applications():
    assert logged_in("VERIFIER", "a5b").get("/api/admin/applications").status_code == 403
    assert logged_in("ADMIN", "a5b").get("/api/admin/applications").status_code == 200


# ---- AUDIT-06: per-account lockout with backoff, no account enumeration -----

def test_five_wrong_passwords_lock_the_account_even_for_the_right_one():
    email = make_user("ADMIN", "a6")
    c = new_client()
    for _ in range(5):
        assert login(c, email, "wrong-password-1").status_code == 401
    assert login(c, email).status_code == 429


def test_unknown_addresses_lock_exactly_the_same_way():
    c = new_client()
    for _ in range(5):
        assert login(c, "ghost-a6@example.org", "wrong-password-1").status_code == 401
    assert login(c, "ghost-a6@example.org").status_code == 429


def test_a_good_login_clears_the_failures():
    email = make_user("VERIFIER", "a6b")
    c = new_client()
    for _ in range(4):
        login(c, email, "wrong-password-1")
    assert login(c, email).status_code == 200
    for _ in range(4):
        assert login(c, email, "wrong-password-1").status_code == 401


def test_unknown_email_still_pays_for_a_password_hash(monkeypatch):
    calls = []
    real = db.verify_password
    monkeypatch.setattr(db, "verify_password", lambda p, s: calls.append(1) or real(p, s))
    new_client().post("/api/auth/login", json={"email": "nobody-a6@example.org", "password": "whatever-1"}, headers=visitor())
    assert calls, "timing would reveal which emails have accounts"


# ---- AUDIT-07: cross-site writes ------------------------------------------

def test_write_from_a_foreign_origin_is_refused():
    admin = logged_in("ADMIN", "a7")
    r = admin.post("/api/auth/logout", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_write_from_the_same_origin_or_a_server_is_allowed():
    admin = logged_in("ADMIN", "a7b")
    assert admin.post("/api/auth/logout", headers={"Origin": "http://testserver"}).status_code == 200
    admin = logged_in("ADMIN", "a7c")
    assert admin.post("/api/auth/logout").status_code == 200  # no Origin: server-to-server


def test_cors_is_not_a_wildcard():
    r = new_client().options("/api/admin/users", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "DELETE"})
    assert r.headers.get("access-control-allow-origin") != "*"
    assert "evil.example" not in r.headers.get("access-control-allow-origin", "")


# ---- AUDIT-08: secure by default -------------------------------------------

def test_cookies_are_secure_unless_dev_is_asked_for_explicitly():
    env = {k: v for k, v in os.environ.items() if k != "DXMAP_ENV"}
    code = "import sys; sys.path.insert(0, 'backend'); import auth; print(auth.SECURE_COOKIE)"
    out = subprocess.run([sys.executable, "-c", code], cwd=os.path.join(os.path.dirname(__file__), ".."),
                         env=env, capture_output=True, text=True).stdout.strip()
    assert out == "True"


# ---- AUDIT-09: the public feed is not free to scrape ----------------------

def test_public_feed_is_rate_limited_per_visitor():
    c, v = new_client(), visitor()
    codes = [c.get("/api/reports?limit=10", headers=v).status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429
    assert c.get("/api/reports?limit=10", headers=visitor()).status_code == 200


def test_public_feed_limit_is_capped():
    assert len(new_client().get("/api/reports?limit=999999", headers=visitor()).json()["reports"]) <= 5000


# ---- AUDIT-10: the edit token belongs in a header, not a logged URL --------

def _filed():
    body = {"title": "Graffiti", "reason": "Swastika", "category": "banned_symbols", "lat": 52.5, "lon": 13.4}
    r = new_client().post("/api/reports", json=body, headers=visitor()).json()
    return r["id"], r["edit_token"]


def test_edit_token_works_in_a_header():
    rid, tok = _filed()
    assert new_client().get(f"/api/reports/{rid}", headers={"X-Edit-Token": tok}).status_code == 200


def test_edit_token_still_works_in_the_query_for_old_links():
    rid, tok = _filed()
    assert new_client().get(f"/api/reports/{rid}?edit_token={tok}").status_code == 200


@pytest.mark.parametrize("bad", ["", "wrong", "ünïcödé-tøken"])
def test_wrong_or_empty_edit_token_is_403_never_500(bad):
    rid, _ = _filed()
    assert new_client().get(f"/api/reports/{rid}", headers={"X-Edit-Token": "x"}).status_code == 403
    assert new_client().get(f"/api/reports/{rid}?edit_token={bad}").status_code in (403, 422)


# ---- AUDIT-11: service API and request size --------------------------------

def test_service_token_with_non_ascii_text_is_401_not_500():
    r = new_client().get("/api/service/stats", headers={"X-Service-Token": "tøken-ünïcode".encode("latin-1", "ignore").decode("latin-1")})
    assert r.status_code == 401


def test_guessing_the_service_token_is_throttled():
    c, v = new_client(), visitor()
    codes = [c.get("/api/service/stats", headers={**v, "X-Service-Token": f"guess-{i}"}).status_code for i in range(12)]
    assert codes[-1] == 429


def test_oversized_request_bodies_are_refused():
    big = {"title": "Graffiti", "reason": "Swastika", "category": "banned_symbols", "lat": 52.5, "lon": 13.4,
           "junk": "x" * 20_000}
    assert new_client().post("/api/reports", json=big, headers=visitor()).status_code == 413


# ---- AUDIT-12: the geocode relay -------------------------------------------

def test_geocode_query_length_is_capped():
    assert new_client().get("/api/geocode?q=" + "a" * 121, headers=visitor()).status_code == 422


def test_geocode_is_rate_limited_per_visitor(monkeypatch):
    app_module._GEOCODE_CACHE["berlin"] = (10**12, [])  # cached: no network in tests
    c, v = new_client(), visitor()
    codes = [c.get("/api/geocode?q=berlin", headers=v).status_code for _ in range(31)]
    assert codes[30] == 429


# ---- AUDIT-16: approving an application must not demote the approver -------

def test_admin_cannot_demote_themselves_by_approving_their_own_application():
    admin_email = make_user("ADMIN", "a16")
    admin = new_client()
    login(admin, admin_email)
    uid = db.get_user_by_email(admin_email)["id"]
    app_id = db.create_application(name="Me", email=admin_email, interest="volunteer", user_id=uid)
    r = admin.post(f"/api/admin/applications/{app_id}/approve", json={"role": "NONE"})
    assert r.status_code == 400
    assert db.get_user_by_email(admin_email)["role"] == "ADMIN"
