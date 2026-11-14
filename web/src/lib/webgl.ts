// MapLibre needs WebGL. Some browsers, locked-down work machines and old
// phones have it switched off; then the map would throw and blank the page.
// Checked once, before the map mounts.
let cached: boolean | null = null

export function hasWebGL(): boolean {
  if (cached !== null) return cached
  try {
    if (typeof document === "undefined") return (cached = false)
    const c = document.createElement("canvas")
    cached = !!(c.getContext("webgl2") || c.getContext("webgl"))
  } catch {
    cached = false
  }
  return cached
}
