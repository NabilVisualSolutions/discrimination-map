import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { api, ApiError, type CategoryMeta, type NewReport } from "../../lib/api"
import { rememberReport } from "../../lib/mine"

// Anonymous incident report — no account. New reports POST to /api/reports;
// the same device can edit for one hour (token kept in localStorage, window
// enforced by the backend). One or more categories. The reporter can set
// when the incident happened (past events allowed). Sensitive categories
// get an explicit consent gate. Fully localised (en/de/fr/ar).

const SENSITIVE = new Set(["sexual_violence", "harassment"])
type Step = "form" | "done"
type Picked = { lat: number; lon: number; label: string }

function toLocalInput(d: Date) {
  const p = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}

export function ReportModal({
  categories,
  editId,
  editToken,
  presetLat,
  presetLon,
  onClose,
  onSaved,
}: {
  categories: Record<string, CategoryMeta>
  editId?: number
  editToken?: string
  presetLat?: number
  presetLon?: number
  onClose: () => void
  onSaved?: () => void
}) {
  const { t } = useTranslation()
  const isEdit = !!editId && !!editToken

  const [step, setStep] = useState<Step>("form")
  const [loading, setLoading] = useState(isEdit)
  const [cats, setCats] = useState<Set<string>>(() => new Set())
  const [title, setTitle] = useState("")
  const [reason, setReason] = useState("")
  const [evidence, setEvidence] = useState("")
  const [impact, setImpact] = useState("")
  const [occurred, setOccurred] = useState(() => toLocalInput(new Date()))
  const [placeQ, setPlaceQ] = useState("")
  const [hits, setHits] = useState<Picked[]>([])
  const [geoBusy, setGeoBusy] = useState(false)
  const [picked, setPicked] = useState<Picked | null>(
    presetLat != null && presetLon != null
      ? { lat: presetLat, lon: presetLon, label: `${presetLat.toFixed(4)}, ${presetLon.toFixed(4)}` }
      : null
  )
  const [sensitiveOk, setSensitiveOk] = useState(false)
  const [err, setErr] = useState("")
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<{ id: number; status: string; edit_token: string } | null>(null)

  const isSensitive = [...cats].some((c) => SENSITIVE.has(c))
  const catEntries = useMemo(
    () => Object.entries(categories).sort((a, b) => a[1].label.localeCompare(b[1].label)),
    [categories]
  )
  const toggleCat = (k: string) =>
    setCats((s) => {
      const n = new Set(s)
      n.has(k) ? n.delete(k) : n.add(k)
      return n
    })

  useEffect(() => {
    if (!isEdit) return
    let cancelled = false
    ;(async () => {
      try {
        const r = await api.ownReport(editId!, editToken!)
        if (cancelled) return
        setCats(new Set(r.category.split(/[,|/]/).map((s) => s.trim()).filter(Boolean)))
        setTitle(r.title)
        setReason(r.reason ?? "")
        setEvidence(r.evidence ?? "")
        setImpact(r.impact ?? "")
        if (r.occurred_at) setOccurred(toLocalInput(new Date(r.occurred_at * 1000)))
        if (r.lat != null && r.lon != null)
          setPicked({ lat: r.lat, lon: r.lon, label: r.place || `${r.lat.toFixed(3)}, ${r.lon.toFixed(3)}` })
      } catch {
        if (!cancelled) setErr(t("rm.loadErr"))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [isEdit, editId, editToken, t])

  const geocode = async () => {
    if (placeQ.trim().length < 2) return
    setGeoBusy(true)
    setErr("")
    try {
      setHits((await api.geocode(placeQ.trim())).slice(0, 6))
    } catch {
      setErr(t("rm.errGeo"))
    } finally {
      setGeoBusy(false)
    }
  }

  const useMyLocation = () => {
    if (!navigator.geolocation) return
    navigator.geolocation.getCurrentPosition(
      (p) => setPicked({ lat: p.coords.latitude, lon: p.coords.longitude, label: t("rm.myLoc") }),
      () => setErr(t("rm.errLoc")),
      { enableHighAccuracy: true }
    )
  }

  const occurredTs = Math.floor(new Date(occurred).getTime() / 1000)
  const occurredValid = Number.isFinite(occurredTs) && occurredTs <= Math.floor(Date.now() / 1000) + 86400

  const canSubmit =
    cats.size > 0 &&
    title.trim().length >= 3 &&
    reason.trim().length >= 3 &&
    !!picked &&
    occurredValid &&
    (!isSensitive || sensitiveOk)

  const submit = async () => {
    if (!canSubmit || !picked) return
    setBusy(true)
    setErr("")
    const categoryStr = [...cats].join(",")
    try {
      if (isEdit) {
        await api.editOwnReport(editId!, editToken!, {
          title: title.trim(),
          reason: reason.trim(),
          evidence: evidence.trim() || undefined,
          impact: impact.trim() || undefined,
          category: categoryStr,
        })
        setResult({ id: editId!, status: "updated", edit_token: editToken! })
      } else {
        const payload: NewReport = {
          title: title.trim(),
          reason: reason.trim(),
          evidence: evidence.trim() || undefined,
          impact: impact.trim() || undefined,
          category: categoryStr,
          lat: picked.lat,
          lon: picked.lon,
          occurred_at: occurredTs,
        }
        const r = await api.createReport(payload)
        rememberReport(r.id, r.edit_token)
        setResult(r)
      }
      setStep("done")
      onSaved?.()
    } catch (e) {
      setErr(
        e instanceof ApiError && e.status === 409 && isEdit
          ? t("rm.errWindowClosed")
          : e instanceof ApiError && e.status === 409
            ? t("rm.errDup")
            : e instanceof ApiError
              ? e.message
              : t("rm.errGeneric")
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
            <div className="rm-kicker rm-kicker-ok">
              {t("rm.doneKicker", { id: String(result.id).padStart(4, "0") })}
            </div>
            <h2 className="rm-h2">{isEdit ? t("rm.doneEdit") : t("rm.doneNew")}</h2>
            <p className="rm-p">
              {result.status === "pending" ? t("rm.doneBodyPending") : t("rm.doneBodyLead")} {t("rm.doneFuzz")}
            </p>
            {!isEdit && (
              <div className="rm-token">
                <div className="rm-token-h">{t("rm.editLinkLabel")}</div>
                {`${location.origin}/?report=${result.id}&token=${result.edit_token}`}
              </div>
            )}
            <div className="btnrow" style={{ marginTop: 14 }}>
              <button className="btn primary" onClick={onClose}>{t("rm.close")}</button>
            </div>
          </>
        ) : loading ? (
          <p className="rm-p">{t("rm.loading")}</p>
        ) : (
          <>
            <div className="rm-kicker">{isEdit ? t("rm.badgeEditMode") : t("rm.badgeNew")}</div>
            <h2 className="rm-h2">{isEdit ? t("rm.titleEdit") : t("rm.titleNew")}</h2>
            <p className="rm-p">{isEdit ? t("rm.editWindowNote") : t("rm.intro")}</p>

            <div className="field">
              <label>{t("rm.cat")} <span className="rm-hint">{t("rm.catMulti")}</span></label>
              <div className="rm-catgrid">
                {catEntries.map(([k, m]) => (
                  <label key={k} className={`rm-catopt${cats.has(k) ? " on" : ""}`}>
                    <input type="checkbox" checked={cats.has(k)} onChange={() => toggleCat(k)} />
                    <span className="dot" style={{ background: m.color }} />
                    {m.label}
                  </label>
                ))}
              </div>
            </div>

            {isSensitive && (
              <div className="rm-consent">
                <b>{t("rm.sensitiveTitle")}</b> {t("rm.sensitiveBody")}
                <label className="rm-consent-row">
                  <input type="checkbox" checked={sensitiveOk} onChange={(e) => setSensitiveOk(e.target.checked)} />
                  {t("rm.sensitiveOk")}
                </label>
              </div>
            )}

            <div className="field">
              <label>{t("rm.fTitle")}</label>
              <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t("rm.fTitlePh")} maxLength={300} />
            </div>
            <div className="field">
              <label>{t("rm.fWhat")}</label>
              <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} maxLength={500} placeholder={t("rm.fWhatPh")} />
            </div>

            <div className="field">
              <label>{t("rm.fWhen")} <span className="rm-hint">{t("rm.fWhenHint")}</span></label>
              <input
                type="datetime-local"
                value={occurred}
                max={toLocalInput(new Date())}
                onChange={(e) => setOccurred(e.target.value)}
              />
            </div>

            <div className="field">
              <label>{t("rm.fWhere")}</label>
              {isEdit ? (
                <div className="rm-picked">
                  <span className="rm-tick">✓</span>
                  <span style={{ flex: 1 }}>{picked?.label ?? "—"}</span>
                  <span className="rm-p" style={{ margin: 0, fontSize: 11 }}>{t("rm.locLocked")}</span>
                </div>
              ) : (
                <>
                  {picked && (presetLat != null || picked.label === t("rm.myLoc")) && (
                    <p className="rm-hint" style={{ marginBottom: 6 }}>{t("rm.pinnedNote")}</p>
                  )}
                  <div style={{ display: "flex", gap: 6 }}>
                    <input
                      value={placeQ}
                      onChange={(e) => setPlaceQ(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), geocode())}
                      placeholder={t("rm.fWherePh")}
                    />
                    <button type="button" className="btn" onClick={geocode} disabled={geoBusy}>
                      {geoBusy ? "…" : t("rm.search")}
                    </button>
                    <button type="button" className="btn" onClick={useMyLocation} title={t("rm.myLoc")}>
                      ◎
                    </button>
                  </div>
                  {hits.length > 0 && (
                    <div className="rm-hits">
                      {hits.map((h) => (
                        <button
                          key={h.label + h.lat}
                          type="button"
                          onClick={() => {
                            setPicked(h)
                            setHits([])
                          }}
                        >
                          {h.label}
                        </button>
                      ))}
                    </div>
                  )}
                  {picked && (
                    <div className="rm-picked">
                      <span className="rm-tick">✓</span>
                      <span style={{ flex: 1 }}>{picked.label}</span>
                      <button type="button" className="btn" style={{ padding: "4px 8px" }} onClick={() => setPicked(null)}>
                        {t("rm.change")}
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>

            <div className="field">
              <label>{t("rm.fEvidence")}</label>
              <input value={evidence} onChange={(e) => setEvidence(e.target.value)} placeholder={t("rm.fEvidencePh")} maxLength={1000} />
            </div>
            <div className="field">
              <label>{t("rm.fImpact")}</label>
              <input value={impact} onChange={(e) => setImpact(e.target.value)} placeholder={t("rm.fImpactPh")} maxLength={1000} />
            </div>

            {err && <p className="rm-err">{err}</p>}

            <div className="btnrow" style={{ marginTop: 8 }}>
              <button className="btn" onClick={onClose}>{t("rm.cancel")}</button>
              <button className="btn primary" onClick={submit} disabled={!canSubmit || busy}>
                {busy ? t("rm.sending") : isEdit ? t("rm.submitEdit") : t("rm.submitNew")}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
