import { useState } from "react"
import { useTranslation } from "react-i18next"
import { api } from "../../lib/api"
import { Honeypot, Turnstile, turnstileEnabled } from "../../lib/botguard"

// "Report this entry": anyone can tell us an entry is unlawful or wrong
// (EU DSA Art. 16). It goes to the admin queue; the entry stays until a
// person acts on it.
export function EntryReport({ id }: { id: number }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState("")
  const [email, setEmail] = useState("")
  const [goodFaith, setGoodFaith] = useState(false)
  const [hp, setHp] = useState("")
  const [botToken, setBotToken] = useState<string | null>(null)
  const [widgetKey, setWidgetKey] = useState(0)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState("")
  const [sent, setSent] = useState(false)

  if (sent) return <p className="muted sm entry-sent">{t("entry.sent")}</p>
  if (!open)
    return (
      <button type="button" className="linklike entry-open" onClick={() => setOpen(true)}>
        {t("entry.open")}
      </button>
    )

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setErr("")
    if (reason.trim().length < 10) return setErr(t("entry.short"))
    if (!goodFaith) return setErr(t("entry.needGoodFaith"))
    if (turnstileEnabled && !botToken) return setErr(t("involved.botWait"))
    setBusy(true)
    try {
      await api.reportEntry({ report_id: id, reason: reason.trim(), email: email.trim(), good_faith: true,
        hp_contact: hp, turnstile_token: botToken ?? "" })
      setSent(true)
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : String(e2))
    } finally {
      setBusy(false)
      setBotToken(null)
      setWidgetKey((k) => k + 1)
    }
  }

  return (
    <form className="entry-form" onSubmit={submit}>
      <div className="d-h">{t("entry.title")}</div>
      <label className="sm">
        {t("entry.reasonLabel")}
        <textarea className="field" value={reason} onChange={(e) => setReason(e.target.value)} rows={4} maxLength={2000} required />
      </label>
      <label className="sm">
        {t("entry.emailLabel")}
        <input className="field" type="email" value={email} onChange={(e) => setEmail(e.target.value)} maxLength={200} autoComplete="email" />
      </label>
      <label className="sm entry-check">
        <input type="checkbox" checked={goodFaith} onChange={(e) => setGoodFaith(e.target.checked)} />
        <span>{t("entry.goodFaith")}</span>
      </label>
      <Honeypot value={hp} onChange={setHp} />
      <Turnstile key={widgetKey} onToken={setBotToken} />
      {err && <p className="err sm" role="alert">{err}</p>}
      <div className="d-actions">
        <button className="btn primary" type="submit" disabled={busy}>{busy ? "…" : t("entry.send")}</button>
        <button className="btn" type="button" onClick={() => setOpen(false)}>{t("entry.cancel")}</button>
      </div>
    </form>
  )
}
