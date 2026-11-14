"""
"Human verified" must be literally true: only a real moderator review earns it.
Migration/backfill on a pre-column database, every path that does or does not
set the flag, and the API shape.
"""
import os
import sqlite3
import sys
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ.setdefault("DXMAP_DB_PATH", _TMP.name)
os.environ["DXMAP_SERVICE_TOKEN"] = "test-service-token"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest  # noqa: E402

import app as app_module  # noqa: E402
import db  # noqa: E402
from test_audit_api import logged_in, new_client, verified_report, visitor  # noqa: E402

db.init_db()
app_module.SERVICE_TOKEN = "test-service-token"
SVC = {"X-Service-Token": "test-service-token"}
MOD = "vol_" + "a" * 32


def flag(rid):
    r = db.get_report(rid)
    return bool(r["human_verified"]), r["human_verified_at"]


def unverified():
    return db.insert_report(source="user", external_id=f"hv-{os.urandom(4).hex()}", title="t", body="b",
                            url="https://example.org/" + os.urandom(4).hex(), category="banned_symbol",
                            status="unverified")


# ---- migration + backfill ---------------------------------------------------

def test_migration_adds_columns_and_backfills_human_only(tmp_path, monkeypatch):
    path = str(tmp_path / "old.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    ids = {}
    for name in ("bulk", "admin", "pantheon", "self", "unknown", "reverted", "reverified_by_script"):
        ids[name] = db.insert_report(source="user", external_id=name, title=name, url=f"https://e.org/{name}",
                                     status="verified")
    ids["dismissed"] = db.insert_report(source="user", external_id="dismissed", title="d",
                                        url="https://e.org/dismissed", status="dismissed")
    with sqlite3.connect(path) as c:
        # Simulate the production DB from before the columns existed.
        c.execute("ALTER TABLE reports DROP COLUMN human_verified")
        c.execute("ALTER TABLE reports DROP COLUMN human_verified_at")

        def hist(name, who, old, new, at):
            c.execute("INSERT INTO report_history (report_id, edited_by, field, old_value, new_value, edited_at)"
                      " VALUES (?, ?, 'status', ?, 'verified', ?)" if new == "verified" else
                      "INSERT INTO report_history (report_id, edited_by, field, old_value, new_value, edited_at)"
                      " VALUES (?, ?, 'status', ?, '" + new + "', ?)", (ids[name], who, old, at))
        hist("admin", "boss@example.org", "unverified", "verified", 1000)
        hist("pantheon", f"pantheon:{MOD}", "unverified", "verified", 2000)
        hist("self", "self", "unverified", "verified", 3000)
        hist("unknown", "unknown", "unverified", "verified", 4000)
        hist("reverted", "boss@example.org", "unverified", "verified", 5000)
        hist("reverted", "boss@example.org", "verified", "unverified", 6000)
        hist("reverted", "unknown", "unverified", "verified", 7000)   # latest is a non-human re-verify
        hist("reverified_by_script", "boss@example.org", "unverified", "verified", 8000)
        hist("dismissed", "boss@example.org", "unverified", "verified", 9000)  # not verified now
        # "bulk" has no history row at all.
    db.init_db()
    cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(reports)")}
    assert {"human_verified", "human_verified_at"} <= cols
    got = {n: flag(i) for n, i in ids.items()}
    assert got["admin"] == (True, 1000)
    assert got["pantheon"] == (True, 2000)
    for n in ("bulk", "self", "unknown", "reverted", "dismissed"):
        assert got[n][0] is False, n
    assert got["reverified_by_script"] == (True, 8000)
    # Idempotent: a second start changes nothing, including a flag cleared since.
    db.set_status(ids["admin"], "unverified", edited_by="boss@example.org")
    db.init_db()
    assert flag(ids["admin"]) == (False, None)
    assert flag(ids["pantheon"]) == (True, 2000)


# ---- paths that set it ------------------------------------------------------

def test_admin_set_status_endpoint_sets_flag():
    rid = unverified()
    admin = logged_in("ADMIN", "hv1")
    assert admin.patch(f"/api/admin/reports/{rid}", json={"status": "verified"}).status_code == 200
    ok, at = flag(rid)
    assert ok and at
    assert admin.patch(f"/api/admin/reports/{rid}", json={"status": "unverified"}).status_code == 200
    assert flag(rid) == (False, None)


def test_pantheon_review_sets_flag_and_dismiss_clears():
    rid = unverified()
    c = new_client()
    r = c.post(f"/api/service/review/{rid}", json={"status": "verified", "moderator": MOD}, headers=SVC)
    assert r.status_code == 200 and flag(rid)[0] is True
    r = c.post(f"/api/service/review/{rid}", json={"status": "dismissed", "moderator": MOD}, headers=SVC)
    assert r.status_code == 200 and flag(rid) == (False, None)


def test_human_review_of_bulk_verified_report_earns_flag():
    rid = verified_report("banned_symbol", human=False)
    assert flag(rid)[0] is False
    admin = logged_in("ADMIN", "hv2")
    assert admin.patch(f"/api/admin/reports/{rid}", json={"status": "verified"}).status_code == 200
    assert flag(rid)[0] is True
    assert any(h["field"] == "status" for h in db.get_report_history(rid))


def test_human_verified_at_is_not_moved_by_a_second_review():
    rid = unverified()
    db.set_status(rid, "verified", edited_by="a@example.org", by_human=True)
    first = flag(rid)[1]
    with db._conn() as conn:
        conn.execute("UPDATE reports SET human_verified_at = ? WHERE id = ?", (first - 500, rid))
    db.set_status(rid, "verified", edited_by="b@example.org", by_human=True)
    assert flag(rid)[1] == first - 500


# ---- paths that must NOT set it ---------------------------------------------

def test_set_status_and_set_verified_default_never_set_flag():
    rid = unverified()
    db.set_status(rid, "verified")
    assert flag(rid)[0] is False
    rid2 = unverified()
    db.set_verified(rid2, True)
    assert flag(rid2)[0] is False
    rid3 = unverified()
    db.set_verified(rid3, True, by_human=True)
    assert flag(rid3)[0] is True
    db.set_verified(rid3, False)
    assert flag(rid3) == (False, None)


def test_a_script_cannot_keep_the_flag_by_reverifying_after_a_revert():
    rid = unverified()
    db.set_status(rid, "verified", edited_by="a@example.org", by_human=True)
    db.set_status(rid, "unverified", edited_by="a@example.org", by_human=True)
    db.set_status(rid, "verified", edited_by="unknown")
    assert flag(rid)[0] is False


def test_insert_report_as_verified_is_not_human_verified():
    assert flag(verified_report("banned_symbol", human=False))[0] is False


def test_moderator_field_edit_does_not_set_flag():
    rid = verified_report("banned_symbol", human=False)
    admin = logged_in("ADMIN", "hv3")
    assert admin.patch(f"/api/admin/reports/{rid}/fields", json={"title": "Better title"}).status_code == 200
    db.update_report_fields(rid, {"title": "Edited"}, edited_by="boss@example.org")
    assert flag(rid)[0] is False


def test_moderator_reedit_of_human_verified_report_keeps_but_does_not_create():
    rid = unverified()
    db.update_report_fields(rid, {"title": "x2"}, edited_by="boss@example.org")
    db.set_status(rid, "verified", edited_by="unknown")
    assert flag(rid)[0] is False
    db.update_report_fields(rid, {"title": "x3"}, edited_by="boss@example.org")
    assert flag(rid)[0] is False


def test_anonymous_self_edit_cannot_set_flag():
    c = new_client()
    r = c.post("/api/reports", json={"title": "Self filed", "body": "b", "category": "banned_symbol",
                                     "reason": "a reason", "evidence": "", "impact": "", "lat": 52.5, "lon": 13.4,
                                     "place": "x"}, headers=visitor())
    assert r.status_code == 201, r.text
    rid, tok = r.json()["id"], r.json()["edit_token"]
    r2 = c.patch(f"/api/reports/{rid}", json={"edit_token": tok, "title": "Edited title", "status": "verified",
                                              "human_verified": True}, headers=visitor())
    assert r2.status_code == 200, r2.text
    assert flag(rid)[0] is False
    assert db.get_report(rid)["status"] != "verified"


# ---- API shape ---------------------------------------------------------------

def test_public_feed_and_single_report_expose_human_verified_bool():
    bulk = verified_report("banned_symbol", human=False)
    human = verified_report("banned_symbol", human=False)
    db.set_status(human, "verified", edited_by="boss@example.org", by_human=True)
    feed = {r["id"]: r for r in new_client().get("/api/reports", headers=visitor()).json()["reports"]}
    assert bulk not in feed  # since 2026-11 the public map shows human-verified rows only
    assert feed[human]["status"] == "verified" and feed[human]["human_verified"] is True
    assert "human_verified_at" in feed[human]
    for k in ("edited_by", "moderator"):
        assert k not in feed[human]


def test_admin_listing_and_review_queue_have_the_field():
    rid = unverified()
    admin = logged_in("ADMIN", "hv4")
    rows = admin.get("/api/admin/reports?status=unverified").json()["reports"]
    assert all(isinstance(r["human_verified"], bool) for r in rows)
    q = new_client().get("/api/service/review-queue", headers=SVC).json()["reports"]
    assert all(isinstance(r["human_verified"], bool) for r in q)
    assert any(r["id"] == rid for r in q)


def test_single_report_endpoint_shape():
    c = new_client()
    r = c.post("/api/reports", json={"title": "Single", "body": "b", "category": "banned_symbol",
                                     "reason": "a reason", "evidence": "", "impact": "", "lat": 52.5, "lon": 13.4,
                                     "place": "x"}, headers=visitor())
    rid, tok = r.json()["id"], r.json()["edit_token"]
    got = c.get(f"/api/reports/{rid}", headers={"X-Edit-Token": tok, **visitor()}).json()
    assert "edit_token" not in got
    assert got["human_verified"] is False


def test_backfill_heals_a_crash_between_alter_and_update_and_is_idempotent(tmp_path, monkeypatch):
    path = str(tmp_path / "crash.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    human = db.insert_report(source="user", external_id="h", title="h", url="https://e.org/h", status="verified")
    bulk = db.insert_report(source="user", external_id="b", title="b", url="https://e.org/b", status="verified")
    with sqlite3.connect(path) as c:
        c.execute("INSERT INTO report_history (report_id, edited_by, field, old_value, new_value, edited_at)"
                  " VALUES (?, 'boss@example.org', 'status', 'unverified', 'verified', 777)", (human,))
    # The column exists (ALTER committed) but the process died before the UPDATE.
    assert flag(human) == (False, None)
    db.init_db()                       # restart: not "first time", must still backfill
    assert flag(human) == (True, 777) and flag(bulk) == (False, None)
    with sqlite3.connect(path) as c:
        before = c.execute("SELECT id, human_verified, human_verified_at FROM reports ORDER BY id").fetchall()
    db.init_db()
    db.init_db()
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT id, human_verified, human_verified_at FROM reports ORDER BY id").fetchall() == before
