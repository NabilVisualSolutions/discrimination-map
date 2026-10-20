"""
Audit fixes, database / scraper layer (backend/db.py, geolocate.py, agent.py,
selfcheck.py). Written before the fixes: each test names the audit finding.
"""
import inspect
import math
import os
import sys
import tempfile
import hashlib

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ.setdefault("DXMAP_DB_PATH", _TMP.name)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import agent  # noqa: E402
import db  # noqa: E402
import geolocate  # noqa: E402
import selfcheck  # noqa: E402

db.init_db()


def _metres(lat1, lon1, lat2, lon2):
    dlat = (lat2 - lat1) * 111_320
    dlon = (lon2 - lon1) * 111_320 * math.cos(math.radians(lat1))
    return math.hypot(dlat, dlon)


def _legacy_fuzz(report_id, lat, lon, radius_m):
    """The old, public formula: anyone could recompute and subtract it."""
    h = hashlib.sha256(f"dxmap-fuzz-{report_id}".encode()).digest()
    angle = (int.from_bytes(h[:4], "big") / 0xFFFFFFFF) * 2 * math.pi
    frac = int.from_bytes(h[4:8], "big") / 0xFFFFFFFF
    dist = radius_m * math.sqrt(frac)
    return (round(lat + (dist * math.cos(angle)) / 111_320, 6),
            round(lon + (dist * math.sin(angle)) / (111_320 * math.cos(math.radians(lat)) or 1), 6))


# ---- AUDIT-02: the blur must not be reversible ------------------------------

def test_fuzz_secret_is_persisted_and_strong():
    a = db.get_fuzz_secret()
    assert isinstance(a, bytes) and len(a) >= 32
    assert db.get_fuzz_secret() == a  # stable across calls (and restarts: stored in the DB)


def test_fuzz_is_not_the_old_public_formula():
    for rid in (1, 7, 123):
        assert db.fuzz_coords(rid, 52.52, 13.40, 5000) != _legacy_fuzz(rid, 52.52, 13.40, 5000)


def test_fuzz_is_stable_per_report_and_stays_inside_the_radius():
    a = db.fuzz_coords(42, 52.52, 13.40, 500)
    assert a == db.fuzz_coords(42, 52.52, 13.40, 500)
    assert _metres(52.52, 13.40, *a) <= 502


def test_fuzz_depends_on_the_secret(monkeypatch):
    before = db.fuzz_coords(9, 48.14, 11.58, 5000)
    monkeypatch.setattr(db, "get_fuzz_secret", lambda: b"another-secret-another-secret-123")
    assert db.fuzz_coords(9, 48.14, 11.58, 5000) != before


# ---- AUDIT-04: nothing in the public feed ties a report to a request log ----

def _report(**kw):
    base = dict(source="user", external_id="user_1700000000123", title="Title", body="b",
                category="banned_symbol", reason="r", evidence="", law=None, impact="",
                lat=52.5, lon=13.4, place="x", status="verified", created_at=1_700_000_123)
    base.update(kw)
    rid = db.insert_report(**base)
    assert rid is not None
    return rid


def test_public_feed_has_no_external_id():
    _report(external_id="user_1700000000124")
    rows = db.list_reports(limit=50, viewer_is_reviewer=False)
    assert rows and all("external_id" not in r for r in rows)


def test_public_feed_coarsens_user_report_timestamps():
    _report(external_id="user_1700000000125", created_at=1_700_000_123)
    rows = [r for r in db.list_reports(limit=500, viewer_is_reviewer=False) if r["source"] == "user"]
    assert rows and all(r["created_at"] % 900 == 0 for r in rows)


def test_reviewer_feed_keeps_exact_timestamps():
    rid = _report(external_id="user_1700000000126", created_at=1_700_000_124)
    rows = {r["id"]: r for r in db.list_reports(limit=500, viewer_is_reviewer=True)}
    assert rows[rid]["created_at"] == 1_700_000_124


def test_scraped_report_timestamps_are_untouched():
    rid = _report(source="bluesky", external_id="at://x/1", url="https://bsky.app/x/1", created_at=1_700_000_125)
    rows = {r["id"]: r for r in db.list_reports(limit=500, viewer_is_reviewer=False)}
    assert rows[rid]["created_at"] == 1_700_000_125


# ---- AUDIT-14: scraped URLs must be http(s) ---------------------------------

def test_non_http_urls_are_rejected():
    for bad in ("javascript:alert(1)", "data:text/html,x", "ftp://example.org/x", "//example.org/x"):
        assert db.insert_report(source="mastodon", external_id=f"bad-{bad}", title="t", url=bad,
                                category="banned_symbol", lat=52.5, lon=13.4) is None


def test_http_and_https_urls_are_accepted():
    assert db.insert_report(source="mastodon", external_id="ok-https", title="t", url="https://example.org/ok1",
                            category="banned_symbol", lat=52.5, lon=13.4) is not None
    assert db.insert_report(source="mastodon", external_id="ok-http", title="t", url="http://example.org/ok2",
                            category="banned_symbol", lat=52.5, lon=13.4) is not None


# ---- AUDIT-15: scraped text must not publish a street address ---------------

def test_coarsen_rounds_to_about_a_kilometre():
    assert geolocate.coarsen(52.520008, 13.404954) == (52.52, 13.40)
    assert geolocate.coarsen(-33.8688, 151.2093) == (-33.87, 151.21)


# ---- AUDIT-13 / minor: self-check must not block the event loop; no key leaks

def test_selfcheck_loop_runs_blocking_work_in_a_thread():
    assert "to_thread" in inspect.getsource(selfcheck.selfcheck_loop)


def test_agent_redacts_secrets_in_error_text():
    out = agent.redact_secrets("GET https://www.googleapis.com/x?part=id&key=AIzaSECRET123&q=a failed")
    assert "AIzaSECRET123" not in out and "key=REDACTED" in out and "q=a" in out
    out = agent.redact_secrets("https://x.example/y?api_key=abc&token=def&secret=ghi&ok=1")
    assert "abc" not in out and "def" not in out and "ghi" not in out and "ok=1" in out
