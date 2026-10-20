import os
import sys
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ.setdefault("DXMAP_DB_PATH", _TMP.name)
os.environ["DXMAP_SERVICE_TOKEN"] = "test-service-token"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402
import db  # noqa: E402

db.init_db()

BODY = {"name": "Vol Unteer", "email": "enum-test@example.org", "password": "correct-horse-battery",
        "message": "I would like to help review reports", "accept": True}


def post(client, body):
    return client.post("/api/auth/signup", json=body, headers={"x-forwarded-for": "203.0.113.77"})


def test_signup_answers_the_same_for_a_new_and_a_registered_email():
    c = TestClient(app_module.app)
    first = post(c, BODY)
    second = post(c, {**BODY, "password": "another-password-123"})
    assert first.status_code == second.status_code and first.status_code < 300
    assert first.json() == second.json()
    assert "set-cookie" not in first.headers and "set-cookie" not in second.headers


def test_signup_no_longer_signs_the_new_account_in_but_the_password_works_at_login():
    c = TestClient(app_module.app)
    post(c, {**BODY, "email": "enum-test2@example.org"})
    assert c.get("/api/auth/me").status_code == 401
    r = c.post("/api/auth/login", json={"email": "enum-test2@example.org", "password": BODY["password"]},
               headers={"x-forwarded-for": "203.0.113.78"})
    assert r.status_code == 200
