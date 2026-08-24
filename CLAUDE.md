# dxmap — Claude Code project notes

Live at **map.nabilvs.com**. See `README.md` for what this documents and why, `PLAN.md` for design/honesty notes, `deploy/DEPLOY-DXMAP.md` for the deploy procedure in full. This file is operational knowledge for working on the codebase — read it before touching deploy, caching, or the zone-rendering system.

## Stack

FastAPI + SQLite backend (`backend/`), static-file frontend served via FastAPI (`frontend/*.html`, no build step, no framework — plain HTML/CSS/JS + Leaflet 1.9.4 via CDN). No ORM — raw SQL in `backend/db.py`. Tests: `pytest tests/` (currently 40, keep it there or higher).

- `backend/app.py` — FastAPI routes
- `backend/db.py` — all SQL, schema, report lifecycle
- `backend/auth.py` — session-cookie auth, ADMIN/VERIFIER roles
- `backend/agent.py` — the scraping agent (Bluesky/Mastodon/YouTube) that files automated leads
- `backend/lawref.py` — category definitions (`CATEGORIES` dict) + StGB statute references
- `backend/geolocate.py` — Nominatim geocoding for scraped posts
- `frontend/index.html` — the live map (biggest file, ~1500 lines, all JS inline)
- `frontend/admin.html` — moderation console
- `frontend/guide.html`, `awareness.html`, `privacy.html`, `terms.html` — static informational pages
- `frontend/i18n.js` — all UI strings, 4 locales (en/de/fr/ar) as flat key objects. Any user-facing string change needs all 4.

## Deploy — NOT git-based on the VPS

Local repo → `rsync -az --delete` (excluding `backend/dxmap.db*`, `improvements.log`, `frontend/data/`, `.env`, `__pycache__/`, `.git/`, `venv/`) → `/docker/dxmap/` on `root@187.127.69.64` (same VPS as nabilvs.com) → `ssh ... "cd /docker/dxmap && docker compose build && docker compose up -d"`. The production DB lives in a Docker named volume, mounted separately from the synced source tree — rsync never touches it. `Dockerfile` does `COPY backend/` and `COPY frontend/` at build time, so **every frontend change needs a full rebuild**, not just a container restart.

Full rsync+build+up command sequence is in `deploy/DEPLOY-DXMAP.md` — copy it exactly, don't improvise the exclude list (getting it wrong risks clobbering the live DB or config).

## Cloudflare cache gotcha

`map.nabilvs.com` is Cloudflare-proxied. `/static/*` (i18n.js, awareness-data.js) gets `max-age=14400` and edge-caches — a deploy's JS changes are invisible to visitors for up to 4h without a cache-bust. The available Cloudflare API token is read-only; there is no working purge-cache path.

**Pattern:** every HTML file that includes `/static/i18n.js` or `/static/awareness-data.js` carries a `?v=YYYYMMDDx` query string. Bump the letter suffix on every deploy that changes either file, across **all 6 files**: `index.html`, `admin.html`, `guide.html`, `awareness.html`, `privacy.html`, `terms.html`. A fresh version string is a new cache key (`cf-cache-status: MISS`), guaranteeing the new content is what gets served. `/` itself is `cf-cache-status: DYNAMIC` (never cached), so only the two `/static/*.js` files need this.

## Report lifecycle — read before touching visibility logic

`status`: `pending` → (moderator reviews) → `verified` | `dismissed`. Automated agent-scraped reports (real source URL) skip `pending` and publish immediately as `unverified` — still a real, unreviewed lead, distinct from a human-filed report which starts `pending`.

`db.list_reports()` (the public feed, `GET /api/reports`) excludes `dismissed` and `pending` always. It does **not** exclude `unverified` — this matters a lot in practice: as of writing, **0 of ~3,800 reports in production are `status='verified'`**. Any filter that requires `status='verified'` will show nothing. If you need to distinguish "auto-detected, not yet categorized" from "properly classified," use `category != 'far_right_mention'` (the literal catch-all category, labeled "Far-right context (needs review)") — not verification status.

Self-filed reports: anonymous, no accounts. `edit_token` returned once at submission, saved client-side in `localStorage`. `GET /api/reports/{id}?edit_token=...` is the only way a filer sees their own `pending` report again on a later visit — it's excluded from the public feed until reviewed. If you touch the submit flow, keep this path working; it's easy to silently break (it broke once already — the filer's own report was visible only for the one moment right after submitting, then gone).

## Zone rendering (`rebuildZones()` in index.html)

Ingress-style: every point in a category joins one connected network via a minimum spanning tree (`minSpanningTree()`, O(n²) Prim's — don't revert to the naive O(n³) full-rescan version), plus one convex-hull "cloud" field per category, colored to that category's hex and CSS-animated. **Opt-in** — off by default (`zonesOn = false`), toggled via a checkbox in the map-key drawer. This was originally always-on and was the single biggest cause of map lag (continuous SVG animations across every category on every load); don't remove the toggle without re-measuring performance first.

`far_right_mention` never joins a zone (see report lifecycle note above) — every other category does, regardless of verification status.

## Categories

`CATEGORIES` in `backend/lawref.py`: 10 Germany/StGB-specific (drive `_INDICATORS` regex classification + `STATUTES`), 9 broader global (UI-only), 1 `solidarity_event` (UI-only, star icon not dot, explicitly excluded from `SENSITIVE_CATEGORIES`). Adding a category is free-text on `reports.category` — no migration needed, just add the dict entry + i18n key (`cat.<key>`) in all 4 languages.

`SENSITIVE_CATEGORIES` (`sexual_violence`, `harassment`) always get wide-radius (5km) fuzzing regardless of verification status, for anyone not logged in.

## Local dev

```bash
./run-dev.sh   # sets DXMAP_ENV=dev + throwaway admin creds, uvicorn on :8020
```

Never test zone rendering or scale-dependent behavior against synthetic 2-3 point datasets — insert real-shaped synthetic data (multiple cities, real category mix) directly into `backend/dxmap.db` via sqlite3, and delete it after. The local dev DB is small (~800 rows); production is ~3,800. Behavior that looks fine at n=3 has broken at n=500+ before (grid-clustering bucket sizes, MST complexity).
