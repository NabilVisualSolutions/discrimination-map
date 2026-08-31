# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

existing codebase: FastAPI + SQLite backend (`backend/`), `frontend/` vanilla HTML/Leaflet (no build) + `web/` React 19 + Vite + MapLibre GL + TanStack Query + react-i18next. Requested addition: `react-simple-maps` for map surface (npm i -S react-simple-maps).

## Users

Primary: Affected witnesses and community volunteers documenting far-right / hate incidents in Germany (and worldwide) — anonymous, no accounts, filing via map pin or "Report" flow, often on mobile, needing guidance and safety. Secondary: Volunteer moderators / verifiers and researchers / press browsing the live feed, filtering by category, reading evidence + statute context, tracking pattern over time. Tertiary: Partner organizations and translators contributing via Volunteer/Awareness surfaces.

## Product Purpose

Document hate incidents with evidence and make the pattern visible over time and space. Every mark carries what happened, evidence link, possibly-applicable German statute (StGB via `lawref.py`), and impact — with timeline and category filters so a region's pattern is legible. Success = more verified leads become findable without losing presumption of innocence; history is never deleted, only faded.

## Positioning

A documentation tool that pairs each pin with checkable evidence and a suggested statute, plus Ingress-style per-category zone networks (MST + convex-hull fields) that turn isolated dots into a readable pattern. Unlike generic trackers: anonymous filing with `edit_token` self-view, fuzzing for sensitive/unverified reports, and a single-copy statute reference — not a verdict.

## Operating Context

Workflows: anonymous file → `pending` → moderator `verified|dismissed`; agent-scraped leads publish as `unverified` (real source URL). `db.list_reports()` hides `dismissed`+`pending`; public feed still needs `far_right_mention` (catch-all) distinction, not just `verified`. Surfaces: map + bottom sheets/rail, Incidents/Laws/Awareness/Volunteer tabs, search + language switcher, timeline slider (`created_at` cutoff), category legend/zone toggle, report modal, detail sheet, admin console. Env: FastAPI + Uvicorn on :8020, SQLite WAL, Leaflet CDN or MapLibre vector tiles, Cloudflare-proxied with `?v=` cache-bust for `/static/*`. i18n: 4 locales (en/de/fr/ar) in `frontend/i18n.js` / `web` i18n.

## Capabilities and Constraints

- Anonymous reports: no names of private persons; evidence optional but required for public visibility without review.
- Agent scrapes Bluesky/Mastodon/YouTube (Nominatim geocoding), heartbeat + self-check loops, improvements.log.
- Fuzzing: `SENSITIVE_CATEGORIES` (sexual_violence, harassment) always 5km; timeline `as_of` filtering.
- Constraints: No paid X/IG ingestion, no user accounts, single Docker volume prod DB never rsync'd, rebuilt on every frontend change, 4h Cloudflare edge cache.
- Open decisions: whether `web/` MapLibre view becomes `react-simple-maps` or coexists with `frontend/` Leaflet map; admin `as_of` support; moderation queue depth.

## Brand Commitments

Name: Discrimination Map (dxmap). Voice: calm, documentary, presumption-of-innocence, no hype. Palette: light public-tool theme `--bg:#f4f7fb` etc. (see `frontend/index.html:13-25`), not hacker/dark. Map style: positron light (CARTO/MapLibre), solidarity stars vs dots, muted category colors. No invented testimonials/pricing — real evidence links only.

## Evidence on Hand

Running code: `backend/app.py` (FastAPI), `backend/db.py` (raw SQL), `frontend/index.html` (~1500 lines), `web/src/features/map/MapView.tsx`, `frontend/i18n.js`, `frontend/awareness-data.js`, `tests/` (40+). Live at `map.nabilvs.com`. No synthetic metrics to fabricate.

## Product Principles

1. Documentation, not accusation — unverified leads never presented as verdicts.
2. Pattern over pins — zones and timeline make distribution legible, not just countable.
3. Safety by default — anonymity, fuzzing, and do-not-confront guidance are non-negotiable.
4. Evidence travels with the mark — statute suggestion is context, not charge.

## Accessibility & Inclusion

Mobile-first, RTL-aware (lang popover uses `inset-inline-end`), focus-visible outlines, reduced-motion disables zone/marker animation, tap targets ≥44px, i18n for all user strings.
