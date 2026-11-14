"""
Phase 2 (2026-11): "verified" on the public map means a person checked it.

- The public feed shows only human_verified rows. A row a script marked
  'verified' stays off the public map.
- /api/health counts human-verified rows on their own.
- Scraped titles and bodies are stored with HTML entities decoded.
- @handles are removed from public text, never from the reviewer view.
- The cleanup script moves script-verified rows back to the review queue
  through db.set_status, so a restart cannot republish them.
- Wikipedia topic articles are not scraped by default.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import app as app_module  # noqa: E402
import db  # noqa: E402
from test_audit_api import logged_in, new_client, verified_report, visitor  # noqa: E402

db.init_db()
app_module.SERVICE_TOKEN = "test-service-token"
ROOT = os.path.join(os.path.dirname(__file__), "..")


def public_ids():
    rows = new_client().get("/api/reports?limit=5000&all=true", headers=visitor()).json()["reports"]
    return {r["id"]: r for r in rows}


def human(rid):
    assert db.set_status(rid, "verified", edited_by="reviewer@dxmap-tests.example-org.dev", by_human=True)
    return rid


def test_script_verified_row_is_not_public():
    rid = verified_report("violence", human=False)
    assert rid not in public_ids()


def test_human_verified_row_is_public():
    rid = human(verified_report("violence", status="unverified", human=False))
    assert rid in public_ids()


def test_reviewers_still_see_script_verified_rows():
    rid = verified_report("violence", human=False)
    rows = logged_in("ADMIN", "p2a").get("/api/reports?limit=5000&all=true").json()["reports"]
    assert rid in {r["id"] for r in rows}


def test_health_counts_human_verified():
    before = db.stats()["human_verified"]
    human(verified_report("arson", status="unverified", human=False))
    assert db.stats()["human_verified"] == before + 1


def test_scraped_text_is_stored_with_entities_decoded():
    rid = db.insert_report(source="mastodon", external_id=f"p2-{os.urandom(4).hex()}",
                           title="called him &quot;x&quot; &amp; left", body="a &lt;b&gt; &#39;c&#39;",
                           url="https://example.social/@a/" + os.urandom(4).hex(), category="racism",
                           reason="r", status="unverified")
    row = db.get_report(rid)
    assert row["title"] == 'called him "x" & left'
    assert row["body"] == "a <b> 'c'"


def test_user_text_is_kept_as_typed():
    rid = verified_report("racism", title="Tom &amp; Jerry", human=False)
    assert db.get_report(rid)["title"] == "Tom &amp; Jerry"


def test_handles_are_removed_from_public_text_only():
    rid = human(verified_report("violence", status="unverified", human=False, source="mastodon",
                                title="Attack reported by @someone and @user@example.social",
                                body="mail a@b.org stays, @x_y.z goes"))
    pub = public_ids()[rid]
    assert "@someone" not in pub["title"] and "@user@example.social" not in pub["title"]
    assert pub["title"] == "Attack reported by @… and @…"
    assert pub["body"] == "mail a@b.org stays, @… goes"
    rows = logged_in("ADMIN", "p2b").get("/api/reports?limit=5000&all=true").json()["reports"]
    seen = next(r for r in rows if r["id"] == rid)
    assert "@someone" in seen["title"]


def test_wikipedia_source_is_off_by_default():
    import agent
    if os.environ.get("DXMAP_WIKIPEDIA") is None:
        assert agent.WIKIPEDIA_ENABLED is False


def _run_cleanup(*args):
    return subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "cleanup_script_verified.py"), *args],
                          capture_output=True, text=True, env={**os.environ, "DXMAP_DB_PATH": db.DB_PATH})


def test_cleanup_dry_run_changes_nothing_and_confirm_moves_rows_for_good():
    bulk = verified_report("assembly", human=False, source="bluesky", title="x &amp; y")
    kept = human(verified_report("assembly", status="unverified", human=False))

    dry = _run_cleanup()
    assert dry.returncode == 0, dry.stderr
    assert db.get_report(bulk)["status"] == "verified"

    done = _run_cleanup("--confirm")
    assert done.returncode == 0, done.stderr
    row = db.get_report(bulk)
    assert row["status"] == "unverified" and row["verified"] == 0 and row["human_verified"] == 0
    assert row["title"] == "x & y"
    hist = [h for h in db.get_report_history(bulk) if h["field"] == "status"]
    assert hist[0]["edited_by"] == "cleanup-2026-11" and hist[0]["new_value"] == "unverified"
    assert db.get_report(kept)["status"] == "verified" and db.get_report(kept)["human_verified"] == 1

    db.init_db()  # what every container start runs
    assert db.get_report(bulk)["status"] == "unverified"
    assert db.get_report(kept)["human_verified"] == 1


def test_review_queue_lists_located_rows_first():
    located = db.insert_report(source="bluesky", external_id=f"p2q-{os.urandom(4).hex()}", title="place",
                               body="b", url="https://bsky.app/x/" + os.urandom(4).hex(), category="arson",
                               reason="r", status="unverified", lat=52.5, lon=13.4, place="Berlin",
                               created_at=1_700_000_000)
    unlocated = db.insert_report(source="bluesky", external_id=f"p2q-{os.urandom(4).hex()}", title="no place",
                                 body="b", url="https://bsky.app/x/" + os.urandom(4).hex(), category="arson",
                                 reason="r", status="unverified", created_at=1_800_000_000)
    # located is older, so newest-first alone would put it after the unlocated one
    q = new_client().get("/api/service/review-queue?limit=1000",
                         headers={"X-Service-Token": "test-service-token"}).json()
    ids = [r["id"] for r in q["reports"]]
    assert ids.index(located) < ids.index(unlocated)
    first_unlocated = next(i for i, r in enumerate(q["reports"]) if r["lat"] is None)
    assert all(r["lat"] is not None for r in q["reports"][:first_unlocated])


app_module  # imported for its side effects (routes)
