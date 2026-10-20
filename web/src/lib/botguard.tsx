import { useEffect, useId, useRef, useState } from "react"

// Bot protection for the public forms (report, sign-up). Two parts:
//
// 1. Honeypot: an input named `hp_contact` (not a name browsers autofill; "website" is) that sits off-screen, out of the tab
//    order and hidden from screen readers. People never fill it; form bots
//    fill every field. The backend rejects a non-empty value
//    (backend/security.py, HONEYPOT_FIELD).
// 2. Cloudflare Turnstile, only when VITE_TURNSTILE_SITE_KEY is set at build
//    time. Without it nothing renders and the backend skips the check
//    (DXMAP_TURNSTILE_SECRET unset), so turning it on is one build variable
//    plus one server secret, after map.nabilvs.com is on the widget's
//    hostname list.

export const TURNSTILE_SITE_KEY: string = import.meta.env.VITE_TURNSTILE_SITE_KEY ?? ""
export const turnstileEnabled = TURNSTILE_SITE_KEY.length > 0
const ACTION = "dxmap-submit" // must match security.TURNSTILE_ACTION

export function Honeypot({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const id = useId()
  return (
    <div aria-hidden="true" style={{ position: "absolute", left: -10000, top: "auto", width: 1, height: 1, overflow: "hidden" }}>
      <label htmlFor={id}>Leave this field empty</label>
      <input id={id} name="hp_contact" type="text" tabIndex={-1} autoComplete="off" value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  )
}

interface TurnstileApi {
  render: (el: HTMLElement, opts: Record<string, unknown>) => string
  remove: (id: string) => void
}
declare global {
  interface Window {
    turnstile?: TurnstileApi
  }
}

let scriptLoading: Promise<void> | null = null
function loadScript(): Promise<void> {
  if (window.turnstile) return Promise.resolve()
  if (!scriptLoading) {
    scriptLoading = new Promise((resolve, reject) => {
      const s = document.createElement("script")
      s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"
      s.async = true
      s.onload = () => resolve()
      s.onerror = () => reject(new Error("turnstile load failed"))
      document.head.appendChild(s)
    })
  }
  return scriptLoading
}

/** Renders nothing unless Turnstile is enabled. Remount (change `key`) for a fresh token: tokens are single-use. */
export function Turnstile({ onToken }: { onToken: (token: string | null) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!turnstileEnabled) return
    let widget: string | null = null
    let cancelled = false
    loadScript()
      .then(() => {
        if (cancelled || !ref.current || !window.turnstile) return
        widget = window.turnstile.render(ref.current, {
          sitekey: TURNSTILE_SITE_KEY,
          action: ACTION,
          callback: (t: string) => onToken(t),
          "expired-callback": () => onToken(null),
          "error-callback": () => onToken(null),
        })
      })
      .catch(() => setFailed(true))
    return () => {
      cancelled = true
      if (widget && window.turnstile) window.turnstile.remove(widget)
    }
  }, [onToken])

  if (!turnstileEnabled) return null
  return (
    <>
      <div ref={ref} />
      {failed && (
        <p className="muted sm" role="alert" style={{ color: "#b23b3b" }}>
          The bot check could not load. Allow challenges.cloudflare.com (an ad blocker may stop it), then reload.
        </p>
      )}
    </>
  )
}
