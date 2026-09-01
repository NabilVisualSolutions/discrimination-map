import { useEffect, useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { useTranslation } from "react-i18next"
import { api, type Report } from "./lib/api"
import { LOCALES, applyLocale, type Locale } from "./i18n"
import { MapView } from "./features/map/MapView"
import { AWARENESS } from "./lib/awareness"
import { ReportModal } from "./features/report/ReportModal"

// Full-screen map. Everything else floats over it: a top search/filter bar,
// a category panel, and one bottom sheet that shows either the incident
// list, a selected incident's Akte, or the Laws / Symbols / Get-involved
// pages. Mobile-first; the same layout scales up on desktop.

type SheetView = "incidents" | "detail" | "laws" | "awareness" | "involved"
type SheetSnap = "peek" | "half" | "full"
type Law = { code: string; title: string; summary?: string; penalty?: string }

const SNAP_H: Record<SheetSnap, string> = { peek: "84px", half: "56vh", full: "92vh" }

export function App() {
  const { t, i18n } = useTranslation()
  const [selected, setSelected] = useState<Report | null>(null)
  const [hiddenCats, setHiddenCats] = useState<Set<string>>(() => new Set())
  const [q, setQ] = useState("")
  const [cutoff, setCutoff] = useState<number | null>(null)
  const [showReport, setShowReport] = useState(false)
  const [focus, setFocus] = useState<{ lon: number; lat: number; zoom: number } | null>(null)
  const [geoHits, setGeoHits] = useState<{ lat: number; lon: number; label: string }[]>([])
  const [showFilters, setShowFilters] = useState(false)
  const [view, setView] = useState<SheetView>("incidents")
  const [snap, setSnap] = useState<SheetSnap>("peek")
  const [noticeDismissed, setNoticeDismissed] = useState(false)
  const [langOpen, setLangOpen] = useState(false)
  void t

  const cats = useQuery({ queryKey: ["categories"], queryFn: api.categories, staleTime: 3_600_000 })
  const reportsQ = useQuery({ queryKey: ["reports"], queryFn: () => api.reports({ limit: 5000, all: true }), staleTime: 60_000 })
  const lawsQ = useQuery({ queryKey: ["laws"], queryFn: api.laws, staleTime: 3_600_000 })
  const meQ = useQuery({ queryKey: ["me"], queryFn: api.me, staleTime: 300_000, retry: false })
  const me = meQ.data?.user ?? null

  const reports = reportsQ.data ?? []
  const categories = cats.data ?? {}
  const laws = (Array.isArray(lawsQ.data) ? lawsQ.data : (lawsQ.data as { laws?: Law[] } | undefined)?.laws ?? []) as Law[]

  const now = Math.floor(Date.now() / 1000)
  const earliest = useMemo(() => (reports.length ? Math.min(...reports.map((r) => r.created_at)) : now - 365 * 86400), [reports, now])
  const effectiveCutoff = cutoff ?? now

  const filtered = useMemo(() => {
    let r = reports.filter((x) => !hiddenCats.has(x.category) && x.created_at <= effectiveCutoff)
    const needle = q.trim().toLowerCase()
    if (needle) {
      r = r.filter(
        (x) =>
          (x.title + " " + (x.body ?? "") + " " + (x.place ?? "") + " " + x.category).toLowerCase().includes(needle) ||
          String(x.id).includes(needle)
      )
    }
    return r.sort((a, b) => b.created_at - a.created_at)
  }, [reports, hiddenCats, effectiveCutoff, q])

  const last24 = useMemo(() => reports.filter((r) => now - r.created_at < 86400).length, [reports, now])
  const aw = (AWARENESS as Record<string, typeof AWARENESS.en>)[i18n.language] || AWARENESS.en

  const quickExit = () => location.replace("https://www.google.com/search?q=weather")
  const locateMe = () => {
    navigator.geolocation?.getCurrentPosition(
      (p) => setFocus({ lon: p.coords.longitude, lat: p.coords.latitude, zoom: 9 }),
      () => {},
      { enableHighAccuracy: true }
    )
  }
  const toggleCat = (c: string) =>
    setHiddenCats((s) => {
      const n = new Set(s)
      if (n.has(c)) n.delete(c)
      else n.add(c)
      return n
    })
  const openDetail = (r: Report) => {
    setSelected(r)
    setView("detail")
    setSnap((s) => (s === "peek" ? "half" : s))
    if (r.lat != null && r.lon != null) setFocus({ lat: r.lat, lon: r.lon, zoom: 11 })
  }
  const cycleSnap = () => setSnap((s) => (s === "peek" ? "half" : s === "half" ? "full" : "peek"))

  useEffect(() => {
    if (q.trim().length < 3) {
      setGeoHits([])
      return
    }
    const id = setTimeout(async () => {
      try {
        setGeoHits((await api.geocode(q.trim())).slice(0, 5))
      } catch {
        setGeoHits([])
      }
    }, 450)
    return () => clearTimeout(id)
  }, [q])

  const timelinePct = earliest === now ? 1000 : Math.round(((effectiveCutoff - earliest) / (now - earliest)) * 1000)
  const catList = useMemo(
    () =>
      Object.entries(categories)
        .map(([k, m]) => ({ k, ...m, count: reports.filter((r) => r.category === k).length }))
        .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label)),
    [categories, reports]
  )

  return (
    <div className="app">
      <MapView reports={reports} categories={categories} onSelect={openDetail} hiddenCats={hiddenCats} focus={focus} />

      {!noticeDismissed && (
        <div className="notice">
          <b>Dokumentation, nicht Anklage.</b> Unverifizierte Hinweise — angeblich, nicht bewiesen. Notfall: 110.
          <button onClick={() => setNoticeDismissed(true)} aria-label="close">✕</button>
        </div>
      )}

      <div className="topbar">
        <div className="search">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
            <circle cx={11} cy={11} r={7} />
            <path d="M21 21l-4.3-4.3" />
          </svg>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ort, Kategorie oder #ID suchen…" aria-label="Suche" />
          {geoHits.length > 0 && (
            <div className="geo">
              {geoHits.map((h) => (
                <button
                  key={h.label + h.lat}
                  onClick={() => {
                    setFocus({ lat: h.lat, lon: h.lon, zoom: 9 })
                    setGeoHits([])
                    setQ(h.label)
                  }}
                >
                  ↗ {h.label}
                </button>
              ))}
            </div>
          )}
        </div>
        <button className={`tb-btn${showFilters ? " on" : ""}`} onClick={() => setShowFilters((v) => !v)} aria-label="Filter">⚑</button>
        <button className="tb-btn" onClick={locateMe} aria-label="Mein Standort">◎</button>
        <div className="lang">
          <button className="tb-btn" onClick={() => setLangOpen((v) => !v)} aria-label="Sprache">{i18n.language.toUpperCase()}</button>
          {langOpen && (
            <div className="lang-menu">
              {LOCALES.map((l) => (
                <button
                  key={l}
                  onClick={() => {
                    applyLocale(l as Locale)
                    setLangOpen(false)
                  }}
                  className={l === i18n.language ? "on" : ""}
                >
                  {l.toUpperCase()}
                </button>
              ))}
            </div>
          )}
        </div>
        <button className="tb-btn exit" onClick={quickExit}>Exit ✕</button>
      </div>

      {showFilters && (
        <div className="filters">
          <div className="frow">
            <b>{last24} neu / 24 h</b>
            <button onClick={() => setHiddenCats(new Set())}>Alle zeigen</button>
          </div>
          <div className="chips">
            {catList.map((c) => {
              const on = !hiddenCats.has(c.k)
              return (
                <button key={c.k} className={`chip${on ? " on" : ""}`} onClick={() => toggleCat(c.k)}>
                  <span className="dot" style={{ background: c.color }} />
                  {c.label}
                  <span className="cnt">{c.count}</span>
                </button>
              )
            })}
          </div>
          <label className="tl">
            <span>{new Date(earliest * 1000).toLocaleDateString("de-DE")}</span>
            <b>{cutoff == null ? "Heute" : new Date(effectiveCutoff * 1000).toLocaleDateString("de-DE")}</b>
          </label>
          <input
            type="range"
            min={0}
            max={1000}
            value={timelinePct}
            onChange={(e) => {
              const v = +e.target.value
              setCutoff(v >= 1000 ? null : Math.round(earliest + (v / 1000) * (now - earliest)))
            }}
          />
        </div>
      )}

      <button className="fab" onClick={() => setShowReport(true)}>+ Vorfall melden</button>

      <div className="sheet" style={{ height: SNAP_H[snap] }}>
        <button className="grip" onClick={cycleSnap} aria-label="Panel-Höhe">
          <span />
        </button>
        <div className="sheet-tabs">
          {(["incidents", "laws", "awareness", "involved"] as SheetView[]).map((v) => (
            <button
              key={v}
              className={view === v || (v === "incidents" && view === "detail") ? "on" : ""}
              onClick={() => {
                setView(v)
                setSelected(null)
                setSnap((s) => (s === "peek" ? "half" : s))
              }}
            >
              {v === "incidents"
                ? `Vorfälle ${filtered.length}`
                : v === "laws"
                  ? `Recht ${laws.length}`
                  : v === "awareness"
                    ? "Symbole"
                    : "Mitmachen"}
            </button>
          ))}
        </div>

        <div className="sheet-body">
          {view === "detail" && selected && (
            <Detail
              r={selected}
              categories={categories}
              onBack={() => setView("incidents")}
              onLocate={(r) => setFocus({ lat: r.lat!, lon: r.lon!, zoom: 12 })}
            />
          )}

          {view === "incidents" && (
            <>
              {reportsQ.isLoading && <p className="muted">Karte wird geladen…</p>}
              {!reportsQ.isLoading && filtered.length === 0 && <p className="muted">Keine Vorfälle für diese Filter.</p>}
              {filtered.slice(0, 300).map((r) => {
                const col = categories[r.category]?.color ?? "#8a97ac"
                const d = new Date(r.created_at * 1000)
                const isNew = now - r.created_at < 3 * 86400
                return (
                  <button key={r.id} className="row" onClick={() => openDetail(r)}>
                    <span className="bar" style={{ background: col }} />
                    <span className="row-main">
                      <span className="row-t">{r.title}</span>
                      <span className="row-m">
                        <b style={{ color: col }}>{categories[r.category]?.label ?? r.category}</b>
                        {" · "}
                        {r.status}
                        {" · "}
                        {r.place || "—"}
                        {" · "}
                        {d.toLocaleDateString("de-DE")}
                        {r.fuzzed ? " · ~ungefähr" : ""}
                      </span>
                    </span>
                    {isNew && <span className="new">neu</span>}
                  </button>
                )
              })}
            </>
          )}

          {view === "laws" && (
            <>
              <p className="muted">StGB — Vorschriften, die einschlägig sein können.</p>
              {laws.map((l) => (
                <div key={l.code} className="card">
                  <div className="card-k">{l.code}</div>
                  <div className="card-t">{l.title}</div>
                  {l.summary && <p className="muted sm">{l.summary}</p>}
                </div>
              ))}
              {laws.length === 0 && <p className="muted">Wird geladen…</p>}
            </>
          )}

          {view === "awareness" && (
            <>
              <h3>{aw.h1}</h3>
              <p className="muted">{aw.lede}</p>
              {aw.symbols.map((s: { code: string; title: string; body: string }) => (
                <div key={s.title} className="card">
                  <div className="card-k">{s.code}</div>
                  <div className="card-t">{s.title}</div>
                  <p className="muted sm">{s.body}</p>
                </div>
              ))}
            </>
          )}

          {view === "involved" && (
            <>
              <h3>Mitmachen</h3>
              <p className="muted">Moderator:innen, Übersetzer:innen, Entwickler:innen, Partnerorganisationen.</p>
              <a className="link-row" href="https://nabilvs.com/projects/discrimination-map#get-involved" target="_blank" rel="noreferrer">
                Freiwillig helfen, übersetzen, mitprogrammieren →
              </a>
              <a className="link-row" href="/guide">Neu? Zum Schritt-für-Schritt-Leitfaden →</a>
              <a className="link-row" href="/admin">Reviewer oder Admin? Zu /admin →</a>
              <a className="link-row" href="/privacy">Datenschutz</a>
              <a className="link-row" href="/terms">Nutzungsbedingungen</a>
              {me && <a className="link-row" href="/admin">Angemeldet als {me.email} · {me.role}</a>}
            </>
          )}
        </div>
      </div>

      {showReport && <ReportModal categories={categories} onClose={() => setShowReport(false)} />}
    </div>
  )
}

