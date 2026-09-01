// Thin typed client over the FastAPI backend. Run `npm run gen:api` (backend
// up) to regenerate src/lib/api-schema.d.ts from /openapi.json and tighten
// these against it.

export type ReportStatus = "pending" | "unverified" | "verified" | "dismissed" | "irrelevant"

// One "Get involved" volunteer application (backend/db.py `applications`).
export interface Application {
  id: number
  name: string
  email: string
  interest: string
  message: string | null
  status: string
  created_at: number
  user_id: number | null
  account_email: string | null
  account_role: string | null
}

// Mirrors the `reports` table (backend/db.py). `created_at` is unix seconds.
export interface Report {
  id: number
  source: string
  title: string
  body: string | null
  url: string | null
  category: string
  reason: string | null
  evidence: string | null
  law: string | null
  impact: string | null
  status: ReportStatus
  lat: number | null
  lon: number | null
  place: string | null
  located: number
  created_at: number
  fuzzed?: boolean
}

export interface CategoryMeta {
  label: string
  color: string
}

export interface Law {
  code: string
  title: string
  summary?: string
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message)
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  })
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string }
    throw new ApiError(res.status, body?.detail ?? res.statusText)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export interface NewReport {
  title: string
  reason: string
  evidence?: string
  law?: string
  impact?: string
  category: string
  lat: number
  lon: number
}

export const api = {
  reports: (params: { limit?: number; all?: boolean } = {}) =>
    req<{ reports: Report[] }>(
      "/api/reports?" +
        new URLSearchParams({
          limit: String(params.limit ?? 3000),
          ...(params.all ? { all: "true" } : {}),
        })
    ).then((d) => d.reports),

  ownReport: (id: number, editToken: string) =>
    req<Report>(`/api/reports/${id}?edit_token=${encodeURIComponent(editToken)}`),

  createReport: (payload: NewReport) =>
    req<{ id: number; status: ReportStatus; edit_token: string }>("/api/reports", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  editOwnReport: (id: number, editToken: string, fields: Partial<NewReport>) =>
    req<{ id: number; status: string }>(`/api/reports/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ ...fields, edit_token: editToken }),
    }),

  categories: () => req<{ categories: Record<string, CategoryMeta> }>("/api/categories").then((d) => d.categories),
  laws: () => req<{ laws: Law[] }>("/api/laws").then((d) => d.laws),
  health: () =>
    req<{ status: string; stats: Record<string, number>; sources: unknown }>("/api/health"),
  heartbeat: () => req<Record<string, unknown>>("/api/heartbeat"),

  // auth
  me: (): Promise<{ email: string; role: string } | null> =>
    req<{ email: string; role: string }>("/api/auth/me")
      .then((d) => ({ email: d.email, role: d.role }))
      .catch(() => null),
  login: (email: string, password: string) =>
    req<{ email: string; role: string }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  signup: (payload: { name: string; email: string; password: string; message?: string }) =>
    req<{ email: string; role: string }>("/api/auth/signup", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  logout: () => req<unknown>("/api/auth/logout", { method: "POST" }),

  // admin / reviewer
  adminReports: (params: { status?: string; limit?: number; offset?: number } = {}) =>
    req<{ reports: Report[]; total: number }>(
      "/api/admin/reports?" +
        new URLSearchParams({
          limit: String(params.limit ?? 100),
          offset: String(params.offset ?? 0),
          ...(params.status ? { status: params.status } : {}),
        })
    ),
  adminApplications: () =>
    req<{ applications: Application[] }>("/api/admin/applications").then((d) => d.applications),
  approveApplication: (id: number, role: "VERIFIER" | "NONE" = "VERIFIER") =>
    req<{ id: number; user_id: number; role: string }>(`/api/admin/applications/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ role }),
    }),
  setStatus: (id: number, status: ReportStatus) =>
    req<{ id: number; status: string }>(`/api/admin/reports/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),

  // P1: server-side geocode proxy (replaces browser -> nominatim)
  geocode: (q: string) =>
    req<{ results: { lat: number; lon: number; label: string }[] }>(
      `/api/geocode?q=${encodeURIComponent(q)}`
    ).then((d) => d.results),
}
