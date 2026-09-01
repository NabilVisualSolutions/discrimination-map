import { useEffect, useMemo, useRef, useState } from "react"
import maplibregl from "maplibre-gl"
import "maplibre-gl/dist/maplibre-gl.css"
import type { Report, CategoryMeta } from "../../lib/api"

// Real tile map (MapLibre GL). react-simple-maps didn't render under React
// 19 at all. This version also fixes the pins-never-appear bug: the report
// data usually arrives before the map's `load` event, so pushing it is
// gated on a `styleReady` state flag and re-runs whenever data OR readiness
// changes. On first data it fits the view to the located reports so they're
// actually on screen instead of lost at world zoom.

const STYLE = "https://tiles.openfreemap.org/styles/positron"

function ageOpacity(created_at: number) {
  const days = (Date.now() / 1000 - created_at) / 86400
  if (days < 2) return 1
  if (days > 3650) return 0.42
  if (days > 720) return 0.6
  if (days > 180) return 0.8
  return 0.94
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

  const visible = useMemo(
    () => reports.filter((r) => r.lat != null && r.lon != null && !hiddenCats.has(r.category)),
    [reports, hiddenCats]
  )

  // init once
  useEffect(() => {
    if (!ref.current || map.current) return
    const m = new maplibregl.Map({
      container: ref.current,
      style: STYLE,
      center: [12, 30],
      zoom: 2.6,
      attributionControl: { compact: true },
    })
    map.current = m
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right")
    m.addControl(new maplibregl.GeolocateControl({ trackUserLocation: false }), "bottom-right")

    m.on("load", () => {
      m.addSource("reports", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
        cluster: true,
        clusterRadius: 46,
        clusterMaxZoom: 12,
      })
      m.addLayer({
        id: "clusters",
        type: "circle",
        source: "reports",
        filter: ["has", "point_count"],
        paint: {
          "circle-color": "#0088cc",
          "circle-opacity": 0.22,
          "circle-stroke-color": "#0088cc",
          "circle-stroke-width": 1,
          "circle-radius": ["step", ["get", "point_count"], 16, 25, 22, 100, 28, 500, 36],
        },
      })
      m.addLayer({
        id: "cluster-count",
        type: "symbol",
        source: "reports",
        filter: ["has", "point_count"],
        layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 12 },
        paint: { "text-color": "#0b1326" },
      })
      m.addLayer({
        id: "point",
        type: "circle",
        source: "reports",
        filter: ["all", ["!", ["has", "point_count"]], ["!=", ["get", "star"], 1]],
        paint: {
          "circle-color": ["get", "color"],
          "circle-opacity": ["get", "op"],
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 2, 4, 6, 7, 12, 10],
          "circle-stroke-width": 1.6,
          "circle-stroke-color": "#fff",
        },
      })
      m.addLayer({
        id: "solidarity",
        type: "circle",
        source: "reports",
        filter: ["all", ["!", ["has", "point_count"]], ["==", ["get", "star"], 1]],
        paint: {
          "circle-color": "#FFD23F",
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 2, 5, 12, 12],
          "circle-stroke-width": 2,
          "circle-stroke-color": "#b8720b",
        },
      })

      m.on("click", "clusters", (e) => {
        const f = m.queryRenderedFeatures(e.point, { layers: ["clusters"] })[0]
        const cid = f?.properties?.cluster_id
        if (cid == null) return
        ;(m.getSource("reports") as maplibregl.GeoJSONSource)
          .getClusterExpansionZoom(cid)
          .then((z) => m.easeTo({ center: (f.geometry as GeoJSON.Point).coordinates as [number, number], zoom: z }))
      })
      for (const layer of ["point", "solidarity"]) {
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

  // refs so the map's own event handlers always see the latest data/callback
  const reportsRef = useRef(reports)
  const onSelectRef = useRef(onSelect)
  reportsRef.current = reports
  onSelectRef.current = onSelect

  // push data whenever it — or the map's readiness — changes
  useEffect(() => {
    const m = map.current
    if (!m || !styleReady) return
    const src = m.getSource("reports") as maplibregl.GeoJSONSource | undefined
    if (!src) return
    src.setData({
      type: "FeatureCollection",
      features: visible.map((r) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [r.lon as number, r.lat as number] },
        properties: {
          id: r.id,
          color: categories[r.category]?.color ?? "#8891A8",
          star: r.category === "solidarity_event" ? 1 : 0,
          op: ageOpacity(r.created_at),
        },
      })),
    })
    if (!fitted.current && visible.length > 0) {
      fitted.current = true
      const b = new maplibregl.LngLatBounds()
      for (const r of visible) b.extend([r.lon as number, r.lat as number])
      m.fitBounds(b, { padding: 60, maxZoom: 9, duration: 600 })
    }
  }, [visible, categories, styleReady])

  useEffect(() => {
    const m = map.current
    if (!m || !focus) return
    m.flyTo({ center: [focus.lon, focus.lat], zoom: focus.zoom || 6, speed: 1.2 })
  }, [focus])

  return <div ref={ref} style={{ position: "absolute", inset: 0 }} />
}
