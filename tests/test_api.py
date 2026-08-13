"""
Tests for Discrimination Map — far-right incident monitor (Germany).

Run from the project root:  python -m pytest -q tests
The self-check loop runs exactly this suite on each tick.
"""
import os
import sys
import tempfile

# Isolated temp DB so tests never touch real data.
_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DXMAP_DB_PATH"] = _TMP.name

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from fastapi.testclient import TestClient  # noqa: E402
import app as app_module  # noqa: E402
import db  # noqa: E402
import geolocate  # noqa: E402
import lawref  # noqa: E402

db.init_db()
client = TestClient(app_module.app)


# ---------------- geolocation ----------------

def test_gazetteer_hits_german_city():
    hit = geolocate.from_gazetteer("Hakenkreuz an Wand in Berlin gesprüht")
    assert hit is not None
    lat, lon, place = hit
    assert geolocate.in_germany(lat, lon)
    assert "Berlin" in place


def test_in_germany_bounding_box():
    assert geolocate.in_germany(52.52, 13.40)      # Berlin
    assert not geolocate.in_germany(51.5074, -0.1278)  # London -> outside DE


def test_gazetteer_miss_returns_none():
    assert geolocate.from_gazetteer("qwerty zxcvb noplace") is None


# ---------------- classifier (lawref) ----------------

def test_classify_flags_banned_symbol():
    v = lawref.classify("Neonazis zeigen Hakenkreuz und rufen Sieg Heil in Dortmund")
    assert v["relevant"] is True
    assert v["law_code"] == "StGB-86a"


def test_classify_ignores_unrelated_post():
    v = lawref.classify("Beautiful sunny morning walk along the river in Munich")
    assert v["relevant"] is False
    assert v["law_code"] is None


def test_classify_march_is_monitoring_not_crime():
    # A far-right march is relevant to monitor but not itself an offence.
    v = lawref.classify("Angekündigter Naziaufmarsch am Samstag in Leipzig")
    assert v["relevant"] is True
    assert v["law_code"] is None


# ---------------- reports API ----------------

def test_post_and_get_user_report_with_documentation():
    """
    A user submission has no verifiable `url`, so it defaults to 'pending' —
    held out of the public feed until an ADMIN/VERIFIER reviews it (the
    evidence-gated status policy).
    """
    payload = {
        "title": "Swastika on memorial",
        "reason": "Swastika sprayed on a memorial overnight",
        "evidence": "https://example.org/photo",
        "law": "StGB-86a",
        "impact": "Targeted the local Jewish community; deeply intimidating.",
        "category": "banned_symbol",
        "lat": 52.52, "lon": 13.40,
    }
    r = client.post("/api/reports", json=payload)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending"

    reasons = [rep["reason"] for rep in client.get("/api/reports?all=true").json()["reports"]]
    assert "Swastika sprayed on a memorial overnight" not in reasons  # pending -> not public yet


def test_post_rejects_unknown_law_code():
    bad = {"title": "x", "reason": "something happened", "law": "StGB-9999",
           "lat": 52.5, "lon": 13.4}
    assert client.post("/api/reports", json=bad).status_code == 422


def test_post_rejects_bad_coordinates():
    bad = {"title": "x", "reason": "off the globe", "lat": 999, "lon": 0}
    assert client.post("/api/reports", json=bad).status_code == 422


def test_post_rejects_short_reason():
    bad = {"title": "x", "reason": "hi", "lat": 52.5, "lon": 13.4}
    assert client.post("/api/reports", json=bad).status_code == 422


# ---------------- laws / health / heartbeat ----------------

def test_laws_endpoint_returns_statutes():
    r = client.get("/api/laws")
    assert r.status_code == 200
    laws = r.json()["laws"]
    assert "StGB-86a" in laws and "title_en" in laws["StGB-86a"]


def test_health_endpoint_shape():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "stats" in body and "sources" in body


