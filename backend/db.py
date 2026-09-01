"""
Persistence layer for Discrimination Map.

Uses SQLite in WAL mode: zero-config, genuinely persistent on disk, and safe
for the concurrent reads (API) + writes (agent) this app does. Swap the
connection factory for Postgres later without touching the API surface.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
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
    status       TEXT    NOT NULL DEFAULT 'unverified', -- pending|unverified|verified|dismissed
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

-- Three roles: NONE (self-registered via email/Google, no permissions until
-- an ADMIN promotes them — this is the "only I can assign reviewers" gate),
-- VERIFIER (can verify/dismiss reports), ADMIN (full control, incl. user
-- management + hard delete). No CHECK constraint here on purpose — role
-- validity is enforced in Python (see create_user/update_user_role) so
-- adding a role later never needs a table-rebuild migration again.
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'NONE',
    provider      TEXT    NOT NULL DEFAULT 'email',  -- 'email' | 'google'
    created_at    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT    PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

-- Volunteer / translator / coder / organization-partner applications from
-- the public "Get involved" tab. Reviewed by ADMIN/VERIFIER from the admin
-- panel; not tied to a user account (applicants aren't required to sign up).
CREATE TABLE IF NOT EXISTS applications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    email       TEXT    NOT NULL,
    interest    TEXT    NOT NULL,   -- volunteer | translator | coder | organization | other
    message     TEXT,
    status      TEXT    NOT NULL DEFAULT 'new',  -- new | contacted | closed
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_applications_created ON applications(created_at DESC);

-- Append-only audit trail for report edits. One row per CHANGED field per
-- edit call (a single PATCH touching 3 fields writes 3 rows), so a
-- moderator can see exactly what changed, when, and by whom — without
-- changing who is allowed to edit what (self-edit/moderator-edit rules are
-- unchanged, this only adds a record of what happened).
CREATE TABLE IF NOT EXISTS report_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id   INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    edited_by   TEXT    NOT NULL,   -- 'self' (edit_token holder) or a moderator's email
    field       TEXT    NOT NULL,
    old_value   TEXT,
    new_value   TEXT,
    edited_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_report_history_report ON report_history(report_id, edited_at DESC);
"""

# Additive migrations for columns added after the initial CREATE TABLE, so
# `init_db()` stays safe to run against an already-populated production DB
# (SQLite's ADD COLUMN is a fast metadata-only change, no table rewrite).
_MIGRATIONS: list[tuple[str, str]] = [
    ("reports", "ALTER TABLE reports ADD COLUMN status TEXT NOT NULL DEFAULT 'unverified'"),
    ("reports", "ALTER TABLE reports ADD COLUMN edit_token TEXT"),
    # Links a "Get involved" application to the account created at signup, so
    # an ADMIN can promote the applicant to VERIFIER in one click.
    ("applications", "ALTER TABLE applications ADD COLUMN user_id INTEGER"),
    # When the incident actually happened, as opposed to when it was filed
    # (`created_at`). Lets people report past events; the map timeline and
    # filters read this. Backfilled to created_at for every existing row.
    ("reports", "ALTER TABLE reports ADD COLUMN occurred_at INTEGER"),
    # Records that a self-registered volunteer accepted the Terms + Privacy
    # Policy at signup (unix seconds).
    ("users", "ALTER TABLE users ADD COLUMN accepted_terms_at INTEGER"),
]


def _run_migrations(conn: sqlite3.Connection) -> None:
    for table, ddl in _MIGRATIONS:
        col = ddl.split("ADD COLUMN")[1].strip().split()[0]
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if col not in existing:
            conn.execute(ddl)
    # Backfill status from the legacy `verified` flag for rows written before
    # `status` existed (verified=1 -> 'verified', everything else stays as
    # the column default, 'unverified').
    conn.execute(
        "UPDATE reports SET status = 'verified' WHERE verified = 1 AND status = 'unverified'"
    )
    # Backfill edit_token for pre-existing rows written before that column
    # existed — each gets its own random token so old reports become
    # editable too (nobody has it yet, but a future export/lookup could).
    for row in conn.execute("SELECT id FROM reports WHERE edit_token IS NULL").fetchall():
        conn.execute(
            "UPDATE reports SET edit_token = ? WHERE id = ?",
            (secrets.token_urlsafe(16), row["id"]),
        )
    # Backfill occurred_at = created_at for rows written before that column
    # existed (and for any scraped row that never sets it explicitly).
    conn.execute("UPDATE reports SET occurred_at = created_at WHERE occurred_at IS NULL")
    # Deferred until here because the column above may not exist until the
    # ALTER TABLE loop just ran.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_occurred ON reports(occurred_at)")
    _migrate_users_table(conn)


