import { useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent } from "react"
import { useQuery } from "@tanstack/react-query"
import { useTranslation } from "react-i18next"
import { api, type Law, type Report, type ReportStatus } from "./lib/api"
import { LOCALES, applyLocale, type Locale } from "./i18n"
import { Honeypot, Turnstile, turnstileEnabled } from "./lib/botguard"
import { MapView, type MapViewMode } from "./features/map/MapView"
import { AWARENESS } from "./lib/awareness"
import { ReportModal } from "./features/report/ReportModal"
import { ConsentBanner } from "./ConsentBanner"
import { analyticsAvailable, clearConsent } from "./lib/analytics"
import { iconFor, catKey, UI_ICONS } from "./lib/category-icons"
import { LucideIcon } from "./lib/LucideIcon"
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

// Render view: remembered per browser. Default GLOBE on desktop, flat 2D on
// touch and small screens (the globe is the heavier render).
const VIEWS: MapViewMode[] = ["globe", "2d", "map", "sat"]
function initialView(): MapViewMode {
  try {
    const v = localStorage.getItem("dx.view") as MapViewMode | null
    if (v && VIEWS.includes(v)) return v
  } catch {
    /* storage blocked: fall through to the default */
  }
  const small = matchMedia("(pointer: coarse), (max-width: 899px)").matches
  return small ? "2d" : "globe"
}
const noticeSeen = () => {
  try {
    return sessionStorage.getItem("dx.notice") === "1"
  } catch {
    return false
  }
}
// Palette colours are mid-tones: fine for dots, bars and glow, too dim as text
// on the dark canvas. Text in a category colour is lifted toward white.
const lift = (c: string) => `color-mix(in srgb, ${c} 55%, #ffffff)`

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
  const [view, setView] = useState<SheetView>("incidents")
  const [snap, setSnap] = useState<SheetSnap>(() => {
    try {
      const v = sessionStorage.getItem("dx.snap") as SheetSnap | null
      if (v === "peek" || v === "half" || v === "full") return v
    } catch {
      /* default */
    }
    return "peek"
  })
  const [noticeDismissed, setNoticeDismissed] = useState(noticeSeen)
  const [view3, setView3] = useState<MapViewMode>(initialView)
  const [threeD, setThreeD] = useState<boolean>(() => {
    try {
      const v = localStorage.getItem("dx.3d")
      if (v) return v === "1"
    } catch {
      /* fall through to the device default */
    }
    // buildings are heavier: on by default only for desktop with a mouse
    return matchMedia("(min-width: 900px) and (pointer: fine)").matches
  })
  const toggle3d = () =>
    setThreeD((v) => {
      try {
        localStorage.setItem("dx.3d", v ? "0" : "1")
      } catch {
        /* not persisted */
      }
      return !v
    })
  // Side panel: desktop collapses to nothing, phone drops to its peek strip.
  // Both remembered for the session.
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return sessionStorage.getItem("dx.panel") === "closed"
    } catch {
      return false
    }
  })
  const [isDesk, setIsDesk] = useState(() => matchMedia("(min-width: 900px)").matches)
  useEffect(() => {
    const mq = matchMedia("(min-width: 900px)")
    const on = () => setIsDesk(mq.matches)
    mq.addEventListener("change", on)
    return () => mq.removeEventListener("change", on)
  }, [])
  const dismissNotice = () => {
    setNoticeDismissed(true)
    try {
      sessionStorage.setItem("dx.notice", "1")
    } catch {
      /* private mode: dismissed for this page view only */
    }
  }
  const pickView = (v: MapViewMode) => {
    setView3(v)
    try {
      localStorage.setItem("dx.view", v)
    } catch {
      /* not persisted */
    }
  }
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

  const catOf = (r: Report) => r.category.split(/[,|/]/).map((s) => s.trim().toLowerCase()).filter(Boolean)
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
    setCollapsed(false)
    // zoom is a floor (see MapView): selecting centres on the incident and never zooms out
    if (r.lat != null && r.lon != null) setFocus({ lat: r.lat, lon: r.lon, zoom: 9 })
  }
  const openReportAt = (lat: number, lon: number) => {
    setReportEdit(null)
    setReportPreset({ lat, lon })
    setShowReport(true)
  }
  const openTab = (v: SheetView) => {
    setView(v)
    setSelected(null)
    setSnap((s) => (s === "peek" ? "half" : s))
  }
  const cycleSnap = () => setSnap((s) => (s === "peek" ? "half" : s === "half" ? "full" : "peek"))
  useEffect(() => {
    try {
      sessionStorage.setItem("dx.snap", snap)
      sessionStorage.setItem("dx.panel", collapsed ? "closed" : "open")
    } catch {
      /* private mode */
    }
  }, [snap, collapsed])
  const panelOpen = isDesk ? !collapsed : snap !== "peek"
  const panelTabRef = useRef<HTMLButtonElement>(null)
  const togglePanel = () => {
    if (isDesk) {
      // focus must leave the sheet before it goes inert
      if (!collapsed) panelTabRef.current?.focus()
      setCollapsed((c) => !c)
    }
    else setSnap((s) => (s === "peek" ? "half" : "peek"))
  }
  const closeDetail = () => {
    setSelected(null)
    setView("incidents")
  }

  useEffect(() => {
    if (view !== "detail") return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !showReport) closeDetail()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, showReport])

  useEffect(() => {
    if (noticeDismissed) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !showReport) dismissNotice()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [noticeDismissed, showReport])

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

  // Deep link from the "edit link" handed back at submission time. The link
  // keeps the token in the URL FRAGMENT (#report=..&token=..): a fragment is
  // never sent to the server, so it stays out of Cloudflare, Caddy and uvicorn
  // access logs. Links issued before 2026-10-20 used the query string; those
  // still open, and the token is removed from the address bar at once.
  useEffect(() => {
    const fromHash = new URLSearchParams(location.hash.replace(/^#/, ""))
    const fromQuery = new URLSearchParams(location.search)
    const p = fromHash.get("token") ? fromHash : fromQuery
    const id = Number(p.get("report"))
    const token = p.get("token")
    if (id && token) {
      setReportEdit({ id, token })
      setShowReport(true)
      history.replaceState(null, "", location.pathname)
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
    <div className={`app${noticeDismissed ? "" : " has-notice"}`}>
      <ConsentBanner />
      <MapView
        reports={mapReports}
        categories={categories}
        onSelect={openDetail}
        onReportAt={openReportAt}
        hiddenCats={hiddenCats}
        focus={focus}
        view={view3}
        selectedId={view === "detail" ? selected?.id : null}
        threeD={threeD}
      />

      {!noticeDismissed && (
        <div className="notice" role="note">
          <span>{t("notice")}</span>
          <button type="button" onClick={dismissNotice} aria-label={t("notice.close")}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>
      )}

      <header className="topbar">
        <div className="brand">
          <BrandMark />
          <div className="brand-txt">
            <span className="brand-name">DX-MAP</span>
            <span className="brand-tag">{t("slogan")}</span>
          </div>
        </div>
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
        <StatusReadout label={t("status.incidents")} n={mapReports.length} />
        <button
          className="tb-report"
          aria-label={t("report.button")}
          onClick={() => {
            setReportEdit(null)
            setReportPreset(null)
            setShowReport(true)
          }}
        >
          <Ico d="M12 5v14M5 12h14" />
        </button>
        <div className="lang">
          <button className="tb-btn" onClick={() => setLangOpen((v) => !v)} aria-label={t("lang.label")} aria-expanded={langOpen}>{i18n.language.toUpperCase()}</button>
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
      </header>

      {/* left rail: one toggle per category, count badge, glows in its colour */}
      <nav className="rail rail-l" aria-label={t("filter.categories")}>
        <button className="rbtn rbtn-sm" data-tip={t("showAll")} aria-label={t("showAll")} onClick={() => setHiddenCats(new Set())}>
          <Ico d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 9a3 3 0 100 6 3 3 0 000-6z" />
        </button>
        <button className="rbtn rbtn-sm" data-tip={t("hideAll")} aria-label={t("hideAll")} onClick={() => setHiddenCats(new Set(allCatKeys))}>
          <Ico d="M3 3l18 18M10.6 6.2A10 10 0 0112 6c6 0 10 6 10 6a17 17 0 01-3.2 3.9M6.6 6.7C3.8 8.5 2 12 2 12s4 7 10 7c1.7 0 3.2-.4 4.5-1" />
        </button>
        <span className="rail-sep" aria-hidden />
        {catList.map((c) => {
          const on = !hiddenCats.has(c.k)
          return (
            <button
              key={c.k}
              className={`rbtn rcat${on ? " on" : ""}`}
              style={{ "--c": c.color } as CSSProperties}
              data-tip={c.label}
              title={c.label}
              aria-label={`${c.label}, ${c.count}`}
              aria-pressed={on}
              onClick={() => toggleCat(c.k)}
            >
              <CatIcon k={c.k} />
              <span className="rbadge">{c.count}</span>
            </button>
          )
        })}
      </nav>

      {lawFilter && (
        <button className="chip on active-filter" onClick={() => setLawFilter(null)}>
          {t("laws.filtered", { code: lawFilter })}
          <svg viewBox="0 0 24 24" width={12} height={12} fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" aria-hidden><path d="M6 6l12 12M18 6L6 18" /></svg>
        </button>
      )}

      {/* right rail: the actions */}
      <nav className="rail rail-r" aria-label={t("rail.tools")}>
        <button
          className="rbtn rbtn-report"
          data-tip={t("report.button")}
          aria-label={t("report.button")}
          onClick={() => {
            setReportEdit(null)
            setReportPreset(null)
            setShowReport(true)
          }}
        >
          <Ico d="M12 5v14M5 12h14" />
        </button>
        <span className="rail-sep rail-sep-report" aria-hidden />
        <a className="rbtn" data-tip={t("guide")} aria-label={t("guide")} href="/guide" target="_blank" rel="noreferrer">
          <Ico d="M4 5a2 2 0 012-2h13v16H6a2 2 0 00-2 2zM4 19a2 2 0 012-2h13" />
        </a>
        <a className="rbtn" data-tip={t("awarenessGuide")} aria-label={t("awarenessGuide")} href="/awareness" target="_blank" rel="noreferrer">
          <Ico d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM12 8v5M12 16v.01" />
        </a>
        <button className={`rbtn${view === "table" ? " on" : ""}`} data-tip={t("tab.table")} aria-label={t("tab.table")} onClick={() => openTab("table")}>
          <Ico d="M3 5a2 2 0 012-2h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2zM3 10h18M9 10v11" />
        </button>
        <button className={`rbtn${view === "laws" ? " on" : ""}`} data-tip={t("tab.laws")} aria-label={t("tab.laws")} onClick={() => openTab("laws")}>
          <Ico d="M12 3v18M6 21h12M5 7h14M5 7l-3 7a3.5 3.5 0 006 0zM19 7l-3 7a3.5 3.5 0 006 0z" />
        </button>
        <button className="rbtn" data-tip={t("locate")} aria-label={t("locate")} onClick={locateMe}>
          <Ico d="M12 9a3 3 0 100 6 3 3 0 000-6zM12 3a9 9 0 100 18 9 9 0 000-18zM12 1v3M12 20v3M1 12h3M20 12h3" />
        </button>
      </nav>

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

      <div className="dock">
        <div className="seg-row">
        <div className="seg" role="group" aria-label={t("view.label")}>
          {VIEWS.map((v) => (
            <button key={v} type="button" className={view3 === v ? "on" : ""} aria-pressed={view3 === v} onClick={() => pickView(v)}>
              {t(`view.${v}`)}
            </button>
          ))}
        </div>
        {(view3 === "globe" || view3 === "2d") && (
          <button type="button" className={`seg-3d${threeD ? " on" : ""}`} aria-pressed={threeD} aria-label={t("view.3dLabel")} title={t("view.3dLabel")} onClick={toggle3d}>
            {t("view.3d")}
          </button>
        )}
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
      </div>

      <button ref={panelTabRef} className="panel-tab" onClick={togglePanel} aria-expanded={panelOpen} aria-label={panelOpen ? t("panel.collapse") : t("panel.expand")} title={panelOpen ? t("panel.collapse") : t("panel.expand")}>
        <LucideIcon node={panelOpen ? UI_ICONS.PanelRightClose : UI_ICONS.PanelRightOpen} />
      </button>
      <div className={`sheet${isDesk && collapsed ? " collapsed" : ""}`} style={{ height: SNAP_H[snap] }} inert={isDesk && collapsed ? true : undefined}>
        <div className="sheet-head">
          <button className="grip" onClick={cycleSnap} aria-label={t("sheet.resize")}>
            <span />
          </button>
          <button className="sheet-x" onClick={togglePanel} aria-label={panelOpen ? t("panel.collapse") : t("panel.expand")}>
            <LucideIcon node={panelOpen ? UI_ICONS.ChevronDown : UI_ICONS.ChevronUp} />
          </button>
        </div>
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
              onBack={closeDetail}
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
                      {hasText(r.body) && <span className="row-d">{r.body}</span>}
                      <span className="row-m">
                        <b style={{ color: lift(col) }}><CatIcon k={catKey(r.category)} small />{categories[catOf(r)[0]]?.label ?? r.category}</b>
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
                          <b style={{ color: lift(col) }}>{categories[catOf(r)[0]]?.label ?? r.category}</b>
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

      <Ticker
        label={t("ticker.label")}
        items={filtered.slice(0, 14)}
        categories={categories}
        onOpen={openDetail}
        fmtDate={fmtDate}
      />

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

// Only truly empty / whitespace-only text counts as missing.
const hasText = (s: string | null | undefined): s is string => !!s && s.trim().length > 0

function CatIcon({ k, small }: { k: string; small?: boolean }) {
  return <LucideIcon node={iconFor(k)} className={small ? "cat-ico sm" : "cat-ico"} />
}

function Ico({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={d} />
    </svg>
  )
}

// Original mark: a gold archive ring with registration ticks and one live point.
function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" aria-hidden>
      <circle cx={16} cy={16} r={11} />
      <path d="M16 2v5M16 25v5M2 16h5M25 16h5" />
      <path d="M9.5 20.5c3-1 5-3.5 6.5-8.5 1.5 5 3.5 7.5 6.5 8.5" opacity={0.7} />
      <circle cx={16} cy={12} r={2} fill="currentColor" stroke="none" />
    </svg>
  )
}

// UTC clock + visible-incident count. The clock ticks in its own component so
// the one-second render never touches the rest of the app, and is hidden from
// screen readers (a ticking value would be read out every second).
function StatusReadout({ label, n }: { label: string; n: number }) {
  const [tick, setTick] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setTick(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  return (
    <div className="status">
      <span className="st-clock" aria-hidden>UTC {tick.toISOString().slice(11, 19)}</span>
      <span className="st-n"><span className="st-l">{label}</span> <b>{n}</b></span>
    </div>
  )
}

// Latest incidents already in memory, scrolling along the bottom edge. Pauses
// on hover and keyboard focus; under prefers-reduced-motion it does not move
// at all and becomes a plain scrollable strip. The second copy is decoration.
function Ticker({
  label,
  items,
  categories,
  onOpen,
  fmtDate,
}: {
  label: string
  items: Report[]
  categories: Record<string, { label: string; color: string }>
  onOpen: (r: Report) => void
  fmtDate: (ts: number) => string
}) {
  if (items.length === 0) return null
  const copy = (dup: boolean) =>
    items.map((r) => {
      const c0 = catKey(r.category)
      const col = categories[c0]?.color ?? "#8a97ac"
      return (
        <button
          key={(dup ? "d" : "a") + r.id}
          className="tk-item"
          tabIndex={dup ? -1 : 0}
          aria-hidden={dup || undefined}
          onClick={() => onOpen(r)}
        >
          <span className="tk-dot" style={{ background: col, boxShadow: `0 0 8px ${col}` }} />
          <span className="tk-cat" style={{ color: lift(col) }}>{categories[c0]?.label ?? r.category}</span>
          <span className="tk-t">{r.title}</span>
          <span className="tk-d">{fmtDate(r.occurred_at ?? r.created_at)}</span>
        </button>
      )
    })
  return (
    <div className="ticker" role="region" aria-label={label}>
      <span className="tk-label">{label}</span>
      <div className="tk-view">
        <div className="tk-track" style={{ animationDuration: `${Math.max(30, items.length * 6)}s` }}>
          {copy(false)}
          {copy(true)}
        </div>
      </div>
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
              const c0 = catKey(r.category)
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
  const cats = r.category.split(/[,|/]/).map((s) => s.trim().toLowerCase()).filter(Boolean)
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
      <div className="d-head">
        <button className="back" onClick={onBack}>{t("detail.back")}</button>
        <button className="d-close" onClick={onBack} aria-label={t("detail.close")} title={t("detail.close")}>
          <LucideIcon node={UI_ICONS.X} />
        </button>
      </div>
      <div className="d-meta">
        #{String(r.id).padStart(4, "0")} · {t("detail.happened")} {new Date((r.occurred_at ?? r.created_at) * 1000).toLocaleDateString(i18n.language)}
        {r.place ? ` · ${r.place}` : ""}
      </div>
      <h3>{r.title}</h3>
      <div className="d-tags">
        {cats.map((c) => (
          <span key={c} className="tag" style={{ background: `${categories[c]?.color ?? col}33`, color: lift(categories[c]?.color ?? col) }}>
            <CatIcon k={c} small />
            {categories[c]?.label ?? c}
          </span>
        ))}
        <span className="tag">{r.status}</span>
        <span className="tag">{r.fuzzed ? t("detail.approx") : t("detail.exact")}</span>
      </div>
      {hasText(r.body) ? (
        <p className="d-body">{r.body}</p>
      ) : (
        !hasText(r.reason) && <p className="muted sm">{t("detail.noDescription")}</p>
      )}
      {hasText(r.reason) && (
        <>
          <div className="d-h">{t("detail.reason")}</div>
          <p className="muted d-body">{r.reason}</p>
        </>
      )}
      {hasText(r.impact) && (
        <>
          <div className="d-h">{t("detail.impact")}</div>
          <p className="muted d-body">{r.impact}</p>
        </>
      )}
      {hasText(r.evidence) && (
        <>
          <div className="d-h">{t("detail.evidence")}</div>
          <p className="muted sm d-body">{r.evidence}</p>
        </>
      )}
      {hasText(r.law) && (
        <>
          <div className="d-h">{t("detail.law")}</div>
          <p className="muted d-body">{r.law}</p>
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
  me: { email: string; role: string; verified?: boolean } | null
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
  const [hp, setHp] = useState("")
  const [botToken, setBotToken] = useState<string | null>(null)
  const [widgetKey, setWidgetKey] = useState(0)
  // Two-step sign-in: the server asks for a code only after a right password.
  const [code, setCode] = useState("")
  const [needCode, setNeedCode] = useState(false)
  // Mailbox check: the link in the mail lands on /?verified=1|0.
  const [verifyNote, setVerifyNote] = useState(() => {
    const v = new URLSearchParams(window.location.search).get("verified")
    return v === "1" ? "involved.verifiedOk" : v === "0" ? "involved.verifiedBad" : ""
  })
  const resend = async () => {
    try {
      await api.resendVerification()
      setVerifyNote("involved.verifySent")
    } catch (e3) {
      setErr(e3 instanceof Error ? e3.message : String(e3))
    }
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setErr("")
    if (mode === "signup" && turnstileEnabled && !botToken) {
      setErr(t("involved.botWait"))
      return
    }
    if (mode === "signup" && !accept) {
      setErr(t("involved.mustAccept"))
      return
    }
    setBusy(true)
    try {
      if (mode === "signup") {
        await api.signup({ name, email, password, message, accept, hp_contact: hp, turnstile_token: botToken ?? "" })
        // Sign-up answers the same for a new and a registered email (so it
        // cannot be used to list accounts) and no longer signs anyone in.
        try {
          await api.login(email, password)
        } catch {
          throw new Error(t("involved.signupExisting"))
        }
      } else await api.login(email, password, code)
      setPassword("")
      setCode("")
      setNeedCode(false)
      await onChanged()
    } catch (e2) {
      const m = e2 instanceof Error ? e2.message : String(e2)
      if (m === "TOTP_REQUIRED" || m === "TOTP_INVALID") {
        setNeedCode(true)
        setErr(t(m === "TOTP_REQUIRED" ? "involved.codeNeeded" : "involved.codeWrong"))
      } else {
        setErr(m)
      }
    } finally {
      setBusy(false)
      setBotToken(null)
      setWidgetKey((k) => k + 1)
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

      {verifyNote && (
        <div className="card" role="status">
          <p className="muted sm">{t(verifyNote)}</p>
        </div>
      )}

      {me && !isReviewer && me.verified === false && (
        <div className="card">
          <div className="card-t">{t("involved.verifyPending")}</div>
          <p className="muted sm">{t("involved.verifyBody")}</p>
          <div className="d-actions" style={{ marginTop: 10 }}>
            <button className="btn" onClick={resend}>{t("involved.verifyResend")}</button>
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
          {mode === "signin" && needCode && (
            <input
              className="field"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={8}
              placeholder={t("involved.code")}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              autoFocus
            />
          )}
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
          {mode === "signup" && <Honeypot value={hp} onChange={setHp} />}
          {mode === "signup" && <Turnstile key={widgetKey} onToken={setBotToken} />}
          {err && <p className="muted sm" style={{ color: "var(--red-text)" }}>{err}</p>}
          <button className="btn primary" type="submit" disabled={busy}>
            {busy ? "…" : mode === "signup" ? t("involved.signupBtn") : t("involved.signinBtn")}
          </button>
        </form>
      )}

      <a className="link-row" href="/guide" target="_blank" rel="noreferrer">{t("involved.guide")}</a>
      <a className="link-row" href="/awareness" target="_blank" rel="noreferrer">{t("involved.awareness")}</a>
      <a className="link-row" href="/privacy">{t("involved.privacy")}</a>
      <a className="link-row" href="/terms">{t("involved.terms")}</a>
      {analyticsAvailable && (
        <p className="muted sm" style={{ marginTop: 14 }}>
          <button type="button" className="linklike" onClick={clearConsent}>{t("consent.footer")}</button>
        </p>
      )}
    </>
  )
}
