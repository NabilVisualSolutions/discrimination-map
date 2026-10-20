"""
Abuse protection for the public write endpoints and the service API.

The map documents far-right incidents, so it is a target for organised
trolling: fake reports, mass sign-ups, brigading of the review queue and
scraping. This module holds the pieces every public route shares:

- client_ip():     the real visitor IP behind Cloudflare + Caddy
- RateLimiter:     in-memory sliding windows (valid: one long-lived process)
- honeypot():      a hidden form field people never fill
- verify_turnstile(): Cloudflare Turnstile, ONLY when DXMAP_TURNSTILE_SECRET
                   is set (otherwise skipped, so local dev and tests work)
- valid_moderator(): the pseudonymous reviewer ids nabilvs.com sends

Nothing here logs or stores IPs beyond the in-memory windows.
"""
from __future__ import annotations

import collections
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import time
import urllib.parse
import urllib.request

from fastapi import HTTPException, Request


# --------------------------------------------------------------------------- #
# Client IP                                                                     #
# --------------------------------------------------------------------------- #

def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


# Cloudflare's published edge ranges (https://www.cloudflare.com/ips/),
# checked 2026-10-20. Only a request whose proxy hop is one of these may
# tell us the visitor's IP through CF-Connecting-IP; anyone connecting to
# the origin directly could otherwise pick any IP they like.
CLOUDFLARE_RANGES = [ipaddress.ip_network(n) for n in (
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
    "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32",
    "2405:8100::/32", "2a06:98c0::/29", "2c0f:f248::/32",
)]


def from_cloudflare(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in CLOUDFLARE_RANGES)


def client_ip(request: Request) -> str:
    """
    The visitor's IP. Path in production: visitor -> Cloudflare -> Caddy ->
    this app. Caddy has no trusted_proxies, so it REPLACES X-Forwarded-For
    with its peer: a Cloudflare edge address, shared by many visitors.
    Cloudflare puts the real visitor in CF-Connecting-IP.

    So: the proxy hop is the last X-Forwarded-For entry (or the socket peer).
    If that hop is Cloudflare, use CF-Connecting-IP; otherwise the hop itself.
    The old code read the FIRST X-Forwarded-For entry, which a client
    controls, so a script could pick a fresh rate-limit bucket per request.
    """
    xff = request.headers.get("x-forwarded-for", "")
    hop = _valid_ip(xff.split(",")[-1]) if xff else None
    if hop is None:
        hop = request.client.host if request.client else "unknown"
    if from_cloudflare(hop):
        cf = _valid_ip(request.headers.get("cf-connecting-ip", ""))
        if cf:
            return _bucket_ip(cf)
    return _bucket_ip(hop)


