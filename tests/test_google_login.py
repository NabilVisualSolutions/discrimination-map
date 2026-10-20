import base64
import json
import os
import sys
import tempfile
import time

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ.setdefault("DXMAP_DB_PATH", _TMP.name)
os.environ["DXMAP_SERVICE_TOKEN"] = "test-service-token"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402
import db  # noqa: E402
import google_login  # noqa: E402
import security  # noqa: E402

db.init_db()


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    security.limiter.reset()
    monkeypatch.setenv("DXMAP_GOOGLE_CLIENT_ID", "cid.apps.googleusercontent.com")
    monkeypatch.setenv("DXMAP_GOOGLE_CLIENT_SECRET", "csecret")
    yield


def _jwt(**claims):
    base = {"aud": "cid.apps.googleusercontent.com", "iss": "https://accounts.google.com",
            "exp": int(time.time()) + 600, "email_verified": True, "email": "g-admin@example.org"}
    base.update(claims)
    seg = base64.urlsafe_b64encode(json.dumps(base).encode()).decode().rstrip("=")
    return f"x.{seg}.y"


def _start(c):
    r = c.get("/api/auth/google/start", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("https://accounts.google.com/")
    state = c.cookies.get("dxmap_oauth")
    assert state and f"state={state}" in r.headers["location"]
    return state


def test_off_without_client_settings(monkeypatch):
    monkeypatch.delenv("DXMAP_GOOGLE_CLIENT_ID")
    c = TestClient(app_module.app)
    assert c.get("/api/auth/google/enabled").json() == {"enabled": False}
    assert c.get("/api/auth/google/start", follow_redirects=False).status_code == 404


def test_existing_admin_signs_in_and_counts_as_two_step_even_without_an_authenticator(monkeypatch):
    monkeypatch.setenv("DXMAP_ENV", "prod")
    db.create_user("g-admin@example.org", "pass-word-12345", "ADMIN")
    monkeypatch.setattr(google_login, "_exchange", lambda code, ru: {"id_token": _jwt()})
    c = TestClient(app_module.app)
    state = _start(c)
    r = c.get(f"/api/auth/google/callback?code=abc&state={state}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin"
    assert c.get("/api/admin/users").status_code == 200  # no TOTP set up, prod, but Google session


def test_unknown_email_unverified_email_wrong_audience_and_bad_state_are_all_refused(monkeypatch):
    db.create_user("g-admin@example.org", "pass-word-12345", "ADMIN")
    for claims in ({"email": "stranger@example.org"}, {"email_verified": False}, {"aud": "other"},
                   {"exp": int(time.time()) - 5}, {"iss": "https://evil.example"}):
        monkeypatch.setattr(google_login, "_exchange", lambda code, ru, c=claims: {"id_token": _jwt(**c)})
        c = TestClient(app_module.app)
        state = _start(c)
        r = c.get(f"/api/auth/google/callback?code=abc&state={state}", follow_redirects=False)
        assert r.headers["location"] == "/admin?google=0", claims
        assert c.get("/api/auth/me").status_code == 401
    monkeypatch.setattr(google_login, "_exchange", lambda code, ru: {"id_token": _jwt()})
    c = TestClient(app_module.app)
    _start(c)
    r = c.get("/api/auth/google/callback?code=abc&state=forged", follow_redirects=False)
    assert r.headers["location"] == "/admin?google=0"


def test_a_user_with_no_role_cannot_use_google(monkeypatch):
    db.create_user("g-none@example.org", "pass-word-12345", "NONE")
    monkeypatch.setattr(google_login, "_exchange", lambda code, ru: {"id_token": _jwt(email="g-none@example.org")})
    c = TestClient(app_module.app)
    state = _start(c)
    r = c.get(f"/api/auth/google/callback?code=abc&state={state}", follow_redirects=False)
    assert r.headers["location"] == "/admin?google=0"
