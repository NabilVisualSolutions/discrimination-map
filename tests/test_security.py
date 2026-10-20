"""
Abuse protection: visitor IP behind Cloudflare, rate limits, honeypot,
Turnstile, pseudonymous moderators, security headers. backend/security.py.
"""
import os
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
import security  # noqa: E402

db.init_db()
app_module.SERVICE_TOKEN = "test-service-token"
client = TestClient(app_module.app)

CF_EDGE = "162.158.1.10"  # inside Cloudflare's 162.158.0.0/15
REPORT = {"title": "Graffiti", "reason": "Swastika on a wall", "category": "banned_symbol", "lat": 52.5, "lon": 13.4}


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    security.limiter.reset()
    monkeypatch.delenv("DXMAP_TURNSTILE_SECRET", raising=False)
    yield


class _Req:
    def __init__(self, headers, peer="10.0.0.1"):
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.client = type("C", (), {"host": peer})()


# ---------------- client IP ----------------

def test_uses_cf_connecting_ip_when_the_hop_is_cloudflare():
    r = _Req({"x-forwarded-for": CF_EDGE, "cf-connecting-ip": "203.0.113.7"})
    assert security.client_ip(r) == "203.0.113.7"


def test_ignores_cf_connecting_ip_from_a_direct_connection():
    # Someone hitting the origin directly cannot choose their own IP.
    r = _Req({"x-forwarded-for": "198.51.100.9", "cf-connecting-ip": "203.0.113.7"})
    assert security.client_ip(r) == "198.51.100.9"


def test_ignores_a_spoofed_first_forwarded_entry():
    r = _Req({"x-forwarded-for": "1.2.3.4, 198.51.100.9"})
    assert security.client_ip(r) == "198.51.100.9"


def test_falls_back_to_the_socket_peer():
    assert security.client_ip(_Req({}, peer="192.0.2.5")) == "192.0.2.5"


def test_rejects_garbage_cf_header():
    r = _Req({"x-forwarded-for": CF_EDGE, "cf-connecting-ip": "not-an-ip"})
    assert security.client_ip(r) == CF_EDGE


# ---------------- rate limits ----------------

def _post(path, body, visitor):
    return client.post(path, json=body, headers={"X-Forwarded-For": CF_EDGE, "CF-Connecting-IP": visitor})


def test_reports_are_capped_per_minute_per_visitor():
    codes = [_post("/api/reports", {**REPORT, "title": f"Graffiti {i}"}, "203.0.113.20").status_code for i in range(6)]
    assert codes[:5] == [201] * 5
    assert codes[5] == 429


def test_visitors_behind_one_cloudflare_edge_get_separate_buckets():
    for i in range(5):
        _post("/api/reports", {**REPORT, "title": f"A {i}"}, "203.0.113.30")
    assert _post("/api/reports", {**REPORT, "title": "Other visitor"}, "203.0.113.31").status_code == 201


def test_reports_hourly_cap(monkeypatch):
    t = [1_000_000.0]
    monkeypatch.setattr(security.time, "time", lambda: t[0])
    codes = []
    for i in range(21):
        t[0] += 61  # a new minute each time, so only the hour cap applies
        codes.append(_post("/api/reports", {**REPORT, "title": f"Slow {i}"}, "203.0.113.40").status_code)
    assert codes[:20] == [201] * 20
    assert codes[20] == 429


def test_limiter_window_expires():
    lim = security.RateLimiter()
    assert lim.hit("k", 1, 60, now=0) is False
    assert lim.hit("k", 1, 60, now=30) is True
    assert lim.hit("k", 1, 60, now=61) is False


# ---------------- honeypot + Turnstile ----------------

def test_honeypot_rejects_report():
    r = _post("/api/reports", {**REPORT, "hp_contact": "http://spam.example"}, "203.0.113.50")
    assert r.status_code == 400
    assert r.json()["detail"] == security.BOT_CHECK_FAILED


def test_honeypot_rejects_application():
    body = {"name": "Bot", "email": "bot@example.org", "interest": "volunteer", "hp_contact": "x"}
    assert _post("/api/apply", body, "203.0.113.51").status_code == 400


