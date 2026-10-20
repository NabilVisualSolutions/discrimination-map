"""
"Sign in with Google" for people who already have an account here (ADMIN or
VERIFIER). It never creates an account: the Google email must match an
existing user and Google must say the email is verified.

Settings (server .env): DXMAP_GOOGLE_CLIENT_ID, DXMAP_GOOGLE_CLIENT_SECRET.
Redirect URI to register in Google Cloud: <DXMAP_PUBLIC_URL>/api/auth/google/callback
Off while the client id or secret is unset.

Standard authorization-code flow: a random `state` kept in a short-lived
HttpOnly cookie guards against forged callbacks; the code is exchanged
server to server over TLS, and the returned id_token is checked for audience,
issuer, expiry and email_verified (no signature check is needed for a token
received straight from Google's token endpoint, per OpenID Connect core 3.1.3.7).
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import time
import urllib.parse
import urllib.request

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
STATE_COOKIE = "dxmap_oauth"


def client_id() -> str:
    return os.environ.get("DXMAP_GOOGLE_CLIENT_ID", "").strip()


def _secret() -> str:
    return os.environ.get("DXMAP_GOOGLE_CLIENT_SECRET", "").strip()


def enabled() -> bool:
    return bool(client_id() and _secret())


def new_state() -> str:
    return secrets.token_urlsafe(24)


def authorize_url(state: str, redirect_uri: str) -> str:
    q = urllib.parse.urlencode({
        "client_id": client_id(), "redirect_uri": redirect_uri, "response_type": "code",
        "scope": "openid email", "state": state, "prompt": "select_account",
    })
    return f"{AUTH_URL}?{q}"


def _exchange(code: str, redirect_uri: str) -> dict:
    data = urllib.parse.urlencode({
        "code": code, "client_id": client_id(), "client_secret": _secret(),
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 - fixed https URL
        return json.loads(r.read())


def _claims(id_token: str) -> dict:
    payload = id_token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def email_from_code(code: str, redirect_uri: str) -> str | None:
    """The verified email Google vouches for, or None on any problem."""
    try:
        claims = _claims(_exchange(code, redirect_uri)["id_token"])
    except Exception:  # noqa: BLE001 - any failure means: not signed in
        return None
    if claims.get("aud") != client_id():
        return None
    if claims.get("iss") not in ("https://accounts.google.com", "accounts.google.com"):
        return None
    if int(claims.get("exp", 0)) < time.time():
        return None
    if claims.get("email_verified") is not True:
        return None
    email = str(claims.get("email", "")).strip().lower()
    return email or None
