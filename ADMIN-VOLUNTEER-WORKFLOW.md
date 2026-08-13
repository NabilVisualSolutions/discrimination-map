# Admin workflow — reviewing volunteer applications

Two systems, on purpose, never merged:

- **nabilvs.com** — WHO applied, their status. Uses nabilvs.com's own account system.
- **map.nabilvs.com/admin** — WHERE actual report moderation happens. Separate login, only for people already approved.

## Flow

1. Applicant fills the form at `nabilvs.com/projects/discrimination-map#get-involved` — name, email, one of Moderator / Translator / Coder / Organization partner / Symbol hunter / Other, optional message. Cloudflare Turnstile blocks bots.
2. On submit: an `Inquiry` row is created (`service = "Discrimination Map — Volunteer"`, `status = PENDING`, `emailVerified = false`). A confirm-your-email link is sent from `dxmap@nabilvs.com` (Google Workspace alias) via `SMTP_USER`/`SMTP_APP_PASSWORD` env.
3. Applicant clicks the link → `emailVerified = true`. Confirms the email is real and reachable — nothing more.
4. Applicant signs up or logs into nabilvs.com (existing account system — email/password, Google, or GitHub) with the **same email**, then sees their status at `/dashboard/volunteer` (queries `Inquiry` by matching email — no separate account link needed).

## Your review step

Go to `nabilvs.com/admin/inquiries`. Each Discrimination Map application shows:
- Name, email, submitted message
- **Email confirmed** / **Email unconfirmed** badge — wait for confirmed before acting, unconfirmed after a day or two usually means a typo'd or fake address
- Status pills: `PENDING` / `IN_PROGRESS` / `COMPLETED` / `CANCELLED` — click to change

**Reject:** click `CANCELLED`. Done — their dashboard reflects it.

**Accept:**
1. Go to `map.nabilvs.com/admin`, log in as ADMIN.
2. Users section → "Add user" → their email, a password you set, role `VERIFIER` (or `ADMIN` if warranted — rare).
3. Tell them the login some way (reply to their application email is fine).
4. Back on `nabilvs.com/admin/inquiries`, click `COMPLETED` on their row so their dashboard shows "Approved."

Non-moderator roles (translator/coder/organization) don't need a `map.nabilvs.com` account at all — just mark `COMPLETED` and follow up directly by email for whatever the actual collaboration is (a translation doc, a GitHub invite, a partnership call).

## Revoking access

Remove them from `map.nabilvs.com/admin` → Users (delete or demote to `VERIFIER`/`NONE`). Optionally flip their nabilvs.com inquiry back to `CANCELLED` for a clean record.

## Why two logins

Deliberate choice (see prior session): keeps the actual moderation tool (dxmap) simple and close to its own data, while application/status tracking reuses nabilvs.com's real account system instead of building a third one. The manual "create their VERIFIER account" step is the one place a human has to bridge the two — that's intentional, not an oversight: it means nobody gets moderation access without you personally creating it.
