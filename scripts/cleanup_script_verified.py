"""
Move rows a script marked 'verified' back to the review queue (2026-11 cleanup).

The 2026-09-01 bulk run set status='verified' on every located report without
a person looking at it. The public map now shows only human_verified rows, so
those rows are already off the map. This moves them back to 'unverified' so
the review queue lists them again, and decodes HTML entities (&quot; &amp;) in
scraped text that was stored before decoding moved into insert_report.

Goes through db.set_status, never a raw UPDATE of status: init_db() promotes
any row with verified=1 and status 'unverified' back to 'verified' on every
start, and set_status clears verified=0. Each move is logged in report_history
as edited_by='cleanup-2026-11'. Rows a person verified are not touched.

Dry run by default. Writes only with --confirm.

    DXMAP_DB_PATH=/app/data/dxmap.db python scripts/cleanup_script_verified.py
    DXMAP_DB_PATH=/app/data/dxmap.db python scripts/cleanup_script_verified.py --confirm

In the container (the image has no scripts/): docker compose cp the file to
/tmp and run it from /app, the working directory, so it finds backend/db.py.
"""
import html
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# repo layout (scripts/ next to backend/), or a copy run from the container's /app
for candidate in (os.path.join(HERE, "..", "backend"), os.path.join(HERE, ".."),
                  os.path.join(os.getcwd(), "backend")):
    if os.path.exists(os.path.join(candidate, "db.py")):
        sys.path.insert(0, candidate)
        break

import db  # noqa: E402

EDITOR = "cleanup-2026-11"


def main() -> int:
    confirm = "--confirm" in sys.argv[1:]
    print(f"database: {db.DB_PATH}")
    print("mode:", "WRITE" if confirm else "dry run (pass --confirm to write)")
    with db._conn() as conn:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM reports WHERE status = 'verified' AND human_verified = 0 ORDER BY id")]
        kept = conn.execute(
            "SELECT COUNT(*) c FROM reports WHERE status = 'verified' AND human_verified = 1").fetchone()["c"]
        texts = [dict(r) for r in conn.execute(
            "SELECT id, title, body, reason FROM reports WHERE source != 'user' AND ("
            " title LIKE '%&%;%' OR body LIKE '%&%;%' OR reason LIKE '%&%;%')")]
    fixes = []
    for r in texts:
        new = {k: html.unescape(r[k]) for k in ("title", "body", "reason") if r[k]}
        if any(new[k] != r[k] for k in new):
            fixes.append((r["id"], new))
    print(f"script-verified rows to move back to review: {len(ids)}")
    print(f"human-verified rows left as they are: {kept}")
    print(f"scraped rows with HTML entities to decode: {len(fixes)}")
    if not confirm:
        return 0

    moved = sum(1 for rid in ids if db.set_status(rid, "unverified", edited_by=EDITOR))
    with db._conn() as conn:
        for rid, new in fixes:
            sets = ", ".join(f"{k} = ?" for k in new)
            conn.execute(f"UPDATE reports SET {sets} WHERE id = ?", (*new.values(), rid))

    db.init_db()  # what every container start runs: nothing may come back
    with db._conn() as conn:
        left = conn.execute(
            "SELECT COUNT(*) c FROM reports WHERE status = 'verified' AND human_verified = 0").fetchone()["c"]
        human = conn.execute(
            "SELECT COUNT(*) c FROM reports WHERE status = 'verified' AND human_verified = 1").fetchone()["c"]
    print(f"moved: {moved}, decoded: {len(fixes)}")
    print(f"after a simulated restart: script-verified left {left}, human-verified {human}")
    if left or human != kept:
        print("CHECK FAILED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
