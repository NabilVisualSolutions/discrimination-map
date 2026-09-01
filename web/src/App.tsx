import { useEffect, useMemo, useRef, useState, type FormEvent } from "react"
import { useQuery } from "@tanstack/react-query"
import { useTranslation } from "react-i18next"
import { api, type Law, type Report, type ReportStatus } from "./lib/api"
import { LOCALES, applyLocale, type Locale } from "./i18n"
import { MapView } from "./features/map/MapView"
import { AWARENESS } from "./lib/awareness"
import { ReportModal } from "./features/report/ReportModal"
import { latestEditable, minutesLeft, type MineEntry } from "./lib/mine"

// Full-screen map. Everything floats over it: a top search/filter bar, a
// category panel, a persistent timeline at the bottom, and one sheet that
// shows the incident list, an incident's file, the spreadsheet, the laws,
// the symbols guide, or Get involved. Mobile-first; scales up on desktop.

type SheetView = "incidents" | "detail" | "table" | "laws" | "awareness" | "involved" | "review"
type SheetSnap = "peek" | "half" | "full"

const SNAP_H: Record<SheetSnap, string> = { peek: "84px", half: "56vh", full: "92vh" }
const when = (r: Report) => r.occurred_at ?? r.created_at
const DAY = 86400

export function App() {
  const { t, i18n } = useTranslation()
  const [selected, setSelected] = useState<Report | null>(null)
  const [hiddenCats, setHiddenCats] = useState<Set<string>>(() => new Set())
  const [lawFilter, setLawFilter] = useState<string | null>(null)
  const [q, setQ] = useState("")
  const [fromTs, setFromTs] = useState<number | null>(null)
  const [showReport, setShowReport] = useState(false)
  const [reportPreset, setReportPreset] = useState<{ lat: number; lon: number } | null>(null)
  const [focus, setFocus] = useState<{ lon: number; lat: number; zoom: number } | null>(null)
  const [geoHits, setGeoHits] = useState<{ lat: number; lon: number; label: string }[]>([])
  const [showFilters, setShowFilters] = useState(false)
  const [view, setView] = useState<SheetView>("incidents")
  const [snap, setSnap] = useState<SheetSnap>("peek")
  const [noticeDismissed, setNoticeDismissed] = useState(false)
  const [langOpen, setLangOpen] = useState(false)
  const [splash, setSplash] = useState(true)
  const [reportEdit, setReportEdit] = useState<{ id: number; token: string } | null>(null)
  const [mine, setMine] = useState<MineEntry | null>(() => latestEditable())
  const didGeo = useRef(false)

  const cats = useQuery({ queryKey: ["categories"], queryFn: api.categories, staleTime: 3_600_000 })
  const reportsQ = useQuery({ queryKey: ["reports"], queryFn: () => api.reports({ limit: 5000, all: true }), staleTime: 60_000 })
  const lawsQ = useQuery({ queryKey: ["laws", i18n.language], queryFn: () => api.laws(i18n.language), staleTime: 600_000 })
  const meQ = useQuery({ queryKey: ["me"], queryFn: api.me, staleTime: 300_000, retry: false })
  const me = meQ.data ?? null
  const isReviewer = me?.role === "ADMIN" || me?.role === "VERIFIER"

  const queueQ = useQuery({
    queryKey: ["review-queue"],
    queryFn: () => api.adminReports({ status: "unverified,pending", limit: 500 }),
    enabled: isReviewer,
    staleTime: 30_000,
  })
  const queue = queueQ.data?.reports ?? []

  const reports = reportsQ.data ?? []
  const categories = cats.data ?? {}
  const laws: Law[] = lawsQ.data?.laws ?? []

  const now = Math.floor(Date.now() / 1000)
  const earliest = useMemo(
    () => (reports.length ? Math.min(...reports.map(when)) : now - 365 * DAY),
    [reports, now]
  )
  const effFrom = fromTs ?? earliest

  const catOf = (r: Report) => r.category.split(/[,|/]/).map((s) => s.trim()).filter(Boolean)
  const visibleCat = (r: Report) => catOf(r).some((c) => !hiddenCats.has(c))

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return reports
      .filter((x) => visibleCat(x) && when(x) >= effFrom)
      .filter((x) => !lawFilter || x.law === lawFilter)
      .filter(
        (x) =>
          !needle ||
          (x.title + " " + (x.body ?? "") + " " + (x.place ?? "") + " " + x.category)
            .toLowerCase()
            .includes(needle) ||
          String(x.id).includes(needle)
      )
      .sort((a, b) => when(b) - when(a))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reports, hiddenCats, effFrom, q, lawFilter])

  // Reports the map itself draws (time + category + law, no text search — the
  // list narrows further but the map stays legible while you type).
  const mapReports = useMemo(
    () =>
      reports
        .filter((x) => visibleCat(x) && when(x) >= effFrom)
        .filter((x) => !lawFilter || x.law === lawFilter),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [reports, hiddenCats, effFrom, lawFilter]
  )

  const aw = (AWARENESS as Record<string, typeof AWARENESS.en>)[i18n.language] || AWARENESS.en

  // Month histogram for the timeline (over the full dataset, not the filter).
  const histogram = useMemo(() => {
    if (!reports.length) return [] as { t: number; n: number }[]
    const span = Math.max(1, now - earliest)
    const buckets = 48
    const arr = Array.from({ length: buckets }, (_, i) => ({
      t: earliest + Math.round((i / buckets) * span),
      n: 0,
    }))
    for (const r of reports) {
      const i = Math.min(buckets - 1, Math.floor(((when(r) - earliest) / span) * buckets))
      if (i >= 0) arr[i].n++
    }
    const max = Math.max(1, ...arr.map((b) => b.n))
    return arr.map((b) => ({ ...b, n: b.n / max }))
  }, [reports, earliest, now])

  const moderate = async (r: Report, status: ReportStatus) => {
    await api.setStatus(r.id, status)
    await Promise.all([reportsQ.refetch(), isReviewer ? queueQ.refetch() : Promise.resolve()])
    setSelected((s) => (s && s.id === r.id ? { ...s, status } : s))
  }
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
  const openReportAt = (lat: number, lon: number) => {
    setReportEdit(null)
    setReportPreset({ lat, lon })
    setShowReport(true)
  }
  const cycleSnap = () => setSnap((s) => (s === "peek" ? "half" : s === "half" ? "full" : "peek"))

  // Slogan interstitial: first load + every language switch, 2.5s.
  useEffect(() => {
    setSplash(true)
    const id = setTimeout(() => setSplash(false), 2500)
    return () => clearTimeout(id)
  }, [i18n.language])

  // One-shot: centre on the visitor's real position while the page opens.
  // Silent if they decline — the worldwide view stays.
  useEffect(() => {
    if (didGeo.current || !navigator.geolocation) return
    didGeo.current = true
    navigator.geolocation.getCurrentPosition(
      (p) => setFocus({ lon: p.coords.longitude, lat: p.coords.latitude, zoom: 6 }),
      () => {},
      { timeout: 8000, maximumAge: 600000 }
    )
  }, [])

  // Deep link from the "edit link" handed back at submission time.
  useEffect(() => {
    const p = new URLSearchParams(location.search)
    const id = Number(p.get("report"))
    const token = p.get("token")
    if (id && token) {
      setReportEdit({ id, token })
      setShowReport(true)
    }
  }, [])

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

  const catList = useMemo(
    () =>
      Object.entries(categories)
        .map(([k, m]) => ({ k, ...m, count: reports.filter((r) => catOf(r).includes(k)).length }))
        .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [categories, reports]
  )
  const allCatKeys = catList.map((c) => c.k)

  const fromPct = earliest === now ? 0 : Math.round(((effFrom - earliest) / (now - earliest)) * 1000)
  const fmtDate = (ts: number) => new Date(ts * 1000).toLocaleDateString(i18n.language)

  const TABS: SheetView[] = isReviewer
    ? ["incidents", "review", "table", "laws", "awareness", "involved"]
    : ["incidents", "table", "laws", "awareness", "involved"]

  return (
    <div className="app">
      <MapView
        reports={mapReports}
        categories={categories}
        onSelect={openDetail}
        onReportAt={openReportAt}
        hiddenCats={hiddenCats}
        focus={focus}
      />

      {!noticeDismissed && (
        <div className="notice">
          {t("notice")}
          <button onClick={() => setNoticeDismissed(true)} aria-label="close">✕</button>
        </div>
      )}

      <div className="topbar">
        <div className="search">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
            <circle cx={11} cy={11} r={7} />
            <path d="M21 21l-4.3-4.3" />
          </svg>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("search.ph")} aria-label={t("search.ph")} />
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
        <button
          className={`tb-btn${showFilters ? " on" : ""}`}
          onClick={() => setShowFilters((v) => !v)}
          aria-label={t("filter")}
        >
          ⚑ {allCatKeys.length - hiddenCats.size}/{allCatKeys.length}
        </button>
        <button className="tb-btn" onClick={locateMe} aria-label={t("locate")}>◎</button>
        <div className="lang">
          <button className="tb-btn" onClick={() => setLangOpen((v) => !v)} aria-label="Language">{i18n.language.toUpperCase()}</button>
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
        <a className="tb-btn" href="/guide" target="_blank" rel="noreferrer">{t("guide")}</a>
        <a className="tb-btn" href="/awareness" target="_blank" rel="noreferrer">{t("awarenessGuide")}</a>
      </div>

      {showFilters && (
        <div className="filters">
          <div className="frow">
            <b>{t("filter.categories")}</b>
            <span>
              <button onClick={() => setHiddenCats(new Set())}>{t("showAll")}</button>
              <button onClick={() => setHiddenCats(new Set(allCatKeys))}>{t("hideAll")}</button>
            </span>
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
          {lawFilter && (
            <button className="chip on" onClick={() => setLawFilter(null)}>
              {t("laws.filtered", { code: lawFilter })} ✕
            </button>
          )}
        </div>
      )}

      <div className="fab-stack">
        {mine && (
          <button
            className="fab ghost"
            onClick={() => {
              setReportEdit({ id: mine.id, token: mine.token })
              setReportPreset(null)
              setShowReport(true)
            }}
          >
            ✎ {t("editMine", { n: minutesLeft(mine) })}
          </button>
        )}
        <button
          className="fab"
          onClick={() => {
            setReportEdit(null)
            setReportPreset(null)
            setShowReport(true)
          }}
        >
          + {t("report.button")}
        </button>
      </div>

      {/* persistent timeline — filter the map + lists by when incidents happened */}
      <div className="timeline">
        <div className="tl-head">
          <span>{t("timeline.label")}</span>
          <b>
            {fromTs == null ? t("timeline.all") : fmtDate(effFrom)} — {t("today")}
          </b>
        </div>
        <div className="tl-hist" aria-hidden>
          {histogram.map((b, i) => (
            <span key={i} style={{ height: `${Math.max(4, b.n * 100)}%`, opacity: b.t >= effFrom ? 1 : 0.25 }} />
          ))}
        </div>
        <input
          type="range"
          min={0}
          max={1000}
          value={fromPct}
          onChange={(e) => {
            const v = +e.target.value
            setFromTs(v <= 0 ? null : Math.round(earliest + (v / 1000) * (now - earliest)))
          }}
          aria-label={t("timeline.label")}
        />
      </div>

      <div className="sheet" style={{ height: SNAP_H[snap] }}>
        <button className="grip" onClick={cycleSnap} aria-label={t("timeline.label")}>
          <span />
        </button>
        <div className="sheet-tabs">
          {TABS.map((v) => (
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
                ? `${t("tab.incidents")} ${filtered.length}`
                : v === "review"
                  ? `${t("tab.review")} ${queue.length}`
                  : v === "table"
                    ? t("tab.table")
                    : v === "laws"
                      ? `${t("tab.laws")} ${laws.filter((l) => l.count).length}`
                      : v === "awareness"
                        ? t("tab.symbols")
                        : t("tab.involved")}
            </button>
          ))}
        </div>

        <div className="sheet-body">
          {view === "detail" && selected && (
            <Detail
              r={selected}
              categories={categories}
              canModerate={isReviewer}
              onModerate={moderate}
              onBack={() => setView("incidents")}
              onLocate={(r) => setFocus({ lat: r.lat!, lon: r.lon!, zoom: 12 })}
            />
          )}

          {view === "incidents" && (
            <>
              {reportsQ.isLoading && <p className="muted">{t("loadingMap")}</p>}
              {!reportsQ.isLoading && filtered.length === 0 && <p className="muted">{t("noResults")}</p>}
              {filtered.slice(0, 300).map((r) => {
                const col = categories[catOf(r)[0]]?.color ?? "#8a97ac"
                const isNew = now - when(r) < 3 * DAY
                return (
                  <button key={r.id} className="row" onClick={() => openDetail(r)}>
                    <span className="bar" style={{ background: col }} />
                    <span className="row-main">
                      <span className="row-t">{r.title}</span>
                      <span className="row-m">
                        <b style={{ color: col }}>{categories[catOf(r)[0]]?.label ?? r.category}</b>
                        {" · "}
                        {r.status}
                        {" · "}
                        {r.place || "—"}
                        {" · "}
                        {fmtDate(when(r))}
                        {r.fuzzed ? ` · ${t("detail.approx")}` : ""}
                      </span>
                    </span>
                    {isNew && <span className="new">{t("row.new")}</span>}
                  </button>
                )
              })}
            </>
          )}

          {view === "table" && (
            <IncidentTable rows={filtered} categories={categories} onOpen={openDetail} fmtDate={fmtDate} />
          )}

          {view === "review" && isReviewer && (
            <>
              <h3>{t("review.title")}</h3>
              <p className="muted sm">{t("review.hint")}</p>
              {queueQ.isLoading && <p className="muted">{t("loadingShort")}</p>}
              {!queueQ.isLoading && queue.length === 0 && <p className="muted">{t("review.empty")}</p>}
              {queue.map((r) => {
                const col = categories[catOf(r)[0]]?.color ?? "#8a97ac"
                return (
                  <div key={r.id} className="qrow">
                    <button className="qrow-main" onClick={() => openDetail(r)}>
                      <span className="bar" style={{ background: col }} />
                      <span className="row-main">
                        <span className="row-t">{r.title}</span>
                        <span className="row-m">
                          <b style={{ color: col }}>{categories[catOf(r)[0]]?.label ?? r.category}</b>
                          {" · "}
                          {r.status}
                          {" · "}
                          {r.place || "—"}
                          {" · "}
                          {fmtDate(when(r))}
                        </span>
                      </span>
                    </button>
                    <div className="qrow-acts">
                      <button className="btn ok sm" onClick={() => moderate(r, "verified")}>{t("mod.confirm")}</button>
                      <button className="btn no sm" onClick={() => moderate(r, "dismissed")}>{t("mod.decline")}</button>
                      <button className="btn sm" onClick={() => moderate(r, "irrelevant")}>{t("mod.irrelevant")}</button>
                    </div>
                  </div>
                )
              })}
            </>
          )}

          {view === "laws" && (
            <>
              <p className="muted">{t("laws.intro")}</p>
              {laws.length === 0 && <p className="muted">{t("loadingShort")}</p>}
              {laws.map((l) => (
                <button
                  key={l.code}
                  className={`card card-btn${lawFilter === l.code ? " on" : ""}`}
                  onClick={() => {
                    setLawFilter((f) => (f === l.code ? null : l.code))
                    setView("incidents")
                  }}
                >
                  <div className="card-k">
                    {l.code}
                    <span className="law-count">{t("laws.count", { n: l.count })}</span>
                  </div>
                  <div className="card-t">{l.title}</div>
                  {l.summary && <p className="muted sm">{l.summary}</p>}
                  {l.penalty && <p className="muted sm"><b>{t("detail.penalty")}:</b> {l.penalty}</p>}
                </button>
              ))}
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
            <Involved
              me={me}
              onChanged={async () => {
                await meQ.refetch()
                await queueQ.refetch()
              }}
              onGoReview={() => {
                setView("review")
                setSnap((s) => (s === "peek" ? "half" : s))
              }}
            />
          )}
        </div>
      </div>

      {showReport && (
        <ReportModal
          categories={categories}
          editId={reportEdit?.id}
          editToken={reportEdit?.token}
          presetLat={reportPreset?.lat}
          presetLon={reportPreset?.lon}
          onClose={() => {
            setShowReport(false)
            setReportEdit(null)
            setReportPreset(null)
          }}
          onSaved={() => {
            setMine(latestEditable())
            void reportsQ.refetch()
          }}
        />
      )}

      {splash && (
        <div className="splash" role="status" aria-live="polite">
          <p className="splash-slogan">{t("slogan")}</p>
        </div>
      )}
    </div>
  )
}

