import { useEffect, useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { useTranslation } from "react-i18next"
import { api, type Report } from "./lib/api"
import { LOCALES, applyLocale, type Locale } from "./i18n"
import { SimpleMap } from "./features/map/SimpleMap"
import { AWARENESS } from "./lib/awareness"

// <!--
// THESIS: Complete world observatory — every old-map information restored in chromatic Signal Atlas, fluid to any device.
// OWN-WORLD: Daylight paper #fffef8 / ink #0a0f1f / vermillion #e11d2d saturated, steel #0284c7, ledger hairlines, tabular mono, EqualEarth/globe inline.
// STORY: Visitor sees global pattern, reads any incident, checks any statute, learns any symbol, volunteers — without leaving the world view.
// FIRST VIEWPORT: Ink world bar, fluid map + rail ledger with 4 tabs (Incidents/Laws/Awareness/Volunteer), live ticker, organ-stop cats, ruler, notice, hunt/about.
// FORM: World keydesk with 4 ledger tabs + 2 modals (Hunt/About) + Notice banner + saturated markers — all fluid via container queries.
// FINISH: unreviewed and undocumented is unfinished; ends with finish review, verdict, DESIGN.md, provenance.
// -->

type LedgerTab = "incidents" | "laws" | "awareness" | "volunteer"

export function App(){
  const { t, i18n } = useTranslation()
  const [selected, setSelected] = useState<Report | null>(null)
  const [hiddenCats, setHiddenCats] = useState<Set<string>>(()=> new Set())
  const [q, setQ] = useState("")
  const [cutoff, setCutoff] = useState<number|null>(null)
  const [showReport, setShowReport] = useState(false)
  const [mobileTab, setMobileTab] = useState<"map"|"ledger">("map")
  const [focus, setFocus] = useState<{lon:number, lat:number, zoom:number}|null>(null)
  const [locating, setLocating] = useState(false)
  const [geoHits, setGeoHits] = useState<{lat:number, lon:number, label:string}[]>([])
  const [showFilters, setShowFilters] = useState(true)
  const [ledgerTab, setLedgerTab] = useState<LedgerTab>("incidents")
  const [showHunt, setShowHunt] = useState(false)
  const [showAbout, setShowAbout] = useState(false)
  const [noticeDismissed, setNoticeDismissed] = useState(false)

  const cats = useQuery({ queryKey:["categories"], queryFn: api.categories, staleTime: 3_600_000 })
  const reportsQ = useQuery({ queryKey:["reports", "world"], queryFn: ()=> api.reports({limit:5000, all:true}), staleTime:60_000 })
  const lawsQ = useQuery({ queryKey:["laws"], queryFn: api.laws, staleTime: 3_600_000 })

  const reports = reportsQ.data ?? []
  const categories = cats.data ?? {}
  const laws: any[] = Array.isArray(lawsQ.data) ? lawsQ.data : (lawsQ.data as any)?.laws ?? []

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

  const stats = useMemo(()=>{
    const total = reports.length
    const visible = filtered.length
    const verified = reports.filter(r=> r.status==="verified").length
    const countries = new Set(filtered.map(r=> (r.place||"").split(",").pop()?.trim()|| r.place||"—").filter(Boolean)).size
    const last24 = reports.filter(r=> now - r.created_at < 86400).length
    const last7 = reports.filter(r=> now - r.created_at < 7*86400).length
    return { total, visible, verified, countries, last24, last7 }
  }, [reports, filtered, now])

  const topCountries = useMemo(()=>{
    const m = new Map<string, number>()
    for(const r of filtered){
      const c = (r.place||"Unverortet").split(",").pop()?.trim() || "Unverortet"
      m.set(c, (m.get(c)||0)+1)
    }
    return [...m.entries()].sort((a,b)=> b[1]-a[1]).slice(0,5)
  }, [filtered])

  const quickExit = ()=> location.replace("https://www.google.com/search?q=weather")
  const locateMe = ()=>{
    if(!navigator.geolocation){ alert("Geolocation not available"); return }
    setLocating(true)
    navigator.geolocation.getCurrentPosition(p=>{
      setFocus({lon: p.coords.longitude, lat: p.coords.latitude, zoom: 4})
      setLocating(false)
    }, ()=> setLocating(false), {enableHighAccuracy:true})
  }
  const toggleCat = (cat: string)=>{
    setHiddenCats(s=>{
      const n = new Set(s)
      if(n.has(cat)) n.delete(cat); else n.add(cat)
      return n
    })
  }
  const timelinePct = earliest===now ? 1000 : Math.round(((effectiveCutoff - earliest)/(now - earliest))*1000)

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

  const aw = (AWARENESS as any)[i18n.language] || (AWARENESS as any).en

  return (
    <>
      <header className="ledger-bar">
        <div style={{display:"flex", alignItems:"baseline", gap:10, minWidth:0}}>
          <b style={{whiteSpace:"nowrap"}}>DISCRIMINATION MAP</b>
          <span style={{font:"800 11px var(--display)", letterSpacing:".06em", color:"var(--vermillion)", whiteSpace:"nowrap"}}>• WELTARCHIV</span>
          <span className="sub" style={{borderLeft:"1px solid rgba(255,254,248,.2)", paddingLeft:10, whiteSpace:"nowrap"}}>
            {stats.countries} LÄNDER • DOKUMENTATION WELTWEIT
          </span>
        </div>
        <div className="ledger-actions">
          <span style={{font:"700 10px var(--mono)", letterSpacing:".08em", color:"rgba(255,254,248,.72)", background:"rgba(255,254,248,.1)", padding:"6px 8px", borderRadius:8, whiteSpace:"nowrap"}}>
            <span style={{width:6,height:6, borderRadius:"50%", background:"var(--mint)", display:"inline-block", marginRight:6, boxShadow:"0 0 0 4px rgba(5,150,105,.22)"}}/>
            {stats.last24} NEU / 24H
          </span>
          <button onClick={()=> setShowAbout(true)} style={{background:"rgba(255,254,248,.1)", color:"var(--paper)", border:"1px solid rgba(255,254,248,.18)", borderRadius:8, padding:"6px 10px", font:"700 10px var(--mono)", cursor:"pointer", whiteSpace:"nowrap"}}>Guide</button>
          <select value={i18n.language} onChange={e=> applyLocale(e.target.value as Locale)} className="langsel" aria-label="Language">
            {LOCALES.map(l=> <option key={l} value={l} style={{color:"#0a0f1f"}}>{l.toUpperCase()}</option>)}
          </select>
          <button onClick={quickExit} className="quickexit">Quick exit ✕</button>
        </div>
      </header>

      <div className="layout" style={{top:56}}>
        <div className="map-pane" style={{display: mobileTab==="ledger" ? "none" : undefined } as any}>
          <SimpleMap reports={reports} categories={categories} onSelect={setSelected} hiddenCats={hiddenCats} focus={focus} />
          <div style={{position:"absolute", top:0, insetInline:0, zIndex:6, background:"rgba(255,254,248,.94)", borderBottom:"1px solid var(--line)", display:"flex", alignItems:"center", gap:10, padding:"8px 12px", font:"10px var(--mono)", letterSpacing:".08em", textTransform:"uppercase", color:"var(--faint)", backdropFilter:"blur(6px)"}}>
            <span style={{color:"var(--ink)", fontWeight:800, display:"inline-flex", gap:6, alignItems:"center"}}>
              <span style={{width:8,height:8, borderRadius:"50%", background:"var(--vermillion)", display:"inline-block"}}/> WELT • WORLD
            </span>
            <span style={{background:"var(--ink)", color:"var(--paper)", padding:"3px 6px", borderRadius:6, fontWeight:700}}>ATLAS / GLOBE</span>
            <span style={{display:"inline-flex", gap:4}}>
              {topCountries.slice(0,3).map(([c,n])=>(
                <span key={c} style={{background:"var(--paper-2)", border:"1px solid var(--line)", padding:"2px 6px", borderRadius:6, color:"var(--ink)", fontWeight:700}}>{c} {n}</span>
              ))}
            </span>
            <button onClick={locateMe} style={{background: locating ? "var(--ink)" : "var(--paper-2)", color: locating ? "#fff" : "var(--ink)", border:"1px solid var(--line)", borderRadius:7, padding:"5px 8px", font:"700 10px var(--mono)", cursor:"pointer"}}>{locating ? "…" : "◎ Locate"}</button>
            <button onClick={()=> setFocus({lon:15, lat:25, zoom:1})} style={{background:"var(--paper-2)", border:"1px solid var(--line)", borderRadius:7, padding:"5px 8px", font:"700 10px var(--mono)", cursor:"pointer"}}>WELT</button>
          </div>
        </div>

        <div className="ledger-pane" style={{display: mobileTab==="map" ? undefined : "flex"} as any}>
          {/* world stat strip */}
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
              <div className="v" style={{color:"var(--mint)"}}>{stats.verified}</div>
              <div className="s">{stats.total? Math.round(stats.verified/stats.total*100):0}% verifiziert</div>
            </div>
            <div className="cell">
              <div className="k">ABDECKUNG</div>
              <div className="v" style={{fontSize:14}}>{topCountries[0]?.[0] ?? "—"}</div>
              <div className="s">Top • {topCountries[0]?.[1] ?? 0} Akten</div>
            </div>
          </div>

          {/* notice — was missing in new version, now restored */}
          {!noticeDismissed && (
            <div style={{background:"rgba(225,29,45,.07)", borderBottom:"1px solid rgba(225,29,45,.16)", padding:"10px 12px", display:"flex", gap:10, alignItems:"flex-start", font:"12px var(--sans)", lineHeight:1.5, color:"var(--muted)"}}>
              <span style={{background:"var(--vermillion)", color:"#fff", font:"700 9px var(--mono)", padding:"2px 6px", borderRadius:6, flex:"none", marginTop:2}}>HINWEIS</span>
              <span style={{flex:1}}><b style={{color:"var(--ink)"}}>Dokumentation, nicht Anklage.</b> Unverifizierte Leads — angeblich, nicht bewiesen. Unschuldsvermutung gilt. Notfall: Polizei 110.</span>
              <button onClick={()=> setNoticeDismissed(true)} style={{background:"none", border:"1px solid var(--line)", borderRadius:7, width:26, height:26, cursor:"pointer", flex:"none"}}>✕</button>
            </div>
          )}

          {/* ledger tabs — Incidents/Laws/Awareness/Volunteer (were missing) */}
          <div style={{display:"flex", borderBottom:"1px solid var(--line-2)", background:"var(--paper)", gap:0}}>
            {(["incidents","laws","awareness","volunteer"] as LedgerTab[]).map(tab=>(
              <button key={tab} onClick={()=> setLedgerTab(tab)} style={{
                flex:1, padding:"10px 6px", border:0, borderBottom: ledgerTab===tab ? "2px solid var(--vermillion)" : "2px solid transparent",
                background: ledgerTab===tab ? "var(--paper-2)" : "transparent",
                font: ledgerTab===tab ? "800 11px var(--mono)" : "700 11px var(--mono)",
                letterSpacing:".08em", textTransform:"uppercase", color: ledgerTab===tab ? "var(--ink)" : "var(--faint)", cursor:"pointer"
              }}>
                {tab==="incidents" ? `Incidents ${filtered.length}` : tab==="laws" ? `Laws ${laws.length || 10}` : tab==="awareness" ? "Awareness" : "Volunteer"}
              </button>
            ))}
          </div>

          {ledgerTab==="incidents" && (
            <>
              <div className="ribbon" style={{flexDirection:"column", alignItems:"stretch", gap:8}}>
                <div style={{display:"flex", gap:8}}>
                  <label className="search" style={{flex:1}}>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><circle cx={11} cy={11} r={7}/><path d="M21 21l-4.3-4.3"/></svg>
                    <input value={q} onChange={e=> setQ(e.target.value)} placeholder="Weltweit suchen — Ort, Land, Kategorie oder #ID…" />
                  </label>
                  <button className={`filter-btn ${showFilters? "on":""}`} onClick={()=> setShowFilters(v=>!v)}>{showFilters ? "◧ Filter" : "◨ Filter"}</button>
                  <button className={`filter-btn ${hiddenCats.size? "on":""}`} onClick={()=> setHiddenCats(new Set())}>↺</button>
                </div>
                {geoHits.length>0 && (
                  <div style={{background:"var(--paper)", border:"1px solid var(--line)", borderRadius:10, overflow:"hidden"}}>
                    {geoHits.map(h=>(
                      <button key={h.label} onClick={()=> flyTo(h.lat, h.lon, h.label)} style={{display:"block", width:"100%", textAlign:"left", padding:"9px 12px", border:0, borderBottom:"1px solid var(--line-2)", background:"none", font:"12px var(--sans)", cursor:"pointer"}}>
                        <span style={{color:"var(--ink)", fontWeight:600}}>↗ {h.label}</span>
                        <span style={{color:"var(--faint)", font:"10px var(--mono)", marginLeft:8}}>{h.lat.toFixed(2)}, {h.lon.toFixed(2)}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>

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
                </div>
              )}

              <div className="ruler">
                <div className="ruler-top">
                  <span>{new Date(earliest*1000).toLocaleDateString("de-DE")}</span>
                  <b style={{display:"inline-flex", gap:6, alignItems:"center"}}>
                    <span style={{width:6,height:6, borderRadius:"50%", background:"var(--vermillion)", display:"inline-block"}}/>
                    {cutoff==null ? "HEUTE • WORLD" : new Date((cutoff as number)*1000).toLocaleDateString("de-DE")}
                  </b>
                </div>
                <input type="range" min={0} max={1000} value={timelinePct} onChange={e=>{
                  const v = Number(e.target.value)
                  if(v>=1000) setCutoff(null)
                  else setCutoff(Math.round(earliest + (v/1000)*(now-earliest)))
                }} />
                <div className="ruler-ticks"><span>ARCHIV</span><span>— WELT-ZEITREISE —</span><span>HEUTE</span></div>
              </div>

              <div className="ledger">
                {reportsQ.isLoading && <div className="ledger-empty">Welt-Vermessung lädt…</div>}
                {filtered.slice(0,220).map((r: Report)=>{
                  const col = (categories as any)[r.category]?.color ?? "#c8c0ad"
                  const d = new Date(r.created_at*1000)
                  const isNew = (now - r.created_at) < 3*86400
                  const faded = (now - r.created_at) > 365*86400*1.8
                  const country = (r.place||"").split(",").pop()?.trim() || "WELT"
                  return (
                    <div key={r.id} className="ledger-row" onClick={()=> setSelected(r)} style={{opacity: faded?0.68:1, background: isNew? "rgba(225,29,45,.04)": undefined, borderLeft: isNew? "3px solid var(--vermillion)": undefined}}>
                      <div className="ref">
                        <b>#{String(r.id).padStart(4,"0")}</b>
                        <span>{d.toLocaleDateString("de-DE", {day:"2-digit", month:"2-digit"})}</span>
                        <span style={{color: r.fuzzed? "var(--amber)":"var(--mint)", fontSize:8, fontWeight:700}}>{r.fuzzed?"~5KM":"EXAKT"}</span>
                      </div>
                      <div className="bar" style={{background:col, opacity: isNew?1:0.9}} />
                      <div className="main">
                        <div className="t" style={{display:"flex", gap:6, alignItems:"flex-start"}}>
                          <span style={{flex:1}}>{r.title}</span>
                          {isNew && <span style={{background:"var(--vermillion)", color:"#fff", font:"700 8px var(--mono)", padding:"2px 5px", borderRadius:6, flex:"none"}}>NEU</span>}
                        </div>
                        <div className="m">
                          <span style={{color:col, fontWeight:800}}>{(categories as any)[r.category]?.label ?? r.category}</span>
                          <span>• {r.status}</span>
                          <span>• {country}</span>
                        </div>
                        {r.place && <div style={{font:"11px var(--sans)", color:"var(--muted)", marginTop:2, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis"}}>{r.place}</div>}
                      </div>
                      <div className="evid" style={{background: r.url? "var(--ink)":"var(--paper-2)", color: r.url? "#fff":"var(--steel)"}}>{r.url ? "↗" : "·"}</div>
                    </div>
                  )
                })}
              </div>
            </>
          )}

          {ledgerTab==="laws" && (
            <div style={{flex:1, overflowY:"auto", padding:"12px", background:"var(--paper)"}}>
              <div style={{font:"10px var(--mono)", letterSpacing:".12em", textTransform:"uppercase", color:"var(--faint)", marginBottom:8}}>StGB • Laws that may apply • {Array.isArray(laws) ? laws.length : 10} statutes</div>
              {laws.map((l:any)=>(
                <div key={l.code} style={{border:"1px solid var(--line)", borderRadius:10, padding:"12px", marginBottom:8, background:"#fff"}}>
                  <div style={{font:"800 11px var(--mono)", color:"var(--vermillion)"}}>{l.code}</div>
                  <div style={{font:"700 14px var(--sans)", marginTop:4}}>{l.title}</div>
                  {l.summary && <div style={{font:"13px var(--sans)", color:"var(--muted)", marginTop:6, lineHeight:1.5}}>{l.summary}</div>}
                  {l.penalty && <div style={{font:"12px var(--sans)", color:"var(--faint)", fontStyle:"italic", marginTop:6}}>{l.penalty}</div>}
                </div>
              ))}
              {!laws.length && <div style={{font:"12px var(--sans)", color:"var(--faint)", textAlign:"center", padding:20}}>Laws loading…</div>}
            </div>
          )}

          {ledgerTab==="awareness" && (
            <div style={{flex:1, overflowY:"auto", background:"var(--paper)"}}>
              <div style={{padding:"14px 12px", borderBottom:"1px solid var(--line-2)"}}>
                <div style={{font:"800 9px var(--mono)", letterSpacing:".12em", textTransform:"uppercase", color:"var(--vermillion)"}}>{aw.eyebrow}</div>
                <h3 style={{margin:"4px 0 6px", font:"800 16px var(--display)"}}>{aw.h1}</h3>
                <p style={{margin:0, font:"13px var(--sans)", color:"var(--muted)", lineHeight:1.5}}>{aw.lede}</p>
              </div>
              <div style={{padding:"10px 12px"}}>
                <div style={{background:"var(--paper-2)", border:"1px solid var(--line-2)", borderRadius:10, padding:"10px 12px", marginBottom:10}}>
                  <div style={{font:"800 10px var(--mono)", color:"var(--ink)"}}>{aw.whyTitle}</div>
                  <div style={{font:"12px var(--sans)", color:"var(--muted)", marginTop:4, lineHeight:1.5}}>{aw.whyBody}</div>
                </div>
                <div style={{font:"800 10px var(--mono)", letterSpacing:".12em", textTransform:"uppercase", color:"var(--faint)", marginBottom:6}}>{aw.symbolsEyebrow} • {aw.symbolsTitle}</div>
                <div style={{font:"12px var(--sans)", color:"var(--muted)", marginBottom:8}}>{aw.symbolsLede}</div>
                {aw.symbols.map((s:any)=>(
                  <div key={s.title} style={{border:"1px solid var(--line)", borderRadius:10, padding:"10px 12px", marginBottom:8, background:"#fff"}}>
                    <div style={{font:"800 10px var(--mono)", color:"var(--vermillion)"}}>{s.code}</div>
                    <div style={{font:"700 13px var(--sans)", marginTop:4}}>{s.title}</div>
                    <div style={{font:"12px var(--sans)", color:"var(--muted)", marginTop:4, lineHeight:1.5}}>{s.body}</div>
                  </div>
                ))}
                <div style={{font:"800 10px var(--mono)", letterSpacing:".12em", textTransform:"uppercase", color:"var(--faint)", margin:"12px 0 6px"}}>{aw.codesTitle}</div>
                <div style={{display:"grid", gridTemplateColumns:"1fr 1fr", gap:8}}>
                  {aw.codes.map((c:any)=>(
                    <div key={c.k} style={{border:"1px solid var(--line)", borderRadius:10, padding:"10px 12px", background:"var(--paper-2)"}}>
                      <div style={{font:"800 18px var(--mono)"}}>{c.k}</div>
                      <div style={{font:"12px var(--sans)", color:"var(--muted)", marginTop:4}}>{c.v}</div>
                    </div>
                  ))}
                </div>
                <div style={{marginTop:12, padding:"10px 12px", background:"var(--ink)", color:"var(--paper)", borderRadius:10}}>
                  <div style={{font:"800 10px var(--mono)", letterSpacing:".1em", textTransform:"uppercase", color:"rgba(255,254,248,.7)"}}>{aw.orgEyebrow}</div>
                  <div style={{font:"700 13px var(--sans)", marginTop:4}}>{aw.orgTitle}</div>
                  <div style={{font:"12px var(--sans)", color:"rgba(255,254,248,.72)", marginTop:4, lineHeight:1.5}}>{aw.orgBody}</div>
                  <a href="https://www.verfassungsschutz.de" target="_blank" rel="noreferrer" style={{display:"inline-block", marginTop:8, font:"700 11px var(--mono)", color:"var(--paper)", textDecoration:"none", border:"1px solid rgba(255,254,248,.22)", padding:"6px 10px", borderRadius:8}}>{aw.orgLink}</a>
                </div>
                <div style={{marginTop:10, padding:"10px 12px", background:"rgba(225,29,45,.06)", border:"1px solid rgba(225,29,45,.14)", borderRadius:10}}>
                  <div style={{font:"800 10px var(--mono)", color:"var(--vermillion)"}}>{aw.safetyTitle}</div>
                  <div style={{font:"12px var(--sans)", color:"var(--muted)", marginTop:4}}>{aw.safetyBody}</div>
                  <button onClick={()=> setShowReport(true)} style={{marginTop:8, font:"700 11px var(--mono)", padding:"6px 10px", borderRadius:8, border:"1px solid var(--vermillion)", background:"var(--vermillion)", color:"#fff", cursor:"pointer"}}>{aw.fileBtn}</button>
                </div>
              </div>
            </div>
          )}

          {ledgerTab==="volunteer" && (
            <div style={{flex:1, overflowY:"auto", padding:"12px", background:"var(--paper)"}}>
              <h3 style={{margin:"0 0 6px", font:"800 16px var(--display)"}}>Get involved • Mitwirken</h3>
              <p style={{margin:"0 0 12px", font:"13px var(--sans)", color:"var(--muted)", lineHeight:1.5}}>This gets more useful with more hands — moderators, translators, developers, partner organizations worldwide.</p>
              <a href="https://nabilvs.com/projects/discrimination-map#get-involved" target="_blank" rel="noreferrer" style={{display:"block", padding:"12px", border:"1px solid var(--line)", borderRadius:10, background:"var(--paper-2)", textDecoration:"none", color:"var(--ink)", font:"600 13px var(--sans)", marginBottom:8}}>Volunteer, translate, code, or partner as an organization →</a>
              <a href="/guide" style={{display:"block", padding:"12px", border:"1px solid var(--line)", borderRadius:10, textDecoration:"none", color:"var(--ink)", font:"600 13px var(--sans)", marginBottom:8}}>New volunteer? Read the step-by-step guide →</a>
              <button onClick={()=> setShowHunt(true)} style={{display:"block", width:"100%", padding:"12px", border:"1px solid var(--line)", borderRadius:10, background:"#fff", font:"600 13px var(--sans)", cursor:"pointer", textAlign:"left", marginBottom:8}}>Spot a banned symbol? Become a symbol hunter →</button>
              <a href="/admin" style={{display:"block", padding:"12px", border:"1px solid var(--line)", borderRadius:10, textDecoration:"none", color:"var(--ink)", font:"600 13px var(--sans)", marginBottom:8}}>Reviewer or admin? Go to /admin →</a>
              <button onClick={()=> setShowAbout(true)} style={{display:"block", width:"100%", padding:"12px", border:"1px dashed var(--hair)", borderRadius:10, background:"var(--paper-2)", font:"600 13px var(--sans)", cursor:"pointer", textAlign:"left"}}>What is this? Read the mission →</button>
              <div style={{marginTop:12, padding:"10px 12px", background:"var(--paper-2)", borderRadius:10, font:"11px var(--sans)", color:"var(--muted)", lineHeight:1.5}}>
                <b style={{color:"var(--ink)"}}>Documentation, not accusation.</b> Every mark is a sourced lead — never a verdict. Unschuldsvermutung worldwide.
              </div>
            </div>
          )}

          <div style={{padding:"10px 12px", borderTop:"1px solid var(--line-2)", background:"var(--paper-2)", display:"flex", gap:10, flexWrap:"wrap", justifyContent:"space-between", alignItems:"center"}}>
            <span style={{font:"800 9px var(--mono)", letterSpacing:".1em", textTransform:"uppercase", color:"var(--faint)"}}>
              DISCRIMINATION MAP • {stats.countries} Länder • {stats.total} Akten
            </span>
            <span style={{display:"flex", gap:8, font:"700 10px var(--mono)"}}>
              <a href="/privacy" style={{color:"var(--faint)"}}>Privacy</a>
              <a href="/terms" style={{color:"var(--faint)"}}>Terms</a>
              <button onClick={()=> setShowAbout(true)} style={{background:"none", border:0, color:"var(--vermillion)", font:"700 10px var(--mono)", cursor:"pointer"}}>About →</button>
            </span>
          </div>
        </div>
      </div>

      <nav className="bottomnav">
        <button className={mobileTab==="map"?"active":""} onClick={()=> setMobileTab("map")}>◍ Weltkarte</button>
        <button className={mobileTab==="ledger"?"active":""} onClick={()=> setMobileTab("ledger")}>☰ Ledger ({filtered.length})</button>
        <button onClick={()=> setShowReport(true)} style={{color:"var(--vermillion)", fontWeight:700}}>+ Melden</button>
        <button onClick={quickExit} style={{color:"var(--ink)"}}>✕ Exit</button>
      </nav>

      <span style={{display:"none"}}>{t("brand.title")}</span>
      <button className="fab" onClick={()=> setShowReport(true)} style={{position:"fixed"}}>
        <span style={{fontSize:16, lineHeight:0}}>+</span> Vorfall melden
      </button>

      {selected && (
        <>
          <div className="sheet-backdrop" onClick={()=> setSelected(null)} />
          <aside className="sheet" role="dialog" aria-label={selected.title} style={{maxHeight:"78vh"}}>
            <div className="sheet-head">
              <div style={{minWidth:0, flex:1}}>
                <div style={{font:"800 9px var(--mono)", letterSpacing:".14em", textTransform:"uppercase", color:"var(--faint)", display:"flex", gap:8, flexWrap:"wrap"}}>
                  <span>AKTE #{String(selected.id).padStart(4,"0")}</span>
                  <span>• {new Date(selected.created_at*1000).toLocaleString("de-DE")}</span>
                  <span>• {selected.place ?? "WELT"}</span>
                </div>
                <h3 style={{margin:"6px 0 6px", font:"800 19px var(--display)", lineHeight:1.2}}>{selected.title}</h3>
                <div style={{display:"flex", gap:6, flexWrap:"wrap", alignItems:"center"}}>
                  <span className={`badge ${selected.status==="verified"?"ok":selected.status==="unverified"?"lead":"user"}`}>{selected.status}</span>
                  <span style={{font:"800 10px var(--mono)", letterSpacing:".08em", textTransform:"uppercase", color:"var(--faint)"}}>
                    {(categories as any)[selected.category]?.label ?? selected.category} • {selected.fuzzed?"~5km weltweit gefuzzt":"exakt"}
                  </span>
                </div>
              </div>
              <button onClick={()=> setSelected(null)} style={{background:"var(--paper-2)", border:"1px solid var(--line)", borderRadius:8, width:32, height:32, cursor:"pointer", flex:"none"}}>✕</button>
            </div>
            <div className="sheet-body">
              <p style={{margin:"0 0 12px", color:"var(--ink)", fontSize:14, lineHeight:1.6}}>{(selected as any).body ?? (selected as any).summary ?? selected.title}</p>
              {selected.reason && <div style={{marginBottom:12}}><div style={{font:"800 10px var(--mono)", letterSpacing:".12em", textTransform:"uppercase", color:"var(--faint)", marginBottom:6}}>Erkennungsgrund</div><div style={{background:"var(--paper-2)", border:"1px solid var(--line-2)", borderRadius:10, padding:"10px 12px", fontSize:13}}>{selected.reason}</div></div>}
              <div style={{display:"grid", gridTemplateColumns:"1fr 1fr", gap:8, marginBottom:12}}>
                <div style={{background:"var(--paper-2)", border:"1px solid var(--line-2)", borderRadius:10, padding:"10px 12px"}}>
                  <div style={{font:"800 9px var(--mono)", letterSpacing:".1em", textTransform:"uppercase", color:"var(--faint)"}}>WELT-ORT</div>
                  <div style={{marginTop:6, font:"600 13px var(--sans)"}}>{selected.place ?? "Unverortet"}</div>
                  <div style={{marginTop:4, font:"11px var(--mono)", color:"var(--muted)"}}>{selected.lat!=null && selected.lon!=null ? `${Number(selected.lat).toFixed(3)}, ${Number(selected.lon).toFixed(3)}` : "—"} • {selected.fuzzed?"gefuzzt":"exakt"}</div>
                  {selected.lat!=null && <button onClick={()=> setFocus({lat: Number(selected.lat), lon: Number(selected.lon), zoom:4.5})} style={{marginTop:8, font:"700 10px var(--mono)", padding:"6px 8px", borderRadius:7, border:"1px solid var(--line)", background:"#fff", cursor:"pointer"}}>Auf Weltkarte zeigen →</button>}
                </div>
                <div style={{background:"var(--paper-2)", border:"1px solid var(--line-2)", borderRadius:10, padding:"10px 12px"}}>
                  <div style={{font:"800 9px var(--mono)", letterSpacing:".1em", textTransform:"uppercase", color:"var(--faint)"}}>RECHT</div>
                  <div style={{marginTop:6, font:"600 13px var(--sans)"}}>{(selected as any).law ?? (selected as any).statute_code ?? <span style={{color:"var(--faint)", fontWeight:400}}>Kein StGB-Vorschlag</span>}</div>
                </div>
              </div>
              {selected.impact && <div style={{background:"rgba(225,29,45,.06)", border:"1px solid rgba(225,29,45,.14)", borderRadius:10, padding:"10px 12px", marginBottom:12}}><div style={{font:"800 10px var(--mono)", letterSpacing:".1em", textTransform:"uppercase", color:"var(--vermillion)", marginBottom:6}}>Auswirkung</div><div style={{fontSize:13, lineHeight:1.5}}>{selected.impact}</div></div>}
              {selected.evidence && <div style={{background:"var(--paper-2)", borderLeft:"3px solid var(--hair)", padding:"10px 12px", borderRadius:"0 10px 10px 0", fontStyle:"italic", color:"var(--muted)", marginBottom:12, fontSize:13}}>{selected.evidence}</div>}
              <div style={{display:"flex", gap:8}}>
                <button onClick={()=> { if(selected.url) window.open(selected.url, "_blank") }} disabled={!selected.url} className="btn primary" style={{flex:1}}>Quelle öffnen ↗</button>
                <button onClick={()=> setSelected(null)} className="btn" style={{flex:1}}>Schließen</button>
              </div>
            </div>
          </aside>
        </>
      )}

      {showReport && (
        <div className="modal-scrim" onClick={()=> setShowReport(false)}>
          <div className="modal" onClick={e=> e.stopPropagation()}>
            <div style={{font:"800 9px var(--mono)", letterSpacing:".14em", textTransform:"uppercase", color:"var(--vermillion)"}}>WELTWEIT • AKTE ANLEGEN</div>
            <h2 style={{margin:"6px 0 6px", font:"800 20px var(--display)"}}>Vorfall weltweit melden</h2>
            <p style={{margin:0, color:"var(--muted)", fontSize:13, lineHeight:1.55}}>Anonym, ohne Konto, weltweit. Mit belastbarer Quelle erscheint der Eintrag direkt als “unverified lead”, sonst erst nach Prüfung. Keine Namen von Privatpersonen — weltweit gültig.</p>
            <div className="btnrow" style={{marginTop:14}}>
              <button className="btn" onClick={()=> setShowReport(false)}>Abbrechen</button>
              <a className="btn primary" href="http://127.0.0.1:8020/" target="_blank" rel="noreferrer" style={{textDecoration:"none", display:"inline-flex", alignItems:"center"}}>Weltweit melden →</a>
            </div>
          </div>
        </div>
      )}

      {showHunt && (
        <div className="modal-scrim" onClick={()=> setShowHunt(false)}>
          <div className="modal" onClick={e=> e.stopPropagation()}>
            <h2 style={{margin:"0 0 6px", font:"800 20px var(--display)"}}>Symbol hunters</h2>
            <p style={{margin:0, color:"var(--muted)", fontSize:13, lineHeight:1.5}}>Banned symbols — swastikas, SS runes, 88/18 codes — show up as graffiti constantly and mostly go undocumented. Photograph from public space, don't confront, report to city, file here with photo link.</p>
            <div className="btnrow" style={{marginTop:12}}>
              <button className="btn" onClick={()=> setShowHunt(false)}>Schließen</button>
              <button className="btn primary" onClick={()=> { setShowHunt(false); setShowReport(true); }}>Melden →</button>
            </div>
          </div>
        </div>
      )}

      {showAbout && (
        <div className="modal-scrim" onClick={()=> setShowAbout(false)}>
          <div className="modal" onClick={e=> e.stopPropagation()}>
            <h2 style={{margin:"0 0 6px", font:"800 20px var(--display)"}}>What this is</h2>
            <p style={{margin:0, color:"var(--muted)", fontSize:13, lineHeight:1.5}}>Hate incidents don't stop being real when the news cycle moves on. This is where the pattern stays visible — worldwide. Documentation, not accusation. Unschuldsvermutung.</p>
            <div style={{display:"flex", gap:8, marginTop:12, flexWrap:"wrap"}}>
              <a className="btn" href="/guide" style={{textDecoration:"none", textAlign:"center"}}>Guide</a>
              <a className="btn" href="/privacy" style={{textDecoration:"none", textAlign:"center"}}>Privacy</a>
              <a className="btn" href="/terms" style={{textDecoration:"none", textAlign:"center"}}>Terms</a>
            </div>
            <div className="btnrow" style={{marginTop:12}}>
              <button className="btn" onClick={()=> setShowAbout(false)}>Schließen</button>
              <a className="btn primary" href="/awareness" style={{textDecoration:"none", textAlign:"center"}}>Awareness →</a>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
