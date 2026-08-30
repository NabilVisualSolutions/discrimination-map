import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { useTranslation } from "react-i18next"
import { api, type Report } from "./lib/api"
import { LOCALES, applyLocale, type Locale } from "./i18n"
import { MapView } from "./features/map/MapView"

// P0/P1 shell: map + top bar + language switch + quick-exit + report FAB.
// Panels (incidents/laws/awareness/volunteer), the report form, the detail
// sheet and admin are the next phases — see docs/REWRITE-PLAN.md.
export function App() {
  const { t, i18n } = useTranslation()
  const [selected, setSelected] = useState<Report | null>(null)

  const cats = useQuery({ queryKey: ["categories"], queryFn: api.categories, staleTime: 3_600_000 })
  const reports = useQuery({
    queryKey: ["reports"],
    queryFn: () => api.reports({ limit: 3000 }),
    staleTime: 60_000,
  })

  const quickExit = () => {
    location.replace("https://www.google.com/search?q=weather")
  }

  return (
    <>
      <MapView
        reports={reports.data?.reports ?? []}
        categories={cats.data?.categories ?? {}}
        onSelect={setSelected}
      />

      <header style={bar}>
        <strong style={{ fontSize: 14 }}>{t("brand.title")}</strong>
        <span style={{ color: "var(--faint)", fontSize: 12 }}>{t("brand.sub")}</span>
        <div style={{ marginInlineStart: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          <select
            value={i18n.language}
            onChange={(e) => applyLocale(e.target.value as Locale)}
            style={sel}
            aria-label="Language"
          >
            {LOCALES.map((l) => (
              <option key={l} value={l}>
                {l.toUpperCase()}
              </option>
            ))}
          </select>
          <button onClick={quickExit} style={exitBtn}>
            {t("quickExit")}
          </button>
        </div>
      </header>

      {reports.isLoading && <div style={badge}>{t("loading")}</div>}
      {reports.isError && <div style={{ ...badge, background: "var(--danger)" }}>{t("error.load")}</div>}

      <button style={fab} onClick={() => alert("Report flow — P2")}>
        + {t("report.button")}
      </button>

      {selected && (
        <aside style={sheet} role="dialog" aria-label={selected.title}>
          <button onClick={() => setSelected(null)} style={{ float: "inline-end" }}>
            ✕
          </button>
          <h3 style={{ marginTop: 4 }}>{selected.title}</h3>
          <p style={{ color: "var(--muted)", fontSize: 13 }}>{selected.summary}</p>
          <p style={{ font: "11px var(--mono)", color: "var(--faint)", textTransform: "uppercase" }}>
            {selected.category} · {selected.status}
            {selected.fuzzed ? " · approx. location" : ""}
          </p>
          {selected.url && (
            <a href={selected.url} target="_blank" rel="noreferrer">
              source
            </a>
          )}
        </aside>
      )}
    </>
  )
}

const bar: React.CSSProperties = {
  position: "absolute",
  insetInline: 0,
  top: 0,
  zIndex: 1200,
  display: "flex",
  gap: 8,
  alignItems: "center",
  padding: "calc(env(safe-area-inset-top,0px) + 10px) 12px 10px",
}
const sel: React.CSSProperties = {
  background: "var(--panel)",
  border: "1px solid var(--line)",
  borderRadius: 10,
  padding: "6px 8px",
  font: "12px var(--disp)",
}
const exitBtn: React.CSSProperties = {
  background: "var(--danger)",
  color: "#fff",
  border: 0,
  borderRadius: 10,
  padding: "8px 12px",
  fontWeight: 700,
  fontSize: 12,
  cursor: "pointer",
}
const fab: React.CSSProperties = {
  position: "absolute",
  insetInlineEnd: 16,
  bottom: "calc(16px + env(safe-area-inset-bottom,0px))",
  zIndex: 1300,
  background: "var(--accent)",
  color: "#fff",
  border: 0,
  borderRadius: 14,
  padding: "14px 20px",
  fontWeight: 700,
  fontSize: 13.5,
  cursor: "pointer",
  boxShadow: "0 8px 26px rgba(0,136,204,.35)",
}
const badge: React.CSSProperties = {
  position: "absolute",
  insetInlineStart: 12,
  top: 56,
  zIndex: 1200,
  background: "var(--panel)",
  border: "1px solid var(--line)",
  borderRadius: 10,
  padding: "6px 10px",
  fontSize: 12,
  color: "var(--ink)",
}
const sheet: React.CSSProperties = {
  position: "absolute",
  insetInline: 12,
  bottom: "calc(90px + env(safe-area-inset-bottom,0px))",
  zIndex: 1350,
  background: "var(--panel)",
  border: "1px solid var(--line)",
  borderRadius: 14,
  padding: 16,
  boxShadow: "0 12px 40px rgba(20,30,50,.2)",
  maxHeight: "50vh",
  overflowY: "auto",
}
