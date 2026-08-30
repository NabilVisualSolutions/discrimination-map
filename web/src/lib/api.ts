// Thin typed client over the FastAPI backend. Hand-written for now; run
// `npm run gen:api` (with the backend up) to regenerate src/lib/api-schema.d.ts
// from /openapi.json and tighten these types against it.

export type ReportStatus = "unverified" | "verified" | "dismissed" | "pending"

export interface Report {
  id: number
  title: string
  summary: string | null
  category: string
  status: ReportStatus
  lat: number
  lon: number
  fuzzed: boolean
  url: string | null
  occurred_at: string | null
  created_at: string
  statute_code: string | null
}

export interface CategoryMeta {
  label: string
  color: string
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(res.status, body?.detail ?? res.statusText)
  }
  return res.json() as Promise<T>
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

export const api = {
  reports: (params: { limit?: number; all?: boolean } = {}) =>
    req<{ reports: Report[] }>(
      `/api/reports?` +
        new URLSearchParams({
          limit: String(params.limit ?? 2000),
          ...(params.all ? { all: "true" } : {}),
        })
    ),
  report: (id: number, editToken?: string) =>
    req<Report>(`/api/reports/${id}` + (editToken ? `?edit_token=${encodeURIComponent(editToken)}` : "")),
  createReport: (payload: Record<string, unknown>) =>
    req<{ id: number; edit_token: string }>("/api/reports", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateReport: (id: number, editToken: string, payload: Record<string, unknown>) =>
    req<Report>(`/api/reports/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ ...payload, edit_token: editToken }),
    }),
  categories: () => req<{ categories: Record<string, CategoryMeta> }>("/api/categories"),
  laws: () => req<{ laws: unknown[] }>("/api/laws"),
  health: () => req<{ status: string; stats: Record<string, number>; sources: unknown }>("/api/health"),
  heartbeat: () => req<Record<string, unknown>>("/api/heartbeat"),
  me: () => req<{ user: { email: string; role: string } | null }>("/api/auth/me"),
  login: (email: string, password: string) =>
    req<{ user: { email: string; role: string } }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  logout: () => req<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  // P1: server-side geocode proxy (replaces browser -> nominatim).
  geocode: (q: string) => req<{ lat: number; lon: number; label: string }[]>(`/api/geocode?q=${encodeURIComponent(q)}`),
}
