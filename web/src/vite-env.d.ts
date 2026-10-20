/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Public Cloudflare Turnstile site key; unset = no widget, backend skips the check. */
  readonly VITE_TURNSTILE_SITE_KEY?: string
}
