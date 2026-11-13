import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import type { Preview } from "../../lib/source-preview"

// Click-to-load source preview. Nothing is requested from the provider until
// the visitor presses the button. A purely visual VHS overlay sits above the
// frame (pointer-events: none, so the frame stays usable) and can be turned off.
export function SourcePreview({ preview, label }: { preview: Preview; label: string }) {
  const { t } = useTranslation()
  const [loaded, setLoaded] = useState(false)
  const [slow, setSlow] = useState(false)
  const [plain, setPlain] = useState(false)

  useEffect(() => {
    if (!loaded) return
    const id = setTimeout(() => setSlow(true), 6000)
    return () => clearTimeout(id)
  }, [loaded])

  return (
    <section className="sp" aria-label={t("preview.title")}>
      <h4 className="sp-h">{t("preview.title")}</h4>
      {!loaded ? (
        <div className="sp-gate">
          <p className="muted sm">{t("preview.privacy", { host: preview.host })}</p>
          <button type="button" className="btn" onClick={() => setLoaded(true)}>
            {t("preview.load", { host: preview.host })}
          </button>
        </div>
      ) : (
        <>
          <div className={`sp-frame${plain ? " plain" : ""}`}>
            <iframe
              src={preview.src}
              title={t("preview.frameTitle", { host: preview.host })}
              sandbox="allow-scripts allow-same-origin allow-popups"
              referrerPolicy={preview.referrer}
              loading="lazy"
              height={360}
            />
            {!plain && (
              <div className="vhs" aria-hidden>
                <i className="vhs-lines" />
                <i className="vhs-grain" />
                <i className="vhs-split" />
                <i className="vhs-track" />
                <span className="vhs-tag">
                  <b className="vhs-rec" />PLAY
                </span>
              </div>
            )}
          </div>
          <div className="sp-bar">
            <button type="button" className="btn sm" aria-pressed={plain} onClick={() => setPlain((v) => !v)}>
              {t("preview.effectOff")}
            </button>
            {slow && <span className="muted sm">{t("preview.slow")}</span>}
          </div>
        </>
      )}
      <span className="sr-only">{label}</span>
    </section>
  )
}
