# Next Steps: From Mockup to Real Discrimination Map

This picks up where `frontend/discrimination-map-mockup.html` leaves off —
that file is a **static preview with sample data**, not wired to the backend.
Work through this checklist on dragon, in order; each step builds on the last.

**Scope assumption to confirm first:** this roadmap assumes you're expanding
from the Germany-only build to a **global** map. If you actually want to
keep it Germany-only for now and go global later, skip step 4 (geo-restriction
removal) and step 6 (multi-region legal packs) — everything else still applies.

---

## 0. Before writing code: decide the sensitive-data policy

This isn't optional groundwork — it shapes the schema in step 1. Decide, and
write down in `PLAN.md`:

- **Does the `sexual` (rape/assault) category go live automatically, or does
  it require human moderation before appearing on the public map?**
  Recommendation: require moderation for this category specifically, even if
  other categories can stay auto-visible as unverified leads. The cost of a
  false/malicious report in this category is much higher than for, say,
  "harassment."
- **Location precision by category.** Decide a default fuzz radius (e.g.
  round to ~5–10km / nearest town centroid) for `sexual` and `harassment`
  categories specifically, applied server-side, not just as a client checkbox
  (the mockup's checkbox is a UI placeholder — see step 3).
- **Retention/appeals.** Who can request a report be removed, and how? Even
  a simple "email us and we'll review within N days" is better than nothing.

Write these decisions down before step 1, so the schema doesn't need a
rewrite later.

---

## 1. Update the database schema (`backend/db.py`)

Generalize `reports` beyond the Germany-specific shape:

```sql
-- Replace the old `law` column's assumption (single German statute) with:
category      TEXT NOT NULL,        -- one of the CATEGORIES keys (see step 2)
approx_loc    INTEGER DEFAULT 0,    -- 1 if lat/lon were fuzzed before storage
moderation    TEXT DEFAULT 'auto',  -- 'auto' | 'pending' | 'approved' | 'rejected'
```

Keep `reason`, `evidence`, `impact`, `status`, `lat`, `lon`, `place`,
`created_at` as-is — they're category-agnostic and already correct.

Add a migration note to `README.md` since existing deployments have the old
schema (SQLite: `ALTER TABLE reports ADD COLUMN ...` for each new column,
guarded with a `try/except` so re-running `init_db()` stays idempotent, same
pattern as the existing `_SCHEMA` script).

## 2. Create `backend/categories.py`

Port the `CATEGORIES` array straight out of the mockup's `<script>` block —
it's already the source of truth for keys, labels, and colors:

```python
CATEGORIES = {
    "racism":       {"label": "Racism", "color": "#FF5C5C"},
    "islamophobia": {"label": "Islamophobia", "color": "#FFA94D"},
    "antisemitism": {"label": "Antisemitism", "color": "#4DA6FF"},
    "homophobia":   {"label": "Homophobia / transphobia", "color": "#B983FF"},
    "neonazi":      {"label": "Neo-Nazi attack or symbol", "color": "#FFD23F"},
    "xenophobia":   {"label": "Xenophobia / anti-migrant", "color": "#4CD97B"},
    "sexual":       {"label": "Rape / sexual assault", "color": "#2BD9C9",
                      "requires_moderation": True, "fuzz_km": 10},
    "harassment":   {"label": "Harassment", "color": "#E8779E", "fuzz_km": 5},
    "other":        {"label": "Other discrimination", "color": "#8891A8"},
}
```

Add a `GET /api/categories` endpoint in `app.py` that returns this dict —
mirrors the existing `/api/laws` pattern, and lets the real frontend build
its filter list from the backend instead of hardcoding it twice.

## 3. Server-side location fuzzing

This is the one item that must not stay client-side-only. In
`db.insert_report`, before storing:

```python
def fuzz_coordinates(lat: float, lon: float, km: float) -> tuple[float, float]:
    """Round to a grid cell roughly `km` wide. Deterministic, not random —
    keeps repeat reports from the same area clustering sensibly."""
    deg = km / 111.0  # ~111km per degree latitude, close enough for fuzzing
    return (round(lat / deg) * deg, round(lon / deg) * deg)
```

Apply it automatically for any category with a `fuzz_km` entry (see step 2),
regardless of what a client sends — never trust the client to have applied
it. Store `approx_loc=1` on the row so the UI can show a "location
approximated" note honestly.

## 4. Generalize `geolocate.py` (drop the hard Germany gate)

Replace the hardcoded `_DE_BOX` bounding-box gate with a configurable
allow-list:

```python
ALLOWED_REGIONS = os.environ.get("HERMES_REGIONS", "").strip()  # "" = no restriction, global
```

Keep the gazetteer, but expand it well beyond German cities — or better,
switch fully to Nominatim for anything the gazetteer misses (already wired
up) and treat the gazetteer as a fast-path cache, not the primary source.

## 5. Update `hermes.py` search terms for multi-category, multi-language

The current `SEARCH_TERMS` list is German-far-right-specific. Restructure as
a dict keyed by category, each with terms in relevant languages:

```python
CATEGORY_TERMS = {
    "islamophobia": ["mosque attack", "hijab harassment", "Islamophobie"],
    "antisemitism": ["antisemitic attack", "synagogue vandalized", "Antisemitismus"],
    # ...
}
```

Start with 2–3 categories and a couple of languages, confirm the classifier
(step 6) isn't producing noise, then expand. Scanning every category in every
language from day one will both blow through your heartbeat budget and
produce a lot of false positives to review.

## 6. Turn `lawref.py` into a pluggable regional legal-reference system

Don't delete the German statute work — it's good and specific. Instead:

```
backend/
  legal/
    __init__.py       # generic interface: classify(text) -> category + optional law_ref
    germany.py         # move the existing lawref.py content here unchanged
    # add more later: france.py, uk.py, us_federal.py, ...
```

The generic classifier (step 2's categories) runs everywhere; a regional pack
like `germany.py` *additionally* tags a possibly-applicable statute when the
report's location falls in that region. This is how you keep the excellent
German legal detail without hardcoding it as the only legal system the whole
app understands.

## 7. Wire the timeline into the API

Add an `as_of` query param to `GET /api/reports`:

```python
@app.get("/api/reports")
def get_reports(limit: int = 500, all: bool = False, as_of: int | None = None):
    # as_of = a year; filter to created_at <= end of that year
```

Keep the fade computation client-side (it's cheap and already correct in the
mockup) — the API just needs to stop returning future-dated reports relative
to `as_of`.

## 8. Moderation queue for the `sexual` category (and anything else you flagged in step 0)

Simplest version that's still real: reports in `moderation='pending'` are
excluded from the public `/api/reports` response by default; add an
authenticated `/api/moderation/queue` + `/api/moderation/{id}/approve|reject`
pair, gated behind HTTP basic auth or a simple token to start (upgrade later).
Don't ship the sensitive category publicly without this — see step 0.

## 9. Bring the real frontend up to the mockup's UX

Port the mockup's rail/timeline/fab/resources markup into `frontend/index.html`,
replacing the sample `SAMPLE` array with real `fetch('/api/reports?as_of=...')`
calls, and `fetch('/api/categories')` for the filter list instead of the
hardcoded `CATEGORIES` array. Keep the quick-exit button and resources panel
— they're not decorative, carry them over exactly.

## 10. Localize the resources panel

The mockup's resources modal is explicitly placeholder content. Before any
public deployment, replace it with real, current, region-appropriate
resources — and if you deploy to multiple regions/languages, key the content
off the visitor's locale or a manual region switcher.

## 11. Tests

Extend `tests/test_api.py`:
- Fuzzing: assert a `sexual`-category report never returns exact submitted
  coordinates.
- Moderation: assert a pending `sexual` report doesn't appear in
  `GET /api/reports` until approved.
- Timeline: assert `as_of=2015` excludes later reports.
- Categories: assert `/api/categories` returns all expected keys.

## 12. Deploy

No changes needed to `deploy/` — same systemd/Nginx setup. Just re-run
`git pull && systemctl restart hermes` on the VPS per
`DEVELOPMENT-WORKFLOW.md` once steps 1–11 are tested locally on dragon.

---

## Suggested order to tackle this in Claude Code sessions

1. Steps 0–2 (one session): policy decisions + schema + categories module.
2. Step 3 (one session): fuzzing, with tests written first.
3. Steps 4–6 (one or two sessions): geo + terms + legal-pack refactor.
4. Steps 7–9 (one session): API + frontend wiring.
5. Step 8 revisited + step 10 (one session): moderation + real resources.
6. Step 11 throughout, not saved for the end — add tests in the same session
   as the feature per `DEVELOPMENT-WORKFLOW.md`'s Tier 1 workflow.
