import { useEffect, useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { useTranslation } from "react-i18next"
import { api, type Report } from "./lib/api"
import { LOCALES, applyLocale, type Locale } from "./i18n"
import { SimpleMap } from "./features/map/SimpleMap"

// <!--
// THESIS: World observatory, not national ledger — every incident read as a coordinate in a worldwide forensic atlas.
// OWN-WORLD: Archival paper on ink, vermillion forensic, ocean blue, ledger hairlines, tabular mono, EqualEarth/Globe atlas, crosshair pins worldwide.
// STORY: Visitor sees global pattern instantly, filters by category/time, flies to any place via geocode, files without losing the world view.
// FIRST VIEWPORT: Ink world bar, EqualEarth world map left 56% + global ledger right 44% (desktop) / stacked 48vh globe (mobile), live ticker, organ-stop categories, ruler timeline, density controls.
// FORM: World observatory keydesk — atlas/globe toggle, geocode flyTo, live 24h ticker, worldwide country tally, quick-exit piston. Worldwide from BUNDESARCHIV seed.
// FINISH: unreviewed and undocumented is unfinished; ends with finish review, verdict, DESIGN.md, provenance.
// -->

export function App(){
  const { t, i18n } = useTranslation()
  const [selected, setSelected] = useState<Report | null>(null)
  const [hiddenCats, setHiddenCats] = useState<Set<string>>(()=> new Set())
  const [q, setQ] = useState("")
  const [cutoff, setCutoff] = useState<number|null>(null)
  const [showReport, setShowReport] = useState(false)
  const [mobileTab, setMobileTab] = useState<"map"|"ledger">("map")
  const [focus, setFocus] = useState<{lon:number, lat:number, zoom:number}|null>(null)
  const [geoHits, setGeoHits] = useState<{lat:number, lon:number, label:string}[]>([])
  const [showFilters, setShowFilters] = useState(true)

  const cats = useQuery({ queryKey:["categories"], queryFn: api.categories, staleTime: 3_600_000 })
  const reportsQ = useQuery({ queryKey:["reports", "world"], queryFn: ()=> api.reports({limit:5000, all:true}), staleTime:60_000 })

  const reports = reportsQ.data ?? []
  const categories = cats.data ?? {}

  const earliest = useMemo(()=> reports.length ? Math.min(...reports.map(r=> r.created_at)) : Math.floor(Date.now()/1000 - 365*86400), [reports])
  const now = Math.floor(Date.now()/1000)
  const effectiveCutoff = cutoff ?? now

  const filtered = useMemo(()=>{
    let r = reports.filter(x=> !hiddenCats.has(x.category) && x.created_at <= effectiveCutoff)
    if(q.trim()){
      const needle = q.trim().toLowerCase()
      r = r.filter(x=> (x.title + " " + (x.body??"") + " " + (x.place??"") + " " + x.category).toLowerCase().includes(needle) || String(x.id).includes(needle))
    }
    return r.sort((a,b)=> b.created_at - a.created_at)
  }, [reports, hiddenCats, effectiveCutoff, q])

  // worldwide stats — not only Germany
  const stats = useMemo(()=>{
    const total = reports.length
    const visible = filtered.length
    const verified = reports.filter(r=> r.status==="verified").length
    const countries = new Set(filtered.map(r=> (r.place||"").split(",").pop()?.trim()|| r.place||"—").filter(Boolean)).size
    const last24 = reports.filter(r=> now - r.created_at < 86400).length
    const last7 = reports.filter(r=> now - r.created_at < 7*86400).length
    return { total, visible, verified, countries, last24, last7 }
  }, [reports, filtered, now])

  // top countries worldwide
  const topCountries = useMemo(()=>{
    const m = new Map<string, number>()
    for(const r of filtered){
      const c = (r.place||"Unverortet").split(",").pop()?.trim() || "Unverortet"
      m.set(c, (m.get(c)||0)+1)
    }
    return [...m.entries()].sort((a,b)=> b[1]-a[1]).slice(0,5)
  }, [filtered])

  const quickExit = ()=> location.replace("https://www.google.com/search?q=weather")

  const toggleCat = (cat: string)=>{
    setHiddenCats(s=>{
      const n = new Set(s)
      if(n.has(cat)) n.delete(cat); else n.add(cat)
      return n
    })
  }

  const timelinePct = earliest===now ? 1000 : Math.round(((effectiveCutoff - earliest)/(now - earliest))*1000)

  // geocode search — fly to worldwide
  useEffect(()=>{
    if(q.trim().length < 3) { setGeoHits([]); return }
    const id = setTimeout(async()=>{
      try{
        const hits = await api.geocode(q.trim())
        setGeoHits(hits.slice(0,4))
      }catch{ setGeoHits([]) }
    }, 450)
    return ()=> clearTimeout(id)
  }, [q])

  const flyTo = (lat:number, lon:number, label:string)=>{
    setFocus({lat, lon, zoom: 3.2})
    setGeoHits([])
    setQ(label)
    setMobileTab("map")
  }

  return (
    <>
      {/* WORLD ledger bar */}
      <header className="ledger-bar">
        <div style={{display:"flex", alignItems:"baseline", gap:10, minWidth:0}}>
          <b style={{whiteSpace:"nowrap"}}>WELTARCHIV</b>
          <span style={{font:"800 11px var(--display)", letterSpacing:".06em", color:"var(--vermillion)", whiteSpace:"nowrap"}}>• WORLD LEDGER</span>
          <span className="sub" style={{display:"none"}}>GLOBAL OBSERVATORY • {stats.countries} LÄNDER • {stats.total.toLocaleString("en-US")} AKTEN WELTWEIT</span>
          <span className="sub" style={{borderLeft:"1px solid rgba(253,248,240,.2)", paddingLeft:10, whiteSpace:"nowrap"}}>
            {stats.countries} LÄNDER • DOKUMENTATION, NICHT ANKLAGE
          </span>
        </div>
        <div className="ledger-actions">
          <span style={{font:"700 10px var(--mono)", letterSpacing:".08em", color:"rgba(253,248,240,.72)", background:"rgba(253,248,240,.1)", padding:"6px 8px", borderRadius:8, whiteSpace:"nowrap"}}>
            <span style={{width:6,height:6, borderRadius:"50%", background:"#1f9b54", display:"inline-block", marginRight:6, boxShadow:"0 0 0 4px rgba(31,155,84,.2)"}}/>
            {stats.last24} NEU / 24H • {stats.last7} / 7T
          </span>
          <select value={i18n.language} onChange={e=> applyLocale(e.target.value as Locale)} className="langsel" aria-label="Language">
            {LOCALES.map(l=> <option key={l} value={l} style={{color:"#0a1629"}}>{l.toUpperCase()}</option>)}
          </select>
          <button onClick={quickExit} className="quickexit">Quick exit ✕</button>
        </div>
      </header>

      <div className="layout" style={{top:56}}>
        {/* WORLD map pane */}
        <div className="map-pane" style={{display: mobileTab==="ledger" ? "none" : undefined } as any}>
          <SimpleMap reports={reports} categories={categories} onSelect={setSelected} hiddenCats={hiddenCats} focus={focus} />
          <div style={{position:"absolute", top:0, insetInline:0, zIndex:6, background:"rgba(253,248,240,.94)", borderBottom:"1px solid var(--line)", display:"flex", alignItems:"center", gap:10, padding:"8px 12px", font:"10px var(--mono)", letterSpacing:".08em", textTransform:"uppercase", color:"var(--faint)", backdropFilter:"blur(6px)"}}>
            <span style={{color:"var(--ink)", fontWeight:800, display:"inline-flex", gap:6, alignItems:"center"}}>
              <span style={{width:8,height:8, borderRadius:"50%", background:"var(--vermillion)", display:"inline-block"}}/> WELT • WORLD
            </span>
            <span style={{background:"var(--ink)", color:"var(--paper)", padding:"3px 6px", borderRadius:6, fontWeight:700}}>ATLAS / GLOBE</span>
            <span style={{display:"inline-flex", gap:4}}>
              {topCountries.slice(0,3).map(([c,n])=>(
                <span key={c} style={{background:"var(--paper-2)", border:"1px solid var(--line)", padding:"2px 6px", borderRadius:6, color:"var(--ink)", fontWeight:700}}>{c} {n}</span>
              ))}
            </span>
            <span style={{marginLeft:"auto", color:"var(--muted)", font:"11px var(--sans)", letterSpacing:0, textTransform:"none", display:"none"}} className="hide-mobile">
              ⌘K Suche • Drag • Scroll zoom • Tap pin → Akte
            </span>
            <button onClick={()=> setFocus({lon:15, lat:25, zoom:1})} style={{background:"var(--paper-2)", border:"1px solid var(--line)", borderRadius:7, padding:"5px 8px", font:"700 10px var(--mono)", cursor:"pointer"}}>WELT</button>
          </div>
        </div>

        {/* WORLD ledger pane — more updated UX */}
        <div className="ledger-pane" style={{display: mobileTab==="map" ? undefined : "flex"} as any}>
          {/* world stat strip — 4 metrics now */}
          <div className="stat-strip" style={{gridTemplateColumns:"1.1fr 0.9fr 0.9fr 1.1fr"}}>
            <div className="cell">
              <div className="k">WELTBESTAND</div>
              <div className="v">{stats.total.toLocaleString("en-US")}</div>
              <div className="s">{stats.countries} Länder • {stats.visible} sichtbar</div>
            </div>
            <div className="cell">
              <div className="k">NEU</div>
              <div className="v" style={{color:"var(--vermillion)"}}>{stats.last24}</div>
              <div className="s">24H • {stats.last7} / 7 Tage</div>
            </div>
            <div className="cell">
              <div className="k">GEPRÜFT</div>
              <div className="v" style={{color:"var(--ok)"}}>{stats.verified}</div>
              <div className="s">{stats.total? Math.round(stats.verified/stats.total*100):0}% verifiziert</div>
            </div>
            <div className="cell">
              <div className="k">ABDECKUNG</div>
              <div className="v" style={{fontSize:14}}>{topCountries[0]?.[0] ?? "—"}</div>
              <div className="s">Top • {topCountries[0]?.[1] ?? 0} Akten</div>
            </div>
          </div>

          {/* search with worldwide geocode */}
          <div className="ribbon" style={{flexDirection:"column", alignItems:"stretch", gap:8}}>
            <div style={{display:"flex", gap:8}}>
              <label className="search" style={{flex:1}}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><circle cx={11} cy={11} r={7}/><path d="M21 21l-4.3-4.3"/></svg>
                <input value={q} onChange={e=> setQ(e.target.value)} placeholder="Weltweit suchen — Ort, Land, Kategorie oder #ID…" />
              </label>
              <button className={`filter-btn ${showFilters? "on":""}`} onClick={()=> setShowFilters(v=>!v)} title="Filter ein/aus">
                {showFilters ? "◧ Filter" : "◨ Filter"}
              </button>
              <button className={`filter-btn ${hiddenCats.size? "on":""}`} onClick={()=> setHiddenCats(new Set())} title="Alle Kategorien zeigen">↺</button>
            </div>
            {geoHits.length>0 && (
              <div style={{background:"var(--paper)", border:"1px solid var(--line)", borderRadius:10, overflow:"hidden", boxShadow:"0 8px 20px rgba(10,22,41,.08)"}}>
                {geoHits.map(h=>(
                  <button key={h.label} onClick={()=> flyTo(h.lat, h.lon, h.label)} style={{display:"block", width:"100%", textAlign:"left", padding:"9px 12px", border:0, borderBottom:"1px solid var(--line-2)", background:"none", font:"12px var(--sans)", cursor:"pointer"}}>
                    <span style={{color:"var(--ink)", fontWeight:600}}>↗ {h.label}</span>
                    <span style={{color:"var(--faint)", font:"10px var(--mono)", marginLeft:8}}>{h.lat.toFixed(2)}, {h.lon.toFixed(2)}</span>
                  </button>
                ))}
              </div>
            )}
            <div style={{display:"flex", gap:6, flexWrap:"wrap", font:"10px var(--mono)", color:"var(--faint)", letterSpacing:".06em", textTransform:"uppercase"}}>
              <span>Schnell:</span>
              {["Berlin","Wien","Warszawa","Paris","London","New York","Kiew"].map(c=>(
                <button key={c} onClick={()=> setQ(c)} style={{border:"1px solid var(--line)", background:"var(--paper-2)", borderRadius:999, padding:"3px 7px", font:"11px var(--sans)", cursor:"pointer", color:"var(--ink)"}}>{c}</button>
              ))}
            </div>
          </div>

          {/* organ stops — now collapsible, worldwide */}
          {showFilters && (
            <div className="cat-rail">
              {Object.entries(categories).sort((a,b)=> (b[1] as any).count - (a[1] as any).count || a[0].localeCompare(b[0])).slice(0,20).map(([key, meta]: any)=>{
                const on = !hiddenCats.has(key)
                const cnt = reports.filter(r=> r.category===key).length
                return (
                  <button key={key} onClick={()=> toggleCat(key)} className={`cat-stop ${on?"on":"dim"}`} title={meta.label}>
                    <span className="dot" style={{background: meta.color}}/>
                    {meta.label}
                    <span className="cnt">{cnt}</span>
                  </button>
                )
              })}
              {Object.keys(categories).length===0 && <span style={{font:"11px var(--mono)", color:"var(--faint)"}}>Kategorien laden…</span>}
              <span style={{marginLeft:"auto", font:"10px var(--mono)", color:"var(--faint)", alignSelf:"center"}}>{filtered.length} Treffer</span>
            </div>
          )}

          {/* ruler — worldwide time */}
          <div className="ruler">
            <div className="ruler-top">
              <span>{new Date(earliest*1000).toLocaleDateString("de-DE")}</span>
              <b style={{display:"inline-flex", gap:6, alignItems:"center"}}>
                <span style={{width:6,height:6, borderRadius:"50%", background:"var(--vermillion)", display:"inline-block"}}/>
                {cutoff==null ? "HEUTE • WORLD" : new Date((cutoff as number)*1000).toLocaleDateString("de-DE")}
              </b>
            </div>
            <input
              type="range" min={0} max={1000} value={timelinePct}
              onChange={e=>{
                const v = Number(e.target.value)
                if(v>=1000) setCutoff(null)
                else setCutoff(Math.round(earliest + (v/1000)*(now-earliest)))
              }}
            />
            <div className="ruler-ticks"><span>ARCHIV</span><span>— WELT-ZEITREISE —</span><span>HEUTE</span></div>
          </div>

          {/* world ledger — richer cards */}
          <div className="ledger">
            {reportsQ.isLoading && <div className="ledger-empty">Welt-Vermessung lädt…<br/><span style={{font:"11px var(--mono)", color:"var(--faint)"}}>816 Akten weltweit werden indiziert</span></div>}
            {reportsQ.isError && <div className="ledger-empty" style={{color:"var(--vermillion)"}}>{t("error.load")}<br/><button className="btn" onClick={()=> reportsQ.refetch()} style={{marginTop:8}}>Erneut versuchen</button></div>}
            {!reportsQ.isLoading && filtered.length===0 && <div className="ledger-empty">Kein Treffer weltweit — Filter oder Zeitraum anpassen.<br/><span style={{font:"10px var(--mono)", color:"var(--faint)"}}>Tipp: Welt-Filter zurücksetzen (↺) oder anderen Suchbegriff probieren.</span></div>}
            {filtered.slice(0,220).map((r: Report)=>{
              const col = (categories as any)[r.category]?.color ?? "#c8c0ad"
              const d = new Date(r.created_at*1000)
              const isNew = (now - r.created_at) < 3*86400
              const faded = (now - r.created_at) > 365*86400*1.8
              const country = (r.place||"").split(",").pop()?.trim() || "WELT"
              return (
                <div key={r.id} className="ledger-row" onClick={()=> setSelected(r)} style={{opacity: faded?0.68:1, background: isNew? "rgba(193,52,32,.04)": undefined, borderLeft: isNew? "3px solid var(--vermillion)": undefined}}>
                  <div className="ref">
                    <b>#{String(r.id).padStart(4,"0")}</b>
                    <span>{d.toLocaleDateString("de-DE", {day:"2-digit", month:"2-digit"})}</span>
                    <span style={{color: r.fuzzed? "var(--amber)":"var(--ok)", fontSize:8, fontWeight:700}}>{r.fuzzed?"~5KM":"EXAKT"}</span>
                  </div>
                  <div className="bar" style={{background:col, opacity: isNew?1:0.9}} />
                  <div className="main">
                    <div className="t" style={{display:"flex", gap:6, alignItems:"flex-start"}}>
                      <span style={{flex:1}}>{r.title}</span>
                      {isNew && <span style={{background:"var(--vermillion)", color:"#fff", font:"700 8px var(--mono)", letterSpacing:".08em", padding:"2px 5px", borderRadius:6, flex:"none"}}>NEU</span>}
                    </div>
                    <div className="m">
                      <span style={{color:col, fontWeight:800}}>{(categories as any)[r.category]?.label ?? r.category}</span>
                      <span>• {r.status}</span>
                      <span>• {country}</span>
                      <span>• {d.toLocaleTimeString("de-DE", {hour:"2-digit", minute:"2-digit"})}</span>
                    </div>
                    {r.place && <div style={{font:"11px var(--sans)", color:"var(--muted)", marginTop:2, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis"}}>{r.place}</div>}
                  </div>
                  <div style={{display:"flex", flexDirection:"column", gap:6, alignItems:"center"}}>
                    <div className="evid" title={r.url? "Quelle vorhanden":"Keine Quelle"} style={{background: r.url? "var(--ink)":"var(--paper-2)", color: r.url? "#fff":"var(--steel)", borderColor: r.url? "var(--ink)":"var(--line)"}}>
                      {r.url ? "↗" : "·"}
                    </div>
                    {r.url && <span style={{font:"8px var(--mono)", color:"var(--faint)", letterSpacing:".06em"}}>QUELLE</span>}
                  </div>
                </div>
              )
            })}
            {filtered.length>220 && <div style={{padding:"12px 14px", font:"11px var(--mono)", color:"var(--faint)", textAlign:"center", borderTop:"1px solid var(--line-2)", background:"var(--paper-2)"}}>
              + {filtered.length-220} weitere weltweit — suche oder filtere schärfer
              <button onClick={()=> setCutoff(null)} style={{marginLeft:8, font:"10px var(--mono)", padding:"4px 8px", borderRadius:6, border:"1px solid var(--line)", background:"#fff", cursor:"pointer"}}>HEUTE</button>
            </div>}
          </div>

          {/* world footer — more updated */}
          <div style={{padding:"10px 12px", borderTop:"1px solid var(--line-2)", background:"var(--paper-2)", display:"flex", gap:10, flexWrap:"wrap", justifyContent:"space-between", alignItems:"center"}}>
            <span style={{font:"9px var(--mono)", letterSpacing:".1em", textTransform:"uppercase", color:"var(--faint)"}}>
              WELTARCHIV • Dokumentation, nicht Anklage • {stats.countries} Länder
            </span>
            <span style={{display:"flex", gap:8, font:"10px var(--mono)"}}>
              <a href="/privacy" style={{color:"var(--faint)"}}>Privacy</a>
              <span style={{color:"var(--line)"}}>•</span>
              <a href="/terms" style={{color:"var(--faint)"}}>Terms</a>
              <span style={{color:"var(--line)"}}>•</span>
              <a href="https://nabilvs.com/projects/discrimination-map#get-involved" target="_blank" rel="noreferrer" style={{color:"var(--vermillion)", fontWeight:700}}>Mitwirken →</a>
            </span>
          </div>
        </div>
      </div>

      {/* mobile tab */}
      <nav className="bottomnav">
        <button className={mobileTab==="map"?"active":""} onClick={()=> setMobileTab("map")}>◍ Weltkarte</button>
        <button className={mobileTab==="ledger"?"active":""} onClick={()=> setMobileTab("ledger")}>☰ Ledger ({filtered.length})</button>
        <button onClick={()=> setShowReport(true)} style={{color:"var(--vermillion)", fontWeight:700}}>+ Melden</button>
        <button onClick={quickExit} style={{color:"var(--ink)"}}>✕ Exit</button>
      </nav>

      <button className="fab" onClick={()=> setShowReport(true)} style={{position:"fixed"}}>
        <span style={{fontSize:16, lineHeight:0}}>+</span> Vorfall melden
      </button>

      {reportsQ.isLoading && <div style={{position:"absolute", left:12, top:66, zIndex:1200, background:"var(--paper)", border:"1px solid var(--line)", borderRadius:10, padding:"6px 10px", font:"11px var(--mono)"}}>{t("loading")}</div>}

      {/* WORLD detail sheet — richer */}
      {selected && (
        <>
          <div className="sheet-backdrop" onClick={()=> setSelected(null)} />
          <aside className="sheet" role="dialog" aria-label={selected.title} style={{maxHeight:"78vh"}}>
            <div className="sheet-head">
              <div style={{minWidth:0, flex:1}}>
                <div style={{font:"9px var(--mono)", letterSpacing:".14em", textTransform:"uppercase", color:"var(--faint)", display:"flex", gap:8, flexWrap:"wrap"}}>
                  <span>AKTE #{String(selected.id).padStart(4,"0")}</span>
                  <span>• {new Date(selected.created_at*1000).toLocaleString("de-DE")}</span>
                  <span>• {selected.place ?? "WELT"}</span>
                </div>
                <h3 style={{margin:"6px 0 6px", font:"800 19px var(--display)", lineHeight:1.2}}>{selected.title}</h3>
                <div style={{display:"flex", gap:6, flexWrap:"wrap", alignItems:"center"}}>
                  <span className={`badge ${selected.status==="verified"?"ok":selected.status==="unverified"?"lead":"user"}`}>{selected.status}</span>
                  <span style={{font:"10px var(--mono)", letterSpacing:".08em", textTransform:"uppercase", color:"var(--faint)"}}>
                    {(categories as any)[selected.category]?.label ?? selected.category} • {selected.fuzzed?"~5km weltweit gefuzzt":"exakt"}
                  </span>
                  {selected.url && <a href={selected.url} target="_blank" rel="noreferrer" style={{font:"11px var(--sans)", color:"var(--steel)", fontWeight:700}}>Quelle ↗</a>}
                </div>
              </div>
              <button onClick={()=> setSelected(null)} style={{background:"var(--paper-2)", border:"1px solid var(--line)", borderRadius:8, width:32, height:32, cursor:"pointer", flex:"none"}}>✕</button>
            </div>
            <div className="sheet-body">
              <p style={{margin:"0 0 12px", color:"var(--ink)", fontSize:14, lineHeight:1.6}}>{(selected as any).body ?? (selected as any).summary ?? selected.title}</p>
              {selected.reason && <div style={{marginBottom:12}}><div style={{font:"10px var(--mono)", letterSpacing:".12em", textTransform:"uppercase", color:"var(--faint)", marginBottom:6}}>Erkennungsgrund • Weltweit</div><div style={{background:"var(--paper-2)", border:"1px solid var(--line-2)", borderRadius:10, padding:"10px 12px", fontSize:13}}>{selected.reason}</div></div>}
              <div style={{display:"grid", gridTemplateColumns:"1fr 1fr", gap:8, marginBottom:12}}>
                <div style={{background:"var(--paper-2)", border:"1px solid var(--line-2)", borderRadius:10, padding:"10px 12px"}}>
                  <div style={{font:"700 9px var(--mono)", letterSpacing:".1em", textTransform:"uppercase", color:"var(--faint)"}}>WELT-ORT</div>
                  <div style={{marginTop:6, font:"13px var(--sans)", fontWeight:600}}>{selected.place ?? "Unverortet"}</div>
                  <div style={{marginTop:4, font:"11px var(--mono)", color:"var(--muted)"}}>{selected.lat!=null && selected.lon!=null ? `${Number(selected.lat).toFixed(3)}, ${Number(selected.lon).toFixed(3)}` : "—"} • {selected.fuzzed?"gefuzzt":"exakt"}</div>
                  {selected.lat!=null && <button onClick={()=> setFocus({lat: Number(selected.lat), lon: Number(selected.lon), zoom:4.5})} style={{marginTop:8, font:"10px var(--mono)", padding:"6px 8px", borderRadius:7, border:"1px solid var(--line)", background:"#fff", cursor:"pointer"}}>Auf Weltkarte zeigen →</button>}
                </div>
                <div style={{background:"var(--paper-2)", border:"1px solid var(--line-2)", borderRadius:10, padding:"10px 12px"}}>
                  <div style={{font:"700 9px var(--mono)", letterSpacing:".1em", textTransform:"uppercase", color:"var(--faint)"}}>RECHT</div>
                  <div style={{marginTop:6, font:"13px var(--sans)", fontWeight:600}}>{(selected as any).law ?? (selected as any).statute_code ?? <span style={{color:"var(--faint)", fontWeight:400}}>Kein StGB-Vorschlag</span>}</div>
                  <div style={{marginTop:6, font:"11px var(--sans)", color:"var(--muted)", lineHeight:1.4}}>Möglicherweise einschlägig — keine Vorverurteilung. Weltweit gilt jeweilige lokale Rechtsordnung.</div>
                </div>
              </div>
              {/* nearby worldwide */}
              {(()=>{
                const nearby = reports.filter(r=> r.id!==selected.id && r.lat!=null && Math.abs(Number(r.lat)-Number(selected.lat||0))< 4 && Math.abs(Number(r.lon)-Number(selected.lon||0))< 6).slice(0,3)
                if(!nearby.length) return null
                return (
                  <div style={{marginBottom:12, border:"1px solid var(--line-2)", borderRadius:10, overflow:"hidden"}}>
                    <div style={{padding:"8px 10px", font:"700 9px var(--mono)", letterSpacing:".1em", textTransform:"uppercase", color:"var(--faint)", background:"var(--paper-3)", borderBottom:"1px solid var(--line-2)"}}>In der Nähe weltweit</div>
                    {nearby.map(r=>(
                      <div key={r.id} onClick={()=> setSelected(r)} style={{padding:"8px 10px", display:"flex", gap:8, borderBottom:"1px solid var(--line-2)", cursor:"pointer", background:"#fff"}}>
                        <span style={{width:6,height:6, borderRadius:"50%", background:(categories as any)[r.category]?.color ?? "#c8c0ad", marginTop:6, flex:"none"}}/>
                        <span style={{font:"12px var(--sans)", color:"var(--ink)", flex:1, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis"}}>{r.title}</span>
                        <span style={{font:"10px var(--mono)", color:"var(--faint)"}}>#{r.id}</span>
                      </div>
                    ))}
                  </div>
                )
              })()}
              {selected.impact && <div style={{background:"rgba(193,52,32,.06)", border:"1px solid rgba(193,52,32,.14)", borderRadius:10, padding:"10px 12px", marginBottom:12}}><div style={{font:"700 10px var(--mono)", letterSpacing:".1em", textTransform:"uppercase", color:"var(--vermillion)", marginBottom:6}}>Auswirkung</div><div style={{fontSize:13, lineHeight:1.5}}>{selected.impact}</div></div>}
              {selected.evidence && <div style={{background:"var(--paper-2)", borderLeft:"3px solid var(--hair)", padding:"10px 12px", borderRadius:"0 10px 10px 0", fontStyle:"italic", color:"var(--muted)", marginBottom:12, fontSize:13}}>{selected.evidence}</div>}
              <div style={{display:"flex", gap:8}}>
                <button onClick={()=> { if(selected.url) window.open(selected.url, "_blank") }} disabled={!selected.url} className="btn primary" style={{flex:1}}>Quelle öffnen ↗</button>
                <button onClick={()=> setSelected(null)} className="btn" style={{flex:1}}>Schließen</button>
              </div>
              <div style={{font:"10px var(--mono)", letterSpacing:".06em", textTransform:"uppercase", color:"var(--faint)", borderTop:"1px solid var(--line-2)", paddingTop:10, marginTop:14, textAlign:"center"}}>
                Weltarchiv • Dokumentation, nicht Anklage • Unschuldsvermutung weltweit
              </div>
            </div>
          </aside>
        </>
      )}

      {/* report modal — worldwide */}
      {showReport && (
        <div className="modal-scrim" onClick={()=> setShowReport(false)}>
          <div className="modal" onClick={e=> e.stopPropagation()}>
            <div style={{font:"700 9px var(--mono)", letterSpacing:".14em", textTransform:"uppercase", color:"var(--vermillion)"}}>WELTWEIT • AKTE ANLEGEN</div>
            <h2 style={{margin:"6px 0 6px", font:"800 20px var(--display)"}}>Vorfall weltweit melden</h2>
            <p style={{margin:0, color:"var(--muted)", fontSize:13, lineHeight:1.55}}>Anonym, ohne Konto, weltweit. Mit belastbarer Quelle erscheint der Eintrag direkt als “unverified lead”, sonst erst nach Prüfung. Keine Namen von Privatpersonen — weltweit gültig.</p>
            <div style={{marginTop:12, display:"grid", gridTemplateColumns:"1fr 1fr", gap:8}}>
              <div style={{padding:10, background:"var(--paper-2)", border:"1px solid var(--line-2)", borderRadius:10, textAlign:"center"}}>
                <div style={{font:"700 10px var(--mono)", color:"var(--faint)"}}>WELT-TOP</div>
                <div style={{font:"700 14px var(--mono)", marginTop:4}}>{topCountries.slice(0,3).map(([c])=> c).join(" • ")}</div>
                <div style={{font:"11px var(--sans)", color:"var(--muted)", marginTop:2}}>Fokusländer</div>
              </div>
              <div style={{padding:10, background:"var(--ink)", color:"var(--paper)", borderRadius:10, textAlign:"center"}}>
                <div style={{font:"700 10px var(--mono)", letterSpacing:".1em", color:"rgba(253,248,240,.7)"}}>LIVE WELTWEIT</div>
                <div style={{font:"700 20px var(--mono)", marginTop:4}}>{stats.last24} / 24H</div>
                <div style={{font:"11px var(--sans)", color:"rgba(253,248,240,.7)", marginTop:2}}>zuletzt eingegangen</div>
              </div>
            </div>
            <div className="btnrow" style={{marginTop:14}}>
              <button className="btn" onClick={()=> setShowReport(false)}>Abbrechen</button>
              <a className="btn primary" href="http://127.0.0.1:8020/" target="_blank" rel="noreferrer" style={{textDecoration:"none", display:"inline-flex", alignItems:"center"}}>Weltweit melden →</a>
            </div>
            <div style={{marginTop:10, font:"11px var(--sans)", color:"var(--faint)", textAlign:"center"}}>Vollformular mit Kategorie, StGB, Evidenz, Ort lebt im Alt-Frontend — dieses Welt-Ledger nutzt dieselbe API weltweit.</div>
          </div>
        </div>
      )}
    </>
  )
}
