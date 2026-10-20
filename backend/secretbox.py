"""
Small authenticated-encryption helper for secrets stored at rest (stdlib only).

Format: 'v1:' + base64url(nonce16 + ciphertext + mac32)
Cipher: HMAC-SHA256 in counter mode as a keystream, XORed with the plaintext.
Integrity: encrypt-then-MAC with HMAC-SHA256 over nonce + ciphertext.
Values without the 'v1:' prefix are legacy plaintext and pass through open_.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

_PREFIX = "v1:"
_DEV_FALLBACK = "dxmap-dev-only-secretbox-key"


def _master() -> bytes:
    token = os.environ.get("DXMAP_SERVICE_TOKEN", "")
    if not token:
        if os.environ.get("DXMAP_ENV", "prod") == "prod":
            raise RuntimeError("DXMAP_SERVICE_TOKEN is required in prod to protect secrets")
        token = _DEV_FALLBACK
    return token.encode()


def _keys() -> tuple[bytes, bytes]:
    m = _master()
    return (
        hmac.new(m, b"dxmap-secretbox-enc-v1", hashlib.sha256).digest(),
        hmac.new(m, b"dxmap-secretbox-mac-v1", hashlib.sha256).digest(),
    )


def _stream(key: bytes, nonce: bytes, n: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < n:
        out += hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:n])


def seal(plain: str) -> str:
    enc, mac = _keys()
    nonce = os.urandom(16)
    data = plain.encode("utf-8")
    ct = bytes(a ^ b for a, b in zip(data, _stream(enc, nonce, len(data))))
    tag = hmac.new(mac, nonce + ct, hashlib.sha256).digest()
    return _PREFIX + base64.urlsafe_b64encode(nonce + ct + tag).decode("ascii")


def open_(token: str) -> str:
    if not token.startswith(_PREFIX):
        return token  # legacy plaintext
    try:
        raw = base64.urlsafe_b64decode(token[len(_PREFIX):].encode("ascii"))
    except Exception as exc:
        raise ValueError("malformed secret") from exc
    if len(raw) < 16 + 32:
        raise ValueError("malformed secret")
    nonce, ct, tag = raw[:16], raw[16:-32], raw[-32:]
    enc, mac = _keys()
    if not hmac.compare_digest(tag, hmac.new(mac, nonce + ct, hashlib.sha256).digest()):
        raise ValueError("secret failed integrity check")
    data = bytes(a ^ b for a, b in zip(ct, _stream(enc, nonce, len(ct))))
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("malformed secret") from exc
