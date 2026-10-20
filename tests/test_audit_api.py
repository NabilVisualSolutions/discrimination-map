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


def login(client, email, password="correct-horse-battery", headers=None):
    return client.post("/api/auth/login", json={"email": email, "password": password}, headers=headers or visitor())


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
])
def test_every_sensitive_spelling_is_blurred(category):
    rid = verified_report(category)
    assert coords_for(new_client(), rid) != (52.52, 13.405)


def test_non_sensitive_verified_report_keeps_its_exact_location():
    rid = verified_report("banned_symbol")
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
    body = {"title": "Graffiti", "reason": "Swastika", "category": "banned_symbol", "lat": 52.5, "lon": 13.4}
    rid = new_client().post("/api/reports", json=body, headers=visitor()).json()["id"]
    ext = db.get_report(rid)["external_id"]
    assert not re.fullmatch(r"user_\d+", ext or "")
    assert len(ext) >= 16


# ---- AUDIT-05: reviewers must not learn who the other volunteers are --------

def test_verifier_cannot_read_moderator_emails_in_history():
    rid = verified_report("banned_symbol")
    db.set_status(rid, "dismissed", edited_by="boss@example.org")
    verifier, admin = logged_in("VERIFIER", "a5"), logged_in("ADMIN", "a5")
    seen = str(verifier.get(f"/api/admin/reports/{rid}/history").json())
    assert "boss@example.org" not in seen and "@" not in seen
    assert "boss@example.org" in str(admin.get(f"/api/admin/reports/{rid}/history").json())


def test_masked_moderator_ids_are_stable_and_opaque():
    assert security.mask_moderator("boss@example.org") == security.mask_moderator("boss@example.org")
    assert security.mask_moderator("boss@example.org") != security.mask_moderator("other@example.org")
    assert "@" not in security.mask_moderator("boss@example.org")


def test_even_nabilvs_pseudonyms_are_masked_for_reviewers():
    # A pseudonym is stable across reports: shown raw, one reviewer could follow
    # another volunteer's verdicts. Only ADMIN sees the raw value.
    raw = "pantheon:vol_" + "a" * 32
    masked = security.mask_moderator(raw)
    assert "vol_" not in masked and masked.startswith("moderator-")


def test_only_admins_can_list_volunteer_applications():
    assert logged_in("VERIFIER", "a5b").get("/api/admin/applications").status_code == 403
    assert logged_in("ADMIN", "a5b").get("/api/admin/applications").status_code == 200


# ---- AUDIT-06: per-account lockout with backoff, no account enumeration -----

def test_five_wrong_passwords_lock_that_address_even_for_the_right_one():
    email = make_user("ADMIN", "a6")
    c, v = new_client(), visitor()
    for _ in range(5):
        assert login(c, email, "wrong-password-1", v).status_code == 401
    assert login(c, email, headers=v).status_code == 429


def test_a_stranger_cannot_lock_the_owner_out_from_the_owners_address():
    email = make_user("ADMIN", "a6owner")
    c, attacker, owner = new_client(), visitor(), visitor()
    for _ in range(8):
        login(c, email, "wrong-password-1", attacker)
    assert login(c, email, headers=attacker).status_code == 429  # the attacker's address is locked
    assert login(c, email, headers=owner).status_code == 200     # the owner is not


def test_unknown_addresses_lock_exactly_the_same_way():
    c, v = new_client(), visitor()
    for _ in range(5):
        assert login(c, "ghost-a6@example.org", "wrong-password-1", v).status_code == 401
    assert login(c, "ghost-a6@example.org", headers=v).status_code == 429


def test_a_good_login_clears_the_failures():
    email = make_user("VERIFIER", "a6b")
    c, v = new_client(), visitor()
    for _ in range(4):
        login(c, email, "wrong-password-1", v)
    assert login(c, email, headers=v).status_code == 200
    for _ in range(4):
        assert login(c, email, "wrong-password-1", v).status_code == 401


def test_a_distributed_flood_locks_unknown_addresses_but_not_the_owners_usual_one():
    email = make_user("ADMIN", "a6dist")
    c, home = new_client(), visitor()
    assert login(c, email, headers=home).status_code == 200  # owner signs in from home: remembered
    for _ in range(security.GLOBAL_FAILS):
        login(c, email, "wrong-password-1", visitor())
    assert login(c, email, headers=visitor()).status_code == 429   # a new address is held back
    assert login(c, email, headers=home).status_code == 200        # the owner's usual address is not


def test_a_persistent_guesser_keeps_escalating_but_only_locks_their_own_address():
    t = 1_000_000.0
    for _ in range(security.LOCK_FREE_FAILURES):
        security.login_failed("esc@example.org", "9.9.9.9", now=t)
    first = security._locks[("esc@example.org", "9.9.9.9")]["until"] - t
    t += first + 1
    security.login_failed("esc@example.org", "9.9.9.9", now=t)
    assert security._locks[("esc@example.org", "9.9.9.9")]["until"] - t == first * 2
    assert not security.login_locked("esc@example.org", "198.51.100.4", now=t)  # someone else is unaffected


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
    codes = [c.get("/api/reports?limit=10", headers=v).status_code for _ in range(301)]
    assert codes[:300] == [200] * 300 and codes[300] == 429
    assert c.get("/api/reports?limit=10", headers=visitor()).status_code == 200


