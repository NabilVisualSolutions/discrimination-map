#!/usr/bin/env bash
#
# Hermes Map — VPS deploy script.
#
# Usage (run AS ROOT on the VPS, after scp-ing the project to /opt/hermes-map):
#   bash /opt/hermes-map/deploy/deploy.sh yourdomain.com
#
# What it does:
#   1. Installs Python + Nginx if missing.
#   2. Creates an unprivileged 'hermes' service user.
#   3. Creates a virtualenv and installs backend/requirements.txt into it.
#   4. Installs the systemd unit and starts the service.
#   5. Installs the Nginx site config, reloads Nginx.
#   6. Optionally provisions a free Let's Encrypt certificate (Certbot).
#
# Safe to re-run: each step is idempotent.

set -euo pipefail

DOMAIN="${1:-}"
APP_DIR="/opt/hermes-map"
SERVICE_USER="hermes"
DATA_DIR="$APP_DIR/data"

if [[ $EUID -ne 0 ]]; then
  echo "Run this as root (e.g. with sudo)." >&2
  exit 1
fi

if [[ -z "$DOMAIN" ]]; then
  echo "Usage: bash deploy.sh yourdomain.com"
  echo "(You can also run without a domain to deploy on HTTP only; pass"
  echo " a real domain later and re-run to add TLS.)"
fi

echo "==> Installing system packages"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip nginx curl >/dev/null

echo "==> Creating service user '$SERVICE_USER' (if needed)"
id -u "$SERVICE_USER" &>/dev/null || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"

echo "==> Setting up the Python virtualenv"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/backend/requirements.txt"

echo "==> Preparing data directory (persistent DB lives here)"
mkdir -p "$DATA_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

echo "==> Writing environment file (edit $APP_DIR/.env to add API keys later)"
if [[ ! -f "$APP_DIR/.env" ]]; then
  cat > "$APP_DIR/.env" <<EOF
# Optional upgrades — uncomment and fill in to activate more sources.
# YOUTUBE_API_KEY=
# HERMES_ALLOW_ORIGINS=https://${DOMAIN:-yourdomain.com}
EOF
fi

echo "==> Installing the systemd service"
cp "$APP_DIR/deploy/hermes.service" /etc/systemd/system/hermes.service
systemctl daemon-reload
systemctl enable hermes
systemctl restart hermes
sleep 2
systemctl --no-pager status hermes || true

echo "==> Installing the Nginx site"
SITE_CONF="/etc/nginx/sites-available/hermes-map"
cp "$APP_DIR/deploy/nginx.conf" "$SITE_CONF"
if [[ -n "$DOMAIN" ]]; then
  sed -i "s/yourdomain.com/$DOMAIN/g" "$SITE_CONF"
fi
ln -sf "$SITE_CONF" /etc/nginx/sites-enabled/hermes-map
nginx -t
systemctl reload nginx

if [[ -n "$DOMAIN" ]]; then
  echo "==> Attempting to provision a free TLS certificate for $DOMAIN"
  if ! command -v certbot &>/dev/null; then
    apt-get install -y -qq certbot python3-certbot-nginx >/dev/null
  fi
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "admin@$DOMAIN" || \
    echo "Certbot failed — check that $DOMAIN's DNS A record points at this VPS, then re-run:
    certbot --nginx -d $DOMAIN"
fi

echo
echo "==> Done."
echo "    Service:  systemctl status hermes"
echo "    Logs:     journalctl -u hermes -f"
echo "    Site:     http://${DOMAIN:-<this-server-ip>}/"
echo "    Self-check log: $APP_DIR/backend/improvements.log"
