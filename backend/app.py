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
import re
import secrets
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import BackgroundTasks, Cookie, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, field_validator

import agent
import auth
import db
import lawref
import mailer
import security
import selfcheck
import totp

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
ENV = os.environ.get("DXMAP_ENV", "prod")  # secure by default; dev must be asked for
PUBLIC_URL = os.environ.get("DXMAP_PUBLIC_URL", "https://map.nabilvs.com").rstrip("/")
# Extra origins allowed to make credentialed writes / CORS. The UI is
# same-origin, so the default is none; "*" is ignored.
ALLOW_ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("DXMAP_ALLOW_ORIGINS", "").split(",") if o.strip() and o.strip() != "*"]

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
    # DXMAP_AGENT=off: no scraping (local review against a copied database,
    # or while production is under attack and the feeds are being gamed).
    if os.environ.get("DXMAP_AGENT", "on").lower() != "off":
        _tasks.append(asyncio.create_task(agent.heartbeat_loop()))
    _tasks.append(asyncio.create_task(selfcheck.selfcheck_loop()))
    try:
        yield
    finally:
        for t in _tasks:
            t.cancel()


app = FastAPI(title="Discrimination Map", version="1.0", lifespan=lifespan)

if ALLOW_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOW_ORIGINS,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["*"],
        allow_credentials=True,
    )


MAX_BODY_BYTES = 16 * 1024


@app.middleware("http")
async def refuse_cross_site_writes(request, call_next):
    """
    A write that carries an Origin header must come from this host (or an
    origin listed in DXMAP_ALLOW_ORIGINS). SameSite=Lax cookies still travel
    between sibling subdomains of nabilvs.com, so without this a page on any
    of them could send credentialed PATCH/DELETE to /api/admin/*. Requests
    with no Origin (curl, nabilvs.com's server calling /api/service/*) pass.
    """
    if request.method in ("POST", "PATCH", "PUT", "DELETE"):
        origin = request.headers.get("origin")
        if origin and not security.origin_allowed(origin, request.headers.get("host", ""), ALLOW_ORIGINS):
            return JSONResponse({"detail": "Cross-site request refused"}, status_code=403)
    return await call_next(request)