def test_heartbeat_endpoint_shape():
    r = client.get("/api/heartbeat")
    assert r.status_code == 200
    assert "beat_count" in r.json()


# ---------------- security headers ----------------

def test_security_headers_present():
    r = client.get("/api/health")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert "referrer-policy" in {k.lower() for k in r.headers}


# ---------------- auth / roles ----------------

def test_admin_login_and_create_verifier():
    db.create_user("admin@dxmap-tests.example-org.dev", "adminpass123", "ADMIN")
    admin = TestClient(app_module.app)
    r = admin.post("/api/auth/login", json={"email": "admin@dxmap-tests.example-org.dev", "password": "adminpass123"})
    assert r.status_code == 200
    assert r.json()["role"] == "ADMIN"

    r = admin.get("/api/auth/me")
    assert r.status_code == 200 and r.json()["email"] == "admin@dxmap-tests.example-org.dev"

    r = admin.post("/api/admin/users", json={
        "email": "verifier@dxmap-tests.example-org.dev", "password": "verifierpass123", "role": "VERIFIER"})
    assert r.status_code == 201

    verifier = TestClient(app_module.app)
    r = verifier.post("/api/auth/login", json={"email": "verifier@dxmap-tests.example-org.dev", "password": "verifierpass123"})
    assert r.status_code == 200 and r.json()["role"] == "VERIFIER"


def test_verifier_can_verify_but_not_delete_or_manage_users():
    verifier = TestClient(app_module.app)
    verifier.post("/api/auth/login", json={"email": "verifier@dxmap-tests.example-org.dev", "password": "verifierpass123"})

    rep = client.post("/api/reports", json={
        "title": "Verifier target", "reason": "verifier-target report for role test",
        "lat": 52.5, "lon": 13.4}).json()

    r = verifier.patch(f"/api/admin/reports/{rep['id']}", json={"status": "verified"})
    assert r.status_code == 200

    assert verifier.delete(f"/api/admin/reports/{rep['id']}").status_code == 403
    assert verifier.get("/api/admin/users").status_code == 403


def test_wrong_password_rejected():
    r = client.post("/api/auth/login", json={"email": "admin@dxmap-tests.example-org.dev", "password": "wrong"})
    assert r.status_code == 401


def test_no_public_signin_endpoints():
    """
    There's deliberately no way to create an account except an ADMIN
    inviting one via /api/admin/users — applications go through nabilvs.com
    instead, and the public map has no sign-in UI at all.
    """
    anon = TestClient(app_module.app)
    assert anon.post("/api/auth/signup", json={"email": "x@example.dev", "password": "whatever123"}).status_code == 404
    assert anon.get("/api/auth/google/login").status_code == 404
    assert anon.get("/api/auth/google/callback").status_code == 404


def test_admin_can_promote_invited_verifier_to_admin_and_back():
    admin = TestClient(app_module.app)
    admin.post("/api/auth/login", json={
        "email": "admin@dxmap-tests.example-org.dev", "password": "adminpass123"})
    r = admin.post("/api/admin/users", json={
        "email": "promote-test@dxmap-tests.example-org.dev", "password": "promotetest123", "role": "VERIFIER"})
    new_id = r.json()["id"]

    r = admin.patch(f"/api/admin/users/{new_id}", json={"role": "ADMIN"})
    assert r.status_code == 200 and r.json()["role"] == "ADMIN"

    r = admin.patch(f"/api/admin/users/{new_id}", json={"role": "VERIFIER"})
    assert r.status_code == 200 and r.json()["role"] == "VERIFIER"


