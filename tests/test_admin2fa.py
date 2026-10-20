"""ADMIN must have two-step sign-in in prod (auth.require_role)."""
import os
import sys
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ.setdefault("DXMAP_DB_PATH", _TMP.name)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402
import db  # noqa: E402
import security  # noqa: E402

db.init_db()


@pytest.fixture(autouse=True)
def _reset():
    security.limiter.reset()
    yield


def _client(email, role):
    uid = db.create_user(email, "pass-word-12345", role)
    if uid is None:
        uid = db.get_user_by_email(email)["id"]
    c = TestClient(app_module.app)
    c.cookies.set("dxmap_session", db.create_session(uid))
    return c, uid


def test_admin_without_totp_blocked_in_prod(monkeypatch):
    monkeypatch.setenv("DXMAP_ENV", "prod")
    c, _ = _client("a1@dxmap-tests.example-org.dev", "ADMIN")
    r = c.get("/api/admin/users")
    assert r.status_code == 403 and r.json()["detail"] == "Set up two-step sign-in first"
    assert c.get("/api/auth/me").status_code == 200
    r = c.post("/api/auth/totp/setup", json={"password": "pass-word-12345"})
    assert r.status_code == 200 and "secret" in r.json()


def test_admin_without_totp_allowed_in_dev(monkeypatch):
    monkeypatch.setenv("DXMAP_ENV", "dev")
    c, _ = _client("a2@dxmap-tests.example-org.dev", "ADMIN")
    assert c.get("/api/admin/users").status_code == 200


def test_admin_with_totp_passes_in_prod(monkeypatch):
    monkeypatch.setenv("DXMAP_ENV", "prod")
    c, uid = _client("a3@dxmap-tests.example-org.dev", "ADMIN")
    db.set_totp_pending(uid, "JBSWY3DPEHPK3PXP")
    db.enable_totp(uid, 1)
    assert c.get("/api/admin/users").status_code == 200


def test_verifier_unaffected_in_prod(monkeypatch):
    monkeypatch.setenv("DXMAP_ENV", "prod")
    c, _ = _client("v1@dxmap-tests.example-org.dev", "VERIFIER")
    r = c.get("/api/admin/users")
    assert r.status_code == 403 and r.json()["detail"] == "Not permitted for this role"
    # a route open to VERIFIER is not hit by the 2FA rule
    assert c.post("/api/auth/totp/setup", json={"password": "pass-word-12345"}).status_code == 200
    assert c.get("/api/auth/me").status_code == 200
