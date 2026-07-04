"""
Tests for the Hermes far-right incident monitor (Germany).

Run from the project root:  python -m pytest -q tests
The self-check loop runs exactly this suite on each tick.
"""
import os
import sys
import tempfile

# Isolated temp DB so tests never touch real data.
_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["HERMES_DB_PATH"] = _TMP.name

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from fastapi.testclient import TestClient  # noqa: E402
import app as app_module  # noqa: E402
import db  # noqa: E402
import geolocate  # noqa: E402
import lawref  # noqa: E402

db.init_db()
client = TestClient(app_module.app)


# ---------------- geolocation ----------------

def test_gazetteer_hits_german_city():
    hit = geolocate.from_gazetteer("Hakenkreuz an Wand in Berlin gesprüht")
    assert hit is not None
    lat, lon, place = hit
    assert geolocate.in_germany(lat, lon)
    assert "Berlin" in place


def test_in_germany_bounding_box():
    assert geolocate.in_germany(52.52, 13.40)      # Berlin
    assert not geolocate.in_germany(51.5074, -0.1278)  # London -> outside DE


def test_gazetteer_miss_returns_none():
    assert geolocate.from_gazetteer("qwerty zxcvb noplace") is None


# ---------------- classifier (lawref) ----------------

def test_classify_flags_banned_symbol():
    v = lawref.classify("Neonazis zeigen Hakenkreuz und rufen Sieg Heil in Dortmund")
    assert v["relevant"] is True
    assert v["law_code"] == "StGB-86a"


def test_classify_ignores_unrelated_post():
    v = lawref.classify("Beautiful sunny morning walk along the river in Munich")
    assert v["relevant"] is False
    assert v["law_code"] is None


def test_classify_march_is_monitoring_not_crime():
    # A far-right march is relevant to monitor but not itself an offence.
    v = lawref.classify("Angekündigter Naziaufmarsch am Samstag in Leipzig")
    assert v["relevant"] is True
    assert v["law_code"] is None


# ---------------- reports API ----------------

def test_post_and_get_user_report_with_documentation():
    payload = {
        "title": "Swastika on memorial",
        "reason": "Swastika sprayed on a memorial overnight",
        "evidence": "https://example.org/photo",
        "law": "StGB-86a",
        "impact": "Targeted the local Jewish community; deeply intimidating.",
        "category": "banned_symbol",
        "lat": 52.52, "lon": 13.40,
    }
    r = client.post("/api/reports", json=payload)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "stored"
    assert body["verified"] is False  # user reports await review

    reasons = [rep["reason"] for rep in client.get("/api/reports").json()["reports"]]
    assert "Swastika sprayed on a memorial overnight" in reasons


def test_post_rejects_unknown_law_code():
    bad = {"title": "x", "reason": "something happened", "law": "StGB-9999",
           "lat": 52.5, "lon": 13.4}
    assert client.post("/api/reports", json=bad).status_code == 422


def test_post_rejects_bad_coordinates():
    bad = {"title": "x", "reason": "off the globe", "lat": 999, "lon": 0}
    assert client.post("/api/reports", json=bad).status_code == 422


def test_post_rejects_short_reason():
    bad = {"title": "x", "reason": "hi", "lat": 52.5, "lon": 13.4}
    assert client.post("/api/reports", json=bad).status_code == 422


# ---------------- laws / health / heartbeat ----------------

def test_laws_endpoint_returns_statutes():
    r = client.get("/api/laws")
    assert r.status_code == 200
    laws = r.json()["laws"]
    assert "StGB-86a" in laws and "title_en" in laws["StGB-86a"]


def test_health_endpoint_shape():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "stats" in body and "sources" in body


def test_heartbeat_endpoint_shape():
    r = client.get("/api/heartbeat")
    assert r.status_code == 200
    assert "beat_count" in r.json()


# ---------------- security headers ----------------

def test_security_headers_present():
    r = client.get("/api/health")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert "referrer-policy" in {k.lower() for k in r.headers}
