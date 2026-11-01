#!/bin/bash
# First-time setup on a NEW server (empty database): installs the textile_inventory module.
# To start from existing data instead, use restore.sh.   Run from the deploy/ folder.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
docker compose up -d db
docker compose run --rm --no-deps odoo odoo -d "${DB_NAME}" -i textile_inventory \
  --without-demo=all --stop-after-init --no-database-list
docker compose up -d
echo "Done. Open https://${DOMAIN} and set the admin password (Settings > Users)."
