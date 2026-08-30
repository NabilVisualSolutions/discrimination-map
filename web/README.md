# dxmap-web — frontend rewrite (in progress)

Vite + React 19 + TS SPA that replaces `../frontend/`. Backend (FastAPI,
`../backend/`) and its API are unchanged. See `../docs/REWRITE-PLAN.md`.

## Dev

```bash
cd ..        && ./run-dev.sh &     # FastAPI on :8020
cd web       && npm install && npm run dev   # Vite on :5180, proxies /api -> :8020
npm run gen:api                    # regenerate src/lib/api-schema.d.ts from /openapi.json (backend up)
npm run typecheck
npm run build                      # -> web/dist (FastAPI will serve this in P5)
```

## Status

- **P0 done:** scaffold, typed API client, react-query + react-i18next
  (en/de/fr/ar + RTL), design tokens from `preview-light.html`, MapLibre
  map with clustered per-category markers + solidarity star layer, top bar
  with language switch + quick-exit, report FAB (stub), detail sheet (read
  only).
- **Next:** P1 map polish + `/api/geocode` proxy, P2 report form, P3 the
  other panels + content pages, P4 admin, P5 parity QA + deploy.

Nothing here is deployed. `../frontend/` is still the live site.
