# Next Steps: broaden Discrimination Map from the Germany prototype to the full vision

**Read this first if you're picking this up on dragon.** This file replaces
the previous version (which predates everything below — auth, roles, i18n,
Docker deploy). If anything here contradicts the live code, the code wins;
update this file in the same session.

**Where things actually stand (2026-08-12):**
- Live at `https://map.nabilvs.com`, deployed via Docker on the shared VPS
  (`ssh dxmap-vps`, `/docker/dxmap`, `docker compose build && up -d` — NOT
  the old systemd/Nginx path some older docs describe).
- `backend/`: FastAPI + SQLite (WAL). `reports` table has `status`
  (`unverified` / `verified` / `dismissed`, NOT the `moderation` enum an
  older version of this doc proposed). `users` + `sessions` tables give
  two roles — `ADMIN` (full control incl. user management) and `VERIFIER`
  (can verify/dismiss reports). Coordinates for non-verified reports are
  fuzzed ~500m server-side for anyone not logged in (`db.fuzz_coords`).
- `frontend/index.html` + `admin.html`: mobile-first, bottom nav
  (Map/Incidents/Verify/Reports), timeline slider, incident detail sheet,
  i18n (en/de/fr/ar, RTL for ar) via `frontend/i18n.js`. **Currently dark
  theme — needs to switch to light, see step 1.**
