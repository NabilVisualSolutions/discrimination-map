"""
Same-origin satellite tile proxy: GET /tiles/sat/{z}/{x}/{y}.jpg

Why: the SAT view used to load NASA GIBS tiles straight from the visitor's
browser, so a US agency received the IP address of every satellite-view
visitor. Now the browser only talks to this server; this server fetches the
public-domain imagery and caches it.

What leaves this server toward NASA: one HTTPS GET for a tile path and our own
identifying User-Agent. No visitor IP, Referer, User-Agent, cookie or any other
visitor header is forwarded. No redirects are followed (the upstream host is a
one-entry allow-list). Visitor IPs are used only as in-memory rate-limit keys
(security.limiter) and are never logged here.

Cache: in memory, bounded by bytes and entries, TTL taken from the upstream
Cache-Control max-age (clamped), 24 h when absent. Errors are not cached.
"""
from __future__ import annotations

import asyncio
import collections
import re
import threading
import time
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

import security

ALLOWED_HOST = "gibs.earthdata.nasa.gov"
LAYER = "BlueMarble_ShadedRelief_Bathymetry"
MATRIX_SET = "GoogleMapsCompatible_Level8"
MAX_Z = 8
USER_AGENT = "dxmap-tile-proxy/1.0 (+https://map.nabilvs.com/privacy; contact via site imprint)"
UPSTREAM_TIMEOUT = httpx.Timeout(6.0, connect=3.0)
MAX_TILE_BYTES = 512 * 1024
# Upstream budget for the whole process: at most this many NASA requests in
# flight; beyond it a tile is answered 503 at once instead of queueing threads.
MAX_UPSTREAM_INFLIGHT = 6

CACHE_MAX_BYTES = 64 * 1024 * 1024
CACHE_MAX_ENTRIES = 4000
TTL_DEFAULT = 24 * 3600
TTL_MIN = 3600
TTL_MAX = 7 * 24 * 3600
BROWSER_MAX_AGE = 24 * 3600

# Per client IP, counted in memory only (600 a minute, 6000 an hour in sat_tile).

router = APIRouter()

_lock = threading.Lock()
_cache: "collections.OrderedDict[tuple[int, int, int], tuple[float, bytes]]" = collections.OrderedDict()
_cache_bytes = 0


def upstream_url(z: int, x: int, y: int) -> str:
    return (
        f"https://{ALLOWED_HOST}/wmts/epsg3857/best/{LAYER}/default/{MATRIX_SET}/{z}/{y}/{x}.jpeg"
    )


def valid_coords(z: int, x: int, y: int) -> bool:
    return 0 <= z <= MAX_Z and 0 <= x < (1 << z) and 0 <= y < (1 << z)


def reset_cache() -> None:
    global _cache_bytes
    with _lock:
        _cache.clear()
        _cache_bytes = 0


def _cache_get(key):
    with _lock:
        hit = _cache.get(key)
        if not hit:
            return None
        if hit[0] <= time.time():
            _drop(key)
            return None
        _cache.move_to_end(key)
        return hit[1]


def _drop(key) -> None:
    global _cache_bytes
    old = _cache.pop(key, None)
    if old:
        _cache_bytes -= len(old[1])


def _cache_put(key, body: bytes, ttl: int) -> None:
    global _cache_bytes
    with _lock:
        _drop(key)
        _cache[key] = (time.time() + ttl, body)
        _cache_bytes += len(body)
        while _cache and (_cache_bytes > CACHE_MAX_BYTES or len(_cache) > CACHE_MAX_ENTRIES):
            _drop(next(iter(_cache)))


def _ttl_from(headers) -> int:
    m = re.search(r"max-age=(\d+)", headers.get("cache-control", "") or "")
    if "no-store" in (headers.get("cache-control", "") or "").lower():
        return TTL_MIN
    ttl = int(m.group(1)) if m else TTL_DEFAULT
    return max(TTL_MIN, min(TTL_MAX, ttl))


# asyncio primitives belong to one event loop; keep one set per running loop
# (the app has one loop, the test client may have several).
_loop_state: "dict[int, tuple[asyncio.Semaphore, dict]]" = {}


def _state():
    loop = asyncio.get_running_loop()
    st = _loop_state.get(id(loop))
    if st is None:
        _loop_state.clear()          # a new loop means the old one is gone
        st = _loop_state[id(loop)] = (asyncio.Semaphore(MAX_UPSTREAM_INFLIGHT), {})
    return st


async def fetch_upstream(url: str) -> tuple[int, bytes, dict]:
    """The only network call. Allow-listed host, no redirects, no cookies, fixed
    headers, identity encoding. The body is read as a stream and abandoned the
    moment it passes MAX_TILE_BYTES, so an oversize response is never buffered."""
    if urlsplit(url).hostname != ALLOWED_HOST:  # defence in depth
        raise ValueError("host not allowed")
    async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT, follow_redirects=False, trust_env=False) as c:
        async with c.stream("GET", url, headers={"User-Agent": USER_AGENT, "Accept": "image/jpeg",
                                                 "Accept-Encoding": "identity"}) as r:
            declared = r.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > MAX_TILE_BYTES:
                raise ValueError("tile too large")
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf += chunk
                if len(buf) > MAX_TILE_BYTES:
                    raise ValueError("tile too large")
            return r.status_code, bytes(buf), dict(r.headers)


@router.get("/tiles/sat/{z}/{x}/{y}.jpg")
async def sat_tile(z: int, x: int, y: int, request: Request) -> Response:
    if security.limiter.hit(f"tiles:{security.client_ip(request)}", 600, 60) or security.limiter.hit(
        f"tiles-h:{security.client_ip(request)}", 6000, 3600
    ):
        raise HTTPException(status_code=429, detail=security.TOO_MANY)
    if not valid_coords(z, x, y):
        raise HTTPException(status_code=404, detail="no such tile")
    headers = {
        "Cache-Control": f"public, max-age={BROWSER_MAX_AGE}",
        "Content-Type": "image/jpeg",
    }
    key = (z, x, y)
    body = _cache_get(key)
    if body is None:
        sem, locks = _state()
        # Single flight: concurrent misses for one tile share one upstream call.
        entry = locks.setdefault(key, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with entry[0]:
                body = _cache_get(key)       # the leader may have filled it while we waited
                if body is None:
                    if sem.locked():         # global budget used up: fail fast, hold no thread
                        raise HTTPException(status_code=503, detail="tile source busy",
                                            headers={"Retry-After": "5"})
                    async with sem:
                        try:
                            status, body, up_headers = await fetch_upstream(upstream_url(z, x, y))
                        except Exception:  # timeout, DNS, oversize: do not leak details
                            raise HTTPException(status_code=502, detail="tile source unavailable") from None
                    if status == 404:
                        raise HTTPException(status_code=404, detail="no such tile")
                    if status != 200 or not body.startswith(b"\xff\xd8"):
                        raise HTTPException(status_code=502, detail="tile source unavailable")
                    _cache_put(key, body, _ttl_from(up_headers))
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                locks.pop(key, None)
    return Response(content=body, media_type="image/jpeg", headers=headers)