def test_public_feed_limit_is_capped():
    assert len(new_client().get("/api/reports?limit=999999", headers=visitor()).json()["reports"]) <= 5000


# ---- AUDIT-10: the edit token belongs in a header, not a logged URL --------

def _filed():
    body = {"title": "Graffiti", "reason": "Swastika", "category": "banned_symbol", "lat": 52.5, "lon": 13.4}
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
    # httpx only sends non-ASCII header values as bytes; a real client can do the same.
    r = new_client().get("/api/service/stats", headers={"X-Service-Token": "tøken-ünïcode".encode("utf-8")})
    assert r.status_code == 401


def test_guessing_the_service_token_is_throttled():
    c, v = new_client(), visitor()
    codes = [c.get("/api/service/stats", headers={**v, "X-Service-Token": f"guess-{i}"}).status_code for i in range(12)]
    assert codes[-1] == 429


def test_oversized_request_bodies_are_refused():
    big = {"title": "Graffiti", "reason": "Swastika", "category": "banned_symbol", "lat": 52.5, "lon": 13.4,
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


# ---- review round: IPv6, null origin, chunked bodies, env defaults ----------

def test_one_ipv6_prefix_is_one_rate_limit_bucket():
    class R:
        headers = {"x-forwarded-for": CF_EDGE, "cf-connecting-ip": "2001:db8:1:2::1"}
        client = type("C", (), {"host": "10.0.0.1"})()
    a = security.client_ip(R())
    R.headers = {"x-forwarded-for": CF_EDGE, "cf-connecting-ip": "2001:db8:1:2:ffff:eeee:dddd:1"}
    assert security.client_ip(R()) == a            # same /64 -> same bucket
    R.headers = {"x-forwarded-for": CF_EDGE, "cf-connecting-ip": "2001:db8:1:3::1"}
    assert security.client_ip(R()) != a            # another /64 is another visitor


def test_ipv4_stays_per_address():
    class R:
        headers = {"x-forwarded-for": CF_EDGE, "cf-connecting-ip": "203.0.113.5"}
        client = type("C", (), {"host": "10.0.0.1"})()
    assert security.client_ip(R()) == "203.0.113.5"


def test_a_null_origin_write_is_refused():
    r = logged_in("ADMIN", "a7null").post("/api/auth/logout", headers={"Origin": "null"})
    assert r.status_code == 403


def test_a_chunked_body_over_the_cap_is_refused_without_being_buffered_whole():
    def chunks():
        for _ in range(64):
            yield b"x" * 1024  # 64 KB, no Content-Length
    r = new_client().post("/api/reports", content=chunks(), headers={**visitor(), "Content-Type": "application/json"})
    assert r.status_code == 413


@pytest.mark.parametrize("code", [
    "import sys; sys.path.insert(0, 'backend'); import security; print(security.frame_ancestors())",
    "import sys; sys.path.insert(0, 'backend'); import selfcheck, os; print(os.environ.get('DXMAP_ENV', 'prod'))",
])
def test_unset_env_means_production_everywhere(code):
    env = {k: v for k, v in os.environ.items() if k not in ("DXMAP_ENV", "DXMAP_FRAME_ANCESTORS_EXTRA")}
    env["DXMAP_FRAME_ANCESTORS_EXTRA"] = "http://localhost:3100"
    out = subprocess.run([sys.executable, "-c", code], cwd=os.path.join(os.path.dirname(__file__), ".."),
                         env=env, capture_output=True, text=True).stdout
    assert "localhost" not in out


def test_cloudflares_test_secret_is_refused_in_production(monkeypatch):
    monkeypatch.setenv("DXMAP_TURNSTILE_SECRET", "1x0000000000000000000000000000000AA")
    monkeypatch.setenv("DXMAP_ENV", "prod")
    monkeypatch.setattr(security, "_siteverify", lambda *a: {"success": True})
    r = new_client().post("/api/reports", json={"title": "Graffiti", "reason": "Swastika", "category": "banned_symbol",
                                                 "lat": 52.5, "lon": 13.4, "turnstile_token": "t"}, headers=visitor())
    assert r.status_code == 403


# ---- review round 2: lockout edge cases -------------------------------------

def test_no_usable_address_never_locks():
    for ip in ("", "unknown"):
        for _ in range(50):
            security.login_failed("noip@example.org", ip, now=1_000.0)
        assert not security.login_locked("noip@example.org", ip, now=1_001.0)


def test_engaging_the_email_ceiling_spends_the_count():
    t = 1_000_000.0
    for i in range(security.GLOBAL_FAILS):
        security.login_failed("spent@example.org", f"192.0.2.{i % 250}", now=t)
    assert security.login_locked("spent@example.org", "198.51.100.9", now=t + 1)
    t += security.GLOBAL_LOCK_S + 1
    assert not security.login_locked("spent@example.org", "198.51.100.9", now=t)
    security.login_failed("spent@example.org", "198.51.100.8", now=t)  # one stray failure
    assert not security.login_locked("spent@example.org", "198.51.100.9", now=t + 1)


def test_expired_email_counters_are_pruned():
    t = 1_000_000.0
    for i in range(security.LOCK_MAX_ENTRIES + 10):
        security.login_failed(f"junk{i}@example.org", "192.0.2.1", now=t)
    later = t + security.GLOBAL_WINDOW_S + 5
    security.login_failed("trigger@example.org", "192.0.2.2", now=later)
    assert len(security._global) < security.LOCK_MAX_ENTRIES
