// Browser smoke test for the map, with WebGL on and off.
//
//   node web/e2e/smoke.mjs http://127.0.0.1:8020
//
// Needs the `playwright` package and a Chromium it can launch (not a web/
// dependency on purpose: it is large and only used before a release). Run it
// with NODE_PATH pointing at an install that has it.
//
// Fails (exit 1) when: the page throws, an asset 404s, a font or style comes
// from anywhere but our own origin, the location is asked for on load, or the
// page is blank without WebGL.
import { createRequire } from "node:module"

// require (not import) so NODE_PATH works, which ES module imports ignore.
const { chromium } = createRequire(import.meta.url)("playwright")

const base = (process.argv[2] || "http://127.0.0.1:8020").replace(/\/$/, "")
const origin = new URL(base).host
const ALLOWED = new Set([origin, "tiles.openfreemap.org", ""])
const problems = []

async function run(name, args, check) {
  const browser = await chromium.launch({ args })
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage()
  await page.addInitScript(() => {
    const g = navigator.geolocation
    if (g) {
      const orig = g.getCurrentPosition.bind(g)
      g.getCurrentPosition = (...a) => { window.__geo = 1; return orig(...a) }
    }
  })
  page.on("pageerror", (e) => problems.push(`${name}: page error ${String(e.message).slice(0, 120)}`))
  page.on("response", (r) => { if (r.status() === 404) problems.push(`${name}: 404 ${r.url()}`) })
  page.on("request", (r) => {
    const host = new URL(r.url()).host
    if (!ALLOWED.has(host)) problems.push(`${name}: outside host ${host} (${r.resourceType()})`)
  })
  await page.goto(`${base}/?lang=en`, { waitUntil: "domcontentloaded" })
  await page.waitForTimeout(7000)
  if (await page.evaluate(() => !!window.__geo)) problems.push(`${name}: location asked for on load`)
  await check(page, name)
  await browser.close()
}

await run("webgl-on", ["--use-angle=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist", "--enable-unsafe-swiftshader"],
  async (page, name) => {
    if (!(await page.locator("canvas").count())) problems.push(`${name}: no map canvas`)
  })
await run("webgl-off", ["--disable-gpu", "--disable-webgl", "--disable-webgl2", "--disable-3d-apis"],
  async (page, name) => {
    if (!(await page.locator(".map-fallback").count())) problems.push(`${name}: no fallback message`)
    if (!(await page.locator(".tab, .sheet, [role=tab], button").count())) problems.push(`${name}: page is blank`)
  })

if (problems.length) {
  console.error(problems.join("\n"))
  process.exit(1)
}
console.log("smoke ok: webgl on and off")
