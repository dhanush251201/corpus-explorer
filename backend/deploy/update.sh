#!/usr/bin/env bash
# Deploy the latest backend from main on a server set up by setup.sh:
#
#   bash /opt/corpus-explorer/backend/deploy/update.sh
set -euo pipefail
APP=/opt/corpus-explorer

sudo -u corpus git -C "$APP" pull -q --ff-only
sudo -u corpus "$APP/backend/.venv/bin/pip" install -q --no-cache-dir -r "$APP/backend/requirements.txt"
sudo install -m 644 "$APP/backend/deploy/corpus-explorer.service" /etc/systemd/system/corpus-explorer.service
sudo systemctl daemon-reload
sudo systemctl restart corpus-explorer
sleep 2
systemctl --no-pager --lines=5 status corpus-explorer
