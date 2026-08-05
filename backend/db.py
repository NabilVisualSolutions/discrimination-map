"""
Persistence layer for Discrimination Map.

Uses SQLite in WAL mode: zero-config, genuinely persistent on disk, and safe
for the concurrent reads (API) + writes (agent) this app does. Swap the
connection factory for Postgres later without touching the API surface.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

# DB lives next to the app data, NOT under any web-served directory.
DB_PATH = os.environ.get("DXMAP_DB_PATH", os.path.join(os.path.dirname(__file__), "dxmap.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT    NOT NULL,          -- 'bluesky', 'mastodon', 'user', ...
    external_id  TEXT,                       -- source's own id, for dedupe
    title        TEXT    NOT NULL,
    body         TEXT,
    url          TEXT,
    category     TEXT    DEFAULT 'general',
    -- Documentation fields (the four asked-for annotations):
    reason       TEXT,                       -- why this is flagged (alleged)
    evidence     TEXT,                       -- the proof: source text / link
    law          TEXT,                       -- possibly-applicable statute code
    impact       TEXT,                       -- harm / "terror" described
    verified     INTEGER NOT NULL DEFAULT 0, -- 1 once a human confirms it
    lat          REAL,
    lon          REAL,
    place        TEXT,                       -- resolved place name, if any
    located      INTEGER NOT NULL DEFAULT 0, -- 1 if lat/lon are set
    created_at   INTEGER NOT NULL,           -- unix seconds
    UNIQUE(source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_reports_created ON reports(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reports_located ON reports(located);
CREATE INDEX IF NOT EXISTS idx_reports_url ON reports(url);

CREATE TABLE IF NOT EXISTS heartbeats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at      INTEGER NOT NULL,
    source      TEXT    NOT NULL,
    ok          INTEGER NOT NULL,
    found       INTEGER NOT NULL DEFAULT 0,
    latency_ms  INTEGER,
    detail      TEXT
);
CREATE INDEX IF NOT EXISTS idx_heartbeats_ran ON heartbeats(ran_at DESC);
"""


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    """Yield a connection with sane pragmas and row access by name."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables/indexes if they do not exist. Safe to call repeatedly."""
    with _conn() as conn:
        conn.executescript(_SCHEMA)


def insert_report(
    *,
    source: str,
    title: str,
    body: Optional[str] = None,
    url: Optional[str] = None,
    category: str = "general",
    external_id: Optional[str] = None,
    reason: Optional[str] = None,
    evidence: Optional[str] = None,
    law: Optional[str] = None,
    impact: Optional[str] = None,
    verified: bool = False,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    place: Optional[str] = None,
) -> Optional[int]:
    """
    Insert a report. Returns the new row id, or None if it was a duplicate
    (same source + external_id, OR same url — the latter catches the same
    post getting federated across Mastodon instances under different
    instance-local external_ids, which the UNIQUE constraint alone misses).
    Never raises on duplicates.
    """
    located = 1 if (lat is not None and lon is not None) else 0
    normalized_url = url.strip().rstrip("/") if url else None
    try:
        with _conn() as conn:
            if normalized_url:
                existing = conn.execute(
                    "SELECT id FROM reports WHERE url = ? LIMIT 1", (normalized_url,)
                ).fetchone()
                if existing is not None:
                    return None
            cur = conn.execute(
                """
                INSERT INTO reports
                    (source, external_id, title, body, url, category,
                     reason, evidence, law, impact, verified,
                     lat, lon, place, located, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (source, external_id, title, body, normalized_url, category,
                 reason, evidence, law, impact, 1 if verified else 0,
                 lat, lon, place, located, int(time.time())),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        # UNIQUE(source, external_id) collision -> already have it.
        return None


def set_location(report_id: int, lat: float, lon: float, place: str) -> None:
    """Attach coordinates to a previously-unlocated report."""
    with _conn() as conn:
        conn.execute(
            "UPDATE reports SET lat=?, lon=?, place=?, located=1 WHERE id=?",
            (lat, lon, place, report_id))


def list_reports(limit: int = 500, located_only: bool = True) -> list[dict[str, Any]]:
    """Return recent reports as plain dicts, newest first."""
    q = "SELECT * FROM reports"
    if located_only:
        q += " WHERE located = 1"
    q += " ORDER BY created_at DESC LIMIT ?"
    with _conn() as conn:
        rows = conn.execute(q, (limit,)).fetchall()
    return [dict(r) for r in rows]


def list_reports_admin(
    limit: int = 100, offset: int = 0, verified: Optional[bool] = None,
) -> dict[str, Any]:
    """
    Every report (located or not), newest first, for the moderation queue.
    `verified` filters to only-verified or only-unverified when given.
    """
    where = ""
    params: list[Any] = []
    if verified is not None:
        where = " WHERE verified = ?"
        params.append(1 if verified else 0)
    with _conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS n FROM reports{where}", params).fetchone()["n"]
        rows = conn.execute(
            f"SELECT * FROM reports{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
    return {"reports": [dict(r) for r in rows], "total": total}


def set_verified(report_id: int, verified: bool) -> bool:
    """Human moderator confirms (or un-confirms) a report. Returns False if no such row."""
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE reports SET verified = ? WHERE id = ?", (1 if verified else 0, report_id)
        )
        return cur.rowcount > 0


def delete_report(report_id: int) -> bool:
    """Remove a report (spam, false positive, takedown request). Returns False if no such row."""
    with _conn() as conn:
        cur = conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
        return cur.rowcount > 0


def find_url_duplicates() -> list[dict[str, Any]]:
    """
    Reports sharing a non-null url with an earlier row — the case the
    UNIQUE(source, external_id) constraint misses (e.g. the same post
    federated across Mastodon instances under different external_ids).
    Keeps the oldest row per url, flags the rest as duplicates.
    """
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT id, url, created_at FROM reports
            WHERE url IS NOT NULL AND url != ''
            ORDER BY url, created_at ASC
            """
        ).fetchall()
    seen: set[str] = set()
    dupes: list[dict[str, Any]] = []
    for r in rows:
        if r["url"] in seen:
            dupes.append(dict(r))
        else:
            seen.add(r["url"])
    return dupes


