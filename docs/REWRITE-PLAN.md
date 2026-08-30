# Discrimination Map — frontend rewrite plan

**Date:** 2026-08-30
**Decision:** rewrite the **frontend** as a Vite + React + TypeScript SPA.
Keep the FastAPI + SQLite backend and its API unchanged — it holds ~3,800
real reports, the scraping agent, the StGB legal classifier, geolocation,
moderation, auth/roles. No database migration: same API, same schema.

---

## 1. Why (heuristic review of the current frontend — no analytics on the
site, so this is a code/UX read, not a replay audit)

| # | Problem | Impact |
|---|---|---|
| 1 | `frontend/` is ~5,500 lines of monolithic vanilla HTML/JS (`index.html` 1597, `admin.html` 468, `i18n.js` 1054), no build, no types, no tests, `?v=20260822j` manual cache-busting. | Git log is full of churny regressions — "Fix broken boot sequence", "Fix zones never rendering", "Fix filed reports never showing". Every change is high-risk. |
| 2 | i18n is `data-i18n=""` attributes swapped by a hand-written 1054-line `i18n.js`. No interpolation/plural rules, RTL handled ad-hoc, easy to miss a key. 96 keys in `index.html` alone. | de/fr/ar quality drifts; Arabic RTL is fragile. |
| 3 | Dark→light theme migration half-done. `preview-light.html` is the agreed design target but was never merged; `index.html` still carries dark remnants (per `NEXT-STEPS.md`). | Inconsistent look; the "serious documentation tool, not hacker terminal" intent isn't fully realised. |
| 4 | Up to 5,000 reports fetched (`/api/reports?limit=5000&all=true`) and drawn as individual Leaflet DOM markers, no clustering / canvas layer. | Jank and battery drain on mid-range phones — the whole point is a mobile field tool. |
| 5 | Browser-side geocoding straight to `nominatim.openstreetmap.org`. | Rate-limit fragile, no fallback, leaks usage pattern, breaks the search + reverse-geocode on the report form when throttled. |
| 6 | Report submission is one large modal — no step guidance, thin client validation, the sensitive-category (`sexual_violence` / `harassment`) consent path is not clearly surfaced. | Bad reports, or people bounce. GDPR Art. 9 categories deserve a deliberate gate. |
| 7 | No error boundaries; a single failed boot fetch breaks the app. | See git history. |
| 8 | `admin.html` is a separate 468-line file duplicating patterns from `index.html`. | Double maintenance. |
| 9 | Accessibility of the custom bottom nav / drawers / modals is unverified. | Civic tool — should be usable with a keyboard and a screen reader. |

## 2. Target stack

- **Vite 6 + React 19 + TypeScript** (`web/`).
- **MapLibre GL JS** + a free vector style (OpenFreeMap or Protomaps) —
  GPU rendering, built-in clustering, far better mobile perf than Leaflet
  DOM markers. Circle markers per category; a star layer for
  `solidarity_event` (keep the "categorically different pin" rule).
- **@tanstack/react-query** for all API state — caching, retry, and the
  boot-sequence fragility (#7) goes away.
- **react-i18next** — `web/src/locales/{en,de,fr,ar}.json`, migrate the 96
  keys, RTL via `dir` + CSS logical properties.
- **Typed API client** — `openapi-typescript` against FastAPI's
  `/openapi.json`, wrapped in a thin `api.ts`.
- **zod** for the report form.
- **Design tokens from `preview-light.html`** as CSS custom properties +
  a small hand-rolled component set (no Tailwind — keep the bundle lean).
- Backend still serves it: Vite builds to `web/dist`, FastAPI serves
  `dist/index.html` as the SPA shell and `dist/assets` static. Existing
  `/awareness` `/guide` `/privacy` `/terms` become SPA routes (content
  ported from the current static pages).
- **One new backend endpoint:** `GET /api/geocode?q=` + `GET
  /api/geocode/reverse?lat=&lon=` — a thin server-side Nominatim proxy
  with a short cache and a real User-Agent (fixes #5). Nothing else in
  the backend changes.

## 3. Phases

| Phase | Scope | Deploys? |
|---|---|---|
| **P0** | Scaffold `web/` (Vite+React+TS), API types from `/openapi.json`, react-query + react-i18next wiring, design tokens, dev proxy to `:8020`. Runs `npm run dev`. | no |
| **P1** | Public map: MapLibre, load reports, category circle/star markers + clustering, incident popup + detail sheet, category filter drawer, timeline slider, quick-exit button, search box. Add + use `/api/geocode`. | no |
| **P2** | Report submission: multi-step (what / where / evidence / contact), zod validation, map location pick, sensitive-category consent gate, success + `edit_token` stored locally, edit-existing flow. | no |
| **P3** | Incidents list · Laws (`/api/laws`) · Awareness · Volunteer (`/api/apply`) · Propose-symbol · status HUD + `/api/heartbeat`. Port `/awareness` `/guide` `/privacy` `/terms` content. | no |
| **P4** | Admin (`/admin` route, role-gated via `/api/auth/me`): login, report queue, verify/dismiss, field edits + history, users, applications, duplicates. | no |
| **P5** | Parity QA across en/de/fr/ar + RTL, a11y pass, mobile perf check on a real phone, Dockerfile node build stage, deploy. Keep `frontend/` in the image until confirmed, then remove. | **yes** |

## 4. Deploy / rollback

- No DB migration. The cutover is: FastAPI serves `web/dist` instead of
  `frontend/`. Add a `SERVE_NEW_FRONTEND` env flag so prod can switch back
  to `frontend/` instantly without a rebuild during the P5 bake.
- `frontend/` stays in the repo and image until the new one is confirmed
  live and stable for a few days, then deleted in its own commit.
- Deploy path unchanged: rsync `~/projects/dxmap` → `vps:/docker/dxmap`,
  `docker compose build && up -d`. DB is the named volume, untouched.

## 5. This session

P0 scaffold + this plan. P1–P5 and the deploy are follow-up — a full
frontend rewrite of a live civic-tech tool is not a same-session
"fix and deploy".
