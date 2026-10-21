import { useEffect, useMemo, useRef, useState } from "react"
import maplibregl from "maplibre-gl"
import "maplibre-gl/dist/maplibre-gl.css"
import type { Report, CategoryMeta } from "../../lib/api"
import { CATEGORY_ICONS, iconFor, iconSvg } from "../../lib/category-icons"

// Worldwide tile map. Every pin renders at every zoom (no clustering).
// Same-category incidents are stitched into a proximity web: each point is
// linked to its nearest few same-category neighbours (bounded by distance),
// so the lines trace real clusters instead of all converging on one point.
// A report whose `category` names several categories (comma / slash / pipe
// separated) blinks through those colours.

// Render views (the bottom-left switch). GLOBE and 2D share OpenFreeMap's
// dark style, tinted navy in tintBasemap(); MAP is the original light
// "positron" daylight style; SAT is NASA GIBS Blue Marble imagery (public
// domain) as a raster source. setStyle() keeps the camera, so switching views
// never moves the viewport; the data layers are re-installed on every style.
export type MapViewMode = "globe" | "2d" | "map" | "sat"
const DARK_STYLE = "https://tiles.openfreemap.org/styles/dark"
const LIGHT_STYLE = "https://tiles.openfreemap.org/styles/positron"
const SAT_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    gibs: {
      type: "raster",
      tiles: [
        "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg",
      ],
      tileSize: 256,
      maxzoom: 8,
      attribution: "Imagery: NASA GIBS (public domain)",
    },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#050810" } },
    { id: "gibs", type: "raster", source: "gibs", paint: { "raster-brightness-max": 0.82 } },
  ],
}
const styleFor = (v: MapViewMode) => (v === "map" ? LIGHT_STYLE : v === "sat" ? SAT_STYLE : DARK_STYLE)
const MAP = { land: "#121c33", water: "#070b14", border: "#3b5379", label: "#8fa3c4", halo: "#050810" }

// Marker treatment per view: glow on dark, a dark scrim under the glow on
// imagery, a plain white-ringed dot on the light map.
const LOOK: Record<MapViewMode, { ring: string; halo: number; scrim: number; link: number }> = {
  globe: { ring: "rgba(255,255,255,0.6)", halo: 0.28, scrim: 0, link: 0.55 },
  "2d": { ring: "rgba(255,255,255,0.6)", halo: 0.28, scrim: 0, link: 0.55 },
  map: { ring: "#ffffff", halo: 0.14, scrim: 0, link: 0.45 },
  sat: { ring: "rgba(5,8,16,0.9)", halo: 0.35, scrim: 0.5, link: 0.85 },
}

function tintBasemap(m: maplibregl.Map) {
  const set = (id: string, prop: string, v: string) => {
    if (m.getLayer(id)) m.setPaintProperty(id, prop, v)
  }
  set("background", "background-color", MAP.land)
  set("water", "fill-color", MAP.water)
  set("waterway", "line-color", MAP.water)
  set("landcover_wood", "fill-color", "#101d33")
  set("landuse_park", "fill-color", "#101d33")
  set("building", "fill-color", "#0f1a30")
  for (const id of ["boundary_state", "boundary_country_z0-4", "boundary_country_z5-"]) {
    set(id, "line-color", id === "boundary_state" ? "#2a3d5e" : MAP.border)
  }
  for (const l of m.getStyle().layers) {
    if (l.type !== "symbol" || !l.id.startsWith("place_")) continue
    set(l.id, "text-color", MAP.label)
    set(l.id, "text-halo-color", MAP.halo)
  }
}

