// Which source links may be previewed in an iframe, and the exact embed URL
// for each. Anything else returns null and only gets an "open in new tab" link.
// The frame hosts here must match `_preview_frame_hosts()` in backend/security.py
// (a pytest pins that list). Mastodon hosts mirror the DXMAP_MASTODON_INSTANCES
// default in backend/agent.py.
export const MASTODON_HOSTS = ["mastodon.social", "norden.social", "nrw.social"]
export const WIKIPEDIA_LANGS = ["en", "de", "fr", "ar"]

export interface Preview {
  provider: "youtube" | "bluesky" | "mastodon" | "wikipedia"
  /** host the frame loads from: shown on the load button */
  host: string
  src: string
  /** YouTube refuses embeds that send no Referer, so only it sends the bare origin */
  referrer: "no-referrer" | "origin"
}

/** Only plain http(s) links are ever rendered as links or frames. */
export function safeHttp(u: string | null | undefined): URL | null {
  if (!u) return null
  try {
    const x = new URL(u)
    return x.protocol === "https:" || x.protocol === "http:" ? x : null
  } catch {
    return null
  }
}

export function previewFor(url: string | null | undefined): Preview | null {
  const u = safeHttp(url)
  if (!u) return null
  const host = u.hostname.toLowerCase().replace(/^www\./, "")
  const path = u.pathname

  if (host === "youtube.com" || host === "m.youtube.com" || host === "youtu.be") {
    const id =
      host === "youtu.be"
        ? path.split("/")[1]
        : path === "/watch"
          ? u.searchParams.get("v")
          : /^\/(shorts|embed)\/([\w-]{11})/.exec(path)?.[2]
    if (id && /^[\w-]{11}$/.test(id))
      return { provider: "youtube", host: "www.youtube-nocookie.com", src: `https://www.youtube-nocookie.com/embed/${id}`, referrer: "origin" }
    return null
  }

  if (host === "bsky.app") {
    // the embed endpoint only accepts a DID, which is what the scraper stores
    const m = /^\/profile\/(did:(?:plc|web):[A-Za-z0-9._:%-]+)\/post\/([A-Za-z0-9]+)\/?$/.exec(path)
    if (m) return { provider: "bluesky", host: "embed.bsky.app", src: `https://embed.bsky.app/embed/${m[1]}/app.bsky.feed.post/${m[2]}`, referrer: "no-referrer" }
    return null
  }

  if (MASTODON_HOSTS.includes(host)) {
    const m = /^\/(@[A-Za-z0-9_.-]+)\/(\d+)\/?$/.exec(path)
    if (m) return { provider: "mastodon", host, src: `https://${host}/${m[1]}/${m[2]}/embed`, referrer: "no-referrer" }
    return null
  }

  const w = /^([a-z]{2})\.wikipedia\.org$/.exec(host)
  if (w && WIKIPEDIA_LANGS.includes(w[1]) && /^\/wiki\/[^/]+$/.test(path))
    return { provider: "wikipedia", host, src: `https://${host}${path}`, referrer: "no-referrer" }
  return null
}
