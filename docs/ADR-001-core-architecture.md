# ADR-001: Core architecture decisions for dxmap

**Status:** Accepted (in production)
**Date:** 2026-08-24
**Deciders:** Project owner

## Context

dxmap (map.nabilvs.com) is a live, public incident-mapping site: a FastAPI backend, SQLite storage, and a no-build vanilla-JS frontend, deployed to a single Hostinger VPS. It handles sensitive, adversarial-input data — anonymous public reports and automated scraper leads about real-world hate incidents — at a moderate and growing scale (~3,800 rows as of this writing, several hundred added per week by the scraping agent). The five decisions below were made early, are all still load-bearing in production, and were never written down. This ADR documents them so future changes are made with the original tradeoffs in view, not rediscovered by trial and error.

## Decision

Keep all five as-is for now. None currently blocks the product; each has a known ceiling that should trigger a revisit (noted per-decision below), not a preemptive rewrite.

### 1. Deploy: rsync + docker compose, not git-based CI/CD

**Decision:** Local repo → `rsync -az --delete` (with an exclude list protecting the live DB, `.env`, and caches) → `/docker/dxmap/` on the VPS → `docker compose build && up -d` over SSH. No GitHub Actions, no CI pipeline, no automated tests-gate-deploy.

**Alternatives considered:** GitHub Actions → SSH deploy; a proper CD pipeline with a staging environment.

| Dimension | rsync+compose | CI/CD pipeline |
|---|---|---|
| Complexity | Low — one shell command sequence | Medium — secrets in CI, staging infra |
| Time-to-deploy | Immediate, no queue | Depends on runner availability |
| Safety net | None — deploy = whatever's on disk locally | Tests gate the merge, not just the deploy |
| Team familiarity | Matches this project's single-operator reality | Overhead not justified at this team size |

**Pros:** Zero infra to maintain, deploys in seconds, works identically to how nabilvs.com (the sibling project) already deploys.
**Cons:** No CI gate — a broken `git push` never blocks a bad deploy, because deploy doesn't go through git at all. `pytest` is run manually, not enforced. No staging: every deploy lands directly on the production VPS.

**Consequences:** Easy to ship fast; easy to ship a regression, because nothing stops an un-tested change from reaching production. Revisit if: a second person starts deploying (coordination risk), or a bad deploy causes real user-facing downtime more than once.

### 2. No ORM — raw parameterized SQL in `backend/db.py`

**Decision:** All queries are hand-written SQL via `sqlite3`, parameterized with `?` placeholders. No SQLAlchemy, no query builder.

**Alternatives considered:** SQLAlchemy Core or ORM; a lighter query builder (e.g. `sqlite-utils`).