// Category markers: a coloured disc with the Lucide icon inside, rendered once
// per category to a bitmap and added with map.addImage on every style.load
// (setStyle drops images). Icon ink flips to dark on light discs for contrast.
const ICON_PX = 44
const iconCache = new Map<string, ImageData>()
const lumOf = (hex: string) => {
  const v = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]
}
function renderMarker(key: string, color: string): Promise<void> {
  const ink = lumOf(color) > 0.35 ? "#0a0f1f" : "#ffffff"
  const svg = iconSvg(iconFor(key), ink, 22, 2.3)
  const img = new Image()
  return new Promise((resolve) => {
    img.onload = () => {
      const c = document.createElement("canvas")
      c.width = c.height = ICON_PX
      const g = c.getContext("2d")!
      g.beginPath()
      g.arc(ICON_PX / 2, ICON_PX / 2, ICON_PX / 2 - 3, 0, Math.PI * 2)
      g.fillStyle = color
      g.fill()
      g.lineWidth = 3
      g.strokeStyle = "#050810"
      g.stroke()
      g.drawImage(img, (ICON_PX - 22) / 2, (ICON_PX - 22) / 2, 22, 22)
      iconCache.set(key, g.getImageData(0, 0, ICON_PX, ICON_PX))
      resolve()
    }
    img.onerror = () => resolve()
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg)
  })
}
async function buildMarkerIcons(categories: Record<string, CategoryMeta>) {
  const keys = new Set([...Object.keys(CATEGORY_ICONS), ...Object.keys(categories).map((k) => k.toLowerCase())])
  await Promise.all([...keys].filter((k) => !iconCache.has(k) || categories[k]).map((k) => renderMarker(k, categories[k]?.color ?? "#8891A8")))
}
function addMarkerImages(m: maplibregl.Map) {
  // updateImage when it already exists, so a changed category colour refreshes
  for (const [k, img] of iconCache) {
    if (m.hasImage("cat-" + k)) m.updateImage("cat-" + k, img)
    else m.addImage("cat-" + k, img, { pixelRatio: 2 })
  }
}

const MULTI_SEP = /\s*[,/|]\s*/

function splitCats(c: string): string[] {
  return c.split(MULTI_SEP).map((x) => x.trim().toLowerCase()).filter(Boolean)
}
function ageOpacity(t: number) {
  const d = (Date.now() / 1000 - t) / 86400
  return d < 2 ? 1 : d > 3650 ? 0.4 : d > 720 ? 0.58 : d > 180 ? 0.78 : 0.94
}

// Rough great-circle distance in km (equirectangular — fine for "nearest").
function distKm(a: [number, number], b: [number, number]) {
  const x = (b[0] - a[0]) * Math.cos((((a[1] + b[1]) / 2) * Math.PI) / 180)
  const y = b[1] - a[1]
  return Math.sqrt(x * x + y * y) * 111.32
}

const MAX_EDGES = 4000 // hard cap for render perf across all categories
const MST_CAP = 1400 // above this many points in one category, fall back to k-NN

// Connect EVERY point in a category into one network. A minimum spanning
// tree (Prim's) gives exactly n-1 edges, one connected web, and no hub the
// lines all converge on. For a very large category we fall back to a
// 2-nearest-neighbour graph so the O(n²) stays cheap.
function categoryNetwork(coords: [number, number][]): [[number, number], [number, number]][] {
  const n = coords.length
  if (n < 2) return []
  if (n > MST_CAP) return kNearestGraph(coords, 2)

  const inTree = new Array<boolean>(n).fill(false)
  const best = new Array<number>(n).fill(Infinity)
  const parent = new Array<number>(n).fill(-1)
  best[0] = 0
  const edges: [[number, number], [number, number]][] = []
  for (let iter = 0; iter < n; iter++) {
    let u = -1
    let bd = Infinity
    for (let v = 0; v < n; v++) if (!inTree[v] && best[v] < bd) (bd = best[v]), (u = v)
    if (u === -1) break
    inTree[u] = true
    if (parent[u] !== -1) edges.push([coords[u], coords[parent[u]]])
    for (let v = 0; v < n; v++) {
      if (inTree[v]) continue
      const d = distKm(coords[u], coords[v])
      if (d < best[v]) (best[v] = d), (parent[v] = u)
    }
  }
  return edges
}

function kNearestGraph(coords: [number, number][], k: number): [[number, number], [number, number]][] {
  const edges: [[number, number], [number, number]][] = []
  const seen = new Set<string>()
  for (let i = 0; i < coords.length; i++) {
    const near = coords
      .map((c, j) => ({ j, d: j === i ? Infinity : distKm(coords[i], c) }))
      .sort((a, b) => a.d - b.d)
      .slice(0, k)
    for (const nb of near) {
      const key = i < nb.j ? `${i}-${nb.j}` : `${nb.j}-${i}`
      if (seen.has(key)) continue
      seen.add(key)
      edges.push([coords[i], coords[nb.j]])
    }
  }
  return edges
}