def record_heartbeat(
    *, source: str, ok: bool, found: int = 0,
    latency_ms: Optional[int] = None, detail: str = "",
) -> None:
    """Log one source poll for health tracking and the status endpoint."""
    with _conn() as conn:
        conn.execute(
            "INSERT INTO heartbeats (ran_at, source, ok, found, latency_ms, detail)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (int(time.time()), source, 1 if ok else 0, found, latency_ms, detail),
        )


def source_health(window: int = 20) -> dict[str, dict[str, Any]]:
    """
    Compute a rolling health summary per source from the last `window` polls.
    Returns {source: {success_rate, avg_latency_ms, last_ran, streak_fail}}.
    """
    with _conn() as conn:
        sources = [r["source"] for r in
                   conn.execute("SELECT DISTINCT source FROM heartbeats").fetchall()]
        health: dict[str, dict[str, Any]] = {}
        for s in sources:
            rows = conn.execute(
                "SELECT ok, latency_ms, ran_at FROM heartbeats"
                " WHERE source = ? ORDER BY ran_at DESC LIMIT ?",
                (s, window),
            ).fetchall()
            if not rows:
                continue
            oks = [r["ok"] for r in rows]
            lats = [r["latency_ms"] for r in rows if r["latency_ms"] is not None]
            # Consecutive failures from the most recent poll backwards.
            streak = 0
            for ok in oks:
                if ok:
                    break
                streak += 1
            health[s] = {
                "success_rate": round(sum(oks) / len(oks), 3),
                "avg_latency_ms": round(sum(lats) / len(lats)) if lats else None,
                "last_ran": rows[0]["ran_at"],
                "streak_fail": streak,
                "samples": len(rows),
            }
        return health


def stats() -> dict[str, Any]:
    """Quick counts for the status endpoint and self-check."""
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM reports").fetchone()["c"]
        located = conn.execute(
            "SELECT COUNT(*) c FROM reports WHERE located = 1").fetchone()["c"]
        by_source = {
            r["source"]: r["c"] for r in conn.execute(
                "SELECT source, COUNT(*) c FROM reports GROUP BY source").fetchall()
        }
    return {"total": total, "located": located, "by_source": by_source}


if __name__ == "__main__":
    init_db()
    print(f"Initialized DB at {DB_PATH}")
    print(json.dumps(stats(), indent=2))
