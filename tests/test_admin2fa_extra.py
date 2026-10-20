"""More ADMIN two-step cases: disable and the deletion record are blocked until enrolled."""
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


@pytest.fixture(autouse=True)
def _reset():
    security.limiter.reset()
    yield


def _admin(email):
    uid = db.create_user(email, "pass-word-12345", "ADMIN") or db.get_user_by_email(email)["id"]
    c = TestClient(app_module.app)
    c.cookies.set("dxmap_session", db.create_session(uid))
    return c, uid


def test_disable_and_deletion_record_blocked_without_two_step_in_prod(monkeypatch):
    monkeypatch.setenv("DXMAP_ENV", "prod")
    c, _ = _admin("x1@dxmap-tests.example-org.dev")
    r = c.post("/api/auth/totp/disable", json={"password": "pass-word-12345", "code": "123456"})
    assert r.status_code == 403 and r.json()["detail"] == "Set up two-step sign-in first"
    r = c.get("/api/admin/deletions")
    assert r.status_code == 403 and r.json()["detail"] == "Set up two-step sign-in first"


def test_deletion_record_opens_once_two_step_is_on(monkeypatch):
    monkeypatch.setenv("DXMAP_ENV", "prod")
    c, uid = _admin("x2@dxmap-tests.example-org.dev")
    db.set_totp_pending(uid, "JBSWY3DPEHPK3PXP")
    db.enable_totp(uid, 1)
    assert c.get("/api/admin/deletions").status_code == 200
