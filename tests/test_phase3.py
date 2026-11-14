"""
Phase 3 (2026-11): reporting an entry, production hardening, palette.

- Anyone can report a public entry (EU DSA Art. 16 notice-and-action). The
  notice lands in the admin applications queue, like a symbol proposal.
- Production serves no /docs, /redoc or /openapi.json.
- The production self-check does not run pytest (the image has no tests)
  and calls the port the container listens on.
- Every category has its own colour.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import app as app_module  # noqa: E402
import db  # noqa: E402
import lawref  # noqa: E402
from test_audit_api import logged_in, new_client, verified_report, visitor  # noqa: E402

db.init_db()
ROOT = os.path.join(os.path.dirname(__file__), "..")


def notice(**over):
    body = {"report_id": verified_report("violence"), "reason": "This names a private person who was not involved.",
            "good_faith": True, "email": ""}
    body.update(over)
    return new_client().post("/api/report-entry", json=body, headers=visitor())


def test_reporting_an_entry_reaches_the_admin_queue():
    rid = verified_report("violence")
    r = notice(report_id=rid, email="notifier@example.org")
    assert r.status_code == 201, r.text
    apps = logged_in("ADMIN", "p3a").get("/api/admin/applications").json()["applications"]
    mine = [a for a in apps if f"[ENTRY REPORT #{rid}]" in a["message"]]
    assert len(mine) == 1 and mine[0]["email"] == "notifier@example.org"
    assert "private person" in mine[0]["message"]


def test_reporting_needs_the_good_faith_statement():
    assert notice(good_faith=False).status_code == 422


def test_reporting_needs_a_reason():
    assert notice(reason="bad").status_code == 422


def test_reporting_an_unknown_entry_is_404():
    assert notice(report_id=99_999_999).status_code == 404


def _prod(code):
    env = {k: v for k, v in os.environ.items() if k != "DXMAP_ENV"}
    return subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'backend'); " + code],
                          cwd=ROOT, env=env, capture_output=True, text=True)


def test_production_has_no_api_docs():
    out = _prod("import app; print(app.app.docs_url, app.app.redoc_url, app.app.openapi_url)")
    assert out.stdout.strip() == "None None None", out.stderr[-400:]


def test_dev_keeps_api_docs():
    assert app_module.app.docs_url == "/docs"


def test_production_selfcheck_skips_pytest_and_uses_the_container_port():
    out = _prod("import selfcheck; print(selfcheck.RUN_TESTS, selfcheck.BASE_URL)")
    assert out.stdout.strip() == "False http://127.0.0.1:8010", out.stderr[-400:]


def test_every_category_has_its_own_colour():
    colours = [c["color"].upper() for c in lawref.CATEGORIES.values()]
    assert len(colours) == len(set(colours))
