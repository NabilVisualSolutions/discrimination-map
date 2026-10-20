"""
Time-based one-time passwords (RFC 6238) with the standard library only, for
two-step sign-in with any authenticator app (Aegis, Google Authenticator,
1Password, ...): 6 digits, 30-second steps, HMAC-SHA1 (what every app speaks).

A code is accepted for the current step and one step either side (clock drift)
and never twice: the caller keeps the last accepted step per user.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

STEP_S = 30
DIGITS = 6
WINDOW = 1  # steps either side of now


def new_secret() -> str:
    """160 random bits as base32 (what authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    mac = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    n = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return str(n).zfill(DIGITS)


def verify(secret: str, code: str, last_step: int = 0, now: float | None = None) -> int | None:
    """
    Return the step the code matched (store it as the new last_step), or None.
    A step <= last_step is refused: one code, one use.
    """
    if not secret:
        return None
    code = (code or "").strip().replace(" ", "")
    if not (code.isdigit() and len(code) == DIGITS):
        return None
    current = int((time.time() if now is None else now) // STEP_S)
    hit = None
    for step in range(current - WINDOW, current + WINDOW + 1):
        # compare every step (no early exit) so timing does not say which matched
        if hmac.compare_digest(_code(secret, step), code) and step > last_step:
            hit = step
    return hit


def provisioning_uri(secret: str, account: str, issuer: str = "Discrimination Map") -> str:
    label = urllib.parse.quote(f"{issuer}:{account}")
    q = urllib.parse.urlencode({"secret": secret, "issuer": issuer, "digits": DIGITS, "period": STEP_S})
    return f"otpauth://totp/{label}?{q}"
