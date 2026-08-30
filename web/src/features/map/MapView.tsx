import { useEffect, useRef } from "react"
import maplibregl from "maplibre-gl"
import "maplibre-gl/dist/maplibre-gl.css"
import type { Report, CategoryMeta } from "../../lib/api"

// P1 scaffold: MapLibre with a free vector style, reports as a clustered
// GeoJSON source coloured per category, solidarity_event as a separate
// star layer. Popups + detail sheet come next.
const STYLE = "https://tiles.openfreemap.org/styles/positron"
const GERMANY_CENTER: [number, number] = [10.45, 51.16]

export function MapView({
  reports,
  categories,
  onSelect,
}: {
  reports: Report[]
  categories: Record<string, CategoryMeta>
  onSelect: (r: Report) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)

  useEffect(() => {
    if (!ref.current || map.current) return
    map.current = new maplibregl.Map({
      container: ref.current,
      style: STYLE,
      center: GERMANY_CENTER,
      zoom: 5.2,
      attributionControl: { compact: true },
    })
    map.current.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right")
    map.current.addControl(new maplibregl.GeolocateControl({ trackUserLocation: false }), "top-right")
    return () => {
      map.current?.remove()
      map.current = null
    }
  }, [])

  useEffect(() => {
    const m = map.current
    if (!m) return
    const draw = () => {
      const fc: GeoJSON.FeatureCollection = {
        type: "FeatureCollection",
        features: reports.map((r) => ({
          type: "Feature",
          geometry: { type: "Point", coordinates: [r.lon, r.lat] },
          properties: {
            id: r.id,
            color: categories[r.category]?.color ?? "#8891A8",
            star: r.category === "solidarity_event" ? 1 : 0,
          },
        })),
      }
      const src = m.getSource("reports") as maplibregl.GeoJSONSource | undefined
      if (src) {
        src.setData(fc)
        return
      }
      m.addSource("reports", { type: "geojson", data: fc, cluster: true, clusterRadius: 44 })
      m.addLayer({
        id: "clusters",
        type: "circle",
        source: "reports",
        filter: ["has", "point_count"],
        paint: {
          "circle-color": "#0088cc",
          "circle-opacity": 0.25,
          "circle-radius": ["step", ["get", "point_count"], 16, 25, 22, 100, 30],
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
        filter: ["all", ["!", ["has", "point_count"]], ["==", ["get", "star"], 0]],
        paint: {
          "circle-color": ["get", "color"],
          "circle-radius": 6,
          "circle-stroke-width": 1.5,
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
          "circle-radius": 7,
          "circle-stroke-width": 2,
          "circle-stroke-color": "#b8720b",
        },
      })
      m.on("click", "point", (e) => {
        const id = e.features?.[0]?.properties?.id as number | undefined
        const r = reports.find((x) => x.id === id)
        if (r) onSelect(r)
      })
      m.on("click", "solidarity", (e) => {
        const id = e.features?.[0]?.properties?.id as number | undefined
        const r = reports.find((x) => x.id === id)
        if (r) onSelect(r)
      })
      for (const layer of ["point", "solidarity", "clusters"]) {
        m.on("mouseenter", layer, () => (m.getCanvas().style.cursor = "pointer"))
        m.on("mouseleave", layer, () => (m.getCanvas().style.cursor = ""))
      }
    }
    if (m.isStyleLoaded()) draw()
    else m.once("load", draw)
  }, [reports, categories, onSelect])

  return <div ref={ref} style={{ position: "absolute", inset: 0 }} />
}