def _migrate_users_table(conn: sqlite3.Connection) -> None:
    """
    Two changes needed on a `users` table created before self-registration
    existed: add the `provider` column, and drop the old
    `CHECK(role IN ('ADMIN','VERIFIER'))` constraint so a self-registered
    'NONE' role can be inserted. SQLite has no ALTER TABLE DROP CONSTRAINT,
    so the CHECK removal rebuilds the table — `id` values are preserved
    exactly, so `sessions.user_id` stays logically valid.

    Gotcha (hit in production once): by default SQLite's `ALTER TABLE
    RENAME` rewrites *every other table's* FOREIGN KEY clauses that
    reference the renamed table, so `sessions`'s `REFERENCES users(id)`
    silently became `REFERENCES users_old_check(id)` — then that table got
    dropped, leaving every session-creating query failing with "no such
    table: users_old_check". `PRAGMA legacy_alter_table=ON` disables that
    rewrite for the duration of the rename.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "provider" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN provider TEXT NOT NULL DEFAULT 'email'")

    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    if row and row["sql"] and "CHECK" in row["sql"]:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("PRAGMA legacy_alter_table=ON")
        conn.execute("ALTER TABLE users RENAME TO users_old_check")
        conn.execute("""
            CREATE TABLE users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                email         TEXT    NOT NULL UNIQUE,
                password_hash TEXT    NOT NULL,
                role          TEXT    NOT NULL DEFAULT 'NONE',
                provider      TEXT    NOT NULL DEFAULT 'email',
                created_at    INTEGER NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO users (id, email, password_hash, role, provider, created_at)
            SELECT id, email, password_hash, role, provider, created_at FROM users_old_check
        """)
        conn.execute("DROP TABLE users_old_check")
        conn.execute("PRAGMA legacy_alter_table=OFF")
        conn.execute("PRAGMA foreign_keys=ON")

    # One-time repair for databases that already hit the bug above (the
    # sessions table's FK clause got rewritten to point at the
    # now-nonexistent `users_old_check`, even though `sessions` itself has
    # no CHECK constraint to trigger the branch above).
    srow = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='sessions'"
    ).fetchone()
    if srow and srow["sql"] and "users_old_check" in srow["sql"]:
        # Mid-transaction PRAGMA foreign_keys toggles are a no-op in SQLite,
        # so DELETE/DROP against the broken table can still trip FK
        # resolution. RENAME is pure metadata (no row/FK validation), so
        # it works regardless — same trick as the users-table fix above.
        conn.execute("PRAGMA legacy_alter_table=ON")
        conn.execute("ALTER TABLE sessions RENAME TO sessions_broken_fk")
        conn.execute("""
            CREATE TABLE sessions (
                token       TEXT    PRIMARY KEY,
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at  INTEGER NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO sessions (token, user_id, expires_at)
            SELECT token, user_id, expires_at FROM sessions_broken_fk
        """)
        conn.execute("DROP TABLE sessions_broken_fk")
        conn.execute("PRAGMA legacy_alter_table=OFF")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)")


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
        _run_migrations(conn)


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
    status: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    place: Optional[str] = None,
    created_at: Optional[int] = None,
    occurred_at: Optional[int] = None,
) -> Optional[int]:
    """
    Insert a report. Returns the new row id, or None if it was a duplicate
    (same source + external_id, OR same url — the latter catches the same
    post getting federated across Mastodon instances under different
    instance-local external_ids, which the UNIQUE constraint alone misses).
    Never raises on duplicates.

    `status` defaults per the evidence policy: a report with a real `url`
    (always true for agent-scraped posts, since they cite a public source)
    stays 'unverified' — visible immediately, fuzzed, labeled as an
    automated lead. A report with no `url` (every user submission today —
    the free-text `evidence` field isn't a verifiable source) defaults to
    'pending' — held out of the public feed until an ADMIN/VERIFIER reviews
    it, because an anonymous unverifiable claim shouldn't publish itself.

    `created_at` allows tests (or future imports) to set a specific timestamp.
    Defaults to current time if not provided.
    """
    located = 1 if (lat is not None and lon is not None) else 0
    normalized_url = url.strip().rstrip("/") if url else None
    if status is None:
        status = "unverified" if normalized_url else "pending"
    ts = created_at if created_at is not None else int(time.time())
    occ = occurred_at if occurred_at is not None else ts
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
                     reason, evidence, law, impact, verified, status,
                     lat, lon, place, located, created_at, occurred_at, edit_token)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (source, external_id, title, body, normalized_url, category,
                 reason, evidence, law, impact, 1 if status == "verified" else 0, status,
                 lat, lon, place, located, ts, occ, secrets.token_urlsafe(16)),
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


def list_reports(
    limit: int = 500, located_only: bool = True, as_of: int | None = None,
    viewer_is_reviewer: bool = False,
) -> list[dict[str, Any]]:
    """
    Return recent reports as plain dicts, newest first.

    Public feed (`viewer_is_reviewer=False`): only `verified` reports. A
    scraped or user-filed lead stays off the public map until a confirmed
    volunteer or admin has reviewed it — "needs review" is never shown to
    visitors.

    Reviewer feed (`viewer_is_reviewer=True`, i.e. VERIFIER/ADMIN): every
    report except the ones already judged out (`dismissed`, `irrelevant`),
    so the review queue and the reviewer's map show the backlog too.

    Optional `as_of` (unix timestamp): only return reports with
    created_at <= as_of. Enables server-side timeline filtering.
    """
    if viewer_is_reviewer:
        q = "SELECT * FROM reports WHERE status NOT IN ('dismissed', 'irrelevant')"
    else:
        q = "SELECT * FROM reports WHERE status = 'verified'"
    params: list[Any] = []
    if located_only:
        q += " AND located = 1"
    if as_of is not None:
        q += " AND created_at <= ?"
        params.append(as_of)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with _conn() as conn:
        rows = conn.execute(q, params).fetchall()
    return [_strip_token(dict(r)) for r in rows]


def _strip_token(row: dict[str, Any]) -> dict[str, Any]:
    """Never let `edit_token` leak through a listing endpoint — it's a
    bearer credential, only handed back once, at creation."""
    row.pop("edit_token", None)
    return row


def list_reports_admin(
    limit: int = 100, offset: int = 0, verified: Optional[bool] = None,
    status: Optional[str] = None,
) -> dict[str, Any]:
    """
    Every report (located or not), newest first, for the moderation queue.
    `status` filters to one or more of pending/unverified/verified/dismissed/
    irrelevant (comma-separated for several, e.g. "unverified,pending" — the
    volunteer review queue); `verified` is the older boolean filter, kept
    for backward compatibility.
    """
    where = ""
    params: list[Any] = []
    if status is not None:
        wanted = [s.strip() for s in status.split(",") if s.strip()]
        bad = [s for s in wanted if s not in _VALID_STATUSES]
        if bad:
            raise ValueError(f"invalid status '{bad[0]}'")
        where = " WHERE status IN (%s)" % ",".join("?" for _ in wanted)
        params.extend(wanted)
    elif verified is not None:
        where = " WHERE verified = ?"
        params.append(1 if verified else 0)
    with _conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS n FROM reports{where}", params).fetchone()["n"]
        rows = conn.execute(
            f"SELECT * FROM reports{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
    return {"reports": [_strip_token(dict(r)) for r in rows], "total": total}


def set_verified(report_id: int, verified: bool) -> bool:
    """Legacy boolean toggle — kept for the existing PATCH contract, now a
    thin wrapper over `set_status`."""
    return set_status(report_id, "verified" if verified else "unverified")


_VALID_STATUSES = {"pending", "unverified", "verified", "dismissed", "irrelevant"}


def set_status(report_id: int, status: str, edited_by: str = "unknown") -> bool:
    """
    A moderator (ADMIN or VERIFIER) sets a report's review status.
    `verified` mirrors status == 'verified' for callers still reading the
    legacy boolean column. Returns False if no such row. Logs a
    `report_history` row (field='status') when the status actually changes.
    """
    if status not in _VALID_STATUSES:
        raise ValueError(f"invalid status '{status}'")
    with _conn() as conn:
        old_row = conn.execute("SELECT status FROM reports WHERE id = ?", (report_id,)).fetchone()
        if old_row is None:
            return False
        cur = conn.execute(
            "UPDATE reports SET status = ?, verified = ? WHERE id = ?",
            (status, 1 if status == "verified" else 0, report_id),
        )
        if old_row["status"] != status:
            conn.execute(
                "INSERT INTO report_history"
                " (report_id, edited_by, field, old_value, new_value, edited_at)"
                " VALUES (?, ?, 'status', ?, ?, ?)",
                (report_id, edited_by, old_row["status"], status, int(time.time())),
            )
        return cur.rowcount > 0


def get_report(report_id: int) -> Optional[dict[str, Any]]:
    """Single report, WITH its edit_token — internal/trusted use only
    (checking a caller-supplied token, or the ADMIN edit form). Never
    return this dict straight out of a public endpoint."""
    with _conn() as conn:
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    return dict(row) if row else None


def get_report_history(report_id: int) -> list[dict[str, Any]]:
    """Full edit trail for one report, newest first — admin/verifier only."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM report_history WHERE report_id = ? ORDER BY edited_at DESC",
            (report_id,),
        ).fetchall()
    return [dict(r) for r in rows]


_EDITABLE_FIELDS = {"title", "reason", "evidence", "law", "impact", "category"}


def update_report_fields(report_id: int, fields: dict[str, Any], edited_by: str = "unknown") -> bool:
    """
    Partial update of a report's documentation fields — used by both the
    original submitter's self-edit (token-gated) and ADMIN/VERIFIER's
    correction tool (role-gated). Deliberately excludes status/lat/lon/
    source/etc: status has its own dedicated endpoint, and location edits
    go through a separate, more guarded path.

    Diffs old vs. new per-field and writes one `report_history` row per
    field that actually changed (a no-op edit — same value resubmitted —
    writes nothing), in the same transaction as the update itself.
    """
    updates = {k: v for k, v in fields.items() if k in _EDITABLE_FIELDS and v is not None}
    if not updates:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with _conn() as conn:
        old_row = conn.execute(
            f"SELECT {', '.join(updates.keys())} FROM reports WHERE id = ?", (report_id,)
        ).fetchone()
        if old_row is None:
            return False
        cur = conn.execute(
            f"UPDATE reports SET {set_clause} WHERE id = ?",
            (*updates.values(), report_id),
        )
        now = int(time.time())
        history_rows = [
            (report_id, edited_by, field, old_row[field], str(new_val), now)
            for field, new_val in updates.items()
            if old_row[field] != new_val
        ]
        if history_rows:
            conn.executemany(
                "INSERT INTO report_history"
                " (report_id, edited_by, field, old_value, new_value, edited_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                history_rows,
            )
        return cur.rowcount > 0


def fuzz_coords(report_id: int, lat: float, lon: float, radius_m: int = 500) -> tuple[float, float]:
    """
    Displace a report's public coordinates by a deterministic pseudo-random
    offset (same report -> same offset every call, so a marker doesn't jump
    on refresh) within `radius_m` metres. Used for unverified leads so a
    single unconfirmed post can't pinpoint a real address. Verified reports
    are shown at their real location.
    """
    h = hashlib.sha256(f"dxmap-fuzz-{report_id}".encode()).digest()
    angle = (int.from_bytes(h[:4], "big") / 0xFFFFFFFF) * 2 * math.pi
    frac = int.from_bytes(h[4:8], "big") / 0xFFFFFFFF
    dist = radius_m * math.sqrt(frac)  # sqrt for uniform density over the disc
    dlat = (dist * math.cos(angle)) / 111_320
    dlon = (dist * math.sin(angle)) / (111_320 * math.cos(math.radians(lat)) or 1)
    return round(lat + dlat, 6), round(lon + dlon, 6)


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
    """Quick counts for the status endpoint, self-check, and the Reports tab."""
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM reports").fetchone()["c"]
        located = conn.execute(
            "SELECT COUNT(*) c FROM reports WHERE located = 1").fetchone()["c"]
        by_source = {
            r["source"]: r["c"] for r in conn.execute(
                "SELECT source, COUNT(*) c FROM reports GROUP BY source").fetchall()
        }
        by_status = {
            r["status"]: r["c"] for r in conn.execute(
                "SELECT status, COUNT(*) c FROM reports GROUP BY status").fetchall()
        }
        by_category = {
            r["category"]: r["c"] for r in conn.execute(
                "SELECT category, COUNT(*) c FROM reports GROUP BY category").fetchall()
        }
    return {
        "total": total, "located": located, "by_source": by_source,
        "by_status": by_status, "by_category": by_category,
    }


def law_incident_counts() -> dict[str, int]:
    """How many published (non-dismissed) incidents cite each statute code —
    powers the Law tab, which lists the laws incidents are actually breaking."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT law, COUNT(*) c FROM reports"
            " WHERE law IS NOT NULL AND law != ''"
            "   AND status NOT IN ('dismissed', 'irrelevant')"
            " GROUP BY law"
        ).fetchall()
    return {r["law"]: r["c"] for r in rows}


# --------------------------------------------------------------------------- #
# Users & sessions                                                             #
# --------------------------------------------------------------------------- #

def _hash_password(password: str, salt: Optional[bytes] = None) -> str:
    """PBKDF2-HMAC-SHA256, stdlib only (no extra dependency). Stored as
    'salt_hex$hash_hex'."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, _ = stored.split("$", 1)
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    candidate = _hash_password(password, salt)
    return secrets.compare_digest(candidate, stored)


_VALID_ROLES = {"NONE", "VERIFIER", "ADMIN"}


def create_user(
    email: str, password: str, role: str, provider: str = "email",
    accepted_terms: bool = False,
) -> Optional[int]:
    """
    Create a user with a hashed password. Returns None if the email is
    already taken. Raises ValueError for an unknown role.

    `role='NONE'` is the self-registration default (Google or email signup)
    — no permissions until an ADMIN promotes the account from /admin. Only
    the admin-only `/api/admin/users` endpoint creates accounts with
    `ADMIN`/`VERIFIER` directly.
    """
    if role not in _VALID_ROLES:
        raise ValueError(f"invalid role '{role}'")
    now = int(time.time())
    with _conn() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, role, provider, created_at, accepted_terms_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (email.strip().lower(), _hash_password(password), role, provider, now,
                 now if accepted_terms else None),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


def get_user_by_email(email: str) -> Optional[dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def list_users() -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, email, role, provider, created_at FROM users ORDER BY created_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def count_users(role: Optional[str] = None) -> int:
    with _conn() as conn:
        if role:
            return conn.execute(
                "SELECT COUNT(*) c FROM users WHERE role = ?", (role,)
            ).fetchone()["c"]
        return conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]


def update_user_role(user_id: int, role: str) -> bool:
    if role not in _VALID_ROLES:
        raise ValueError(f"invalid role '{role}'")
    with _conn() as conn:
        cur = conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        return cur.rowcount > 0


def delete_user(user_id: int) -> bool:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return cur.rowcount > 0


SESSION_TTL_SECONDS = 60 * 60 * 24 * 14  # 14 days


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with _conn() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user_id, int(time.time()) + SESSION_TTL_SECONDS),
        )
    return token


