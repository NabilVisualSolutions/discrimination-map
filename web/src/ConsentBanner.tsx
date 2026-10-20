import { useState } from "react"
import { useTranslation } from "react-i18next"
import { analyticsAvailable, getConsent, setConsent } from "./lib/analytics"

// Shown once, only when analytics exist and no choice was made. "Decline" is as
// easy as "Accept" (same size, same place).
export function ConsentBanner() {
  const { t } = useTranslation()
  const [choice, setChoice] = useState(getConsent())
  if (!analyticsAvailable || choice) return null
  const pick = (v: "granted" | "denied") => {
    setConsent(v)
    setChoice(v)
  }
  return (
    <div className="consent" role="dialog" aria-label={t("consent.title")}>
      <p>
        <strong>{t("consent.title")}</strong> {t("consent.body")}{" "}
        <a href="/privacy" target="_blank" rel="noreferrer">{t("consent.more")}</a>
      </p>
      <div className="consent-actions">
        <button className="btn" onClick={() => pick("denied")}>{t("consent.decline")}</button>
        <button className="btn" onClick={() => pick("granted")}>{t("consent.accept")}</button>
      </div>
    </div>
  )
}