- `frontend/preview-light.html` (new, 2026-08-12): a **static, sample-data
  preview** of the light theme + full discrimination taxonomy + 10-year
  fade + persistent report button. This is the visual target for step 1 —
  open it in a browser, that's the look to carry into `index.html`. It is
  NOT wired to the API and should stay that way until it's merged into the
  real frontend (don't deploy it as-is).
- `backend/lawref.py` CATEGORIES is still the old Germany/far-right-only
  set (arson, violence, threat, banned_symbol, holocaust_denial,
  incitement, propaganda, banned_org, assembly, far_right_mention), each
  tied to a specific StGB statute. The broader taxonomy (racism,
  islamophobia, antisemitism, homophobia/transphobia, xenophobia, Neo-Nazi
  signs/attacks, sexual violence, harassment, other) does **not exist in
  the backend yet** — only in the outreach copy and the new static preview.
- `outreach/landing-page.html` and `outreach/PITCH-SCRIPT.md` already
  describe the full taxonomy, the 10-year fade, and the safety principles
  accurately — they were written ahead of the code. Use them as the source
  of truth for wording; don't rewrite them unless the plan changes.

---

## 0. Before writing code: the sensitive-category legal gate

Not optional groundwork — it changes the schema in step 3. Decide, and
write the decision into this file (not just your head) before touching
`sexual_violence` or `harassment`:

- **Sexual violence / harassment reports must not go straight to the
  public map.** Recommendation: a new status value, `pending`, default
  for these two categories only. Extend `db.list_reports`'s public query
  from `WHERE status != 'dismissed'` to
  `WHERE status NOT IN ('dismissed', 'pending')`. An ADMIN/VERIFIER
  promotes `pending → unverified` (or straight to `verified`) after
  review, using the same `/api/admin/reports/{id}` PATCH endpoint that
  already exists — no new endpoint needed, just a new allowed status value
  and a queue view that includes `pending`.
- **This is GDPR Art. 9 special-category data** (health/sex-life-adjacent).
  If you're taking this beyond a personal prototype, get an actual legal
  read before public launch — this file is not legal advice, and neither
  is the honest hedging already in `outreach/PITCH-SCRIPT.md`.
- **Location precision.** `db.fuzz_coords(report_id, lat, lon, radius_m)`
  already exists and defaults to 500m for any non-verified report. For
  `sexual_violence`/`harassment` specifically, widen the default radius
  (e.g. 5–10km) regardless of verification status — these should never
  show a tight pin even once verified. Simplest change: add a
  per-category radius lookup in `app.py`'s `get_reports()` instead of the
  current flat `500`.
- **Retention/appeals.** Decide who can request a report be taken down and
  how (even "email the admin, reviewed within N days" is enough to start)
  and put a line about it on the awareness/about page.

---

## 1. Light mode (do this first — it's the most visible gap right now)

`frontend/preview-light.html` already has the exact palette to use. Port
these CSS custom-property values into `frontend/index.html` and
`admin.html`, replacing the current dark tokens:

```css
--bg:#f4f7fb; --panel:#ffffff; --panel-2:#eef2f8;
--line:#dbe3ee; --line-soft:#e8eef6;
--ink:#0b1326; --muted:#5b6b85; --faint:#8a97ac;
--accent:#0088cc; --danger:#D6363F; --ok:#1F9B54; --warn:#B8720B;
```

Also swap the Leaflet tile layer back from `dark_all` to `light_all`
(`https://{s}.basemaps.cartocdn.com/light_all/...`) and the `.mk.faded`
filter direction (fading should brighten/desaturate toward the light
background, not darken — see the comment that used to be in the very
first version of `index.html`, in git history around commit `59f6374`,
for the exact reasoning if you need it again).

Keep everything else from the current build — bottom nav, rail, timeline,
sheet, i18n wiring, role gating. This is a token swap, not a rebuild.

## 2. Make the "Report" button always reachable, independent of tab/filter

`preview-light.html` already does this — the FAB is a fixed, global
element (`position:absolute` outside `.floatbar`), not scoped to the Map
tab. Port that structure into `index.html`: currently the fab lives
inside `#mapFloatbar`, which is hidden on the Incidents/Verify/Reports
tabs (`setTab()` sets `display:none` on it). Pull the `<button class="fab"
id="fab">` out of `#mapFloatbar` to a standalone fixed element so it
survives every tab switch, same as `#quickExit` already does.

## 3. Expand the taxonomy in the backend

`reports.category` is already a free-text `TEXT` column with no CHECK
constraint — **adding new category values needs zero schema migration.**
The work is all in `backend/lawref.py`:

```python
CATEGORIES: dict[str, dict[str, str]] = {
    # existing Germany/StGB-specific ones stay — they're good, keep them
    "arson": {...}, "violence": {...}, ...,  # unchanged

    # new, broader taxonomy — colors already chosen, keep them identical
    # to outreach/landing-page.html's chipcloud and preview-light.html
    "racism":                  {"label": "Racism", "color": "#FF5C5C"},
    "islamophobia":            {"label": "Islamophobia", "color": "#FFA94D"},
    "antisemitism":            {"label": "Antisemitism", "color": "#4DA6FF"},
    "homophobia_transphobia":  {"label": "Homophobia / transphobia", "color": "#B983FF"},
    "neo_nazi":                {"label": "Neo-Nazi activity / signs", "color": "#C99400"},
    "xenophobia":              {"label": "Xenophobia", "color": "#4CD97B"},
    "sexual_violence":         {"label": "Sexual violence", "color": "#2BD9C9"},
    "harassment":              {"label": "Harassment", "color": "#E8779E"},
    "other":                   {"label": "Other", "color": "#8891A8"},
}
```

Decide whether the existing far-right/StGB categories become a *subset*
selectable only when `law` is set, or stay fully parallel/independent —
simplest for now: keep them parallel, both show in the filter list. Revisit
if it's confusing in practice.

Extend `_INDICATORS` (the regex classifier) with English-language patterns
for the new categories — it's currently German-only because the prototype
was Germany-only. Don't try to cover every language on day one; start with
English + German for 2–3 new categories, confirm signal quality, expand.

## 4. Wire `/api/reports` to accept `as_of` (year cutoff) server-side

Currently the timeline filtering in `index.html` is entirely client-side
(`timelineCutoff` + `withinTimeline()` over an already-fetched `limit=1000`
batch). That's fine while the total row count is in the low thousands —
revisit if it grows past what's comfortable to ship on every page load.
Not urgent; the client-side approach in both `index.html` and
`preview-light.html` already matches what step 7 of the old plan asked
for, functionally. Lower priority than steps 1–3.

## 5. 10-year fade (small, do alongside step 1)

`index.html` currently has `const FADE_DAYS = 30;` — a leftover from the
Germany prototype's "recent activity" framing, not the intended "history
isn't deleted, just fades after a decade" behavior. Change to:

```js
const FADE_SECONDS = 10 * 365 * 24 * 3600;
// and switch the age check from days to seconds accordingly
```

`preview-light.html` already has this correct — copy the constant and the
`ageSeconds >= FADE_SECONDS` check straight over.

## 6. i18n for the new categories

`frontend/i18n.js` has `cat.*` keys for the old 10 Germany categories in
all 4 languages. Add `cat.racism`, `cat.islamophobia`, `cat.antisemitism`,
`cat.homophobia_transphobia`, `cat.neo_nazi`, `cat.xenophobia`,
`cat.sexual_violence`, `cat.harassment` (en/de/fr/ar) — the outreach page's
English labels are a fine starting point for `en`; get real translations
for the other three before shipping, same bar as the rest of the site.

## 7. Geography — separate decision, don't couple to the taxonomy expansion

`backend/geolocate.py` still hard-gates to Germany (`in_germany()`
bounding box, Nominatim `countrycodes=de`). The new taxonomy categories
aren't Germany-specific in nature, but going global is a bigger decision
(more moderation load, more languages, more legal jurisdictions for the
`law`/statute feature). Recommendation: ship the taxonomy expansion
Germany-only first, decide geography expansion as its own follow-up once
the category work is live and you've seen real usage.

## 8. Tests

Extend `tests/test_api.py`:
- A `pending`-status report (once step 0's gate exists) is excluded from
  `GET /api/reports` for both anonymous and logged-in-but-not-ADMIN users.
- Widened fuzz radius for `sexual_violence`/`harassment` even once
  `verified` (once step 0's per-category radius exists).
- New categories appear in `GET /api/categories`.

## 9. Deploy

Same pipeline as every deploy so far — no new mechanics needed:

```bash
rsync -az --delete --exclude .git --exclude venv --exclude .pytest_cache \
  --exclude '__pycache__' --exclude 'backend/dxmap.db*' --exclude '.env' \
  /home/nabil/projects/dxmap/ dxmap-vps:/docker/dxmap/
ssh dxmap-vps "cd /docker/dxmap && docker compose build --no-cache && docker compose up -d"
```

**Use `--no-cache`.** A plain `docker compose build` bit us once already
this cycle (BuildKit reused a stale `COPY backend/` layer despite changed
source — root cause not fully diagnosed, `--no-cache` is the confirmed
reliable workaround, costs ~15s). Back up `dxmap.db` first:
`docker exec dxmap-map-1 cp /app/data/dxmap.db /app/data/dxmap.db.bak-$(date +%Y%m%d)`.

---

## Suggested order for dragon sessions

1. **Step 1 + 2 + 5** (one session, low risk, no schema/backend changes):
   light theme + persistent report button + 10-year fade. Ship this first —
   it's the most visible gap and touches only `frontend/`.
2. **Step 0 + 3** (one session): sensitive-category gate + taxonomy in
   `lawref.py`. Write the `pending` status handling with tests before
   wiring the frontend to it.
3. **Step 6** (can run parallel to step 3 once category keys are decided):
   i18n for new categories, all 4 languages.
4. **Step 4 + 8** (one session): server-side timeline param + full test
   coverage for everything shipped so far.
5. **Step 7** (separate session, only if/when you decide to go global):
   geography expansion.

Deploy (step 9) after each session that touches `backend/` or `frontend/`
— don't batch multiple sessions' changes into one deploy, keeps rollback
easier if something's wrong.
