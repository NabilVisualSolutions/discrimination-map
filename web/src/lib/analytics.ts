// Optional product analytics (Amplitude, EU data centre). OFF until the visitor
// says yes in the consent banner: nothing is downloaded, stored or sent before
// that. No autocapture and no session replay: this site collects reports about
// discrimination, so what people type and click must never be recorded.
// The choice is kept in this browser only (localStorage) and can be changed
// again from the footer link "Privacy choices".

const KEY = "dxmap-analytics-consent"
const API_KEY: string = import.meta.env.VITE_AMPLITUDE_API_KEY ?? ""

export type Consent = "granted" | "denied" | null

export const analyticsAvailable = API_KEY.length > 0

export function getConsent(): Consent {
  try {
    const v = localStorage.getItem(KEY)
    return v === "granted" || v === "denied" ? v : null
  } catch {
    return null
  }
}

let started = false

async function start() {
  if (started || !analyticsAvailable) return
  started = true
  try {
    // The plain analytics SDK only: the "unified" bundle also starts session
    // replay and in-page surveys, which this site must never run.
    const amplitude = await import("@amplitude/analytics-browser")
    await amplitude.init(API_KEY, undefined, {
      serverZone: "EU",
      defaultTracking: false,
      autocapture: false,
      trackingOptions: { ipAddress: false },
    }).promise
    amplitude.track("Viewed Map")
  } catch {
    started = false
  }
}

export function setConsent(value: "granted" | "denied") {
  try {
    localStorage.setItem(KEY, value)
  } catch {
    /* private mode: the choice just lasts until reload */
  }
  if (value === "granted") void start()
  else if (started) location.reload() // simplest way to stop an already-running SDK
}

export function clearConsent() {
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* ignore */
  }
  location.reload()
}

/** Call once at startup: resumes only if the visitor already agreed. */
export function initAnalyticsIfConsented() {
  if (getConsent() === "granted") void start()
}
