"""
Follow-up fixes: authenticator-app sign-in, hashed and shorter sessions, a
record that survives deleting a report, a cap on what one scraper source may add.
"""
import asyncio
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

import agent  # noqa: E402
import app as app_module  # noqa: E402
import db  # noqa: E402
import security  # noqa: E402
import totp  # noqa: E402

db.init_db()
CF_EDGE = "162.158.1.10"
_n = [0]


def visitor():
    _n[0] += 1
    return {"X-Forwarded-For": CF_EDGE, "CF-Connecting-IP": f"198.51.100.{_n[0] % 250 + 1}"}


@pytest.fixture(autouse=True)
def _fresh():
    security.limiter.reset()
    security.reset_login_locks()
    yield


PW = "correct-horse-battery"


def make_user(role, tag):
    email = f"{role.lower()}-{tag}@followup.example.org"
    if not db.get_user_by_email(email):
        db.create_user(email, "correct-horse-battery", role)
    return email


def login(client, email, code=None, headers=None):
    body = {"email": email, "password": "correct-horse-battery"}
    if code is not None:
        body["code"] = code
    return client.post("/api/auth/login", json=body, headers=headers or visitor())


def now_code(secret, offset=0):
    return totp._code(secret, int(time.time() // totp.STEP_S) + offset)


# ---------------- the code generator ----------------

def test_matches_the_rfc_6238_test_vector():
    assert totp._code("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", 59 // 30) == "287082"  # RFC 6238, T=59


def test_accepts_the_current_step_and_one_either_side_and_nothing_further():
    s = totp.new_secret()
    t = 1_700_000_000.0
    step = int(t // 30)
    assert totp.verify(s, totp._code(s, step), now=t) == step
    assert totp.verify(s, totp._code(s, step - 1), now=t) == step - 1
    assert totp.verify(s, totp._code(s, step + 1), now=t) == step + 1
    assert totp.verify(s, totp._code(s, step + 2), now=t) is None
    assert totp.verify(s, totp._code(s, step - 2), now=t) is None


def test_a_code_cannot_be_used_twice():
    s = totp.new_secret()
    t = 1_700_000_000.0
    step = totp.verify(s, totp._code(s, int(t // 30)), now=t)
    assert totp.verify(s, totp._code(s, int(t // 30)), last_step=step, now=t) is None


@pytest.mark.parametrize("bad", ["", "12345", "1234567", "abcdef", "12 34 5x"])
def test_malformed_codes_are_refused(bad):
    assert totp.verify(totp.new_secret(), bad) is None


def test_provisioning_uri_is_what_authenticator_apps_read():
    uri = totp.provisioning_uri("ABCDEF", "me@example.org")
    assert uri.startswith("otpauth://totp/Discrimination%20Map%3Ame%40example.org?")
    assert "secret=ABCDEF" in uri and "digits=6" in uri and "period=30" in uri


# ---------------- sign-in with the second step ----------------

def enrol(email):
    c = TestClient(app_module.app)
    assert login(c, email).status_code == 200
    secret = c.post("/api/auth/totp/setup", json={"password": PW}).json()["secret"]
    assert c.post("/api/auth/totp/enable", json={"code": now_code(secret)}).status_code == 200
    return secret


def test_password_alone_is_not_enough_once_two_step_is_on():
    email = make_user("ADMIN", "t1")
    secret = enrol(email)
    r = login(TestClient(app_module.app), email)
    assert r.status_code == 401 and r.json()["detail"] == "TOTP_REQUIRED"
    assert "set-cookie" not in r.headers


def test_a_right_code_signs_in_and_cannot_be_replayed():
    email = make_user("ADMIN", "t2")
    secret = enrol(email)
    code = now_code(secret, 1)  # a step the enrolment code did not use
    assert login(TestClient(app_module.app), email, code).status_code == 200
    assert login(TestClient(app_module.app), email, code).status_code == 401


def test_a_wrong_code_is_refused_and_counts_toward_the_lockout():
    email = make_user("ADMIN", "t3")
    enrol(email)
    c, v = TestClient(app_module.app), visitor()
    for _ in range(5):
        assert login(c, email, "000000", v).status_code == 401
    assert login(c, email, "000000", v).status_code == 429


def test_a_wrong_password_never_reveals_that_two_step_is_on():
    email = make_user("ADMIN", "t4")
    enrol(email)
    r = TestClient(app_module.app).post("/api/auth/login", json={"email": email, "password": "wrong-password"}, headers=visitor())
    assert r.status_code == 401 and r.json()["detail"] == "Wrong email or password"


def test_turning_it_off_needs_a_current_code():
    email = make_user("VERIFIER", "t5")
    c = TestClient(app_module.app)
    login(c, email)
    secret = c.post("/api/auth/totp/setup", json={"password": PW}).json()["secret"]
    c.post("/api/auth/totp/enable", json={"code": now_code(secret)})
    assert c.post("/api/auth/totp/disable", json={"code": "000000", "password": PW}).status_code == 400
    assert c.post("/api/auth/totp/disable", json={"code": now_code(secret, 1), "password": "wrong-password-1"}).status_code == 403
    assert c.post("/api/auth/totp/disable", json={"code": now_code(secret, 1), "password": PW}).status_code == 200
    assert login(TestClient(app_module.app), email).status_code == 200  # back to password only


def test_setup_is_for_reviewers_only_and_refuses_a_second_enrolment():
    anon = TestClient(app_module.app)
    assert anon.post("/api/auth/totp/setup", json={"password": PW}).status_code == 401
    none = TestClient(app_module.app)
    login(none, make_user("NONE", "t6"))
    assert none.post("/api/auth/totp/setup", json={"password": PW}).status_code == 403
    email = make_user("ADMIN", "t6b")
    enrol(email)
    again = TestClient(app_module.app)
    login(again, email, now_code(db.get_totp(db.get_user_by_email(email)["id"])["totp_secret"], 1))
    assert again.post("/api/auth/totp/setup", json={"password": PW}).status_code == 409


def test_a_half_finished_enrolment_does_not_lock_anyone_out():
    email = make_user("ADMIN", "t7")
    c = TestClient(app_module.app)
    login(c, email)
    c.post("/api/auth/totp/setup", json={"password": PW})  # never confirmed
    assert login(TestClient(app_module.app), email).status_code == 200


def test_me_reports_whether_two_step_is_on():
    email = make_user("ADMIN", "t8")
    c = TestClient(app_module.app)
    login(c, email)
    assert c.get("/api/auth/me").json()["totp"] is False


# ---------------- sessions ----------------

def test_sessions_are_stored_hashed():
    uid = db.get_user_by_email(make_user("VERIFIER", "s1"))["id"]
    token = db.create_session(uid)
    import sqlite3
    raw = [r[0] for r in sqlite3.connect(db.DB_PATH).execute("SELECT token FROM sessions").fetchall()]
    assert token not in raw and db._session_key(token) in raw
    assert db.get_session_user(token)["id"] == uid
    db.delete_session(token)
    assert db.get_session_user(token) is None


def test_admin_sessions_are_shorter_than_reviewer_sessions():
    import sqlite3
    a = db.get_user_by_email(make_user("ADMIN", "s2"))["id"]
    v = db.get_user_by_email(make_user("VERIFIER", "s3"))["id"]
    ta, tv = db.create_session(a), db.create_session(v)
    conn = sqlite3.connect(db.DB_PATH)
    exp = lambda t: conn.execute("SELECT expires_at FROM sessions WHERE token = ?", (db._session_key(t),)).fetchone()[0]
    now = time.time()
    assert exp(ta) - now <= db.ADMIN_SESSION_TTL_SECONDS + 5 and db.ADMIN_SESSION_TTL_SECONDS == 12 * 3600
    assert exp(tv) - now <= db.SESSION_TTL_SECONDS + 5 and db.SESSION_TTL_SECONDS == 7 * 86400


# ---------------- deleting a report leaves a record ----------------

def _report():
    rid = db.insert_report(source="user", external_id=f"f-{os.urandom(4).hex()}", title="Secret title text",
                           body="private body", category="banned_symbol", reason="private reason",
                           evidence="private evidence", law=None, impact="", lat=52.5, lon=13.4,
                           place="x", status="verified")
    assert rid
    return rid


def test_a_deleted_report_leaves_who_when_and_which_fields_but_no_content():
    rid = _report()
    db.update_report_fields(rid, {"title": "Edited secret title"}, edited_by="mod@example.org")
    admin_email = make_user("ADMIN", "d1")
    c = TestClient(app_module.app)
    login(c, admin_email)
    assert c.delete(f"/api/admin/reports/{rid}").status_code == 200
    assert db.get_report(rid) is None and db.get_report_history(rid) == []
    rec = next(d for d in c.get("/api/admin/deletions").json()["deletions"] if d["report_id"] == rid)
    assert rec["deleted_by"] == admin_email and rec["category"] == "banned_symbol"
    assert any(h["field"] == "title" and h["edited_by"] == "mod@example.org" for h in rec["history"])
    flat = str(rec)
    for secret_text in ("Secret title text", "Edited secret title", "private body", "private reason", "private evidence"):
        assert secret_text not in flat


def test_deleting_an_unknown_report_is_404_and_records_nothing():
    c = TestClient(app_module.app)
    login(c, make_user("ADMIN", "d2"))
    before = len(db.list_report_deletions())
    assert c.delete("/api/admin/reports/99999999").status_code == 404
    assert len(db.list_report_deletions()) == before


def test_only_admins_read_the_deletion_record():
    v = TestClient(app_module.app)
    login(v, make_user("VERIFIER", "d3"))
    assert v.get("/api/admin/deletions").status_code == 403


# ---------------- scraper cap ----------------

def test_one_source_cannot_add_more_than_the_cap_in_one_beat(monkeypatch):
    monkeypatch.setattr(agent, "MAX_NEW_PER_SOURCE_PER_BEAT", 5)
    items = [
        {"title": "Neonazis zeigen Hakenkreuz und rufen Sieg Heil in Dortmund", "body": "x",
         "url": f"https://example.social/@x/cap{i}", "external_id": f"cap-{i}"}
        for i in range(40)
    ]

    async def adapter(_client):
        return items

    asyncio.run(agent.run_one_source("capsource", adapter, None))
    import sqlite3
    n = sqlite3.connect(db.DB_PATH).execute("SELECT count(*) FROM reports WHERE source = 'capsource'").fetchone()[0]
    assert n == 5


def test_the_heartbeat_says_when_a_source_was_capped(monkeypatch):
    monkeypatch.setattr(agent, "MAX_NEW_PER_SOURCE_PER_BEAT", 2)
    items = [
        {"title": "Neonazis zeigen Hakenkreuz und rufen Sieg Heil in Dortmund", "body": "x",
         "url": f"https://example.social/@x/hb{i}", "external_id": f"hb-{i}"}
        for i in range(10)
    ]

    async def adapter(_client):
        return items

    asyncio.run(agent.run_one_source("hbsource", adapter, None))
    import sqlite3
    detail = sqlite3.connect(db.DB_PATH).execute(
        "SELECT detail FROM heartbeats WHERE source = 'hbsource' ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert "stored=2" in detail and "CAPPED" in detail


# ---------------- review round: stolen sessions, races, migration ----------------

def test_a_stolen_session_cannot_enrol_its_own_authenticator():
    email = make_user("ADMIN", "r1")
    thief = TestClient(app_module.app)
    login(thief, email)  # holds a session, does not know the password
    assert thief.post("/api/auth/totp/setup", json={"password": "wrong-password-1"}).status_code == 403
    assert db.get_totp(db.get_user_by_email(email)["id"])["totp_secret"] is None
    assert thief.post("/api/auth/totp/setup", json={}).status_code == 422


def test_turning_two_step_on_or_off_ends_the_other_sessions():
    email = make_user("VERIFIER", "r2")
    mine, other = TestClient(app_module.app), TestClient(app_module.app)
    login(mine, email); login(other, email)
    assert other.get("/api/auth/me").status_code == 200
    secret = mine.post("/api/auth/totp/setup", json={"password": PW}).json()["secret"]
    mine.post("/api/auth/totp/enable", json={"code": now_code(secret)})
    assert mine.get("/api/auth/me").status_code == 200     # the session making the change stays
    assert other.get("/api/auth/me").status_code == 401    # every other session is gone


def test_an_admin_can_reset_a_reviewers_two_step_and_it_is_logged():
    email = make_user("VERIFIER", "r3")
    enrol(email)
    admin = TestClient(app_module.app)
    login(admin, make_user("ADMIN", "r3"))
    uid = db.get_user_by_email(email)["id"]
    assert admin.post(f"/api/admin/users/{uid}/totp/reset").status_code == 200
    assert login(TestClient(app_module.app), email).status_code == 200  # password alone again
    import sqlite3
    row = sqlite3.connect(db.DB_PATH).execute(
        "SELECT actor, action, target FROM admin_actions ORDER BY id DESC LIMIT 1").fetchone()
    assert row == (make_user("ADMIN", "r3"), "totp_reset", email)
    v = TestClient(app_module.app)
    login(v, make_user("VERIFIER", "r3b"))
    assert v.post(f"/api/admin/users/{uid}/totp/reset").status_code == 403


def test_two_logins_racing_with_the_same_code_cannot_both_win():
    uid = db.get_user_by_email(make_user("ADMIN", "r4"))["id"]
    db.set_totp_pending(uid, totp.new_secret())
    db.enable_totp(uid, 100)
    assert db.claim_totp_step(uid, 101) is True
    assert db.claim_totp_step(uid, 101) is False   # same step again
    assert db.claim_totp_step(uid, 100) is False   # an older step
    assert db.claim_totp_step(uid, 102) is True


def test_guessing_codes_from_many_addresses_is_stopped_per_account():
    email = make_user("ADMIN", "r5")
    secret = enrol(email)
    c = TestClient(app_module.app)
    for _ in range(security.TOTP_MAX_FAILS):
        assert login(c, email, "000000").status_code == 401        # a new address every time
    r = login(c, email, now_code(secret, 1))                       # even the RIGHT code now waits
    assert r.status_code == 429


def test_the_code_lock_never_applies_before_the_password_is_right():
    email = make_user("ADMIN", "r6")
    enrol(email)
    uid = db.get_user_by_email(email)["id"]
    for _ in range(security.TOTP_MAX_FAILS):
        security.totp_failed(uid)
    wrong_pw = TestClient(app_module.app).post(
        "/api/auth/login", json={"email": email, "password": "wrong-password-1"}, headers=visitor())
    assert wrong_pw.status_code == 401 and wrong_pw.json()["detail"] == "Wrong email or password"


def test_changing_a_role_ends_that_users_sessions():
    uid = db.get_user_by_email(make_user("VERIFIER", "r7"))["id"]
    token = db.create_session(uid)
    assert db.get_session_user(token)
    db.update_user_role(uid, "ADMIN")
    assert db.get_session_user(token) is None
    db.update_user_role(uid, "VERIFIER")


def test_the_admin_cookie_lifetime_matches_the_admin_session():
    c = TestClient(app_module.app)
    r = login(c, make_user("ADMIN", "r8"))
    assert f"Max-Age={db.ADMIN_SESSION_TTL_SECONDS}" in r.headers["set-cookie"]
    r = login(TestClient(app_module.app), make_user("VERIFIER", "r8"))
    assert f"Max-Age={db.SESSION_TTL_SECONDS}" in r.headers["set-cookie"]


def test_the_old_users_table_rebuild_keeps_every_column(tmp_path):
    """An old production database still has the CHECK(role...) users table; the
    rebuild must not drop the consent record or the two-step columns."""
    import sqlite3, subprocess
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.executescript("""
    CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('ADMIN','VERIFIER')),
      created_at INTEGER NOT NULL);
    INSERT INTO users (email, password_hash, role, created_at) VALUES ('old@example.org','x$y','ADMIN',1);
    """)
    c.commit(); c.close()
    code = (
        "import sys, sqlite3; sys.path.insert(0,'backend'); import db; db.init_db();"
        "c=sqlite3.connect(db.DB_PATH); cols=[r[1] for r in c.execute('PRAGMA table_info(users)')];"
        "print(','.join(cols)); print(c.execute('SELECT email,role FROM users').fetchall())"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=os.path.join(os.path.dirname(__file__), ".."),
                         env={**os.environ, "DXMAP_DB_PATH": str(path)}, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    cols_line, rows_line = out.stdout.strip().splitlines()[-2:]
    for col in ("accepted_terms_at", "totp_secret", "totp_enabled", "totp_last_step", "provider"):
        assert col in cols_line.split(",")
    assert "old@example.org" in rows_line


def test_pre_hashing_session_rows_are_removed_at_startup(tmp_path):
    import sqlite3, subprocess
    path = tmp_path / "s.db"
    code = (
        "import sys, sqlite3; sys.path.insert(0,'backend'); import db; db.init_db();"
        "c=sqlite3.connect(db.DB_PATH); c.execute(\"INSERT INTO users (email,password_hash,role,created_at) VALUES ('u@e.org','x$y','NONE',1)\");"
        "c.execute(\"INSERT INTO sessions (token,user_id,expires_at) VALUES ('rawtoken',1,9999999999)\"); c.commit(); c.close();"
        "db.init_db(); c=sqlite3.connect(db.DB_PATH); print(c.execute('SELECT count(*) FROM sessions').fetchone()[0])"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=os.path.join(os.path.dirname(__file__), ".."),
                         env={**os.environ, "DXMAP_DB_PATH": str(path)}, capture_output=True, text=True)
    assert out.stdout.strip().splitlines()[-1] == "0", out.stderr


def test_the_deletion_record_keeps_only_known_category_names():
    rid = db.insert_report(source="user", external_id=f"c-{os.urandom(4).hex()}", title="t t t", body="b",
                           category="banned_symbol,my home address is 12 Example Street", reason="r", evidence="",
                           law=None, impact="", lat=52.5, lon=13.4, place="x", status="verified")
    db.delete_report(rid, deleted_by="admin@example.org")
    rec = next(d for d in db.list_report_deletions() if d["report_id"] == rid)
    assert rec["category"] == "banned_symbol"
    assert "Example Street" not in str(rec)


def test_old_deletion_records_are_removed_after_a_year():
    import sqlite3
    c = sqlite3.connect(db.DB_PATH)
    c.execute("INSERT INTO report_deletions (report_id, deleted_by, deleted_at, history) VALUES (777, 'a@b.c', ?, '[]')",
              (int(time.time()) - 366 * 86400,))
    c.commit(); c.close()
    assert not any(d["report_id"] == 777 for d in db.list_report_deletions())


def test_a_feed_that_fits_under_the_cap_is_not_reported_as_capped(monkeypatch):
    monkeypatch.setattr(agent, "MAX_NEW_PER_SOURCE_PER_BEAT", 3)
    items = [{"title": "Neonazis zeigen Hakenkreuz und rufen Sieg Heil in Dortmund", "body": "x",
              "url": f"https://example.social/@x/fit{i}", "external_id": f"fit-{i}"} for i in range(3)]

    async def adapter(_client):
        return items

    asyncio.run(agent.run_one_source("fitsource", adapter, None))
    import sqlite3
    detail = sqlite3.connect(db.DB_PATH).execute(
        "SELECT detail FROM heartbeats WHERE source = 'fitsource' ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert "stored=3" in detail and "CAPPED" not in detail


def test_the_vanilla_page_sends_the_edit_token_in_a_header():
    html = open(os.path.join(os.path.dirname(__file__), "..", "frontend", "index-vanilla.html")).read()
    assert "?edit_token=" not in html and "X-Edit-Token" in html
