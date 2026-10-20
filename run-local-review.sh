#!/bin/sh
# Run a LOCAL copy of the map for reviewing changes, safely:
#   - works on a COPY of the database (never the real one, never prod's)
#   - the scraping agent is off (DXMAP_AGENT=off): no calls to Bluesky/Mastodon,
#     no new rows
#   - frame-ancestors also allows the local nabilvs.com preview, so the map
#     shows inside http://localhost:3100/projects/discrimination-map
#     (ignored when DXMAP_ENV=prod)
#
#   ./run-local-review.sh                 serve on http://127.0.0.1:8020
#   DXMAP_SRC_DB=/path/to.db ./run-local-review.sh   copy another database
#
# Build the frontend first when web/ changed:  sh web/sync-to-frontend.sh
set -e
cd "$(dirname "$0")"
# The copy holds password hashes, session and edit tokens: owner-only, in a
# private directory, deleted when the server stops.
umask 077
SRC="${DXMAP_SRC_DB:-backend/dxmap.db}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM
COPY="$WORK/dxmap-local-review.db"
if [ -f "$SRC" ]; then cp "$SRC" "$COPY"; fi
export DXMAP_ENV=dev
export DXMAP_AGENT=off
export DXMAP_DB_PATH="$COPY"
export DXMAP_ADMIN_EMAIL="dev-admin@example.org"
export DXMAP_ADMIN_PASSWORD="dev-admin-password-123"
export DXMAP_FRAME_ANCESTORS_EXTRA="http://localhost:3100 http://localhost:3000"
echo "map: http://127.0.0.1:8020  (database copy: $COPY, scraper off)"
venv/bin/python -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8020
