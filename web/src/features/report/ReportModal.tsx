import { useState } from "react"
import { api, ApiError, type CategoryMeta, type NewReport } from "../../lib/api"

// A real report form (the Signal Atlas rewrite had stubbed this to a dead
// localhost link). Anonymous, no account. POSTs to /api/reports; the
// backend holds it as `pending` until a moderator reviews it unless a real
// source URL is given, and fuzzes the public location. Sensitive
// categories get an explicit consent gate.

const SENSITIVE = new Set(["sexual_violence", "harassment"])

type Step = "form" | "done"

export function ReportModal({
  categories,
  onClose,
}: {
  categories: Record<string, CategoryMeta>
  onClose: () => void
}) {
  const [step, setStep] = useState<Step>("form")
  const [category, setCategory] = useState("")
  const [title, setTitle] = useState("")
  const [reason, setReason] = useState("")
  const [evidence, setEvidence] = useState("")
  const [impact, setImpact] = useState("")
  const [placeQ, setPlaceQ] = useState("")
  const [hits, setHits] = useState<{ lat: number; lon: number; label: string }[]>([])
  const [geoBusy, setGeoBusy] = useState(false)
  const [picked, setPicked] = useState<{ lat: number; lon: number; label: string } | null>(null)
  const [sensitiveOk, setSensitiveOk] = useState(false)
  const [err, setErr] = useState("")
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<{ id: number; status: string; edit_token: string } | null>(null)

  const isSensitive = SENSITIVE.has(category)
  const catEntries = Object.entries(categories).sort((a, b) => a[1].label.localeCompare(b[1].label))

  const geocode = async () => {
    if (placeQ.trim().length < 2) return
    setGeoBusy(true)
    setErr("")
    try {
      setHits((await api.geocode(placeQ.trim())).slice(0, 6))
    } catch {
      setErr("Ortssuche nicht verfügbar — bitte später erneut versuchen.")
    } finally {
      setGeoBusy(false)
    }
  }

  const useMyLocation = () => {
    if (!navigator.geolocation) return
    navigator.geolocation.getCurrentPosition(
      (p) => setPicked({ lat: p.coords.latitude, lon: p.coords.longitude, label: "Mein Standort" }),
      () => setErr("Standort nicht verfügbar."),
      { enableHighAccuracy: true }
    )
  }

  const canSubmit =
    !!category &&
    title.trim().length >= 3 &&
    reason.trim().length >= 3 &&
    !!picked &&
    (!isSensitive || sensitiveOk)

  const submit = async () => {
    if (!canSubmit || !picked) return
    setBusy(true)
    setErr("")
    const payload: NewReport = {
      title: title.trim(),
      reason: reason.trim(),
      evidence: evidence.trim() || undefined,
      impact: impact.trim() || undefined,
      category,
      lat: picked.lat,
      lon: picked.lon,
    }
    try {
      const r = await api.createReport(payload)
      setResult(r)
      setStep("done")
    } catch (e) {
      setErr(
        e instanceof ApiError && e.status === 409
          ? "Dieser Vorfall scheint bereits gemeldet zu sein."
          : e instanceof ApiError
            ? e.message
            : "Konnte nicht gesendet werden. Bitte erneut versuchen."
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 560 }}>
        {step === "done" && result ? (
          <>
            <div style={{ font: "800 9px var(--mono)", letterSpacing: ".14em", textTransform: "uppercase", color: "var(--mint)" }}>
              Akte #{String(result.id).padStart(4, "0")} angelegt
            </div>
            <h2 style={{ margin: "6px 0 8px", font: "800 20px var(--display)" }}>Danke — Ihr Bericht ist eingegangen.</h2>
            <p style={{ margin: 0, color: "var(--muted)", fontSize: 13, lineHeight: 1.6 }}>
              {result.status === "pending"
                ? "Er wird von einer Person geprüft, bevor er öffentlich auf der Karte erscheint."
                : "Er erscheint als unbestätigter Hinweis auf der Karte."}{" "}
              Der genaue Ort wird für die Öffentlichkeit unscharf angezeigt.
            </p>
            <div
              style={{
                marginTop: 12,
                background: "var(--paper-2)",
                border: "1px solid var(--line-2)",
                borderRadius: 10,
                padding: "10px 12px",
                font: "11px var(--mono)",
                wordBreak: "break-all",
              }}
            >
              <div style={{ color: "var(--faint)", marginBottom: 4, letterSpacing: ".1em", textTransform: "uppercase" }}>
                Bearbeitungs-Link — speichern, um Ihren Bericht später zu ändern
              </div>
              {`${location.origin}/?report=${result.id}&token=${result.edit_token}`}
            </div>
            <div className="btnrow" style={{ marginTop: 14 }}>
              <button className="btn primary" onClick={onClose}>
                Schließen
              </button>
            </div>
          </>
        ) : (
          <>
            <div style={{ font: "800 9px var(--mono)", letterSpacing: ".14em", textTransform: "uppercase", color: "var(--vermillion)" }}>
              Weltweit • Akte anlegen
            </div>
            <h2 style={{ margin: "6px 0 4px", font: "800 20px var(--display)" }}>Vorfall melden</h2>
            <p style={{ margin: "0 0 10px", color: "var(--muted)", fontSize: 12.5, lineHeight: 1.5 }}>
              Anonym, ohne Konto. Dokumentation, nicht Anklage — keine Namen von Privatpersonen. Notfall: Polizei 110.
            </p>

            <div className="field">
              <label>Kategorie</label>
              <select value={category} onChange={(e) => setCategory(e.target.value)}>
                <option value="">— wählen —</option>
                {catEntries.map(([k, m]) => (
                  <option key={k} value={k}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>

            {isSensitive && (
              <div
                style={{
                  background: "rgba(225,29,45,.06)",
                  border: "1px solid rgba(225,29,45,.2)",
                  borderRadius: 10,
                  padding: "10px 12px",
                  marginBottom: 12,
                  fontSize: 12.5,
                  lineHeight: 1.5,
                  color: "var(--ink)",
                }}
              >
                <b>Besonders schützenswert.</b> Dieser Bericht geht nicht direkt auf die öffentliche Karte — eine Person prüft ihn zuerst,
                und der Ort wird weiträumig (~5 km) unscharf gemacht. Bitte keine identifizierenden Details zu Betroffenen.
                <label style={{ display: "flex", gap: 8, marginTop: 8, font: "12px var(--sans)", textTransform: "none", letterSpacing: 0, color: "var(--ink)" }}>
                  <input type="checkbox" checked={sensitiveOk} onChange={(e) => setSensitiveOk(e.target.checked)} />
                  Ich habe das verstanden.
                </label>
              </div>
            )}

            <div className="field">
              <label>Titel</label>
              <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Kurz: was ist passiert?" maxLength={300} />
            </div>
            <div className="field">
              <label>Was ist passiert?</label>
              <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} maxLength={500} placeholder="Sachlich beschreiben. Angeblich, nicht bewiesen." />
            </div>

            <div className="field">
              <label>Wo? (Ort, Stadt, Land)</label>
              <div style={{ display: "flex", gap: 6 }}>
                <input
                  value={placeQ}
                  onChange={(e) => setPlaceQ(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), geocode())}
                  placeholder="z. B. Alexanderplatz, Berlin"
                />
                <button type="button" className="btn" onClick={geocode} disabled={geoBusy}>
                  {geoBusy ? "…" : "Suchen"}
                </button>
                <button type="button" className="btn" onClick={useMyLocation} title="Meinen Standort verwenden">
                  ◎
                </button>
              </div>
              {hits.length > 0 && !picked && (
                <div style={{ border: "1px solid var(--line)", borderRadius: 10, overflow: "hidden", marginTop: 6 }}>
                  {hits.map((h) => (
                    <button
                      key={h.label + h.lat}
                      type="button"
                      onClick={() => {
                        setPicked(h)
                        setHits([])
                      }}
                      style={{ display: "block", width: "100%", textAlign: "left", padding: "8px 10px", border: 0, borderBottom: "1px solid var(--line-2)", background: "none", font: "12px var(--sans)", cursor: "pointer" }}
                    >
                      {h.label}
                    </button>
                  ))}
                </div>
              )}
              {picked && (
                <div style={{ marginTop: 6, font: "12px var(--sans)", color: "var(--ink)", display: "flex", gap: 8, alignItems: "center" }}>
                  <span style={{ color: "var(--mint)", fontWeight: 700 }}>✓</span>
                  <span style={{ flex: 1 }}>{picked.label}</span>
                  <button type="button" className="btn" style={{ padding: "4px 8px" }} onClick={() => setPicked(null)}>
                    ändern
                  </button>
                </div>
              )}
            </div>

            <div className="field">
              <label>Beleg (Link oder Beschreibung) — optional</label>
              <input value={evidence} onChange={(e) => setEvidence(e.target.value)} placeholder="Foto-Link, Nachrichtenartikel, Zeugenschilderung…" maxLength={1000} />
            </div>
            <div className="field">
              <label>Auswirkung — optional</label>
              <input value={impact} onChange={(e) => setImpact(e.target.value)} placeholder="Wer war betroffen, welche Folgen?" maxLength={1000} />
            </div>

            {err && <p style={{ color: "var(--vermillion)", fontSize: 12.5, margin: "4px 0" }}>{err}</p>}

            <div className="btnrow" style={{ marginTop: 8 }}>
              <button className="btn" onClick={onClose}>
                Abbrechen
              </button>
              <button className="btn primary" onClick={submit} disabled={!canSubmit || busy}>
                {busy ? "Wird gesendet…" : "Weltweit melden →"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
