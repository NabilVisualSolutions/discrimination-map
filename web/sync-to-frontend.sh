#!/bin/sh
# Build web/ and drop the result into frontend/ so FastAPI serves it
# (frontend/index.html is the SPA shell, /static mounts frontend/).
# Run from repo root:  sh web/sync-to-frontend.sh
set -e
cd "$(dirname "$0")"
npx vite build
cd ..
rm -f frontend/assets/*
cp web/dist/assets/* frontend/assets/
cp web/dist/index.html frontend/index.html  # vite base is /static/, no rewrite needed
echo "synced web/dist -> frontend/  (commit frontend/index.html + frontend/assets/)"