class BodyCap:
    """
    Pure ASGI middleware: refuse any request body over MAX_BODY_BYTES. A
    declared Content-Length is checked up front; a chunked body is counted as
    it streams and aborted the moment it passes the cap, so an oversized body
    is never buffered whole.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PATCH", "PUT"):
            return await self.app(scope, receive, send)
        for name, value in scope.get("headers", []):
            if name == b"content-length" and value.isdigit() and int(value) > MAX_BODY_BYTES:
                return await self._too_large(scope, receive, send)
        seen = 0
        refused = False

        async def counting_receive():
            nonlocal seen, refused
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > MAX_BODY_BYTES:
                    refused = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def guarded_send(message):
            if refused and message["type"] == "http.response.start":
                return  # the downstream response is replaced below
            if refused and message["type"] == "http.response.body":
                return
            await send(message)

        await self.app(scope, counting_receive, guarded_send)
        if refused:
            await self._too_large(scope, receive, send)

    @staticmethod
    async def _too_large(scope, receive, send):
        await JSONResponse({"detail": "Request too large"}, status_code=413)(scope, receive, send)


app.add_middleware(BodyCap)


# Per-IP rate limits on the public write endpoints, minute and hour windows
# (backend/security.py). The hour caps are what stop a slow, scripted flood
# of fake reports or sign-ups; the old 30-a-minute limit alone allowed
# 43,000 reports a day from one address. Keyed on the real visitor IP
# behind Cloudflare (security.client_ip), not the spoofable first
# X-Forwarded-For entry the old code read.
RATE_LIMITS: dict[str, list[tuple[int, float]]] = {
    "/api/auth/login": [(10, 60), (60, 3600)],
    "/api/auth/signup": [(3, 60), (5, 3600)],
    "/api/reports": [(5, 60), (20, 3600), (60, 86400)],
    "/api/apply": [(3, 60), (10, 3600)],
    "/api/propose-symbol": [(3, 60), (10, 3600)],
}


@app.middleware("http")
async def rate_limit(request, call_next):
    rules = RATE_LIMITS.get(request.url.path)
    if request.method == "POST" and rules:
        try:
            security.enforce(request, request.url.path, rules)
        except HTTPException as e:
            return JSONResponse({"detail": e.detail}, status_code=e.status_code)
    return await call_next(request)


@app.middleware("http")
async def security_headers(request, call_next):
    """Baseline security headers on every response (values: backend/security.py)."""
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    # Framing is controlled by CSP frame-ancestors ONLY. We deliberately do
    # not send X-Frame-Options: it has no allowlist form (only DENY /
    # SAMEORIGIN), so `XFO: DENY` next to a permissive frame-ancestors does
    # NOT "fall through" to the CSP on modern browsers — XFO wins and blocks
    # every embed, including the trusted nabilvs.com case-study page (this
    # was a real bug: the embedded map rendered blank).
    resp.headers["Content-Security-Policy"] = security.content_security_policy()
    resp.headers["Content-Security-Policy-Report-Only"] = security.content_security_policy_report_only()
    resp.headers["Referrer-Policy"] = "no-referrer"
    if ENV == "prod":
        resp.headers["Strict-Transport-Security"] = "max-age=31536000"
    # "self" plus nabilvs.com — the case-study page embeds this map in an
    # iframe, and the locate-me button needs geolocation delegated to it
    # there too, not just when this origin is loaded top-level.
    resp.headers["Permissions-Policy"] = (
        'geolocation=(self "https://nabilvs.com" "https://www.nabilvs.com"), '
        "camera=(), microphone=(), payment=(), usb=()"
    )
    return resp


# --------------------------------------------------------------------------- #
# Models                                                                        #
# --------------------------------------------------------------------------- #

class BotFields(BaseModel):
    """Hidden honeypot + optional Turnstile token, on every public form."""
    hp_contact: str = Field(default="", max_length=500)
    turnstile_token: str = Field(default="", max_length=2048)


def _bot_check(body: BotFields, request: Request) -> None:
    security.honeypot(body.hp_contact)
    security.verify_turnstile(body.turnstile_token, request)


class UserReport(BotFields):
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


    @field_validator("category")
    @classmethod
    def _known_categories(cls, v: str) -> str:
        tokens = [t.strip().lower() for t in re.split(r"[,|/]", v or "")]
        tokens = [t for t in tokens if t]
        if not tokens: tokens = ["user_report"]
        for t in tokens:
            if t != "user_report" and t not in lawref.CATEGORIES:
                raise ValueError(f"unknown category {t!r}")
        return ",".join(tokens)

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
    request: Request,
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
    # The whole feed in one call is cheap to scrape. 300 a minute per address
    # is far above one visitor (the map loads it about once a minute) and
    # still leaves room for a mobile carrier or an office sharing one address.
    security.enforce(request, "reports-feed", [(300, 60)])
    limit = max(1, min(limit, 5000))  # headroom above the current ~3.8k public-eligible total
    is_reviewer = bool(user and user["role"] in ("VERIFIER", "ADMIN"))
    reports = db.list_reports(
        limit=limit, located_only=not all, as_of=as_of, viewer_is_reviewer=is_reviewer
    )
    if not is_reviewer:
        for r in reports:
            if r["lat"] is None or r["lon"] is None:
                continue
            sensitive = security.is_sensitive(r["category"])
            if sensitive or r["status"] != "verified":
                radius = SENSITIVE_FUZZ_RADIUS_M if sensitive else DEFAULT_FUZZ_RADIUS_M
                r["lat"], r["lon"] = db.fuzz_coords(r["id"], r["lat"], r["lon"], radius_m=radius)
                r["fuzzed"] = True
    return {"reports": reports}


@app.post("/api/reports", status_code=201)
def post_report(report: UserReport, request: Request):
    """
    Store a user-filed report. Always located (client supplies coords).
    No `url` is ever set for a user submission (the free-text `evidence`
    field isn't a verifiable source), so `db.insert_report` defaults its
    status to 'pending' — held out of the public feed until an ADMIN/
    VERIFIER reviews it. Automated agent-scraped reports (which always cite
    a real source url) still publish immediately as 'unverified' leads.
    """
    _bot_check(report, request)
    new_id = db.insert_report(
        source="user",
        external_id=f"user_{secrets.token_hex(12)}",
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
def get_own_report(report_id: int, x_edit_token: str = Header(default="")):
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
    # Header only: URLs end up in access logs. (The old ?edit_token= form is
    # gone; a token only works for one hour, so every old link has expired.)
    if not security.token_equal(x_edit_token, existing.get("edit_token")):
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
    if not security.token_equal(body.edit_token, existing.get("edit_token")):
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
    report_id: int, user: dict = Depends(auth.require_role("ADMIN", "VERIFIER")),
):
    """Full edit trail for one report — who changed what, when."""
    if db.get_report(report_id) is None:
        raise HTTPException(status_code=404, detail="Report not found")
    rows = db.get_report_history(report_id)
    if user["role"] != "ADMIN":
        rows = [{**row, "edited_by": security.mask_moderator(row.get("edited_by") or "")} for row in rows]
    return {"history": rows}


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
def admin_delete_report(report_id: int, user: dict = Depends(auth.require_role("ADMIN"))):
    """Permanently remove a report — ADMIN only (VERIFIER should dismiss instead).
    A content-free record of the deletion is kept (GET /api/admin/deletions)."""
    if not db.delete_report(report_id, deleted_by=user["email"]):
        raise HTTPException(status_code=404, detail="Report not found")
    return {"id": report_id, "status": "deleted"}


@app.get("/api/admin/deletions")
def admin_list_deletions(limit: int = 200, _: dict = Depends(auth.require_role("ADMIN"))):
    """Who deleted which report and when. No content: see db.report_deletions."""
    return {"deletions": db.list_report_deletions(limit)}


@app.get("/api/admin/duplicates")
def admin_find_duplicates(_: dict = Depends(auth.require_role("ADMIN", "VERIFIER"))):
    """Reports sharing a url with an earlier row — candidates for cleanup."""
    return {"duplicates": db.find_url_duplicates()}


# --------------------------------------------------------------------------- #
# Service API — trusted server-to-server (nabilvs.com Pantheon)               #
# --------------------------------------------------------------------------- #

def require_service(request: Request, x_service_token: str = Header(default="")) -> None:
    if not SERVICE_TOKEN:
        raise HTTPException(status_code=503, detail="Service integration not configured")
    if not security.token_equal(x_service_token, SERVICE_TOKEN):
        # Only FAILED attempts count (10 a minute per visitor), so the token
        # cannot be guessed at speed while nabilvs.com's real traffic, which
        # always carries the right token, is never throttled here.
        security.enforce(request, "service-bad-token", [(10, 60)])
        raise HTTPException(status_code=401, detail="Bad service token")


class ServiceReview(BaseModel):
    status: Literal["verified", "dismissed", "irrelevant", "unverified"]
    # nabilvs.com's HMAC pseudonym for the volunteer ("vol_" + 32 hex).
    # An email is refused, so report_history never holds who volunteers are.
    moderator: str = Field(min_length=1, max_length=200)

    @field_validator("moderator")
    @classmethod
    def _pseudonymous(cls, v: str) -> str:
        if not security.valid_moderator(v):
            raise ValueError("moderator must be a pseudonymous id (vol_<32 hex>)")
        return v
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
    Apply a volunteer's verdict. `moderator` is the reviewer's stable
    pseudonym from nabilvs.com — recorded in report_history so one
    reviewer's verdicts can be audited and reverted together, without the
    history naming a person. Capped per reviewer against brigading by a
    hijacked account (nabilvs.com caps it too).
    """
    if security.limiter.hit(f"service-review:{body.moderator}", 30, 60) or security.limiter.hit(
        f"service-review-hour:{body.moderator}", 300, 3600
    ):
        raise HTTPException(status_code=429, detail="Too many reviews from this reviewer, slow down")
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
    code: str = Field(default="", max_length=16)  # authenticator code, when two-step sign-in is on


def _rate_limit(key: str, limit: int, window: float = 3600.0) -> None:
    """Extra per-route limits on top of the middleware (security.limiter)."""
    if security.limiter.hit(key, limit, window):
        raise HTTPException(status_code=429, detail="Too many attempts — try again later")


def _client_ip(request) -> str:
    return security.client_ip(request)


_DUMMY_HASH: str | None = None


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = db._hash_password(secrets.token_hex(16))
    return _DUMMY_HASH


@app.post("/api/auth/login")
def login(body: LoginBody, response: Response, request: Request):
    _rate_limit(f"login:{_client_ip(request)}", limit=20, window=900)
    # Per-address lockout with backoff (security.py), checked before the
    # password and for addresses with no account too, so a locked unknown
    # address answers exactly like a locked real one.
    ip = _client_ip(request)
    if security.login_locked(body.email, ip):
        raise HTTPException(status_code=429, detail="Too many attempts — try again later")
    user = db.get_user_by_email(body.email)
    if not user:
        # Same PBKDF2 cost as a real check: response time must not reveal
        # which e-mail addresses have accounts.
        db.verify_password(body.password, _dummy_hash())
        security.login_failed(body.email, ip)
        raise HTTPException(status_code=401, detail="Wrong email or password")
    if not db.verify_password(body.password, user["password_hash"]):
        security.login_failed(body.email, ip)
        raise HTTPException(status_code=401, detail="Wrong email or password")
    # Two-step sign-in. Only asked AFTER the password was right, so it tells
    # nobody which accounts exist; a wrong or missing code counts as a failed
    # attempt (the same lockout as a wrong password) and is single-use.
    totp_state = db.get_totp(user["id"])
    if totp_state and totp_state["totp_enabled"]:
        if not body.code.strip():
            raise HTTPException(status_code=401, detail="TOTP_REQUIRED")
        if security.totp_locked(user["id"]):
            raise HTTPException(status_code=429, detail="Too many wrong codes — try again in a few minutes")
        step = totp.verify(totp_state["totp_secret"], body.code, totp_state["totp_last_step"])
        # claim_totp_step is atomic: two logins racing with the same code
        # cannot both win.
        if step is None or not db.claim_totp_step(user["id"], step):
            security.login_failed(body.email, ip)
            security.totp_failed(user["id"])
            raise HTTPException(status_code=401, detail="TOTP_INVALID")
        security.totp_ok(user["id"])
    security.login_ok(body.email, ip)
    token = db.create_session(user["id"])
    auth.set_session_cookie(response, token, user["role"])
    return {"email": user["email"], "role": user["role"], "totp": bool(totp_state and totp_state["totp_enabled"])}


# ---- two-step sign-in management (any signed-in reviewer or admin) ----------

class TotpCode(BaseModel):
    code: str = Field(min_length=6, max_length=16)


class TotpSetupBody(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class TotpDisableBody(TotpCode):
    password: str = Field(min_length=1, max_length=200)


def _password_ok(user: dict, password: str) -> bool:
    full = db.get_user_by_email(user["email"])
    return bool(full) and db.verify_password(password, full["password_hash"])


@app.post("/api/auth/totp/setup")
def totp_setup(
    body: TotpSetupBody, request: Request, user: dict = Depends(auth.require_role("ADMIN", "VERIFIER", allow_without_2fa=True)),
):
    """
    Start enrolment: a new secret (not required at sign-in until confirmed).
    Needs the current PASSWORD: without it, a stolen session could enrol its own
    authenticator and lock the real owner out for good.
    """
    security.enforce(request, "totp-setup", [(10, 3600)], key=str(user["id"]))
    if not _password_ok(user, body.password):
        raise HTTPException(status_code=403, detail="Wrong password")
    state = db.get_totp(user["id"])
    if state and state["totp_enabled"]:
        raise HTTPException(status_code=409, detail="Two-step sign-in is already on; turn it off first")
    secret = totp.new_secret()
    db.set_totp_pending(user["id"], secret)
    return {"secret": secret, "uri": totp.provisioning_uri(secret, user["email"])}


@app.post("/api/auth/totp/enable")
def totp_enable(
    body: TotpCode, request: Request, user: dict = Depends(auth.require_role("ADMIN", "VERIFIER", allow_without_2fa=True)),
    dxmap_session: str = Cookie(default=None),
):
    """Confirm enrolment with a first code from the app. Ends the user's other sessions."""
    security.enforce(request, "totp-confirm", [(10, 600)], key=str(user["id"]))
    state = db.get_totp(user["id"])
    if not state or not state["totp_secret"]:
        raise HTTPException(status_code=409, detail="Start setup first")
    step = totp.verify(state["totp_secret"], body.code, 0)
    if step is None:
        raise HTTPException(status_code=400, detail="That code is not right. Check the clock on your phone.")
    db.enable_totp(user["id"], step)
    db.delete_other_sessions(user["id"], dxmap_session)
    return {"totp": True}


@app.post("/api/auth/totp/disable")
def totp_disable(
    body: TotpDisableBody, request: Request, user: dict = Depends(auth.require_role("ADMIN", "VERIFIER")),
    dxmap_session: str = Cookie(default=None),
):
    """Turn it off: needs the password AND a current code, so a stolen session
    cannot remove it. Ends the user's other sessions."""
    security.enforce(request, "totp-disable", [(10, 600)], key=str(user["id"]))
    if not _password_ok(user, body.password):
        raise HTTPException(status_code=403, detail="Wrong password")
    state = db.get_totp(user["id"])
    if not state or not state["totp_enabled"]:
        raise HTTPException(status_code=409, detail="Two-step sign-in is not on")
    if totp.verify(state["totp_secret"], body.code, state["totp_last_step"]) is None:
        raise HTTPException(status_code=400, detail="That code is not right")
    db.disable_totp(user["id"])
    db.delete_other_sessions(user["id"], dxmap_session)
    return {"totp": False}


@app.post("/api/admin/users/{user_id}/totp/reset")
def admin_reset_totp(user_id: int, user: dict = Depends(auth.require_role("ADMIN"))):
    """
    Recovery for a reviewer who lost their phone: the ADMIN switches their
    two-step sign-in off and ends their sessions. Logged (admin_actions). If the
    ADMIN loses their own device, recover on the server:
      docker compose exec map python -c "import sqlite3; c=sqlite3.connect('/app/data/dxmap.db');
      c.execute('UPDATE users SET totp_enabled=0, totp_secret=NULL WHERE email=?', ('<email>',)); c.commit()"
    """
    target = db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    db.disable_totp(user_id)
    db.delete_other_sessions(user_id, None)
    db.log_admin_action(user["email"], "totp_reset", target["email"])
    return {"id": user_id, "totp": False}


class SignupBody(BotFields):
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
def signup(body: SignupBody, response: Response, request: Request, background: BackgroundTasks):
    """
    Public volunteer sign-up from the map's "Get involved" tab. Creates an
    account with role NONE (no permissions) plus a linked volunteer
    application. An ADMIN then approves it (POST .../applications/{id}
    /approve), which promotes the account to VERIFIER — at which point the
    volunteer sees the review queue on their volunteering page.
    """
    _rate_limit(f"signup:{_client_ip(request)}", limit=5, window=3600)
    _bot_check(body, request)
    uid = db.create_user(body.email, body.password, "NONE", accepted_terms=body.accept,
                         # With no mail setup nobody could ever confirm: do not strand applicants.
                         verified=not mailer.can_send())
    if uid is None:
        # Same answer as for a new account, so the form cannot be used to find
        # out which emails are registered. The person signs in with the password
        # they typed; if the account was not theirs, that sign-in fails.
        return {"email": body.email, "role": "NONE"}
    db.create_application(
        name=body.name, email=body.email, interest="volunteer",
        message=body.message, user_id=uid,
    )
    if mailer.can_send():
        _queue_verification_mail(background, uid, body.email)
    return {"email": body.email, "role": "NONE"}


def _queue_verification_mail(background: BackgroundTasks, user_id: int, email: str) -> None:
    token = db.create_email_token(user_id)
    link = f"{PUBLIC_URL}/api/auth/verify-email?token={token}"
    background.add_task(
        mailer.send, email, "Confirm your email for the Discrimination Map",
        "Hello,\n\nplease confirm this email address to finish your volunteer application "
        f"for the Discrimination Map:\n\n{link}\n\nThe link works once and expires in 48 hours. "
        "If you did not apply, ignore this mail; nothing happens until the link is opened.\n",
    )


@app.get("/api/auth/verify-email")
def verify_email(request: Request, token: str = ""):
    """The link in the mail. Always redirects (never shows whether a token existed)."""
    security.enforce(request, "verify-email", [(20, 600)])
    ok = bool(token) and db.consume_email_token(token) is not None
    return RedirectResponse(f"/?verified={'1' if ok else '0'}", status_code=303)


@app.post("/api/auth/verify-email/resend")
def resend_verification(
    request: Request, background: BackgroundTasks, user: dict = Depends(auth.require_user),
):
    security.enforce(request, "verify-resend", [(3, 3600)], key=str(user["id"]))
    if not db.is_email_verified(user["id"]):
        _queue_verification_mail(background, user["id"], user["email"])
    return {"sent": True}


@app.post("/api/auth/logout")
def logout(response: Response, dxmap_session: str = Cookie(default=None)):
    if dxmap_session:
        db.delete_session(dxmap_session)
    auth.clear_session_cookie(response)
    return {"status": "logged out"}


@app.get("/api/auth/me")
def me(user: dict = Depends(auth.require_user)):
    full = db.get_user_by_id(user["id"])
    state = db.get_totp(user["id"])
    return {
        "email": user["email"], "role": user["role"], "provider": full["provider"] if full else "email",
        "totp": bool(state and state["totp_enabled"]),
        "verified": bool(full and full.get("email_verified_at")),
    }


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

class ApplicationBody(BotFields):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    interest: Literal["volunteer", "translator", "coder", "organization", "other"]
    message: str = Field(default="", max_length=2000)


@app.post("/api/apply", status_code=201)
def apply(body: ApplicationBody, request: Request):
    """Public — volunteer/translator/coder/organization applications, reviewed from /admin."""
    _bot_check(body, request)
    new_id = db.create_application(
        name=body.name, email=body.email, interest=body.interest, message=body.message,
    )
    return {"id": new_id, "status": "received"}


class SymbolProposalBody(BotFields):
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
def propose_symbol(body: SymbolProposalBody, request: Request):
    """
    Public — reuses the applications table (interest='other', message
    tagged) so a proposed symbol lands in the same /admin review queue as
    volunteer applications, without needing a new table or migration.
    """
    _bot_check(body, request)
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
    # ADMIN only: the table holds every applicant's name, e-mail and free text.
    # A volunteer reviewer must not be able to list the other volunteers.
    status: str | None = None, _: dict = Depends(auth.require_role("ADMIN")),
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
    current: dict = Depends(auth.require_role("ADMIN")),
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
    if role == "VERIFIER" and not row.get("email_verified_at"):
        raise HTTPException(
            status_code=409,
            detail="The applicant has not confirmed their email yet. Ask them to open the link we mailed.",
        )
    if row["user_id"] == current["id"] and role != "ADMIN":
        raise HTTPException(status_code=400, detail="Cannot demote your own account")
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
_GEOCODE_MAX = 2000
_GEOCODE_UA = "discrimination-map/1.0 (+https://map.nabilvs.com)"


@app.get("/api/geocode")
async def geocode(request: Request, q: str = Query(default="", max_length=120)):
    security.enforce(request, "geocode", [(30, 60)])
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
    while len(_GEOCODE_CACHE) > _GEOCODE_MAX:
        _GEOCODE_CACHE.pop(next(iter(_GEOCODE_CACHE)))  # oldest first
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