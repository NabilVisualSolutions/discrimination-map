# Discrimination Map (dxmap) — Build & Deploy Plan

A live situational-awareness web app. A background monitoring agent scrapes
free social APIs for geolocatable reports and plots them on a map. Users file
their own reports with one button. Everything persists. The agent runs a
heartbeat loop and a self-check routine (tests + security audit + health).

## 1. Architecture

```
                 ┌──────────────────────────────────────────┐
   Browser  ───► │  Nginx (TLS, static, reverse proxy)      │
   (Leaflet map) │            │                              │
                 │            ▼                              │
                 │  FastAPI (uvicorn)  ── /api/reports       │
                 │        │              /api/health         │
                 │        │              /api/heartbeat      │
                 │        ▼                                  │
                 │   SQLite (WAL, persistent on disk)        │
                 │        ▲                                  │
                 │        │  writes scraped reports          │
                 │  Monitoring agent (asyncio heartbeat loop) │
                 │    ├─ Reddit    (free public JSON)  ✅     │
                 │    ├─ YouTube   (free API key quota) ◑     │
                 │    ├─ X/Twitter (paid — stub)        ✕     │
                 │    └─ IG/TikTok (no free API — stub) ✕     │
                 │  Self-check (tests, sec audit, health)    │
                 └──────────────────────────────────────────┘
```

- **Backend:** Python + FastAPI + uvicorn. One process serves the API, the
  static frontend, and runs the monitoring agent as an asyncio background task.
- **DB:** SQLite in WAL mode. Zero-config, genuinely persistent on the VPS
  disk, survives restarts. Swap to Postgres later without changing the API.
- **Frontend:** Single `index.html` — Leaflet + OpenStreetMap tiles (no API
  key, no build step). Markers colored by source. One "File a report" button.
- **Deploy:** systemd unit keeps it alive; Nginx terminates TLS and proxies.

## 2. Data sources (honest status)

| Platform     | Free? | How | Status in prototype |
|--------------|-------|-----|---------------------|
| Reddit       | Yes   | Public `.json` endpoints, no key | **Working** |
| YouTube      | Partial | Data API v3, free daily quota, needs key | Ready — add `YOUTUBE_API_KEY` |
| X / Twitter  | No    | API is paid for meaningful volume | Stub + clear log message |
| Instagram/TikTok | No | No free official API; scraping breaks ToS & is fragile | Stub + clear log message |

The prototype is genuinely useful on **Reddit alone**. YouTube switches on the
moment you drop in a free key. The other two are stubbed with explicit reasons
so nothing pretends to work that doesn't.

## 3. Geolocation

Scraped text rarely has coordinates. Pipeline:
1. Match against a built-in gazetteer of world cities (instant, offline).
2. Fall back to OSM **Nominatim** geocoding (free, rate-limited to 1 req/s).
3. If nothing resolves, the report is stored `unlocated` and not mapped.

## 4. "Self-improvement" — what it actually does

Autonomous rewriting of live code is a security risk, so the agent does the
safe, valuable version on each self-check tick:
- **Tester:** runs the `pytest` suite against the running API; logs pass/fail.
- **Security audit:** checks response security headers, that the DB file isn't
  web-exposed, that debug mode is off, that CORS isn't wildcarded in prod.
- **Health:** tracks per-source success rate, latency, error streaks; backs off
  a source that keeps failing.
- **Suggestions log:** writes concrete improvement notes to `improvements.log`
  (e.g. "reddit latency rising", "add index on reports.created_at") for a human
  to action. It does **not** edit and redeploy itself.

## 5. Build order

1. `db.py` — schema + persistence helpers.
2. `geolocate.py` — gazetteer + Nominatim fallback.
3. `agent.py` — source adapters + heartbeat loop.
4. `selfcheck.py` — tests + security audit + health.
5. `app.py` — FastAPI: `/api/reports` (GET/POST), `/api/health`,
   `/api/heartbeat`, serve frontend.
6. `frontend/index.html` — map, markers, report button.
7. `tests/test_api.py` — API + geolocation tests.
8. `deploy/` — systemd unit, Nginx config, `deploy.sh`.

## 6. Deploy to Hostinger VPS (summary — full steps in README)

```bash
scp -r dxmap root@YOUR_VPS_IP:/opt/
ssh root@YOUR_VPS_IP 'bash /opt/dxmap/deploy/deploy.sh yourdomain.com'
```

Installs Python deps, creates the systemd service, configures Nginx, and
(optionally) provisions a Let's Encrypt certificate.

## 7. Explicitly out of scope for the prototype

- Paid X/Twitter and IG/TikTok ingestion (stubbed with reasons).
- User accounts / auth (reports are anonymous; add auth before public launch).
- Moderation queue (add before exposing user reports publicly).
