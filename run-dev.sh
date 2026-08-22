#!/bin/sh
# Local dev launcher — bootstraps a throwaway admin account so the admin
# console/moderation endpoints are testable, without touching prod env vars.
export DXMAP_ENV=dev
export DXMAP_ADMIN_EMAIL="dev-admin@example.org"
export DXMAP_ADMIN_PASSWORD="dev-admin-password-123"
cd "$(dirname "$0")"
exec venv/bin/python -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8020
