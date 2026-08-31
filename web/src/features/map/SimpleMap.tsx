import { useMemo, useState } from "react"
import { ComposableMap, Geographies, Geography, Marker, ZoomableGroup, Graticule } from "react-simple-maps"
import type { Report, CategoryMeta } from "../../lib/api"

const GEO_URL = "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json"

type Projection = "geoEqualEarth" | "geoMercator" | "geoOrthographic"

function ageOpacity(created_at: number){
  const days = (Date.now()/1000 - created_at)/86400
  if(days < 2) return 1
  if(days > 3650) return 0.42
  if(days > 720) return 0.58
  if(days > 180) return 0.78
  return 0.94
}

export function SimpleMap({
  reports,
  categories,
  onSelect,
  hiddenCats,
  focus,
}:{
  reports: Report[]
  categories: Record<string, CategoryMeta>
  onSelect: (r: Report)=>void
  hiddenCats: Set<string>
  focus?: { lon:number, lat:number, zoom:number } | null
}){
  const [proj, setProj] = useState<Projection>("geoEqualEarth")
  const [zoom, setZoom] = useState(1)

  const visible = useMemo(()=> reports.filter(r=> r.lat!=null && r.lon!=null && !hiddenCats.has(r.category)), [reports, hiddenCats])

  // worldwide stats for caption
  const countries = useMemo(()=>{
    const s = new Set(visible.map(r=> (r.place||"").split(",").pop()?.trim()).filter(Boolean))
    return s.size
  }, [visible])

  const center: [number, number] = focus ? [focus.lon, focus.lat] : (proj==="geoOrthographic" ? [10, 35] : [15, 25])
  const scale = proj==="geoOrthographic" ? 420 : proj==="geoEqualEarth" ? 175 : 145

  return (
    <div style={{position:"absolute", inset:0, background:"#eef2fb", overflow:"hidden"}}>
      {/* ocean + paper gradient */}
      <div style={{
        position:"absolute", inset:0,
        background: proj==="geoOrthographic"
          ? "radial-gradient(ellipse at 50% 42%, #dbeafe 0%, #bfdbfe 22%, #93c5fd 55%, #0a1629 98%)"
          : "linear-gradient(180deg, #eef2fb 0%, #fdf8f0 62%, #f4efe6 100%)",
        opacity: proj==="geoOrthographic" ? 1 : 0.92
      }}/>
      <div className="ledger-grid" style={{position:"absolute", inset:0, opacity: proj==="geoOrthographic" ? 0 : 0.38}}/>

      {/* projection switcher — archival tabs */}
      <div style={{
        position:"absolute", left:12, top:12, zIndex:7, display:"flex", gap:6,
        background:"rgba(253,248,240,.96)", border:"1px solid var(--line)", borderRadius:10, padding:4,
        boxShadow:"0 4px 14px rgba(10,22,41,.1)"
      }}>
        {(["geoEqualEarth","geoMercator","geoOrthographic"] as Projection[]).map(p=>(
          <button key={p} onClick={()=> setProj(p)}
            style={{
              padding:"6px 9px", borderRadius:7, border: proj===p ? "1px solid var(--ink)" : "1px solid transparent",
              background: proj===p ? "var(--ink)" : "transparent",
              color: proj===p ? "var(--paper)" : "var(--muted)",
              font:"700 10px var(--mono)", letterSpacing:".08em", textTransform:"uppercase", cursor:"pointer"
            }}>
            {p==="geoEqualEarth" ? "ATLAS" : p==="geoMercator" ? "MERCATOR" : "GLOBE"}
          </button>
        ))}
        <span style={{width:1, background:"var(--line-2)", margin:"2px 2px"}}/>
        <button onClick={()=> setZoom(z=> Math.min(8, +(z*1.35).toFixed(2)))} style={iconBtn}>＋</button>
        <button onClick={()=> setZoom(z=> Math.max(0.85, +(z/1.35).toFixed(2)))} style={iconBtn}>－</button>
        <button onClick={()=> {setZoom(1)}} style={{...iconBtn, fontSize:9, letterSpacing:".06em"}}>RESET</button>
      </div>

      <ComposableMap
        projection={proj}
        projectionConfig={proj==="geoOrthographic" ? { scale, center } : { scale, center }}
        style={{width:"100%", height:"100%"}}
      >
        <ZoomableGroup zoom={zoom} center={center} minZoom={0.85} maxZoom={10} onMoveEnd={({zoom:z}:any)=> setZoom(z)}>
          {proj!=="geoOrthographic" && (
            <Graticule stroke="rgba(10,22,41,.06)" step={[15,15]} />
          )}
          <Geographies geography={GEO_URL}>
            {({ geographies }) =>
              geographies.map((geo:any) => {
                const name = geo.properties.name as string
                const isGermany = name==="Germany"
                // highlight countries with incidents
                const hasIncidents = visible.some(r=> (r.place||"").includes(name) || (name==="United States of America" && (r.place||"").includes("USA")))
                const isEU = ["Poland","France","Czechia","Austria","Switzerland","Netherlands","Belgium","Denmark","Luxembourg","Italy","Spain","United Kingdom"].includes(name)
                return (
                  <Geography
                    key={geo.rsmKey}
                    geography={geo}
                    fill={
                      isGermany ? "#ede7db"
                      : hasIncidents ? "#f7ede0"
                      : isEU ? "#f7f3ea"
                      : proj==="geoOrthographic" ? "#fdf8f0"
                      : "#fdf8f0"
                    }
                    stroke={isGermany ? "#0a1629" : hasIncidents ? "#c8c0ad" : "rgba(168,160,140,.42)"}
                    strokeWidth={isGermany ? 0.85 : hasIncidents ? 0.45 : 0.28}
                    style={{
                      default:{ outline:"none", transition:"fill .2s" },
                      hover:{ fill: isGermany ? "#e8e1d1" : hasIncidents ? "#ede7db" : "#f4efe6", outline:"none" },
                      pressed:{ outline:"none" },
                    }}
                  />
                )
              })
            }
          </Geographies>

          {/* markers — worldwide */}
          {visible.map(r=>{
            const col = categories[r.category]?.color ?? "#8a97ac"
            const isStar = r.category==="solidarity_event"
            const op = ageOpacity(r.created_at)
            const faded = op < 0.62
            const isNew = (Date.now()/1000 - r.created_at) < 2*86400
            // scale marker with zoom so worldwide stays legible
            const s = 1 / Math.pow(zoom, 0.28)
            return (
              <Marker key={r.id} coordinates={[r.lon as number, r.lat as number]}>
                <g
                  onClick={()=> onSelect(r)}
                  style={{cursor:"pointer"}}
                  opacity={r.fuzzed ? op*0.92 : op}
                  transform={`scale(${s})`}
                >
                  {r.fuzzed && !faded && <circle r={isStar?15:11} fill={col} opacity={0.07} />}
                  <line x1={-7} y1={0} x2={7} y2={0} stroke="rgba(10,22,41,.16)" strokeWidth={0.6} />
                  <line x1={0} y1={-7} x2={0} y2={7} stroke="rgba(10,22,41,.16)" strokeWidth={0.6} />
                  {isStar ? (
                    <path
                      d="M0 -9 L2.6 -2.9 L9.2 -2.9 L4.1 1.1 L5.7 7.3 L0 3.4 L-5.7 7.3 L-4.1 1.1 L-9.2 -2.9 L-2.6 -2.9 Z"
                      fill={col} stroke="#fff" strokeWidth={1.35}
                      style={{filter: faded ? "grayscale(1) brightness(1.35)" : `drop-shadow(0 1px 3px ${col}66)`}}
                    />
                  ) : (
                    <circle r={6.2} fill={col} stroke="#fff" strokeWidth={1.45}
                      style={{filter: faded ? "grayscale(1) brightness(1.42)" : `drop-shadow(0 0 5px ${col}7a)`}} />
                  )}
                  {isNew && !faded && (
                    <circle r={9} fill="none" stroke={col} strokeWidth={1.05} opacity={0.38}>
                      <animate attributeName="r" values="7;15" dur="1.7s" repeatCount="indefinite"/>
                      <animate attributeName="opacity" values="0.45;0" dur="1.7s" repeatCount="indefinite"/>
                    </circle>
                  )}
                </g>
              </Marker>
            )
          })}
        </ZoomableGroup>
      </ComposableMap>

      {/* archival caption — worldwide */}
      <div style={{
        position:"absolute", left:10, right:10, bottom:10, zIndex:6,
        background:"rgba(253,248,240,.96)", border:"1px solid var(--line)", borderRadius:12,
        padding:"8px 10px", display:"flex", gap:10, alignItems:"center", flexWrap:"wrap",
        font:"10px var(--mono)", letterSpacing:".07em", textTransform:"uppercase", color:"var(--faint)",
        boxShadow:"0 6px 18px rgba(10,22,41,.08)"
      }}>
        <span style={{color:"var(--ink)", fontWeight:800, display:"inline-flex", gap:6, alignItems:"center"}}>
          <span style={{width:7,height:7, borderRadius:"50%", background:"var(--mint)", boxShadow:"0 0 0 4px rgba(31,155,84,.16)", display:"inline-block"}}/>
          {proj==="geoOrthographic" ? "GLOBE • WELT" : "WELTARCHIV • WORLD LEDGER"}
        </span>
        <span style={{width:1, height:10, background:"var(--line)"}}/>
        <span><b style={{color:"var(--ink)"}}>{visible.length}</b> EREIGNISSE • <b style={{color:"var(--ink)"}}>{countries}</b> LÄNDER</span>
        <span style={{width:1, height:10, background:"var(--line)"}}/>
        <span style={{display:"inline-flex", gap:6}}>
          <span style={{width:8,height:8, borderRadius:"50%", background:"#c13420", display:"inline-block"}}/> LIVE
          <span style={{width:8,height:8, borderRadius:"50%", background:"#1f9b54", display:"inline-block"}}/> VERIFIZIERT
          <span style={{width:8,height:8, borderRadius:"50%", background:"#9C6109", display:"inline-block"}}/> LEAD
        </span>
        <span style={{marginLeft:"auto", font:"9px var(--mono)", color:"var(--muted)", letterSpacing:".06em", textTransform:"none"}}>
          Drag • Scroll • Tap pin → Akte
        </span>
      </div>

      {/* live ticker — top right under header */}
      <div style={{
        position:"absolute", right:12, top:54, zIndex:6,
        background:"var(--ink)", color:"var(--paper)", borderRadius:10, padding:"7px 10px",
        font:"10px var(--mono)", letterSpacing:".08em", display:"flex", gap:8, alignItems:"center",
        boxShadow:"0 6px 18px rgba(10,22,41,.18)"
      }}>
        <span style={{width:6,height:6, borderRadius:"50%", background:"var(--mint)", boxShadow:"0 0 0 5px rgba(31,155,84,.22)", display:"inline-block"}}/>
        LIVE • {visible.filter(r=> Date.now()/1000 - r.created_at < 86400).length} NEU / 24H
        <span style={{width:1, height:10, background:"rgba(253,248,240,.18)"}}/>
        <span style={{color:"rgba(253,248,240,.72)"}}>{new Date().toLocaleTimeString("de-DE", {hour:"2-digit", minute:"2-digit"})} UTC</span>
      </div>
    </div>
  )
}

const iconBtn: React.CSSProperties = {
  width:28, height:28, borderRadius:7, border:"1px solid var(--line)", background:"#fff",
  display:"grid", placeItems:"center", font:"700 12px var(--mono)", cursor:"pointer", color:"var(--ink)"
}
