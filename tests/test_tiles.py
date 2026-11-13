"""Satellite tile proxy (backend/tiles.py): validation, caching, privacy of the upstream call."""
import os
import sys
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ.setdefault("DXMAP_DB_PATH", _TMP.name)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402
import db  # noqa: E402
import security  # noqa: E402
import tiles  # noqa: E402

db.init_db()
client = TestClient(app_module.app)
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100


@pytest.fixture(autouse=True)
def _reset():
    security.limiter.reset()
    tiles.reset_cache()
    yield


def _stub(monkeypatch, status=200, body=JPEG, headers=None, calls=None):
    async def fake(url):
        if calls is not None:
            calls.append(url)
        return status, body, headers or {}
    monkeypatch.setattr(tiles, "fetch_upstream", fake)


def test_valid_tile_is_served_as_jpeg_with_cache_control(monkeypatch):
    calls = []
    _stub(monkeypatch, calls=calls)
    r = client.get("/tiles/sat/3/4/5.jpg")
    assert r.status_code == 200 and r.content == JPEG
    assert r.headers["content-type"] == "image/jpeg"
    assert "public" in r.headers["cache-control"] and "max-age=" in r.headers["cache-control"]
    assert "set-cookie" not in r.headers
    # WMTS order is z/row(y)/col(x), host is the allow-listed one
    assert calls == [
        "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/3/5/4.jpeg"
    ]


@pytest.mark.parametrize("path", [
    "/tiles/sat/9/0/0.jpg",      # z above 8
    "/tiles/sat/3/8/0.jpg",      # x out of range for z=3
    "/tiles/sat/3/0/8.jpg",      # y out of range
    "/tiles/sat/-1/0/0.jpg",
    "/tiles/sat/3/-1/0.jpg",
])
def test_out_of_range_never_reaches_upstream(monkeypatch, path):
    calls = []
    _stub(monkeypatch, calls=calls)
    assert client.get(path).status_code == 404
    assert calls == []


@pytest.mark.parametrize("path", ["/tiles/sat/a/0/0.jpg", "/tiles/sat/1/0/0.png", "/tiles/sat/1/0/0.jpg/x", "/tiles/sat/1.5/0/0.jpg"])
def test_non_integer_or_wrong_extension_is_rejected(monkeypatch, path):
    calls = []
    _stub(monkeypatch, calls=calls)
    assert client.get(path).status_code in (404, 422)
    assert calls == []


def test_second_request_comes_from_cache(monkeypatch):
    calls = []
    _stub(monkeypatch, calls=calls)
    client.get("/tiles/sat/2/1/1.jpg")
    assert client.get("/tiles/sat/2/1/1.jpg").content == JPEG
    assert len(calls) == 1


def test_errors_are_not_cached(monkeypatch):
    calls = []
    _stub(monkeypatch, status=500, body=b"", calls=calls)
    assert client.get("/tiles/sat/2/1/1.jpg").status_code == 502
    _stub(monkeypatch, calls=calls)
    assert client.get("/tiles/sat/2/1/1.jpg").status_code == 200
    assert len(calls) == 2


def test_upstream_404_maps_to_404_and_non_jpeg_to_502(monkeypatch):
    _stub(monkeypatch, status=404, body=b"nope")
    assert client.get("/tiles/sat/2/1/1.jpg").status_code == 404
    _stub(monkeypatch, body=b"<html>captive portal</html>")
    assert client.get("/tiles/sat/2/1/2.jpg").status_code == 502


def test_upstream_exception_is_502_without_details(monkeypatch):
    async def boom(url):
        raise httpx.ConnectTimeout("secret internal detail")
    monkeypatch.setattr(tiles, "fetch_upstream", boom)
    r = client.get("/tiles/sat/2/1/1.jpg")
    assert r.status_code == 502 and "secret" not in r.text


def test_ttl_follows_upstream_header_within_bounds():
    assert tiles._ttl_from({"cache-control": "max-age=7200"}) == 7200
    assert tiles._ttl_from({"cache-control": "max-age=5"}) == tiles.TTL_MIN
    assert tiles._ttl_from({"cache-control": "max-age=99999999"}) == tiles.TTL_MAX
    assert tiles._ttl_from({}) == tiles.TTL_DEFAULT


def test_cache_is_bounded_by_bytes_and_entries(monkeypatch):
    monkeypatch.setattr(tiles, "CACHE_MAX_ENTRIES", 3)
    for i in range(10):
        tiles._cache_put((8, i, 0), JPEG, 3600)
    assert len(tiles._cache) == 3
    tiles.reset_cache()
    monkeypatch.setattr(tiles, "CACHE_MAX_BYTES", 250)
    for i in range(10):
        tiles._cache_put((8, i, 0), JPEG, 3600)
    assert tiles._cache_bytes <= 250