def test_pending_report_visible_to_admin_not_public():
    rep = client.post("/api/reports", json={
        "title": "Pending visibility test", "reason": "pending visibility test reason",
        "lat": 52.5, "lon": 13.4}).json()
    assert rep["status"] == "pending"

    public_ids = [r["id"] for r in client.get("/api/reports?all=true").json()["reports"]]
    assert rep["id"] not in public_ids

    admin = TestClient(app_module.app)
    admin.post("/api/auth/login", json={
        "email": "admin@dxmap-tests.example-org.dev", "password": "adminpass123"})
    admin_ids = [r["id"] for r in admin.get("/api/admin/reports?status=pending").json()["reports"]]
    assert rep["id"] in admin_ids


def test_apply_endpoint_and_admin_listing():
    r = client.post("/api/apply", json={
        "name": "Test Volunteer", "email": "volunteer@dxmap-tests.example-org.dev",
        "interest": "translator", "message": "Happy to help translate."})
    assert r.status_code == 201

    assert client.get("/api/admin/applications").status_code == 401

    admin = TestClient(app_module.app)
    admin.post("/api/auth/login", json={
        "email": "admin@dxmap-tests.example-org.dev", "password": "adminpass123"})
    apps = admin.get("/api/admin/applications").json()["applications"]
    assert any(a["email"] == "volunteer@dxmap-tests.example-org.dev" for a in apps)


def test_scraped_report_with_url_is_unverified_and_fuzzed_for_public():
    """
    Agent-scraped items always carry a real source `url`, so they publish
    immediately as 'unverified' leads (not 'pending') — but still fuzzed for
    anyone not logged in as ADMIN/VERIFIER.
    """
    new_id = db.insert_report(
        source="mastodon", external_id="test_scraped_1", title="Scraped test",
        body="scraped test body", url="https://example.social/@x/1",
        category="banned_symbol", reason="scraped test reason",
        lat=52.5200, lon=13.4000, place="Berlin",
    )
    assert new_id is not None
    listed = [r for r in client.get("/api/reports?all=true").json()["reports"] if r["id"] == new_id][0]
    assert listed["status"] == "unverified"
    assert (listed["lat"], listed["lon"]) != (52.5200, 13.4000)
    assert listed.get("fuzzed") is True


def test_sexual_violence_report_uses_wider_fuzz_radius():
    new_id = db.insert_report(
        source="mastodon", external_id="test_scraped_2", title="Sensitive scraped test",
        body="sensitive", url="https://example.social/@x/2",
        category="sexual_violence", reason="sensitive scraped reason",
        lat=52.5200, lon=13.4000, place="Berlin",
    )
    listed = [r for r in client.get("/api/reports?all=true").json()["reports"] if r["id"] == new_id][0]
    assert listed["status"] == "unverified"  # has a url, so not pending
    assert listed.get("fuzzed") is True
    dist_deg = ((listed["lat"] - 52.52) ** 2 + (listed["lon"] - 13.40) ** 2) ** 0.5
    assert dist_deg * 111 > 1.0  # well beyond the default 500m radius (in km)


# ---------------- propose-a-symbol (Awareness tab) ----------------

def test_propose_symbol_reuses_applications_table():
    r = client.post("/api/propose-symbol", json={
        "description": "A specific hand gesture used at recent rallies, not covered in the guide.",
        "context": "Seen at a demonstration, on a livestream",
        "email": "tipster@dxmap-tests.example-org.dev",
    })
    assert r.status_code == 201

    admin = TestClient(app_module.app)
    admin.post("/api/auth/login", json={
        "email": "admin@dxmap-tests.example-org.dev", "password": "adminpass123"})
    apps = admin.get("/api/admin/applications").json()["applications"]
    match = [a for a in apps if a["email"] == "tipster@dxmap-tests.example-org.dev"]
    assert len(match) == 1
    assert match[0]["interest"] == "other"
    assert "[SYMBOL PROPOSAL]" in match[0]["message"]
    assert "hand gesture" in match[0]["message"]


def test_propose_symbol_email_optional_but_must_look_like_one():
    r = client.post("/api/propose-symbol", json={"description": "No email given for this tip at all."})
    assert r.status_code == 201

    bad = client.post("/api/propose-symbol", json={
        "description": "Has a malformed email attached to it.", "email": "not-an-email"})
    assert bad.status_code == 422


