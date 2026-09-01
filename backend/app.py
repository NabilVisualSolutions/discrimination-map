"""
Discrimination Map (dxmap) — FastAPI application.

One process serves the JSON API, the static frontend, and launches two
background loops on startup: the monitoring agent's heartbeat and the
self-check.
"""
from __future__ import annotations

import asyncio
import collections
import os
import secrets
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, field_validator

import agent
import auth
import db
import lawref
import selfcheck

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
ENV = os.environ.get("DXMAP_ENV", "dev")
ALLOW_ORIGINS = os.environ.get("DXMAP_ALLOW_ORIGINS", "*").split(",")

# Shared secret for the trusted server-to-server integration: nabilvs.com's
# Pantheon dashboard calls /api/service/* with this in an X-Service-Token
# header so approved volunteers can review incidents from there. dxmap stays
# the source of truth. Unset => the /api/service/* routes are disabled.
SERVICE_TOKEN = os.environ.get("DXMAP_SERVICE_TOKEN", "").strip()

# Background task handles, so we can cancel them cleanly on shutdown.
_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Init DB, bootstrap the first admin, start the heartbeat + self-check loops."""
    db.init_db()
    auth.bootstrap_admin()
    _tasks.append(asyncio.create_task(agent.heartbeat_loop()))
    _tasks.append(asyncio.create_task(selfcheck.selfcheck_loop()))
    try:
        yield
    finally:
        for t in _tasks:
            t.cancel()


app = FastAPI(title="Discrimination Map", version="1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


# Best-effort per-IP rate limiting on the public write endpoints (login,
# report/apply/symbol-proposal submission) — in-memory, single-process,
# not a substitute for WAF-level protection but cheap defense against
# scripted spam/brute-force against a single-container deploy. Reads the
# client IP from X-Forwarded-For (set by the Caddy reverse proxy in front
# of this app) so it doesn't collapse every visitor onto the proxy's IP.
_rate_buckets: dict[str, collections.deque] = collections.defaultdict(collections.deque)
RATE_LIMITS = {
    "/api/auth/login": (30, 60),
    "/api/reports": (30, 60),
    "/api/apply": (10, 60),
    "/api/propose-symbol": (10, 60),
}


def _client_ip(request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def rate_limit(request, call_next):
    limits = RATE_LIMITS.get(request.url.path)
    if request.method == "POST" and limits:
        limit, window = limits
        key = f"{_client_ip(request)}:{request.url.path}"
        now = time.time()
        bucket = _rate_buckets[key]
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) >= limit:
            return JSONResponse({"detail": "Too many requests, try again shortly"}, status_code=429)
        bucket.append(now)
    return await call_next(request)


@app.middleware("http")
async def security_headers(request, call_next):
    """Set baseline security headers on every response."""
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    # Framing is controlled by CSP frame-ancestors ONLY. We deliberately do
    # not send X-Frame-Options: it has no allowlist form (only DENY /
    # SAMEORIGIN), so `XFO: DENY` next to a permissive frame-ancestors does
    # NOT "fall through" to the CSP on modern browsers — XFO wins and blocks
    # every embed, including the trusted nabilvs.com case-study page (this
    # was a real bug: the embedded map rendered blank). frame-ancestors is
    # honoured by every browser since ~2017; the rare one without it can
    # frame the map, an acceptable trade for the embed actually working.
    resp.headers["Content-Security-Policy"] = (
        "frame-ancestors 'self' https://nabilvs.com https://www.nabilvs.com"
    )
    resp.headers["Referrer-Policy"] = "no-referrer"
    # "self" plus nabilvs.com — the case-study page embeds this map in an
    # iframe, and the locate-me button needs geolocation delegated to it
    # there too, not just when this origin is loaded top-level.
    resp.headers["Permissions-Policy"] = (
        'geolocation=(self "https://nabilvs.com" "https://www.nabilvs.com")'
    )
    return resp


# --------------------------------------------------------------------------- #
# Models                                                                        #
# --------------------------------------------------------------------------- #

class UserReport(BaseModel):
    """
    A report filed by a person via the button. The documentation fields make
    each mark accountable: what happened, the evidence, the possibly-applicable
    statute, and the impact. Everything is treated as ALLEGED and unverified
    until a moderator confirms it.
    """
    title: str = Field(min_length=3, max_length=300)
    reason: str = Field(min_length=3, max_length=500,
                        description="What happened / why it's being reported")
    evidence: str = Field(default="", max_length=1000,
                          description="Link or description of the proof")
    law: str = Field(default="", max_length=40,
                     description="Possibly-applicable statute code from /api/laws")
    impact: str = Field(default="", max_length=1000,
                        description="Harm caused / people affected")
    category: str = Field(default="user_report", max_length=120,
                          description="One or more category slugs, comma-separated")
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    occurred_at: int | None = Field(
        default=None,
        description="Unix seconds — when the incident happened (may be in the past). "
                    "Defaults to submission time.")

    @field_validator("occurred_at")
    @classmethod
    def _sane_occurred(cls, v: int | None) -> int | None:
        if v is None:
            return None
        now = int(time.time())
        if v > now + 86400:
            raise ValueError("occurred_at cannot be in the future")
        if v < now - 60 * 60 * 24 * 365 * 40:
            raise ValueError("occurred_at is implausibly far in the past")
        return v

    @field_validator("law")
    @classmethod
    def _known_law(cls, v: str) -> str:
        """Reject unknown statute codes so the field stays trustworthy."""
        if v and v not in lawref.STATUTES:
            raise ValueError(f"unknown law code '{v}'")
        return v


# --------------------------------------------------------------------------- #
# API                                                                           #
# --------------------------------------------------------------------------- #

# Categories that never show a tight pin to the public, even once verified —
# a sexual-violence or harassment report can re-identify someone from
# location alone in a way "banned symbol graffiti" can't.
SENSITIVE_CATEGORIES = {"sexual_violence", "harassment"}
SENSITIVE_FUZZ_RADIUS_M = 5000
DEFAULT_FUZZ_RADIUS_M = 500
ANON_EDIT_WINDOW_SECONDS = int(os.environ.get("DXMAP_ANON_EDIT_WINDOW", str(60 * 60)))


@app.get("/api/reports")
def get_reports(
    limit: int = 500,
    all: bool = False,
    as_of: int | None = None,
    user: dict | None = Depends(auth.get_current_user),
):
    """
    Return recent reports. By default only mapped (located) ones.
    Unverified reports get their coordinates fuzzed for anyone not logged
    in as ADMIN/VERIFIER, so a single unconfirmed post can't pinpoint a real
    address. Sensitive categories (sexual violence, harassment) are always
    fuzzed at a wider radius for the public regardless of verification
    status — logged-in moderators still see the real location to review it.

    Optional `as_of` (unix timestamp): only return reports with
    created_at <= as_of. Enables server-side timeline filtering so clients
    don't need to fetch the entire dataset.
    """
    limit = max(1, min(limit, 5000))  # headroom above the current ~3.8k public-eligible total
    is_reviewer = bool(user and user["role"] in ("VERIFIER", "ADMIN"))
    reports = db.list_reports(
        limit=limit, located_only=not all, as_of=as_of, viewer_is_reviewer=is_reviewer
    )
    if user is None:
        for r in reports:
            if r["lat"] is None or r["lon"] is None:
                continue
            sensitive = r["category"] in SENSITIVE_CATEGORIES
            if sensitive or r["status"] != "verified":
                radius = SENSITIVE_FUZZ_RADIUS_M if sensitive else DEFAULT_FUZZ_RADIUS_M
                r["lat"], r["lon"] = db.fuzz_coords(r["id"], r["lat"], r["lon"], radius_m=radius)
                r["fuzzed"] = True
    return {"reports": reports}


@app.post("/api/reports", status_code=201)
def post_report(report: UserReport):
    """
    Store a user-filed report. Always located (client supplies coords).
    No `url` is ever set for a user submission (the free-text `evidence`
    field isn't a verifiable source), so `db.insert_report` defaults its
    status to 'pending' — held out of the public feed until an ADMIN/
    VERIFIER reviews it. Automated agent-scraped reports (which always cite
    a real source url) still publish immediately as 'unverified' leads.
    """
    new_id = db.insert_report(
        source="user",
        external_id=f"user_{int(time.time()*1000)}",
        title=report.title,
        body=report.reason,
        category=report.category,
        reason=report.reason,
        evidence=report.evidence,
        law=report.law or None,
        impact=report.impact,
        lat=report.lat, lon=report.lon,
        place="user-reported",
        occurred_at=report.occurred_at,
    )
    if new_id is None:
        raise HTTPException(status_code=409, detail="Duplicate report")
    saved = db.get_report(new_id)
    return {"id": new_id, "status": saved["status"], "edit_token": saved["edit_token"]}


@app.get("/api/reports/{report_id}")
def get_own_report(report_id: int, edit_token: str):
    """
    Fetch a single report by id, gated by its edit_token. This is the only
    way an anonymous submitter can see their own report on the map again —
    a 'pending' or 'unverified' report is invisible on /api/reports (the
    public feed) until a moderator acts on it, so without this the map
    would only ever show a filer their own report for the one moment right
    after submission. Same trust model as the self-edit PATCH below: the
    token, not an account, proves "you're the one who filed this" — so the
    real (unfuzzed) coordinates are fine to return here.
    """
    existing = db.get_report(report_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if not secrets.compare_digest(existing.get("edit_token") or "", edit_token):
        raise HTTPException(status_code=403, detail="Wrong edit token")
    existing.pop("edit_token", None)
    return existing


class StatusUpdate(BaseModel):
    # verified  -> shown on the public map
    # dismissed -> rejected (spam / false positive)
    # irrelevant-> reviewed, not a discrimination incident
    # unverified/pending -> still "needs review", hidden from the public map
    status: Literal["pending", "unverified", "verified", "dismissed", "irrelevant"]


class ReportEdit(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    reason: str | None = Field(default=None, min_length=3, max_length=500)
    evidence: str | None = Field(default=None, max_length=1000)
    law: str | None = Field(default=None, max_length=40)
    impact: str | None = Field(default=None, max_length=1000)
    category: str | None = Field(default=None, max_length=50)

    @field_validator("law")
    @classmethod
    def _known_law(cls, v: str | None) -> str | None:
        if v and v not in lawref.STATUTES:
            raise ValueError(f"unknown law code '{v}'")
        return v


class UserReportEdit(ReportEdit):
    edit_token: str = Field(min_length=1, max_length=200)


@app.patch("/api/reports/{report_id}")
def user_edit_report(report_id: int, body: UserReportEdit):
    """
    Self-edit for the person who filed a report, gated by the edit_token
    handed back once at submission time (not an account — anonymous
    reports have no account to authenticate with, but the token proves
    "you're the one who filed this"). Locked once a moderator has already
    acted on it (verified/dismissed), so a self-edit can't be used to
    quietly rewrite a report after it's been reviewed.
    """
    existing = db.get_report(report_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if not secrets.compare_digest(existing.get("edit_token") or "", body.edit_token):
        raise HTTPException(status_code=403, detail="Wrong edit token")
    if existing["status"] not in ("pending", "unverified"):
        raise HTTPException(status_code=409, detail="Already reviewed — no longer self-editable")
    # Anonymous edits are allowed only from the reporting device, and only
    # within one hour of filing. After that the report is frozen to whoever
    # holds the token.
    if int(time.time()) - int(existing["created_at"]) > ANON_EDIT_WINDOW_SECONDS:
        raise HTTPException(status_code=409, detail="Edit window closed — reports lock 1 hour after filing")
    fields = body.model_dump(exclude={"edit_token"}, exclude_none=True)
    db.update_report_fields(report_id, fields, edited_by="self")
    return {"id": report_id, "status": "updated"}


@app.patch("/api/admin/reports/{report_id}/fields")
def admin_edit_report(
    report_id: int, body: ReportEdit,
    user: dict = Depends(auth.require_role("ADMIN", "VERIFIER")),
):
    """Moderator correction tool — full-field edit, no token/status gate."""
    fields = body.model_dump(exclude_none=True)
    if not db.update_report_fields(report_id, fields, edited_by=user["email"]):
        raise HTTPException(status_code=404, detail="Report not found or nothing to update")
    return {"id": report_id, "status": "updated"}


@app.get("/api/admin/reports/{report_id}/history")
def admin_report_history(
    report_id: int, _: dict = Depends(auth.require_role("ADMIN", "VERIFIER")),
):
    """Full edit trail for one report — who changed what, when."""
    if db.get_report(report_id) is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"history": db.get_report_history(report_id)}


@app.get("/api/admin/reports")
def admin_list_reports(
    limit: int = 100, offset: int = 0, status: str | None = None,
    _: dict = Depends(auth.require_role("ADMIN", "VERIFIER")),
):
    """Every report, located or not, for the moderation queue. Open to both
    roles. `status` accepts a comma list, e.g. ?status=unverified,pending."""
    limit = max(1, min(limit, 1000))
    return db.list_reports_admin(limit=limit, offset=offset, status=status)


@app.patch("/api/admin/reports/{report_id}")
def admin_set_report_status(
    report_id: int, body: StatusUpdate,
    user: dict = Depends(auth.require_role("ADMIN", "VERIFIER")),
):
    """Verify or dismiss a report after human review. Open to both roles."""
    if not db.set_status(report_id, body.status, edited_by=user["email"]):
        raise HTTPException(status_code=404, detail="Report not found")
    return {"id": report_id, "status": body.status}


@app.delete("/api/admin/reports/{report_id}")
def admin_delete_report(report_id: int, _: dict = Depends(auth.require_role("ADMIN"))):
    """Permanently remove a report — ADMIN only (VERIFIER should dismiss instead)."""
    if not db.delete_report(report_id):
        raise HTTPException(status_code=404, detail="Report not found")
    return {"id": report_id, "status": "deleted"}


@app.get("/api/admin/duplicates")
def admin_find_duplicates(_: dict = Depends(auth.require_role("ADMIN", "VERIFIER"))):
    """Reports sharing a url with an earlier row — candidates for cleanup."""
    return {"duplicates": db.find_url_duplicates()}


# --------------------------------------------------------------------------- #
# Service API — trusted server-to-server (nabilvs.com Pantheon)               #
# --------------------------------------------------------------------------- #

def require_service(x_service_token: str = Header(default="")) -> None:
    if not SERVICE_TOKEN:
        raise HTTPException(status_code=503, detail="Service integration not configured")
    if not secrets.compare_digest(x_service_token, SERVICE_TOKEN):
        raise HTTPException(status_code=401, detail="Bad service token")


class ServiceReview(BaseModel):
    status: Literal["verified", "dismissed", "irrelevant", "unverified"]
    moderator: str = Field(min_length=1, max_length=200)
    # Optional reclassification: one or more category slugs, comma-separated.
    category: str | None = Field(default=None, max_length=120)


@app.get("/api/service/review-queue")
def service_review_queue(
    limit: int = 200, offset: int = 0, _: None = Depends(require_service),
):
    """Incidents still needing review (unverified + pending), newest first."""
    limit = max(1, min(limit, 1000))
    return db.list_reports_admin(limit=limit, offset=offset, status="unverified,pending")


@app.post("/api/service/review/{report_id}")
def service_review(report_id: int, body: ServiceReview, _: None = Depends(require_service)):
    """
    Apply a volunteer's verdict. `moderator` is the reviewer's identity on
    the calling system (their nabilvs.com email) — recorded in
    report_history so the audit trail names a real person.
    """
    if not db.set_status(report_id, body.status, edited_by=f"pantheon:{body.moderator}"):
        raise HTTPException(status_code=404, detail="Report not found")
    if body.category:
        cats = ",".join(
            c.strip() for c in body.category.replace("|", ",").replace("/", ",").split(",") if c.strip()
        )
        if cats:
            db.update_report_fields(report_id, {"category": cats}, edited_by=f"pantheon:{body.moderator}")
    return {"id": report_id, "status": body.status, "category": body.category}


@app.get("/api/service/stats")
def service_stats(_: None = Depends(require_service)):
    return db.stats()


# --------------------------------------------------------------------------- #
# Auth                                                                          #
# --------------------------------------------------------------------------- #

class LoginBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


# Tiny in-memory sliding-window guard. Valid because this runs as one
# long-lived process (not serverless). Keyed by client IP.
_RL: dict[str, list[float]] = collections.defaultdict(list)


def _rate_limit(key: str, limit: int, window: float = 3600.0) -> None:
    now = time.time()
    hits = [t for t in _RL[key] if now - t < window]
    if len(hits) >= limit:
        raise HTTPException(status_code=429, detail="Too many attempts — try again later")
    hits.append(now)
    _RL[key] = hits


def _client_ip(request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else "") or (request.client.host if request.client else "unknown")


@app.post("/api/auth/login")
def login(body: LoginBody, response: Response, request: Request):
    _rate_limit(f"login:{_client_ip(request)}", limit=20, window=900)
    user = db.get_user_by_email(body.email)
    if not user or not db.verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Wrong email or password")
    token = db.create_session(user["id"])
    auth.set_session_cookie(response, token)
    return {"email": user["email"], "role": user["role"]}


class SignupBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    message: str = Field(default="", max_length=2000)
    accept: bool = Field(description="Must accept the Terms of Use and Privacy Policy")

    @field_validator("accept")
    @classmethod
    def _must_accept(cls, v: bool) -> bool:
        if not v:
            raise ValueError("You must accept the Terms of Use and Privacy Policy")
        return v


@app.post("/api/auth/signup", status_code=201)
def signup(body: SignupBody, response: Response, request: Request):
    """
    Public volunteer sign-up from the map's "Get involved" tab. Creates an
    account with role NONE (no permissions) plus a linked volunteer
    application. An ADMIN then approves it (POST .../applications/{id}
    /approve), which promotes the account to VERIFIER — at which point the
    volunteer sees the review queue on their volunteering page.
    """
    _rate_limit(f"signup:{_client_ip(request)}", limit=5, window=3600)
    uid = db.create_user(body.email, body.password, "NONE", accepted_terms=body.accept)
    if uid is None:
        raise HTTPException(status_code=409, detail="That email already has an account")
    db.create_application(
        name=body.name, email=body.email, interest="volunteer",
        message=body.message, user_id=uid,
    )
    token = db.create_session(uid)
    auth.set_session_cookie(response, token)
    return {"email": body.email, "role": "NONE"}


@app.post("/api/auth/logout")
def logout(response: Response, dxmap_session: str = Cookie(default=None)):
    if dxmap_session:
        db.delete_session(dxmap_session)
    auth.clear_session_cookie(response)
    return {"status": "logged out"}


@app.get("/api/auth/me")
def me(user: dict = Depends(auth.require_user)):
    full = db.get_user_by_id(user["id"])
    return {"email": user["email"], "role": user["role"], "provider": full["provider"] if full else "email"}


# Public self-registration and Google sign-in were removed: applications now
# go through nabilvs.com's own form (email verification + Cloudflare
# Turnstile there), and an ADMIN invites reviewers directly via
# /api/admin/users below. Only /admin has a login at all.


# --------------------------------------------------------------------------- #
# User / role management — ADMIN only                                          #
# --------------------------------------------------------------------------- #

class NewUserBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    role: Literal["NONE", "VERIFIER", "ADMIN"]


class RoleUpdate(BaseModel):
    role: Literal["NONE", "VERIFIER", "ADMIN"]


@app.get("/api/admin/users")
def admin_list_users(_: dict = Depends(auth.require_role("ADMIN"))):
    return {"users": db.list_users()}


@app.post("/api/admin/users", status_code=201)
def admin_create_user(body: NewUserBody, _: dict = Depends(auth.require_role("ADMIN"))):
    """Invite a new user and assign their role (this is how VERIFIER access is granted)."""
    new_id = db.create_user(body.email, body.password, body.role)
    if new_id is None:
        raise HTTPException(status_code=409, detail="Email already has an account")
    return {"id": new_id, "email": body.email, "role": body.role}


@app.patch("/api/admin/users/{user_id}")
def admin_update_user_role(
    user_id: int, body: RoleUpdate, current: dict = Depends(auth.require_role("ADMIN")),
):
    if user_id == current["id"] and body.role != "ADMIN":
        raise HTTPException(status_code=400, detail="Cannot demote your own account")
    if not db.update_user_role(user_id, body.role):
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": user_id, "role": body.role}


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: int, current: dict = Depends(auth.require_role("ADMIN"))):
    if user_id == current["id"]:
        raise HTTPException(status_code=400, detail="Cannot remove your own account")
    target = db.get_user_by_id(user_id)
    if target and target["role"] == "ADMIN" and db.count_users(role="ADMIN") <= 1:
        raise HTTPException(status_code=400, detail="Cannot remove the last admin")
    if not db.delete_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": user_id, "status": "deleted"}


# --------------------------------------------------------------------------- #
# Applications — the public "Get involved" tab                                 #
# --------------------------------------------------------------------------- #

class ApplicationBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    interest: Literal["volunteer", "translator", "coder", "organization", "other"]
    message: str = Field(default="", max_length=2000)


@app.post("/api/apply", status_code=201)
def apply(body: ApplicationBody):
    """Public — volunteer/translator/coder/organization applications, reviewed from /admin."""
    new_id = db.create_application(
        name=body.name, email=body.email, interest=body.interest, message=body.message,
    )
    return {"id": new_id, "status": "received"}


class SymbolProposalBody(BaseModel):
    """
    Someone spotted a possible symbol/code/gesture that isn't in the
    awareness guide yet. Deliberately not tied to the strict `EmailStr`
    validator the rest of the app uses — this is meant to work without an
    account or even a real address, so email is just a loosely-checked,
    optional contact hint rather than a verified identity.
    """
    description: str = Field(min_length=5, max_length=1000)
    context: str = Field(default="", max_length=300)
    email: str = Field(default="", max_length=200)

    @field_validator("email")
    @classmethod
    def _loose_email_shape(cls, v: str) -> str:
        v = v.strip()
        if v and "@" not in v:
            raise ValueError("doesn't look like an email address")
        return v


@app.post("/api/propose-symbol", status_code=201)
def propose_symbol(body: SymbolProposalBody):
    """
    Public — reuses the applications table (interest='other', message
    tagged) so a proposed symbol lands in the same /admin review queue as
    volunteer applications, without needing a new table or migration.
    """
    message = f"[SYMBOL PROPOSAL] {body.description}"
    if body.context:
        message += f"\nContext: {body.context}"
    new_id = db.create_application(
        name="(symbol proposal)",
        email=body.email or "no-reply@dxmap.local",
        interest="other",
        message=message,
    )
    return {"id": new_id, "status": "received"}


@app.get("/api/admin/applications")
def admin_list_applications(
    status: str | None = None, _: dict = Depends(auth.require_role("ADMIN", "VERIFIER")),
):
    return {"applications": db.list_applications(status=status)}


class ApplicationStatusUpdate(BaseModel):
    status: Literal["new", "contacted", "closed"]


@app.patch("/api/admin/applications/{app_id}")
def admin_set_application_status(
    app_id: int, body: ApplicationStatusUpdate,
    _: dict = Depends(auth.require_role("ADMIN", "VERIFIER")),
):
    if not db.set_application_status(app_id, body.status):
        raise HTTPException(status_code=404, detail="Application not found")
    return {"id": app_id, "status": body.status}


class ApplicationApproval(BaseModel):
    role: Literal["VERIFIER", "NONE"] = "VERIFIER"


@app.post("/api/admin/applications/{app_id}/approve")
def admin_approve_application(
    app_id: int, body: ApplicationApproval | None = None,
    _: dict = Depends(auth.require_role("ADMIN")),
):
    """
    Confirm a volunteer: promote the account they created at signup to
    VERIFIER (or demote back to NONE with role='NONE') and close the
    application. ADMIN only — this is the "admin confirms their
    volunteering" gate.
    """
    row = db.get_application(app_id)
    if not row:
        raise HTTPException(status_code=404, detail="Application not found")
    if not row.get("user_id"):
        raise HTTPException(
            status_code=400,
            detail="This application has no linked account — the applicant must sign up first",
        )
    role = (body.role if body else "VERIFIER")
    db.update_user_role(row["user_id"], role)
    db.set_application_status(app_id, "closed" if role == "VERIFIER" else "new")
    return {"id": app_id, "user_id": row["user_id"], "role": role}


@app.get("/api/laws")
def laws():
    """The statute reference the UI uses for the law dropdown and popups,
    plus how many mapped incidents currently cite each one."""
    return {"laws": lawref.STATUTES, "counts": db.law_incident_counts()}


# Server-side geocode proxy. The old frontend called nominatim.openstreetmap
# .org straight from the browser — rate-limit fragile, no fallback, leaks the
# usage pattern, and OSM's policy wants a real contact in the User-Agent. This
# funnels it through one identified server with a short in-memory cache.
_GEOCODE_CACHE: dict[str, tuple[float, list[dict]]] = {}
_GEOCODE_TTL = 3600.0
_GEOCODE_UA = "discrimination-map/1.0 (+https://map.nabilvs.com)"


@app.get("/api/geocode")
async def geocode(q: str = ""):
    q = q.strip()
    if len(q) < 2:
        return {"results": []}
    key = q.lower()
    hit = _GEOCODE_CACHE.get(key)
    now = time.time()
    if hit and now - hit[0] < _GEOCODE_TTL:
        return {"results": hit[1]}
    import httpx

    try:
        async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": _GEOCODE_UA}) as client:
            r = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"format": "json", "limit": 5, "q": q, "accept-language": "en"},
            )
            r.raise_for_status()
            data = r.json()
    except Exception:
        raise HTTPException(status_code=502, detail="Geocoding is unavailable right now")
    results = [
        {"lat": float(d["lat"]), "lon": float(d["lon"]), "label": d.get("display_name", q)}
        for d in data
        if d.get("lat") and d.get("lon")
    ]
    _GEOCODE_CACHE[key] = (now, results)
    return {"results": results}


@app.get("/api/categories")
def categories():
    """Category -> {label, color} the UI uses for marker colors and the legend."""
    return {"categories": lawref.CATEGORIES}


@app.get("/api/health")
def health():
    """Liveness + rolling source health for the status endpoint."""
    return {
        "status": "ok",
        "env": ENV,
        "stats": db.stats(),
        "sources": db.source_health(),
    }


@app.get("/api/heartbeat")
def heartbeat_status():
    """Live heartbeat state for the HUD: last beat, count, countdown."""
    st = dict(agent.STATE)
    st["now"] = int(time.time())
    st["heartbeat_seconds"] = agent.HEARTBEAT_SECONDS
    return st


# --------------------------------------------------------------------------- #
# Static frontend                                                               #
# --------------------------------------------------------------------------- #

@app.get("/")
def index():
    """Serve the map app."""
    path = os.path.join(FRONTEND_DIR, "index.html")
    if not os.path.exists(path):
        return JSONResponse({"error": "frontend not built"}, status_code=500)
    return FileResponse(path)


@app.get("/awareness")
def awareness_page():
    """Serve the far-right symbol recognition/awareness reference."""
    path = os.path.join(FRONTEND_DIR, "awareness.html")
    if not os.path.exists(path):
        return JSONResponse({"error": "awareness page not built"}, status_code=500)
    return FileResponse(path)


@app.get("/guide")
def guide_page():
    """Serve the public volunteer guide — public on purpose, same as /awareness."""
    path = os.path.join(FRONTEND_DIR, "guide.html")
    if not os.path.exists(path):
        return JSONResponse({"error": "guide page not built"}, status_code=500)
    return FileResponse(path)


@app.get("/privacy")
def privacy_page():
    """Serve the Privacy Policy — public, linked from the map footer/report form."""
    path = os.path.join(FRONTEND_DIR, "privacy.html")
    if not os.path.exists(path):
        return JSONResponse({"error": "privacy page not built"}, status_code=500)
    return FileResponse(path)


@app.get("/terms")
def terms_page():
    """Serve the Terms of Use — public, linked from the map footer/report form."""
    path = os.path.join(FRONTEND_DIR, "terms.html")
    if not os.path.exists(path):
        return JSONResponse({"error": "terms page not built"}, status_code=500)
    return FileResponse(path)


@app.get("/admin")
def admin_page():
    """
    Serve the moderation console. The page itself is static and unprotected
    at the HTTP level (no reports data is embedded in the HTML) — every
    actual read/write it makes goes through the bearer-token-gated
    /api/admin/* endpoints above, so nothing sensitive loads before login.
    """
    path = os.path.join(FRONTEND_DIR, "admin.html")
    if not os.path.exists(path):
        return JSONResponse({"error": "admin page not built"}, status_code=500)
    return FileResponse(path)


# Any other static assets (there are none by default, but future-proof).
if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
