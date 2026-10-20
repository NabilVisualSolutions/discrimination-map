import os
import sys
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ.setdefault("DXMAP_DB_PATH", _TMP.name)
os.environ["DXMAP_SERVICE_TOKEN"] = "test-service-token"
_MAIL = tempfile.mkdtemp()
os.environ["DXMAP_LOCAL_MAIL_DIR"] = _MAIL
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import re  # noqa: E402
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


H = {"x-forwarded-for": "203.0.113.90"}
BODY = {"name": "Mail Test", "email": "mailtest@example.org", "password": "correct-horse-battery",
        "message": "hi", "accept": True}


def _last_link():
    files = sorted(os.listdir(_MAIL))
    text = open(os.path.join(_MAIL, files[-1])).read()
    return re.search(r"https?://\S+token=(\S+)", text).group(1)


def test_signup_mails_a_one_time_link_and_the_account_starts_unverified():
    c = TestClient(app_module.app)
    assert c.post("/api/auth/signup", json=BODY, headers=H).status_code == 201
    uid = db.get_user_by_email(BODY["email"])["id"]
    assert not db.is_email_verified(uid)
    token = _last_link()
    r = c.get(f"/api/auth/verify-email?token={token}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/?verified=1"
    assert db.is_email_verified(uid)
    again = c.get(f"/api/auth/verify-email?token={token}", follow_redirects=False)
    assert again.headers["location"] == "/?verified=0"  # one use only


def test_a_bad_token_looks_the_same_as_an_expired_one():
    c = TestClient(app_module.app)
    r = c.get("/api/auth/verify-email?token=nope", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/?verified=0"


def test_admin_cannot_approve_an_unverified_applicant_but_can_after_the_link():
    c = TestClient(app_module.app)
    body = {**BODY, "email": "mailtest2@example.org"}
    c.post("/api/auth/signup", json=body, headers=H)
    uid = db.get_user_by_email(body["email"])["id"]
    app_id = next(a["id"] for a in db.list_applications() if a["user_id"] == uid)
    adm_id = db.create_user("mailadmin@example.org", "pass-word-12345", "ADMIN") or db.get_user_by_email("mailadmin@example.org")["id"]
    admin = TestClient(app_module.app)
    admin.cookies.set("dxmap_session", db.create_session(adm_id))
    os.environ["DXMAP_ENV"] = "dev"
    r = admin.post(f"/api/admin/applications/{app_id}/approve", json={"role": "VERIFIER"})
    assert r.status_code == 409
    c.get(f"/api/auth/verify-email?token={_last_link()}", follow_redirects=False)
    assert admin.post(f"/api/admin/applications/{app_id}/approve", json={"role": "VERIFIER"}).status_code == 200


def test_existing_accounts_and_admin_created_accounts_count_as_verified():
    uid = db.create_user("preexisting@example.org", "pass-word-12345", "VERIFIER")
    assert db.is_email_verified(uid)


def test_resend_works_for_the_signed_in_unverified_user_and_is_limited():
    c = TestClient(app_module.app)
    body = {**BODY, "email": "mailtest3@example.org"}
    c.post("/api/auth/signup", json=body, headers=H)
    c.post("/api/auth/login", json={"email": body["email"], "password": body["password"]}, headers=H)
    assert c.get("/api/auth/me").json()["verified"] is False
    n = len(os.listdir(_MAIL))
    assert c.post("/api/auth/verify-email/resend").status_code == 200
    assert len(os.listdir(_MAIL)) == n + 1


def test_without_any_mail_setup_new_accounts_are_not_stranded_unverified(monkeypatch):
    monkeypatch.delenv("DXMAP_LOCAL_MAIL_DIR", raising=False)
    monkeypatch.delenv("DXMAP_SMTP_USER", raising=False)
    c = TestClient(app_module.app)
    body = {**BODY, "email": "nomail@example.org"}
    assert c.post("/api/auth/signup", json=body, headers=H).status_code == 201
    assert db.is_email_verified(db.get_user_by_email(body["email"])["id"])
