"""
Shared test setup. DXMAP_ENV defaults to prod now (secure cookies, no dev
shortcuts), so the suite asks for dev explicitly before app/auth are imported.
"""
import os

os.environ.setdefault("DXMAP_ENV", "dev")
os.environ["DXMAP_AGENT"] = "off"
