import { useEffect, useMemo, useRef } from "react"
import maplibregl from "maplibre-gl"
import "maplibre-gl/dist/maplibre-gl.css"
import type { Report, CategoryMeta } from "../../lib/api"

// Real tile map (MapLibre GL). Replaces react-simple-maps, which does not
// render under React 19 — that was why the map showed nothing. Reports are
// a clustered GeoJSON source coloured per category; solidarity_event is a
// separate star-ish layer. Fully responsive; resizes on container change
// and when the mobile tab toggles it back into view.

const STYLE = "https://tiles.openfreemap.org/styles/positron"
const WORLD_CENTER: [number, number] = [12, 30]

function ageOpacity(created_at: number) {
  const days = (Date.now() / 1000 - created_at) / 86400
  if (days < 2) return 1
  if (days > 3650) return 0.4
  if (days > 720) return 0.58
  if (days > 180) return 0.78
  return 0.92
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
  const ready = useRef(false)

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
      center: WORLD_CENTER,
      zoom: 3.4,
      attributionControl: { compact: true },
    })
    map.current = m
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right")
    m.addControl(new maplibregl.GeolocateControl({ trackUserLocation: false }), "top-right")

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
          "circle-radius": ["step", ["get", "point_count"], 15, 25, 20, 100, 26, 500, 34],
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
          "circle-radius": 6,
          "circle-stroke-width": 1.4,
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
          "circle-radius": 7.5,
          "circle-stroke-width": 2,
          "circle-stroke-color": "#b8720b",
        },
      })

      m.on("click", "clusters", (e) => {
        const f = m.queryRenderedFeatures(e.point, { layers: ["clusters"] })[0]
        const cid = f?.properties?.cluster_id
        const src = m.getSource("reports") as maplibregl.GeoJSONSource
        if (cid != null) {
          src.getClusterExpansionZoom(cid).then((z) => {
            m.easeTo({ center: (f.geometry as GeoJSON.Point).coordinates as [number, number], zoom: z })
          })
        }
      })
      for (const layer of ["point", "solidarity"]) {
        m.on("click", layer, (e) => {
          const id = e.features?.[0]?.properties?.id as number | undefined
          const r = reports.find((x) => x.id === id)
          if (r) onSelect(r)
        })
        m.on("mouseenter", layer, () => (m.getCanvas().style.cursor = "pointer"))
        m.on("mouseleave", layer, () => (m.getCanvas().style.cursor = ""))
      }
      ready.current = true
      pushData()
    })

    // keep the canvas sized to its container (mobile tab toggle, rotation…)
    const ro = new ResizeObserver(() => m.resize())
    ro.observe(ref.current)
    const onVis = () => !document.hidden && m.resize()
    document.addEventListener("visibilitychange", onVis)

    return () => {
      ro.disconnect()
      document.removeEventListener("visibilitychange", onVis)
      m.remove()
      map.current = null
      ready.current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const pushData = () => {
    const m = map.current
    if (!m || !ready.current) return
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
  }

  useEffect(pushData, [visible, categories])

  useEffect(() => {
    const m = map.current
    if (!m || !focus) return
    m.flyTo({ center: [focus.lon, focus.lat], zoom: focus.zoom || 4, speed: 1.2 })
  }, [focus])

  return <div ref={ref} style={{ position: "absolute", inset: 0 }} />
}
