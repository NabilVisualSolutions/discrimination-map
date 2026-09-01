import { useEffect, useMemo, useRef, useState } from "react"
import maplibregl from "maplibre-gl"
import "maplibre-gl/dist/maplibre-gl.css"
import type { Report, CategoryMeta } from "../../lib/api"

// Worldwide tile map. Every pin renders at every zoom (no clustering).
// Points that share a category are linked to that category's centroid with
// a thin coloured thread. A report whose `category` names several
// categories (comma / slash / pipe separated) blinks through those colours.

const STYLE = "https://tiles.openfreemap.org/styles/positron"
const MULTI_SEP = /\s*[,/|]\s*/

function splitCats(c: string): string[] {
  return c.split(MULTI_SEP).map((x) => x.trim()).filter(Boolean)
}
function ageOpacity(t: number) {
  const d = (Date.now() / 1000 - t) / 86400
  return d < 2 ? 1 : d > 3650 ? 0.4 : d > 720 ? 0.58 : d > 180 ? 0.78 : 0.94
}

export function MapView({
  reports,
  categories,
  onSelect,
  hiddenCats,
  focus,
}: {
  reports: Report[]
  categories: Record<string, CategoryMeta>
  onSelect: (r: Report) => void
  hiddenCats: Set<string>
  focus?: { lon: number; lat: number; zoom: number } | null
}) {
  const ref = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const [styleReady, setStyleReady] = useState(false)
  const fitted = useRef(false)
  const reportsRef = useRef(reports)
  const onSelectRef = useRef(onSelect)
  reportsRef.current = reports
  onSelectRef.current = onSelect

  const visible = useMemo(
    () =>
      reports.filter(
        (r) => r.lat != null && r.lon != null && splitCats(r.category).some((c) => !hiddenCats.has(c))
      ),
    [reports, hiddenCats]
  )

  // per-category point features + centroid, and the multi-category subset
  const { pointFC, linkFC, multi } = useMemo(() => {
    const byCat: Record<string, [number, number][]> = {}
    const pts: GeoJSON.Feature[] = []
    const mlt: { id: number; lon: number; lat: number; colors: string[] }[] = []
    for (const r of visible) {
      const cats = splitCats(r.category).filter((c) => !hiddenCats.has(c))
      const colors = cats.map((c) => categories[c]?.color ?? "#8891A8")
      for (const c of cats) (byCat[c] ??= []).push([r.lon as number, r.lat as number])
      pts.push({
        type: "Feature",
        geometry: { type: "Point", coordinates: [r.lon as number, r.lat as number] },
        properties: {
          id: r.id,
          color: colors[0] ?? "#8891A8",
          star: r.category === "solidarity_event" ? 1 : 0,
          multi: colors.length > 1 ? 1 : 0,
          op: ageOpacity(r.created_at),
        },
      })
      if (colors.length > 1) mlt.push({ id: r.id, lon: r.lon as number, lat: r.lat as number, colors })
    }
    const links: GeoJSON.Feature[] = []
    for (const [cat, coords] of Object.entries(byCat)) {
      if (coords.length < 2) continue
      const cx = coords.reduce((s, c) => s + c[0], 0) / coords.length
      const cy = coords.reduce((s, c) => s + c[1], 0) / coords.length
      const color = categories[cat]?.color ?? "#8891A8"
      for (const c of coords) {
        links.push({
          type: "Feature",
          geometry: { type: "LineString", coordinates: [c, [cx, cy]] },
          properties: { color },
        })
      }
    }
    return {
      pointFC: { type: "FeatureCollection", features: pts } as GeoJSON.FeatureCollection,
      linkFC: { type: "FeatureCollection", features: links } as GeoJSON.FeatureCollection,
      multi: mlt,
    }
  }, [visible, categories, hiddenCats])

  useEffect(() => {
    if (!ref.current || map.current) return
    const m = new maplibregl.Map({
      container: ref.current,
      style: STYLE,
      center: [8, 25],
      zoom: 1.7,
      attributionControl: { compact: true },
      renderWorldCopies: false,
    })
    map.current = m
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right")
    m.addControl(new maplibregl.GeolocateControl({ trackUserLocation: false }), "bottom-right")

    m.on("load", () => {
      m.addSource("links", { type: "geojson", data: { type: "FeatureCollection", features: [] } })
      m.addSource("reports", { type: "geojson", data: { type: "FeatureCollection", features: [] } })
      m.addLayer({
        id: "links",
        type: "line",
        source: "links",
        paint: { "line-color": ["get", "color"], "line-width": 0.6, "line-opacity": 0.28 },
      })
      m.addLayer({
        id: "point",
        type: "circle",
        source: "reports",
        filter: ["all", ["!=", ["get", "star"], 1], ["!=", ["get", "multi"], 1]],
        paint: {
          "circle-color": ["get", "color"],
          "circle-opacity": ["get", "op"],
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 3.5, 6, 6, 12, 9],
          "circle-stroke-width": 1.4,
          "circle-stroke-color": "#fff",
        },
      })
      m.addLayer({
        id: "point-multi",
        type: "circle",
        source: "reports",
        filter: ["==", ["get", "multi"], 1],
        paint: {
          "circle-color": "#8891A8",
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 4.5, 12, 11],
          "circle-stroke-width": 2.4,
          "circle-stroke-color": "#fff",
        },
      })
      m.addLayer({
        id: "solidarity",
        type: "circle",
        source: "reports",
        filter: ["==", ["get", "star"], 1],
        paint: {
          "circle-color": "#FFD23F",
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 4.5, 12, 12],
          "circle-stroke-width": 2,
          "circle-stroke-color": "#b8720b",
        },
      })
      for (const layer of ["point", "point-multi", "solidarity"]) {
        m.on("click", layer, (e) => {
          const id = e.features?.[0]?.properties?.id as number | undefined
          const r = reportsRef.current.find((x) => x.id === id)
          if (r) onSelectRef.current(r)
        })
        m.on("mouseenter", layer, () => (m.getCanvas().style.cursor = "pointer"))
        m.on("mouseleave", layer, () => (m.getCanvas().style.cursor = ""))
      }
      setStyleReady(true)
    })

    const ro = new ResizeObserver(() => m.resize())
    ro.observe(ref.current)
    const onVis = () => !document.hidden && m.resize()
    document.addEventListener("visibilitychange", onVis)
    return () => {
      ro.disconnect()
      document.removeEventListener("visibilitychange", onVis)
      m.remove()
      map.current = null
      setStyleReady(false)
      fitted.current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // push data
  useEffect(() => {
    const m = map.current
    if (!m || !styleReady) return
    ;(m.getSource("reports") as maplibregl.GeoJSONSource | undefined)?.setData(pointFC)
    ;(m.getSource("links") as maplibregl.GeoJSONSource | undefined)?.setData(linkFC)
    if (!fitted.current && pointFC.features.length > 0) {
      fitted.current = true
      const b = new maplibregl.LngLatBounds()
      for (const f of pointFC.features) b.extend((f.geometry as GeoJSON.Point).coordinates as [number, number])
      m.fitBounds(b, { padding: 50, maxZoom: 6, duration: 600 })
    }
  }, [pointFC, linkFC, styleReady])

  // blink the multi-category points through their colours
  useEffect(() => {
    const m = map.current
    if (!m || !styleReady || multi.length === 0) return
    let i = 0
    const maxLen = Math.max(...multi.map((x) => x.colors.length))
    const id = window.setInterval(() => {
      i = (i + 1) % maxLen
      if (!m.getLayer("point-multi")) return
      m.setPaintProperty("point-multi", "circle-color", [
        "match",
        ["get", "id"],
        ...multi.flatMap((x) => [x.id, x.colors[i % x.colors.length]]),
        "#8891A8",
      ])
    }, 650)
    return () => window.clearInterval(id)
  }, [multi, styleReady])

  useEffect(() => {
    const m = map.current
    if (!m || !focus) return
    m.flyTo({ center: [focus.lon, focus.lat], zoom: focus.zoom || 6, speed: 1.2 })
  }, [focus])

  return <div ref={ref} style={{ position: "absolute", inset: 0 }} />
}