def _bucket_ip(ip: str) -> str:
    """An IPv6 customer normally holds a whole /64 (2**64 addresses): keyed
    per address, one client would own an unlimited number of rate-limit
    buckets. IPv6 is therefore keyed on its /64; IPv4 stays per address."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if addr.version == 6:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False).network_address) + "/64"
    return ip


# --------------------------------------------------------------------------- #
# Rate limiting                                                                 #
# --------------------------------------------------------------------------- #

class RateLimiter:
    """Sliding-window counters keyed by an arbitrary string. Bounded in size."""

    MAX_KEYS = 50_000

    def __init__(self) -> None:
        self._hits: dict[str, collections.deque] = {}

    def hit(self, key: str, limit: int, window: float, now: float | None = None) -> bool:
        """Count one hit. Returns True when the caller is over the limit (reject)."""
        now = time.time() if now is None else now
        if len(self._hits) > self.MAX_KEYS:
            self._sweep(now)
        q = self._hits.setdefault(key, collections.deque())
        while q and now - q[0] >= window:
            q.popleft()
        if len(q) >= limit:
            return True
        q.append(now)
        return False

    def _sweep(self, now: float) -> None:
        # Drop keys idle for a day (nothing can still be counting them). If a
        # flood still leaves too many, drop keys idle for 10 minutes: only
        # sub-10-minute windows lose their count, never a key hit just now.
        for idle in (86400, 600):
            if len(self._hits) <= self.MAX_KEYS:
                break
            for k in [k for k, q in self._hits.items() if not q or now - q[-1] > idle]:
                del self._hits[k]

    def reset(self) -> None:
        self._hits.clear()


limiter = RateLimiter()

TOO_MANY = "Too many requests, try again later"


def enforce(request: Request, scope: str, rules: list[tuple[int, float]], key: str | None = None) -> None:
    """
    Apply every (limit, window_seconds) rule to `scope`, keyed by client IP
    (or `key`). Raises 429 on the first one exceeded.
    """
    who = key if key is not None else client_ip(request)
    for limit, window in rules:
        if limiter.hit(f"{scope}:{int(window)}:{who}", limit, window):
            raise HTTPException(status_code=429, detail=TOO_MANY)


# --------------------------------------------------------------------------- #
# Honeypot + Turnstile                                                          #
# --------------------------------------------------------------------------- #

HONEYPOT_FIELD = "hp_contact"  # not a name browsers autofill (a field called "website" is)
BOT_CHECK_FAILED = "Verification failed. Reload the page and try again."


def honeypot(value: str | None) -> None:
    """Reject when the hidden field has a value. People never see it."""
    if value and value.strip():
        raise HTTPException(status_code=400, detail=BOT_CHECK_FAILED)


TURNSTILE_ACTION = "dxmap-submit"


def _turnstile_secret() -> str:
    return os.environ.get("DXMAP_TURNSTILE_SECRET", "").strip()


def turnstile_enabled() -> bool:
    return bool(_turnstile_secret())


def _allowed_hostname(hostname: str) -> bool:
    h = (hostname or "").lower()
    extra = {x.strip().lower() for x in os.environ.get("DXMAP_TURNSTILE_HOSTNAMES", "").split(",") if x.strip()}
    return h == "nabilvs.com" or h.endswith(".nabilvs.com") or h in extra


def _siteverify(secret: str, token: str, ip: str) -> dict:
    data = urllib.parse.urlencode({"secret": secret, "response": token, "remoteip": ip}).encode()
    req = urllib.request.Request(
        "https://challenges.cloudflare.com/turnstile/v0/siteverify", data=data, method="POST"
    )
    with urllib.request.urlopen(req, timeout=8) as resp:  # noqa: S310 — fixed https URL
        return json.loads(resp.read().decode())


# Cloudflare's published test secrets (always pass / always fail / spent).
_TEST_SECRET = re.compile(r"^[123]x0{30,}AA$")


def verify_turnstile(token: str | None, request: Request) -> None:
    """
    Raise 403 unless the token is a valid Turnstile token for this site.
    No-op while DXMAP_TURNSTILE_SECRET is unset (local dev, tests, and
    production until the widget's hostname list includes map.nabilvs.com).
    """
    secret = _turnstile_secret()
    if not secret:
        return
    if not token or len(token) > 4096:
        raise HTTPException(status_code=403, detail=BOT_CHECK_FAILED)
    try:
        result = _siteverify(secret, token, client_ip(request))
    except Exception:  # Cloudflare unreachable: fail closed
        raise HTTPException(status_code=403, detail=BOT_CHECK_FAILED)
    if result.get("success") is not True:
        raise HTTPException(status_code=403, detail=BOT_CHECK_FAILED)
    if _TEST_SECRET.match(secret):
        if os.environ.get("DXMAP_ENV", "prod") == "prod":
            raise HTTPException(status_code=403, detail=BOT_CHECK_FAILED)  # never in production
        return
    if result.get("action") != TURNSTILE_ACTION or not _allowed_hostname(result.get("hostname", "")):
        raise HTTPException(status_code=403, detail=BOT_CHECK_FAILED)


# --------------------------------------------------------------------------- #
# Service-API moderator ids                                                     #
# --------------------------------------------------------------------------- #

# nabilvs.com sends an HMAC pseudonym per volunteer (its
# src/lib/volunteer/pseudonym.ts): "vol_" + 32 hex chars. Never an email,
# so report_history holds no list of who the volunteers are.
PSEUDONYM = re.compile(r"^vol_[0-9a-f]{32}$")


def valid_moderator(moderator: str) -> bool:
    return bool(PSEUDONYM.match(moderator))


# --------------------------------------------------------------------------- #
# Security headers                                                              #
# --------------------------------------------------------------------------- #

def frame_ancestors() -> str:
    """nabilvs.com embeds the map. DXMAP_FRAME_ANCESTORS_EXTRA adds origins
    (local preview: http://localhost:3100) and is only honoured outside prod."""
    base = ["'self'", "https://nabilvs.com", "https://www.nabilvs.com"]
    if os.environ.get("DXMAP_ENV", "prod") != "prod":
        base += [o.strip() for o in os.environ.get("DXMAP_FRAME_ANCESTORS_EXTRA", "").split() if o.strip()]
    return " ".join(base)


def content_security_policy() -> str:
    """Enforced: framing, plugins, <base>. Kept small on purpose: a wrong
    script-src would blank the map, so the full policy below ships as
    Report-Only until a browser run shows no violations."""
    return f"frame-ancestors {frame_ancestors()}; object-src 'none'; base-uri 'self'"


def content_security_policy_report_only() -> str:
    turnstile = " https://challenges.cloudflare.com" if turnstile_enabled() else ""
    return "; ".join([
        "default-src 'self'",
        f"script-src 'self'{turnstile}",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "img-src 'self' data: blob: https:",
        "font-src 'self' data: https://fonts.gstatic.com",
        "connect-src 'self' https://tiles.openfreemap.org https://*.amplitude.com",
        "worker-src 'self' blob:",
        f"frame-src 'self'{turnstile}",
        "form-action 'self'",
    ])


SENSITIVE = {"sexual_violence", "harassment"}  # owner decision 2026-10-20: homophobia_transphobia is NOT blurred

def is_sensitive(category: str) -> bool:
    tokens = [t.strip().lower() for t in re.split(r"[,|/]", category or "")]
    return any(t in SENSITIVE for t in tokens)


_MASK_KEY = secrets.token_bytes(32)


def mask_moderator(edited_by: str) -> str:
    """Opaque, stable-per-process label for a moderator. Applied to EVERY value
    shown to a non-admin, including nabilvs.com's pseudonyms: a pseudonym is
    stable across reports, so unmasked it would let one reviewer follow
    another's verdicts."""
    value = edited_by or ""
    digest = hmac.new(_MASK_KEY, value.lower().encode(), hashlib.sha256).hexdigest()
    return "moderator-" + digest[:8]



# --------------------------------------------------------------------------- #
# Login lockout                                                                 #
# --------------------------------------------------------------------------- #

# Keyed on (typed e-mail, client address), whether or not the account exists,
# so a locked unknown address answers like a locked real one (no account
# enumeration). 5 failures from one address lock THAT address for 60 s,
# doubling per further failure up to 1 h. Keying on the pair, not the e-mail
# alone, is what stops a stranger from keeping the ADMIN locked out: their
# failures lock only their own address.
#
# Spread-out guessing (many addresses, one account) hits a second, per-
# e-mail ceiling: 100 failures in an hour start a 15-minute lock for every
# address EXCEPT ones that signed in successfully within 30 days (the owner's
# usual locations), so the real owner still gets through.
#
# A good login clears the pair and remembers the address. Failures older
# than a day are forgotten. The count is not reset when a lock expires, so a
# persistent guesser climbs to the hour-long lock; that is safe for the owner
# because the pair is keyed on the address (it only ever locks the guesser).
# In memory, per process: valid for one container.
LOCK_FREE_FAILURES = 5
LOCK_BASE_S = 60
LOCK_MAX_S = 3600
LOCK_FORGET_S = 24 * 3600
LOCK_MAX_ENTRIES = 20_000
GLOBAL_FAILS = 100
GLOBAL_WINDOW_S = 3600
GLOBAL_LOCK_S = 900
TRUST_S = 30 * 24 * 3600
TRUST_MAX = 5
_locks: dict[tuple[str, str], dict] = {}
_global: dict[str, dict] = {}
_trusted: dict[str, dict[str, float]] = {}


def _norm(email: str) -> str:
    return (email or "").strip().lower()


def _has_address(ip: str) -> bool:
    # No usable client address: a pair key would collapse to one shared lock per
    # e-mail, which is the stranger-locks-the-owner problem. Never lock then.
    return bool(ip) and ip != "unknown"


def _prune_locks(now: float) -> None:
    # The per-e-mail counters never expire by themselves.
    for k in [k for k, g in _global.items() if now - g["start"] >= GLOBAL_WINDOW_S and g["until"] <= now]:
        del _global[k]
    for k in [k for k, e in _locks.items() if now - e["last"] >= LOCK_FORGET_S]:
        del _locks[k]
    # Over the cap: drop the oldest entries that are NOT locked right now
    # (flooding junk must not clear a victim's lock).
    for k in [k for k, e in _locks.items() if e["until"] <= now]:
        if len(_locks) <= LOCK_MAX_ENTRIES:
            break
        del _locks[k]


def login_locked(email: str, ip: str = "", now: float | None = None) -> bool:
    if not _has_address(ip):
        return False
    now = time.time() if now is None else now
    e = _norm(email)
    pair = _locks.get((e, ip))
    if pair and pair["until"] > now:
        return True
    g = _global.get(e)
    if g and g["until"] > now:
        seen = _trusted.get(e, {}).get(ip)
        return not (seen and now - seen < TRUST_S)
    return False


def login_failed(email: str, ip: str = "", now: float | None = None) -> None:
    if not _has_address(ip):
        return
    now = time.time() if now is None else now
    if len(_locks) > LOCK_MAX_ENTRIES or len(_global) > LOCK_MAX_ENTRIES:
        _prune_locks(now)
    e = _norm(email)
    key = (e, ip)
    p = _locks.get(key)
    if p is None or now - p["last"] >= LOCK_FORGET_S:
        p = {"fails": 0, "until": 0.0, "last": now}
    p["fails"] += 1
    p["last"] = now
    if p["fails"] >= LOCK_FREE_FAILURES:
        p["until"] = now + min(LOCK_BASE_S * 2 ** (p["fails"] - LOCK_FREE_FAILURES), LOCK_MAX_S)
    _locks[key] = p

    g = _global.get(e)
    if g is None or now - g["start"] >= GLOBAL_WINDOW_S:
        g = {"start": now, "n": 0, "until": 0.0}
    g["n"] += 1
    if g["n"] >= GLOBAL_FAILS:
        # Engaging the ceiling spends the count: another GLOBAL_FAILS failures
        # are needed to engage it again, so one stray failure after a lock
        # lapses cannot re-arm it.
        g["until"] = now + GLOBAL_LOCK_S
        g["n"] = 0
        g["start"] = now
    _global[e] = g


def login_ok(email: str, ip: str = "", now: float | None = None) -> None:
    if not _has_address(ip):
        return
    now = time.time() if now is None else now
    e = _norm(email)
    _locks.pop((e, ip), None)
    seen = _trusted.setdefault(e, {})
    seen[ip] = now
    while len(seen) > TRUST_MAX:
        del seen[min(seen, key=seen.get)]


def reset_login_locks() -> None:
    _locks.clear()
    _global.clear()
    _trusted.clear()


# --------------------------------------------------------------------------- #
# Constant-time compare that cannot raise                                       #
# --------------------------------------------------------------------------- #

def token_equal(supplied: str | None, stored: str | None) -> bool:
    """False for empty values on either side; compares bytes so non-ASCII
    text cannot raise TypeError (which answered 500 instead of 401/403)."""
    if not supplied or not stored:
        return False
    return secrets.compare_digest(supplied.encode("utf-8", "replace"), stored.encode("utf-8", "replace"))


def origin_allowed(origin: str, host: str, extra: list[str]) -> bool:
    """Cross-site write check: Origin must be this host, or listed explicitly."""
    try:
        netloc = urllib.parse.urlparse(origin).netloc.lower()
    except ValueError:
        return False
    return bool(netloc) and (netloc == (host or "").lower() or origin.rstrip("/") in extra)