// 3D buildings from the vector tiles the dark style already loads
// (OpenMapTiles "building": render_height / render_min_height). Only on the
// dark views, only from zoom 14, so no building geometry is drawn or tiled
// at world or regional zoom. Inserted under our own layers so markers stay on top.
function applyBuildings(m: maplibregl.Map, view: MapViewMode, on: boolean) {
  const want = on && (view === "globe" || view === "2d")
  const has = !!m.getLayer("buildings-3d")
  if (!want && has) m.removeLayer("buildings-3d")
  if (!want || has) return
  const src = m.getStyle().layers.find((l) => "source-layer" in l && l["source-layer"] === "building") as { source?: string } | undefined
  if (!src?.source) return
  m.addLayer(
    {
      id: "buildings-3d",
      type: "fill-extrusion",
      source: src.source,
      "source-layer": "building",
      minzoom: 14,
      paint: {
        "fill-extrusion-base": ["coalesce", ["get", "render_min_height"], 0],
        "fill-extrusion-height": ["coalesce", ["get", "render_height"], 6],
        "fill-extrusion-color": "#1b2740",
        "fill-extrusion-opacity": 0.72,
      },
    },
    m.getLayer("links-glow") ? "links-glow" : undefined
  )
}

export function MapView({
  reports,
  categories,
  onSelect,
  onReportAt,
  hiddenCats,
  focus,
  view,
  selectedId,
  threeD,
}: {
  reports: Report[]
  categories: Record<string, CategoryMeta>
  onSelect: (r: Report) => void
  onReportAt?: (lat: number, lon: number) => void
  hiddenCats: Set<string>
  focus?: { lon: number; lat: number; zoom: number } | null
  view: MapViewMode
  selectedId?: number | null
  threeD: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const [styleReady, setStyleReady] = useState(false)
  const fitted = useRef(false)
  const reportsRef = useRef(reports)
  const onSelectRef = useRef(onSelect)
  const onReportAtRef = useRef(onReportAt)
  const viewRef = useRef(view)
  const dataRef = useRef<{ pointFC: GeoJSON.FeatureCollection; linkFC: GeoJSON.FeatureCollection } | null>(null)
  viewRef.current = view
  const selRef = useRef(selectedId ?? null)
  const threeRef = useRef(threeD)
  selRef.current = selectedId ?? null
  threeRef.current = threeD
  reportsRef.current = reports
  onSelectRef.current = onSelect
  onReportAtRef.current = onReportAt

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
          cat: (cats[0] ?? "").toLowerCase(),
          star: r.category.trim().toLowerCase() === "solidarity_event" ? 1 : 0,
          multi: colors.length > 1 ? 1 : 0,
          op: ageOpacity(r.created_at),
        },
      })
      if (colors.length > 1) mlt.push({ id: r.id, lon: r.lon as number, lat: r.lat as number, colors })
    }
    const links: GeoJSON.Feature[] = []
    for (const [cat, coords] of Object.entries(byCat)) {
      if (coords.length < 2 || links.length >= MAX_EDGES) continue
      const color = categories[cat]?.color ?? "#8891A8"
      for (const [a, b] of categoryNetwork(coords)) {
        if (links.length >= MAX_EDGES) break
        links.push({
          type: "Feature",
          geometry: { type: "LineString", coordinates: [a, b] },
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
      style: styleFor(viewRef.current),
      center: [8, 25],
      zoom: 1.7,
      attributionControl: { compact: true, customAttribution: "Icons: Lucide (ISC)" },
      renderWorldCopies: false,
    })
    map.current = m
    if (import.meta.env.DEV) (window as unknown as { __dxmap?: maplibregl.Map }).__dxmap = m // dev-only handle for browser tests
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right")
    m.addControl(new maplibregl.GeolocateControl({ trackUserLocation: false }), "bottom-right")

    // (Re)install sources + layers: runs on every style load, i.e. at start and
    // after each view switch, then pushes the current data back in.
    const install = () => {
      const look = LOOK[viewRef.current]
      if (viewRef.current === "globe" || viewRef.current === "2d") tintBasemap(m)
      m.addSource("links", { type: "geojson", data: { type: "FeatureCollection", features: [] } })
      m.addSource("reports", { type: "geojson", data: { type: "FeatureCollection", features: [] } })
      // glowing network lines: a wide blurred underlay plus a hairline on top
      m.addLayer({
        id: "links-glow",
        type: "line",
        source: "links",
        paint: { "line-color": ["get", "color"], "line-width": 3, "line-blur": 3, "line-opacity": 0.16 },
      })
      m.addLayer({
        id: "links",
        type: "line",
        source: "links",
        paint: { "line-color": ["get", "color"], "line-width": 0.7, "line-opacity": look.link },
      })
      if (look.scrim > 0) {
        // dark scrim under the glow keeps markers legible on bright imagery
        m.addLayer({
          id: "scrim",
          type: "circle",
          source: "reports",
          paint: { "circle-color": "#050810", "circle-opacity": look.scrim, "circle-blur": 0.6, "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 8, 6, 12, 12, 17] },
        })
      }
      // soft halo under every marker so points read as glowing on the dark map
      m.addLayer({
        id: "halo",
        type: "circle",
        source: "reports",
        paint: {
          "circle-color": ["case", ["==", ["get", "star"], 1], "#FFD23F", ["get", "color"]],
          "circle-opacity": ["*", ["get", "op"], look.halo],
          "circle-blur": 0.9,
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 9, 6, 15, 12, 22],
        },
      })
      addMarkerImages(m)
      // Always-visible fallback: a plain coloured dot under the icon layers, so
      // pins never vanish while category images are loading or if they fail.
      m.addLayer({
        id: "point-base",
        type: "circle",
        source: "reports",
        filter: ["!=", ["get", "multi"], 1],
        paint: {
          "circle-color": ["case", ["==", ["get", "star"], 1], "#FFD23F", ["get", "color"]],
          "circle-opacity": ["get", "op"],
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 3, 6, 5, 12, 8],
          "circle-stroke-width": 1,
          "circle-stroke-color": look.ring,
        },
      })
      const iconSize = ["interpolate", ["linear"], ["zoom"], 1, 0.5, 6, 0.62, 12, 0.9] as maplibregl.ExpressionSpecification
      m.addLayer({
        id: "point",
        type: "symbol",
        source: "reports",
        filter: ["all", ["!=", ["get", "star"], 1], ["!=", ["get", "multi"], 1]],
        layout: { "icon-image": ["concat", "cat-", ["get", "cat"]], "icon-size": iconSize, "icon-allow-overlap": true, "icon-ignore-placement": true },
        paint: { "icon-opacity": ["get", "op"] },
      })
      m.addLayer({
        id: "point-multi",
        type: "circle",
        source: "reports",
        filter: ["==", ["get", "multi"], 1],
        paint: {
          "circle-color": "#8891A8",
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 4.5, 12, 11],
          "circle-stroke-width": 1.8,
          "circle-stroke-color": look.ring,
        },
      })
      m.addLayer({
        id: "solidarity",
        type: "symbol",
        source: "reports",
        filter: ["==", ["get", "star"], 1],
        layout: { "icon-image": "cat-solidarity_event", "icon-size": ["interpolate", ["linear"], ["zoom"], 1, 0.6, 12, 1], "icon-allow-overlap": true, "icon-ignore-placement": true },
      })
      // ring around the open incident
      m.addLayer({
        id: "selected",
        type: "circle",
        source: "reports",
        filter: ["==", ["get", "id"], selRef.current ?? -1],
        paint: { "circle-color": "rgba(0,0,0,0)", "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 11, 12, 20], "circle-stroke-width": 2, "circle-stroke-color": "#8fd8ea" },
      })
      applyBuildings(m, viewRef.current, threeRef.current)
      const d = dataRef.current
      if (d) {
        ;(m.getSource("reports") as maplibregl.GeoJSONSource).setData(d.pointFC)
        ;(m.getSource("links") as maplibregl.GeoJSONSource).setData(d.linkFC)
      }
      m.setProjection({ type: viewRef.current === "globe" ? "globe" : "mercator" })
      if (viewRef.current === "globe") {
        // a thin atmosphere so the sphere reads against the dark canvas
        m.setSky({ "sky-color": "#0c1830", "horizon-color": "#1c3a63", "fog-color": "#070b14", "sky-horizon-blend": 0.5, "horizon-fog-blend": 0.6, "fog-ground-blend": 0.9, "atmosphere-blend": 0.8 })
      }
      setStyleReady(true)
    }
    m.on("style.load", install)

    m.on("load", () => {
      // phones: start the attribution collapsed to its (i) button so it never
      // spans the screen over other controls; tapping (i) opens the full text
      if (matchMedia("(max-width: 899px)").matches) {
        const at = m.getContainer().querySelector(".maplibregl-ctrl-attrib")
        at?.classList.remove("maplibregl-compact-show")
        at?.removeAttribute("open")
      }
      for (const layer of ["point-base", "point", "point-multi", "solidarity"]) {
        m.on("click", layer, (e) => {
          const id = e.features?.[0]?.properties?.id as number | undefined
          const r = reportsRef.current.find((x) => x.id === id)
          if (r) onSelectRef.current(r)
        })
        m.on("mouseenter", layer, () => (m.getCanvas().style.cursor = "pointer"))
        m.on("mouseleave", layer, () => (m.getCanvas().style.cursor = ""))
      }

      // Right-click (desktop) / long-press (touch) an empty spot to file a
      // report pinned exactly there.
      m.on("contextmenu", (e) => onReportAtRef.current?.(e.lngLat.lat, e.lngLat.lng))
      let lpTimer: number | undefined
      let lpStart: { x: number; y: number } | null = null
      const canvas = m.getCanvas()
      canvas.addEventListener("touchstart", (ev) => {
        if (ev.touches.length !== 1) return
        const tp = ev.touches[0]
        lpStart = { x: tp.clientX, y: tp.clientY }
        lpTimer = window.setTimeout(() => {
          if (!lpStart) return
          const rect = canvas.getBoundingClientRect()
          const ll = m.unproject([lpStart.x - rect.left, lpStart.y - rect.top])
          onReportAtRef.current?.(ll.lat, ll.lng)
        }, 550)
      }, { passive: true })
      const cancelLp = (ev?: TouchEvent) => {
        if (ev && lpStart && ev.touches[0]) {
          const dx = ev.touches[0].clientX - lpStart.x
          const dy = ev.touches[0].clientY - lpStart.y
          if (Math.hypot(dx, dy) < 12) return
        }
        window.clearTimeout(lpTimer)
        lpStart = null
      }
      canvas.addEventListener("touchmove", cancelLp, { passive: true })
      canvas.addEventListener("touchend", () => cancelLp(), { passive: true })

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

  // switch render view: swap the style, the camera stays where it is
  const shownView = useRef(view)
  useEffect(() => {
    const m = map.current
    if (!m || shownView.current === view) return
    shownView.current = view
    setStyleReady(false)
    m.setStyle(styleFor(view))
  }, [view])

  // push data
  useEffect(() => {
    dataRef.current = { pointFC, linkFC }
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
    // easeTo, not flyTo: flyTo arcs out to a wide zoom on long trips. The
    // requested zoom is a floor, so selecting never zooms the map out.
    const calm = matchMedia("(prefers-reduced-motion: reduce)").matches
    m.easeTo({ center: [focus.lon, focus.lat], zoom: Math.max(m.getZoom(), focus.zoom || 6), duration: calm ? 0 : 900 })
  }, [focus])

  // marker images once categories (and their colours) are known
  useEffect(() => {
    const m = map.current
    if (!m || !styleReady || Object.keys(categories).length === 0) return
    let live = true
    void buildMarkerIcons(categories).then(() => live && map.current && addMarkerImages(map.current))
    return () => {
      live = false
    }
  }, [categories, styleReady])

  useEffect(() => {
    const m = map.current
    if (!m || !styleReady || !m.getLayer("selected")) return
    m.setFilter("selected", ["==", ["get", "id"], selectedId ?? -1])
  }, [selectedId, styleReady])

  useEffect(() => {
    const m = map.current
    if (!m || !styleReady) return
    applyBuildings(m, view, threeD)
    const tilt = threeD && (view === "globe" || view === "2d")
    if (tilt) m.setMaxPitch(60)
    else if (m.getPitch() > 0) {
      // ease back to flat first, then lock the pitch, so toggling 3D off does not snap
      const calm = matchMedia("(prefers-reduced-motion: reduce)").matches
      m.once("moveend", () => m.setMaxPitch(0))
      m.easeTo({ pitch: 0, duration: calm ? 0 : 400 })
    } else m.setMaxPitch(0)
  }, [threeD, view, styleReady])

  return <div ref={ref} style={{ position: "absolute", inset: 0 }} />
}