def test_turnstile_is_skipped_without_a_secret():
    assert _post("/api/reports", REPORT, "203.0.113.52").status_code == 201


def test_turnstile_required_when_secret_set(monkeypatch):
    monkeypatch.setenv("DXMAP_TURNSTILE_SECRET", "real-secret")
    monkeypatch.setattr(security, "_siteverify", lambda *a: {"success": False})
    assert _post("/api/reports", {**REPORT, "turnstile_token": "bad"}, "203.0.113.53").status_code == 403
    assert _post("/api/reports", REPORT, "203.0.113.53").status_code == 403


def test_turnstile_checks_action_and_hostname(monkeypatch):
    monkeypatch.setenv("DXMAP_TURNSTILE_SECRET", "real-secret")
    answer = {"success": True, "action": security.TURNSTILE_ACTION, "hostname": "map.nabilvs.com"}
    monkeypatch.setattr(security, "_siteverify", lambda *a: answer)
    assert _post("/api/reports", {**REPORT, "turnstile_token": "ok"}, "203.0.113.54").status_code == 201
    answer["hostname"] = "evil.example"
    assert _post("/api/reports", {**REPORT, "title": "Second try", "turnstile_token": "ok"}, "203.0.113.54").status_code == 403


def test_turnstile_fails_closed_when_cloudflare_is_down(monkeypatch):
    monkeypatch.setenv("DXMAP_TURNSTILE_SECRET", "real-secret")

    def boom(*a):
        raise OSError("down")

    monkeypatch.setattr(security, "_siteverify", boom)
    assert _post("/api/reports", {**REPORT, "turnstile_token": "ok"}, "203.0.113.55").status_code == 403


# ---------------- service API ----------------

def _review(moderator, rid):
    return client.post(
        f"/api/service/review/{rid}",
        json={"status": "dismissed", "moderator": moderator},
        headers={"X-Service-Token": "test-service-token"},
    )


def _new_report_id():
    rid = db.insert_report(source="user", external_id=f"t_{os.urandom(4).hex()}", title="t", body="b",
                           category="banned_symbol", reason="r", evidence="", law=None, impact="",
                           lat=52.5, lon=13.4, place="x")
    assert rid is not None
    return rid


def test_service_review_refuses_an_email_as_moderator():
    r = _review("volunteer@example.org", _new_report_id())
    assert r.status_code == 422


def test_service_review_accepts_a_pseudonym_and_records_it():
    rid = _new_report_id()
    pseud = "vol_" + "a" * 32
    assert _review(pseud, rid).status_code == 200
    hist = db.get_report_history(rid)
    assert any(f"pantheon:{pseud}" in str(h) for h in hist)
    assert not any("@" in str(h.get("edited_by", "")) for h in hist)


def test_service_review_is_capped_per_moderator():
    rid = _new_report_id()
    pseud = "vol_" + "b" * 32
    codes = [_review(pseud, rid).status_code for _ in range(31)]
    assert codes[:30] == [200] * 30
    assert codes[30] == 429


# ---------------- headers ----------------

def test_headers_on_every_response():
    h = client.get("/api/health").headers
    assert "frame-ancestors 'self' https://nabilvs.com https://www.nabilvs.com" in h["content-security-policy"]
    assert "object-src 'none'" in h["content-security-policy"]
    assert "x-frame-options" not in h  # would block the nabilvs.com embed
    assert "default-src 'self'" in h["content-security-policy-report-only"]
    assert "camera=()" in h["permissions-policy"]


def test_extra_frame_ancestors_only_outside_prod(monkeypatch):
    monkeypatch.setenv("DXMAP_FRAME_ANCESTORS_EXTRA", "http://localhost:3100")
    monkeypatch.setenv("DXMAP_ENV", "dev")
    assert "http://localhost:3100" in security.frame_ancestors()
    monkeypatch.setenv("DXMAP_ENV", "prod")
    assert "localhost" not in security.frame_ancestors()
