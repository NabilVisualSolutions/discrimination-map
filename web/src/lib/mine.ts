// Anonymous reporters have no account. When someone files a report we keep
// its edit token on THIS device for one hour, so they can correct it from
// the same browser without an email or link — after the hour the report
// locks (the backend enforces the same window).

export type MineEntry = { id: number; token: string; exp: number }

const KEY = "dxmap_mine"
export const EDIT_WINDOW_MS = 60 * 60 * 1000 // 1 hour

export function readMine(): MineEntry[] {
  try {
    const list = JSON.parse(localStorage.getItem(KEY) || "[]") as MineEntry[]
    const live = list.filter((m) => m && m.exp > Date.now())
    if (live.length !== list.length) localStorage.setItem(KEY, JSON.stringify(live))
    return live
  } catch {
    return []
  }
}

export function rememberReport(id: number, token: string): void {
  try {
    const list = readMine().filter((m) => m.id !== id)
    list.unshift({ id, token, exp: Date.now() + EDIT_WINDOW_MS })
    localStorage.setItem(KEY, JSON.stringify(list.slice(0, 10)))
  } catch {
    /* private mode / disabled storage — reporting still works, just no local edit */
  }
}

export function latestEditable(): MineEntry | null {
  return readMine()[0] ?? null
}

export function minutesLeft(entry: MineEntry): number {
  return Math.max(0, Math.round((entry.exp - Date.now()) / 60000))
}
