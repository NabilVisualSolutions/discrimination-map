"""
Session-cookie auth with three roles: NONE (no permissions — vestigial;
nothing creates these anymore since public self-registration was removed),
VERIFIER (can verify/dismiss reports), ADMIN (full control, incl. inviting/
removing users and hard-deleting reports). There is no public sign-up here:
volunteer applications go through nabilvs.com's own form, and an ADMIN
invites reviewers directly via POST /api/admin/users. Only /admin has a
login at all — the public map has none.

Bootstrap: on startup, if no ADMIN exists yet and DXMAP_ADMIN_EMAIL +
DXMAP_ADMIN_PASSWORD are both set, create that admin. Otherwise admin
management stays fail-closed — same philosophy as the old ADMIN_TOKEN
default (unset = nobody gets in), just extended to real accounts.
"""
from __future__ import annotations

import os

from fastapi import Cookie, HTTPException, Response

import db

SESSION_COOKIE = "dxmap_session"
# Secure-only cookies require HTTPS. Prod is always behind Cloudflare/Caddy
# TLS; dev/test run over plain http, where a Secure cookie would silently
# never be sent back by the browser (or by TestClient), breaking login.
SECURE_COOKIE = os.environ.get("DXMAP_ENV", "dev") == "prod"


def bootstrap_admin() -> None:
    """Create the first admin from env vars, once, if none exists yet."""
    if db.count_users(role="ADMIN") > 0:
        return
    email = os.environ.get("DXMAP_ADMIN_EMAIL", "").strip()
    password = os.environ.get("DXMAP_ADMIN_PASSWORD", "").strip()
    if not email or not password:
        return
    db.create_user(email, password, "ADMIN")


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=db.SESSION_TTL_SECONDS, httponly=True, samesite="lax",
        secure=SECURE_COOKIE, path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def get_current_user(dxmap_session: str = Cookie(default=None)) -> dict | None:
    """Optional-auth dependency: returns the user dict or None, never raises.
    Use this where a route's response just changes shape when logged in
    (e.g. exact vs. fuzzed coordinates)."""
    return db.get_session_user(dxmap_session) if dxmap_session else None


def require_user(dxmap_session: str = Cookie(default=None)) -> dict:
    """Any logged-in user (ADMIN or VERIFIER)."""
    user = db.get_session_user(dxmap_session) if dxmap_session else None
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_role(*roles: str):
    """Dependency factory: 401 if not logged in, 403 if role isn't allowed."""
    def _dep(dxmap_session: str = Cookie(default=None)) -> dict:
        user = db.get_session_user(dxmap_session) if dxmap_session else None
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Not permitted for this role")
        return user
    return _dep