def get_session_user(token: str) -> Optional[dict[str, Any]]:
    """Resolve a session token to its user, or None if missing/expired.
    Opportunistically sweeps expired sessions on the way."""
    if not token:
        return None
    now = int(time.time())
    with _conn() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.email, u.role FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ? AND s.expires_at > ?
            """,
            (token, now),
        ).fetchone()
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
    return dict(row) if row else None


def delete_session(token: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


# --------------------------------------------------------------------------- #
# Applications — the public "Get involved" tab                                 #
# --------------------------------------------------------------------------- #

_VALID_INTERESTS = {"volunteer", "translator", "coder", "organization", "other"}
_VALID_APP_STATUSES = {"new", "contacted", "closed"}


def create_application(
    *, name: str, email: str, interest: str, message: str = "",
    user_id: Optional[int] = None,
) -> int:
    if interest not in _VALID_INTERESTS:
        raise ValueError(f"invalid interest '{interest}'")
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO applications (name, email, interest, message, user_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (name.strip(), email.strip().lower(), interest, message.strip(),
             user_id, int(time.time())),
        )
        return cur.lastrowid


def list_applications(status: Optional[str] = None) -> list[dict[str, Any]]:
    where, params = "", []
    if status is not None:
        if status not in _VALID_APP_STATUSES:
            raise ValueError(f"invalid status '{status}'")
        where, params = " WHERE a.status = ?", [status]
    with _conn() as conn:
        rows = conn.execute(
            "SELECT a.*, u.email AS account_email, u.role AS account_role"
            " FROM applications a LEFT JOIN users u ON u.id = a.user_id"
            f"{where} ORDER BY a.created_at DESC",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_application(app_id: int) -> Optional[dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT a.*, u.email AS account_email, u.role AS account_role"
            " FROM applications a LEFT JOIN users u ON u.id = a.user_id"
            " WHERE a.id = ?",
            (app_id,),
        ).fetchone()
    return dict(row) if row else None


def set_application_status(app_id: int, status: str) -> bool:
    if status not in _VALID_APP_STATUSES:
        raise ValueError(f"invalid status '{status}'")
    with _conn() as conn:
        cur = conn.execute("UPDATE applications SET status = ? WHERE id = ?", (status, app_id))
        return cur.rowcount > 0


if __name__ == "__main__":
    init_db()
    print(f"Initialized DB at {DB_PATH}")
    print(json.dumps(stats(), indent=2))
