#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 24.04 server for the Corpus Explorer API.
#
#   API_HOST=<public IP or domain> bash setup.sh
#
# Installs Python and Caddy, clones the repository to /opt/corpus-explorer, runs
# the API as the `corpus` system user under systemd, and puts Caddy in front of
# it with HTTPS. Safe to run again. Afterwards, put MONGO_URI (the read-only Atlas
# user) in /opt/corpus-explorer/backend/.env and restart: see ../README.md.
set -euo pipefail

API_HOST="${API_HOST:?set API_HOST to the public IP address or domain name of this server}"
ALLOW_ORIGINS="${ALLOW_ORIGINS:-https://dhanush251201.github.io}"
REPO="${REPO:-https://github.com/dhanush251201/corpus-explorer.git}"
APP=/opt/corpus-explorer

echo "== packages"
sudo apt-get update -q
sudo apt-get install -y -q python3-venv git debian-keyring debian-archive-keyring apt-transport-https curl
if ! command -v caddy >/dev/null; then
  # Caddy's official repository: https://caddyserver.com/docs/install#debian-ubuntu-raspbian
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | sudo gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
  sudo apt-get update -q
  sudo apt-get install -y -q caddy
fi

echo "== code"
id corpus >/dev/null 2>&1 || sudo useradd --system --home-dir "$APP" --shell /usr/sbin/nologin corpus
if [ ! -d "$APP/.git" ]; then
  sudo git clone -q "$REPO" "$APP"
fi
sudo chown -R corpus:corpus "$APP"
sudo -u corpus python3 -m venv "$APP/backend/.venv"
sudo -u corpus "$APP/backend/.venv/bin/pip" install -q --no-cache-dir --upgrade pip
sudo -u corpus "$APP/backend/.venv/bin/pip" install -q --no-cache-dir -r "$APP/backend/requirements.txt"

echo "== settings"
ENV_FILE="$APP/backend/.env"
if [ ! -f "$ENV_FILE" ]; then
  # MONGO_URI is left empty for the operator to fill in; the file is readable by
  # the service user only.
  printf 'MONGO_URI=\nALLOW_ORIGINS=%s\n' "$ALLOW_ORIGINS" \
    | sudo -u corpus install -m 600 /dev/stdin "$ENV_FILE"
fi

echo "== services"
sudo install -m 644 "$APP/backend/deploy/corpus-explorer.service" /etc/systemd/system/corpus-explorer.service
sed "s/__API_HOST__/$API_HOST/g" "$APP/backend/deploy/Caddyfile" | sudo tee /etc/caddy/Caddyfile >/dev/null
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl daemon-reload
sudo systemctl enable --now corpus-explorer
sudo systemctl enable caddy
sudo systemctl restart caddy

echo "== done: https://$API_HOST/api/health"
