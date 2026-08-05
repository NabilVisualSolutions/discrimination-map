"""
Discrimination Map (dxmap) — FastAPI application.

One process serves the JSON API, the static frontend, and launches two
background loops on startup: the monitoring agent's heartbeat and the
self-check.
"""
from __future__ import annotations

import asyncio
import os
import secrets
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

import agent
import db
import lawref
import selfcheck

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
ENV = os.environ.get("DXMAP_ENV", "dev")
ALLOW_ORIGINS = os.environ.get("DXMAP_ALLOW_ORIGINS", "*").split(",")
ADMIN_TOKEN = os.environ.get("DXMAP_ADMIN_TOKEN", "").strip()


def require_admin(authorization: str = Header(default="")) -> None:
    """
    Single shared-secret bearer token — this is a one-operator moderation
    tool, not a multi-user system, so a full auth stack would be overhead
    without adding real security. Set DXMAP_ADMIN_TOKEN in the environment;
    unset means admin routes are disabled entirely (fail closed, not open).
    """
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="Admin not configured")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token, ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")

# Background task handles, so we can cancel them cleanly on shutdown.
_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Init DB and start the heartbeat + self-check loops on boot."""
    db.init_db()
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


@app.middleware("http")
async def security_headers(request, call_next):
    """Set baseline security headers on every response."""
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    # Legacy fallback for browsers that don't understand CSP frame-ancestors —
    # modern browsers use the CSP directive below instead, which allows the
    # one trusted parent site (the case-study page embeds this map) while
    # still blocking everyone else, same as DENY did.
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Content-Security-Policy"] = (
        "frame-ancestors 'self' https://nabilvs.com https://www.nabilvs.com"
    )
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "geolocation=(self)"
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
    category: str = Field(default="user_report", max_length=50)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)

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

@app.get("/api/reports")
def get_reports(limit: int = 500, all: bool = False):
    """Return recent reports. By default only mapped (located) ones."""
    limit = max(1, min(limit, 1000))
    return {"reports": db.list_reports(limit=limit, located_only=not all)}


@app.post("/api/reports", status_code=201)
def post_report(report: UserReport):
    """Store a user-filed report. Always located (client supplies coords)."""
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
        verified=False,           # user reports await moderation before "verified"
        lat=report.lat, lon=report.lon,
        place="user-reported",
    )
    if new_id is None:
        raise HTTPException(status_code=409, detail="Duplicate report")
    return {"id": new_id, "status": "stored", "verified": False}


class VerifyUpdate(BaseModel):
    verified: bool


@app.get("/api/admin/reports")
def admin_list_reports(
    limit: int = 100, offset: int = 0, verified: bool | None = None,
    _: None = Depends(require_admin),
):
    """Every report, located or not, for the moderation queue."""
    limit = max(1, min(limit, 500))
    return db.list_reports_admin(limit=limit, offset=offset, verified=verified)


@app.patch("/api/admin/reports/{report_id}")
def admin_verify_report(report_id: int, body: VerifyUpdate, _: None = Depends(require_admin)):
    """Mark a report verified (or revert it) after human review."""
    if not db.set_verified(report_id, body.verified):
        raise HTTPException(status_code=404, detail="Report not found")
    return {"id": report_id, "verified": body.verified}


@app.delete("/api/admin/reports/{report_id}")
def admin_delete_report(report_id: int, _: None = Depends(require_admin)):
    """Remove a report — spam, false positive, or a takedown request."""
    if not db.delete_report(report_id):
        raise HTTPException(status_code=404, detail="Report not found")
    return {"id": report_id, "status": "deleted"}


@app.get("/api/admin/duplicates")
def admin_find_duplicates(_: None = Depends(require_admin)):
    """Reports sharing a url with an earlier row — candidates for cleanup."""
    return {"duplicates": db.find_url_duplicates()}


@app.get("/api/laws")
def laws():
    """The statute reference the UI uses for the law dropdown and popups."""
    return {"laws": lawref.STATUTES}


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
