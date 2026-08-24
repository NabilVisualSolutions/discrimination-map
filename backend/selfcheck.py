"""
Self-check — the safe version of "self-improvement".

On each tick it:
  - runs the pytest suite (tester),
  - audits live security posture (headers, debug flag, DB exposure, CORS),
  - reads per-source health and flags degradations,
  - appends concrete, human-actionable notes to improvements.log.

It deliberately does NOT edit or redeploy code. Autonomous rewriting of running
production code is a security and reliability risk; a human reviews the log.
"""
from __future__ import annotations

import os
import subprocess
import time
from typing import Any

import httpx

import db

LOG_PATH = os.environ.get(
    "DXMAP_IMPROVE_LOG", os.path.join(os.path.dirname(__file__), "improvements.log"))
SELFCHECK_SECONDS = int(os.environ.get("DXMAP_SELFCHECK_SECONDS", "900"))  # 15 min
BASE_URL = os.environ.get("DXMAP_BASE_URL", "http://127.0.0.1:8020")

# Security headers we expect the app / proxy to set on responses.
EXPECTED_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": None,          # presence is enough
    "referrer-policy": None,
}


def _log(lines: list[str]) -> None:
    """Append timestamped notes; keep the file from growing unbounded."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        for line in lines:
            f.write(f"[{stamp}] {line}\n")
    # Trim to the last 500 lines.
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            kept = f.readlines()[-500:]
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            f.writelines(kept)
    except OSError:
        pass


def run_tests() -> dict[str, Any]:
    """Run pytest and capture the summary line. Returns {ok, summary}."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        proc = subprocess.run(
            ["python", "-m", "pytest", "-q", "tests"],
            cwd=root, capture_output=True, text=True, timeout=120,
        )
        tail = proc.stdout.strip().splitlines()[-1:] or [""]
        return {"ok": proc.returncode == 0, "summary": tail[0]}
    except Exception as exc:
        return {"ok": False, "summary": f"pytest failed to run: {exc}"}


def audit_security() -> list[str]:
    """Check live security posture; return a list of findings (empty = clean)."""
    findings: list[str] = []

    # 1. Response security headers.
    try:
        r = httpx.get(f"{BASE_URL}/api/health", timeout=8)
        got = {k.lower(): v for k, v in r.headers.items()}
        for header, expected in EXPECTED_HEADERS.items():
            if header not in got:
                findings.append(f"SECURITY: missing response header '{header}'")
            elif expected is not None and got[header].lower() != expected:
                findings.append(
                    f"SECURITY: header '{header}' = '{got[header]}', want '{expected}'")
    except Exception as exc:
        findings.append(f"SECURITY: could not reach app for header audit ({exc})")

    # 2. DB file must not sit under a web-served path.
    db_path = os.path.abspath(db.DB_PATH)
    if os.sep + "frontend" + os.sep in db_path or db_path.endswith(os.sep + "frontend"):
        findings.append("SECURITY: database file is under the served frontend dir")

    # 3. Debug / reload must be off in production.
    if os.environ.get("DXMAP_DEBUG", "0") == "1":
        findings.append("SECURITY: DXMAP_DEBUG is on — disable in production")

    # 4. CORS must not be wildcard in production. Default matches app.py's
    # own default ("*") — an *unset* var is exactly the case this needs to
    # catch, not just an explicit "*", so the defaults here must agree.
    if os.environ.get("DXMAP_ALLOW_ORIGINS", "*") == "*" and \
            os.environ.get("DXMAP_ENV", "dev") == "prod":
        findings.append("SECURITY: CORS allow-origins is '*' in prod")

    return findings


def audit_health() -> list[str]:
    """Flag sources that are failing or slow. Returns human-readable notes."""
    notes: list[str] = []
    health = db.source_health()
    for source, h in health.items():
        if h["streak_fail"] >= 3:
            notes.append(
                f"HEALTH: source '{source}' failed {h['streak_fail']} polls in a row "
                f"— consider backing off or checking credentials")
        if h["success_rate"] < 0.5 and h["samples"] >= 5:
            notes.append(
                f"HEALTH: source '{source}' success rate {h['success_rate']:.0%} "
                f"over last {h['samples']} polls")
        if h["avg_latency_ms"] and h["avg_latency_ms"] > 5000:
            notes.append(
                f"HEALTH: source '{source}' avg latency {h['avg_latency_ms']}ms is high")
    return notes


def suggest_improvements() -> list[str]:
    """Data-driven suggestions for a human to action. Cheap heuristics only."""
    suggestions: list[str] = []
    s = db.stats()
    if s["total"] > 0:
        located_ratio = s["located"] / s["total"]
        if located_ratio < 0.3:
            suggestions.append(
                f"FRONTEND/DATA: only {located_ratio:.0%} of reports are mapped — "
                f"expand the gazetteer or enable Nominatim fallback in the loop")
    if s["total"] > 5000:
        suggestions.append(
            "DB: reports table is large — add a retention/archival job")
    if "youtube" not in s["by_source"]:
        suggestions.append(
            "DATA: YouTube source inactive — add a free YOUTUBE_API_KEY to widen coverage")
    return suggestions


def run_selfcheck() -> dict[str, Any]:
    """Run the whole self-check once, log findings, and return a summary."""
    tests = run_tests()
    security = audit_security()
    health = audit_health()
    suggestions = suggest_improvements()

    lines = [f"TESTS: {'pass' if tests['ok'] else 'FAIL'} — {tests['summary']}"]
    lines += security or ["SECURITY: no findings"]
    lines += health or ["HEALTH: all sources nominal"]
    lines += suggestions or ["SUGGESTIONS: none"]
    _log(lines)

    return {
        "ran_at": int(time.time()),
        "tests_ok": tests["ok"],
        "tests_summary": tests["summary"],
        "security_findings": security,
        "health_notes": health,
        "suggestions": suggestions,
    }


async def selfcheck_loop() -> None:
    """Async wrapper so app.py can launch it alongside the heartbeat."""
    import asyncio
    while True:
        try:
            run_selfcheck()
        except Exception:
            pass
        await asyncio.sleep(SELFCHECK_SECONDS)


if __name__ == "__main__":
    import json
    print(json.dumps(run_selfcheck(), indent=2))