function Detail({
  r,
  categories,
  onBack,
  onLocate,
}: {
  r: Report
  categories: Record<string, { label: string; color: string }>
  onBack: () => void
  onLocate: (r: Report) => void
}) {
  const col = categories[r.category]?.color ?? "#8a97ac"
  return (
    <div className="detail">
      <button className="back" onClick={onBack}>← Alle Vorfälle</button>
      <div className="d-meta">
        AKTE #{String(r.id).padStart(4, "0")} · {new Date(r.created_at * 1000).toLocaleString("de-DE")} · {r.place ?? "—"}
      </div>
      <h3>{r.title}</h3>
      <div className="d-tags">
        <span className="tag" style={{ background: `${col}22`, color: col }}>{categories[r.category]?.label ?? r.category}</span>
        <span className="tag">{r.status}</span>
        <span className="tag">{r.fuzzed ? "~ungefähr" : "exakt"}</span>
      </div>
      {r.body && <p>{r.body}</p>}
      {r.reason && (
        <>
          <div className="d-h">Erkennungsgrund</div>
          <p className="muted">{r.reason}</p>
        </>
      )}
      {r.impact && (
        <>
          <div className="d-h">Auswirkung</div>
          <p className="muted">{r.impact}</p>
        </>
      )}
      {r.evidence && (
        <>
          <div className="d-h">Beleg</div>
          <p className="muted sm">{r.evidence}</p>
        </>
      )}
      {r.law && (
        <>
          <div className="d-h">Recht</div>
          <p className="muted">{r.law}</p>
        </>
      )}
      <div className="d-actions">
        {r.lat != null && <button className="btn" onClick={() => onLocate(r)}>Auf der Karte zeigen</button>}
        {r.url && (
          <a className="btn primary" href={r.url} target="_blank" rel="noreferrer">
            Quelle öffnen ↗
          </a>
        )}
      </div>
    </div>
  )
}