def test_propose_symbol_too_short_description_rejected():
    r = client.post("/api/propose-symbol", json={"description": "hi"})
    assert r.status_code == 422


# ---------------- self-edit via edit_token ----------------

def test_report_creation_returns_edit_token_not_leaked_in_listings():
    r = client.post("/api/reports", json={
        "title": "Edit-token test", "reason": "checking the edit token flow",
        "lat": 48.85, "lon": 2.35})
    body = r.json()
    assert "edit_token" in body and len(body["edit_token"]) > 10

    admin = TestClient(app_module.app)
    admin.post("/api/auth/login", json={
        "email": "admin@dxmap-tests.example-org.dev", "password": "adminpass123"})
    admin_rows = admin.get("/api/admin/reports").json()["reports"]
    assert all("edit_token" not in row for row in admin_rows)


def test_user_can_edit_own_pending_report_with_token():
    r = client.post("/api/reports", json={
        "title": "Original title", "reason": "original reason text here",
        "lat": 48.85, "lon": 2.35})
    body = r.json()
    rid, token = body["id"], body["edit_token"]

    bad = client.patch(f"/api/reports/{rid}", json={"edit_token": "wrong-token", "reason": "hacked"})
    assert bad.status_code == 403

    ok = client.patch(f"/api/reports/{rid}", json={"edit_token": token, "reason": "an edited reason text"})
    assert ok.status_code == 200

    admin = TestClient(app_module.app)
    admin.post("/api/auth/login", json={
        "email": "admin@dxmap-tests.example-org.dev", "password": "adminpass123"})
    row = next(r for r in admin.get("/api/admin/reports").json()["reports"] if r["id"] == rid)
    assert row["reason"] == "an edited reason text"


def test_user_cannot_edit_report_after_verification():
    r = client.post("/api/reports", json={
        "title": "Locks after review", "reason": "should lock after verification",
        "lat": 48.85, "lon": 2.35})
    body = r.json()
    rid, token = body["id"], body["edit_token"]

    admin = TestClient(app_module.app)
    admin.post("/api/auth/login", json={
        "email": "admin@dxmap-tests.example-org.dev", "password": "adminpass123"})
    admin.patch(f"/api/admin/reports/{rid}", json={"status": "verified"})

    resp = client.patch(f"/api/reports/{rid}", json={"edit_token": token, "reason": "too late now"})
    assert resp.status_code == 409


def test_admin_can_edit_report_fields_directly():
    r = client.post("/api/reports", json={
        "title": "Admin edit test", "reason": "admin should be able to fix this",
        "lat": 48.85, "lon": 2.35})
    rid = r.json()["id"]

    assert client.patch(f"/api/admin/reports/{rid}/fields", json={"reason": "unauthorized edit"}).status_code == 401

    admin = TestClient(app_module.app)
    admin.post("/api/auth/login", json={
        "email": "admin@dxmap-tests.example-org.dev", "password": "adminpass123"})
    ok = admin.patch(f"/api/admin/reports/{rid}/fields", json={"reason": "corrected by admin"})
    assert ok.status_code == 200
    row = next(r for r in admin.get("/api/admin/reports").json()["reports"] if r["id"] == rid)
    assert row["reason"] == "corrected by admin"


# ---------------- rate limiting ----------------

def test_login_rate_limited_after_repeated_attempts():
    rl_client = TestClient(app_module.app)
    statuses = []
    for _ in range(35):
        resp = rl_client.post("/api/auth/login", json={
            "email": "admin@dxmap-tests.example-org.dev", "password": "wrong-password"})
        statuses.append(resp.status_code)
    assert 429 in statuses
    assert statuses.count(401) <= 30  # the 401s stop once the limiter kicks in