**Pros:** Zero abstraction overhead, every query is exactly what runs, no ORM-generated-query surprises, trivial to reason about for a schema this size (2 tables: `reports`, `report_history`, plus `users`/`sessions`/`applications`).
**Cons:** Schema migrations are hand-rolled (`ALTER TABLE` blocks with `PRAGMA table_info` existence checks, visible in `db.py`'s `init_db()`) — correct today, but this pattern doesn't scale past a handful of migrations before it needs a real migration tool (Alembic or similar).

**Consequences:** Fast to write, easy to audit for SQL-injection safety (confirmed during this review — column names interpolated into `f"..."` SQL are always filtered through a hardcoded allowlist first, e.g. `_EDITABLE_FIELDS` in `update_report_fields()`, never raw user input). Revisit if: the schema grows past ~5-6 tables, or a second developer needs to reason about migration ordering.

### 3. No-build-step vanilla JS frontend

**Decision:** `frontend/index.html` (and `admin.html`, `guide.html`, etc.) are plain HTML files with inline `<script>` blocks — no React/Vue, no bundler, no `npm install`, no build step. Leaflet loaded from a CDN.

**Alternatives considered:** A React/Vite SPA; a lightweight framework (Svelte, Alpine.js).

| Dimension | Vanilla JS | React/Vite SPA |
|---|---|---|
| Complexity | Low for this size (~1,500 lines) | Medium — build tooling, bundle config |
| Deploy | Copy the file, done | Build step must run before every deploy |
| Iteration speed | Edit → refresh, zero latency | Edit → build → refresh |
| Team familiarity | No framework lock-in | Requires framework fluency |

**Pros:** Deploy is `COPY frontend/` in the Dockerfile — no build step to break, no `node_modules` to manage in production, no framework version to keep current. Fastest possible iteration loop for a single-operator project.
**Cons:** `index.html`'s inline script has grown to ~1,500 lines in one file — past the point where a framework's component boundaries would start paying for themselves. No type safety (a plain object shape typo fails silently at runtime, not at build time).

**Consequences:** Consequences: cheap to ship, increasingly awkward to navigate as the file grows. Revisit if: the file crosses ~2,500 lines, or a second frontend contributor joins (shared mental model of "where does X live" gets harder without file/component boundaries).

### 4. SQLite, not Postgres

**Decision:** SQLite file on local disk (Docker named volume), not a managed Postgres instance.

**Alternatives considered:** Postgres (self-hosted on the same VPS, or managed via Hostinger/Supabase).

**Pros:** Zero operational overhead — no separate DB process, no connection pooling to tune, backups are `cp dxmap.db dxmap.db.bak` (confirmed this pattern is already in use — timestamped `.bak-*` files exist in the deployed data volume). Fast enough: read-heavy workload (`GET /api/reports` dominates traffic), SQLite handles concurrent reads well.
**Cons:** SQLite serializes writes — a single writer at a time. At current scale (a few hundred writes/day from the scraper + occasional user submissions) this is a non-issue; it becomes one if either the scraper's write rate or moderator-action volume grows an order of magnitude. No built-in replication — the VPS is a single point of failure for both the app and the data.

**Consequences:** Matches the actual write load today. Revisit if: write throughput becomes visibly contended (`database is locked` errors), or the project needs redundancy/failover it currently has none of.

### 5. Anonymous edit-token self-serve editing, not accounts

**Decision:** A person filing a report gets a random `edit_token` back once, stored client-side (`localStorage`), never emailed or recoverable. It's the only credential that proves "you filed this" — used for `PATCH /api/reports/{id}` (self-edit) and, as of this session's fix, `GET /api/reports/{id}` (self-view of a still-pending report).

**Alternatives considered:** Require an account (email/password or OAuth) to file a report.

**Pros:** Genuinely anonymous reporting is a stated product requirement (see `PLAN.md` / `guide.html` copy) — for a site documenting potentially dangerous hate-incident information, requiring an account is a real barrier and a real risk (an account is one more thing that can be subpoenaed, breached, or tie a report to a real identity). Zero signup friction.
**Cons:** Lose the token (clear browser data, switch devices) and the report is unrecoverable — there is no account to fall back on, by design. This is documented in-product (`guide.html`: "there's no account we can use to recover the edit link for you later"), so it's a known, accepted tradeoff, not an oversight.

**Consequences:** Matches the anonymity requirement exactly. Revisit only if the anonymity requirement itself changes — this isn't a technical ceiling, it's a product/safety decision.

## Action Items

1. [ ] Add `pytest` as a required step before deploy (even a manual checklist item in `deploy/DEPLOY-DXMAP.md` is better than the current "run it if you remember")
2. [ ] Consider a lightweight migration tracking file (even a `MIGRATIONS.md` log) once `init_db()`'s hand-rolled `ALTER TABLE` blocks exceed ~5
3. [ ] Watch `index.html` line count — flag for a possible split (e.g. extract the zone-rendering and i18n-application logic into separate `<script src>` files, still no build step) if it crosses 2,500 lines
4. [ ] No action needed on SQLite or edit-tokens — both are correct for current scale/requirements, listed here only so a future "should we migrate to Postgres / add accounts" conversation starts from the real reasoning, not from scratch