function IncidentTable({
  rows,
  categories,
  onOpen,
  fmtDate,
}: {
  rows: Report[]
  categories: Record<string, { label: string; color: string }>
  onOpen: (r: Report) => void
  fmtDate: (ts: number) => string
}) {
  const { t } = useTranslation()
  const [sort, setSort] = useState<{ key: keyof Report | "when"; dir: 1 | -1 }>({ key: "when", dir: -1 })
  const sorted = useMemo(() => {
    const val = (r: Report) =>
      sort.key === "when" ? (r.occurred_at ?? r.created_at) : ((r[sort.key] as string | number | null) ?? "")
    return [...rows].sort((a, b) => (val(a) > val(b) ? sort.dir : val(a) < val(b) ? -sort.dir : 0))
  }, [rows, sort])

  const th = (key: keyof Report | "when", label: string) => (
    <th onClick={() => setSort((s) => ({ key, dir: s.key === key && s.dir === 1 ? -1 : 1 }))}>
      {label}
      {sort.key === key ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
    </th>
  )

  const exportCsv = () => {
    const head = ["id", "date", "category", "status", "place", "source", "title", "url"]
    const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`
    const lines = [
      head.join(","),
      ...sorted.map((r) =>
        [
          r.id,
          new Date((r.occurred_at ?? r.created_at) * 1000).toISOString().slice(0, 10),
          r.category,
          r.status,
          r.place ?? "",
          r.source,
          r.title,
          r.url ?? "",
        ]
          .map(esc)
          .join(",")
      ),
    ]
    const blob = new Blob([lines.join("\n")], { type: "text/csv" })
    const a = document.createElement("a")
    a.href = URL.createObjectURL(blob)
    a.download = `incidents-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="tablewrap">
      <div className="table-bar">
        <span className="muted sm">{t("table.count", { n: sorted.length })}</span>
        <button className="btn sm" onClick={exportCsv}>{t("table.csv")}</button>
      </div>
      <div className="table-scroll">
        <table className="sheet-table">
          <thead>
            <tr>
              {th("id", "#")}
              {th("when", t("table.date"))}
              {th("category", t("table.category"))}
              {th("status", t("table.status"))}
              {th("place", t("table.place"))}
              {th("title", t("table.title"))}
            </tr>
          </thead>
          <tbody>
            {sorted.slice(0, 1000).map((r) => {
              const c0 = r.category.split(/[,|/]/)[0]?.trim()
              return (
                <tr key={r.id} onClick={() => onOpen(r)}>
                  <td>{r.id}</td>
                  <td>{fmtDate(r.occurred_at ?? r.created_at)}</td>
                  <td>
                    <span className="dot" style={{ background: categories[c0]?.color ?? "#8a97ac" }} />
                    {r.category}
                  </td>
                  <td>{r.status}</td>
                  <td>{r.place || "—"}</td>
                  <td className="td-title">{r.title}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Detail({
  r,
  categories,
  canModerate,
  onModerate,
  onBack,
  onLocate,
}: {
  r: Report
  categories: Record<string, { label: string; color: string }>
  canModerate: boolean
  onModerate: (r: Report, status: ReportStatus) => void | Promise<void>
  onBack: () => void
  onLocate: (r: Report) => void
}) {
  const { t, i18n } = useTranslation()
  const [busy, setBusy] = useState<ReportStatus | null>(null)
  const cats = r.category.split(/[,|/]/).map((s) => s.trim()).filter(Boolean)
  const col = categories[cats[0]]?.color ?? "#8a97ac"
  const act = async (status: ReportStatus) => {
    setBusy(status)
    try {
      await onModerate(r, status)
    } finally {
      setBusy(null)
    }
  }
  return (
    <div className="detail">
      <button className="back" onClick={onBack}>{t("detail.back")}</button>
      <div className="d-meta">
        #{String(r.id).padStart(4, "0")} · {t("detail.happened")} {new Date((r.occurred_at ?? r.created_at) * 1000).toLocaleDateString(i18n.language)} · {r.place ?? "—"}
      </div>
      <h3>{r.title}</h3>
      <div className="d-tags">
        {cats.map((c) => (
          <span key={c} className="tag" style={{ background: `${categories[c]?.color ?? col}22`, color: categories[c]?.color ?? col }}>
            {categories[c]?.label ?? c}
          </span>
        ))}
        <span className="tag">{r.status}</span>
        <span className="tag">{r.fuzzed ? t("detail.approx") : t("detail.exact")}</span>
      </div>
      {r.body && <p>{r.body}</p>}
      {r.reason && (
        <>
          <div className="d-h">{t("detail.reason")}</div>
          <p className="muted">{r.reason}</p>
        </>
      )}
      {r.impact && (
        <>
          <div className="d-h">{t("detail.impact")}</div>
          <p className="muted">{r.impact}</p>
        </>
      )}
      {r.evidence && (
        <>
          <div className="d-h">{t("detail.evidence")}</div>
          <p className="muted sm">{r.evidence}</p>
        </>
      )}
      {r.law && (
        <>
          <div className="d-h">{t("detail.law")}</div>
          <p className="muted">{r.law}</p>
        </>
      )}
      <div className="d-actions">
        {r.lat != null && <button className="btn" onClick={() => onLocate(r)}>{t("detail.showOnMap")}</button>}
        {r.url && (
          <a className="btn primary" href={r.url} target="_blank" rel="noreferrer">
            {t("detail.openSource")}
          </a>
        )}
      </div>
      {canModerate && (
        <div className="d-mod">
          <div className="d-h">{t("mod.title")}</div>
          <p className="muted sm">{t("mod.hint")}</p>
          <div className="d-actions">
            <button className="btn ok" disabled={!!busy} onClick={() => act("verified")}>
              {busy === "verified" ? "…" : t("mod.confirm")}
            </button>
            <button className="btn no" disabled={!!busy} onClick={() => act("dismissed")}>
              {busy === "dismissed" ? "…" : t("mod.decline")}
            </button>
          </div>
          <div className="d-actions">
            <button className="btn" disabled={!!busy} onClick={() => act("irrelevant")}>
              {busy === "irrelevant" ? "…" : t("mod.irrelevant")}
            </button>
            <button className="btn" disabled={!!busy} onClick={onBack}>{t("mod.pass")}</button>
          </div>
        </div>
      )}
    </div>
  )
}

function Involved({
  me,
  onChanged,
  onGoReview,
}: {
  me: { email: string; role: string } | null
  onChanged: () => void | Promise<void>
  onGoReview: () => void
}) {
  const { t } = useTranslation()
  const [mode, setMode] = useState<"signup" | "signin">("signup")
  const [name, setName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [message, setMessage] = useState("")
  const [accept, setAccept] = useState(false)
  const [err, setErr] = useState("")
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setErr("")
    if (mode === "signup" && !accept) {
      setErr(t("involved.mustAccept"))
      return
    }
    setBusy(true)
    try {
      if (mode === "signup") await api.signup({ name, email, password, message, accept })
      else await api.login(email, password)
      setPassword("")
      await onChanged()
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : String(e2))
    } finally {
      setBusy(false)
    }
  }
  const logout = async () => {
    await api.logout()
    await onChanged()
  }

  const isReviewer = me?.role === "ADMIN" || me?.role === "VERIFIER"

  return (
    <>
      <h3>{t("involved.title")}</h3>

      {me && isReviewer && (
        <div className="card">
          <div className="card-t">{t("involved.signedInReviewer", { email: me.email, role: me.role })}</div>
          <div className="d-actions" style={{ marginTop: 10 }}>
            <button className="btn primary" onClick={onGoReview}>{t("involved.reviewerCta")}</button>
            <button className="btn" onClick={logout}>{t("involved.logout")}</button>
          </div>
        </div>
      )}

      {me && !isReviewer && (
        <div className="card">
          <div className="card-t">{t("involved.pending")}</div>
          <p className="muted sm">{t("involved.pendingBody")}</p>
          <div className="d-actions" style={{ marginTop: 10 }}>
            <button className="btn" onClick={logout}>{t("involved.logout")}</button>
          </div>
        </div>
      )}

      {!me && (
        <form className="auth" onSubmit={submit}>
          <div className="auth-tabs">
            <button type="button" className={mode === "signup" ? "on" : ""} onClick={() => setMode("signup")}>
              {t("involved.signupBtn")}
            </button>
            <button type="button" className={mode === "signin" ? "on" : ""} onClick={() => setMode("signin")}>
              {t("involved.signinBtn")}
            </button>
          </div>
          <p className="muted sm">{mode === "signup" ? t("involved.signupBody") : t("involved.signinBody")}</p>
          {mode === "signup" && (
            <input className="field" placeholder={t("involved.name")} value={name} onChange={(e) => setName(e.target.value)} required />
          )}
          <input className="field" type="email" placeholder={t("involved.email")} value={email} onChange={(e) => setEmail(e.target.value)} required />
          <input
            className="field"
            type="password"
            placeholder={t("involved.password")}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
            required
          />
          {mode === "signup" && (
            <textarea className="field" rows={3} placeholder={t("involved.msgPh")} value={message} onChange={(e) => setMessage(e.target.value)} />
          )}
          {mode === "signup" && (
            <label className="accept">
              <input type="checkbox" checked={accept} onChange={(e) => setAccept(e.target.checked)} />
              <span>
                {t("involved.acceptPre")}{" "}
                <a href="/terms" target="_blank" rel="noreferrer">{t("involved.terms")}</a>
                {" "}{t("involved.acceptAnd")}{" "}
                <a href="/privacy" target="_blank" rel="noreferrer">{t("involved.privacy")}</a>.
              </span>
            </label>
          )}
          {err && <p className="muted sm" style={{ color: "#b23b3b" }}>{err}</p>}
          <button className="btn primary" type="submit" disabled={busy}>
            {busy ? "…" : mode === "signup" ? t("involved.signupBtn") : t("involved.signinBtn")}
          </button>
        </form>
      )}

      <a className="link-row" href="/guide" target="_blank" rel="noreferrer">{t("involved.guide")}</a>
      <a className="link-row" href="/awareness" target="_blank" rel="noreferrer">{t("involved.awareness")}</a>
      <a className="link-row" href="/privacy">{t("involved.privacy")}</a>
      <a className="link-row" href="/terms">{t("involved.terms")}</a>
    </>
  )
}
