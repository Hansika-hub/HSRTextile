#!/bin/bash
# Restore a backup into the running stack.   Run from the deploy/ folder.
#   ./scripts/restore.sh backups/HSRTextile-20261101-020000.dump [backups/HSRTextile-20261101-020000-filestore.tar.gz]
# The existing database is replaced ONLY when you add --force (a safety copy dump is taken first).
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

DUMP=${1:?usage: restore.sh <dump> [filestore.tar.gz] [--force]}
FILES=""; FORCE=0
shift
for a in "$@"; do
  if [ "$a" = "--force" ]; then FORCE=1; else FILES="$a"; fi
done
[ -f "$DUMP" ] || { echo "dump not found: $DUMP"; exit 1; }

DC="docker compose"
PSQL="$DC exec -T db psql -U odoo -d postgres -v ON_ERROR_STOP=1 -Atc"

exists=$($PSQL "select 1 from pg_database where datname='${DB_NAME}'" || true)
if [ -n "$exists" ] && [ "$FORCE" -ne 1 ]; then
  echo "Database ${DB_NAME} already exists. Re-run with --force to replace it."; exit 1
fi

$DC stop odoo backup >/dev/null
if [ -n "$exists" ]; then
  SAFE="backups/${DB_NAME}-before-restore-$(date +%Y%m%d-%H%M%S).dump"
  echo "Safety copy of current database -> $SAFE"
  $DC exec -T db pg_dump -U odoo -Fc "${DB_NAME}" > "$SAFE"
  $PSQL "select pg_terminate_backend(pid) from pg_stat_activity where datname='${DB_NAME}'" >/dev/null
  $PSQL "drop database \"${DB_NAME}\"" >/dev/null
fi
$PSQL "create database \"${DB_NAME}\" owner odoo" >/dev/null
echo "Restoring database..."
$DC exec -T db pg_restore -U odoo -d "${DB_NAME}" --no-owner --no-privileges < "$DUMP"

if [ -n "$FILES" ]; then
  [ -f "$FILES" ] || { echo "filestore archive not found: $FILES"; exit 1; }
  echo "Restoring filestore..."
  $DC run --rm --no-deps -T --user root -v "$(pwd)/$(dirname "$FILES"):/restore:ro" --entrypoint bash odoo -c \
    "mkdir -p /var/lib/odoo/filestore && rm -rf /var/lib/odoo/filestore/${DB_NAME} && tar xzf /restore/$(basename "$FILES") -C /var/lib/odoo/filestore && chown -R odoo:odoo /var/lib/odoo/filestore"
fi

$DC up -d odoo backup
echo "Restore finished. Check the site, then keep the safety copy until you are sure."