def test_expired_entry_is_refetched(monkeypatch):
    calls = []
    _stub(monkeypatch, calls=calls)
    client.get("/tiles/sat/2/1/1.jpg")
    key = (2, 1, 1)
    tiles._cache[key] = (0.0, tiles._cache[key][1])  # expired
    client.get("/tiles/sat/2/1/1.jpg")
    assert len(calls) == 2


def test_per_ip_rate_limit(monkeypatch):
    _stub(monkeypatch)
    codes = [client.get("/tiles/sat/1/0/0.jpg", headers={"x-forwarded-for": "203.0.113.9"}).status_code for _ in range(601)]
    assert codes[:600] == [200] * 600 and codes[600] == 429


def test_upstream_call_forwards_nothing_from_the_visitor(monkeypatch):
    seen = {}
    real = httpx.AsyncClient

    def handler(request):
        seen["url"], seen["headers"] = str(request.url), dict(request.headers)
        return httpx.Response(200, content=JPEG, headers={"cache-control": "max-age=3600"})

    class FakeClient(real):
        def __init__(self, **kw):
            seen["client_kw"] = kw
            super().__init__(transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != "trust_env"})

    monkeypatch.setattr(tiles.httpx, "AsyncClient", FakeClient)
    r = client.get("/tiles/sat/1/0/0.jpg", headers={
        "Cookie": "a=b", "Referer": "https://map.nabilvs.com/", "User-Agent": "Visitor/1",
        "X-Forwarded-For": "198.51.100.7", "CF-Connecting-IP": "198.51.100.7",
    })
    assert r.status_code == 200
    assert seen["headers"]["user-agent"] == tiles.USER_AGENT
    assert seen["headers"]["accept-encoding"] == "identity"
    assert "cookie" not in seen["headers"] and "referer" not in seen["headers"]
    assert "198.51.100.7" not in str(seen) and "Visitor" not in str(seen)
    assert seen["client_kw"]["follow_redirects"] is False


def test_fetch_refuses_other_hosts():
    import asyncio
    with pytest.raises(ValueError):
        asyncio.run(tiles.fetch_upstream("https://example.com/x.jpeg"))


def test_oversize_body_is_abandoned_while_streaming(monkeypatch):
    import asyncio
    read = []

    class Endless(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(10_000):                  # 10 GB if anyone kept reading
                read.append(1)
                yield b"x" * 1_000_000

    real = httpx.AsyncClient

    class C(real):
        def __init__(self, **kw):
            super().__init__(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Endless())),
                             **{k: v for k, v in kw.items() if k != "trust_env"})

    monkeypatch.setattr(tiles.httpx, "AsyncClient", C)
    with pytest.raises(ValueError):
        asyncio.run(tiles.fetch_upstream(tiles.upstream_url(1, 0, 0)))
    assert len(read) <= 2                                # stopped after the first MB, not after 10 GB


def test_concurrent_misses_share_one_upstream_fetch(monkeypatch):
    import asyncio
    calls = []

    async def slow(url):
        calls.append(url)
        await asyncio.sleep(0.05)
        return 200, JPEG, {}

    monkeypatch.setattr(tiles, "fetch_upstream", slow)

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_module.app), base_url="http://t") as c:
            return await asyncio.gather(*[c.get("/tiles/sat/3/2/2.jpg") for _ in range(8)])

    rs = asyncio.run(go())
    assert [r.status_code for r in rs] == [200] * 8 and len(calls) == 1


def test_global_budget_fails_fast_with_503(monkeypatch):
    import asyncio
    monkeypatch.setattr(tiles, "MAX_UPSTREAM_INFLIGHT", 2)
    tiles._loop_state.clear()
    gate = {"n": 0, "peak": 0}

    async def slow(url):
        gate["n"] += 1
        gate["peak"] = max(gate["peak"], gate["n"])
        await asyncio.sleep(0.1)
        gate["n"] -= 1
        return 200, JPEG, {}

    monkeypatch.setattr(tiles, "fetch_upstream", slow)

    async def go():
        async with httpx.ASGITransport(app=app_module.app) as tr:
            async with httpx.AsyncClient(transport=tr, base_url="http://t") as c:
                return await asyncio.gather(*[c.get(f"/tiles/sat/4/{i}/1.jpg") for i in range(6)])

    rs = asyncio.run(go())
    codes = sorted(r.status_code for r in rs)
    assert gate["peak"] <= 2 and 503 in codes and codes.count(200) >= 2
    assert all(r.headers.get("retry-after") == "5" for r in rs if r.status_code == 503)
