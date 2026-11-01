#!/bin/bash
# One backup run: database dump + filestore archive, verified, old ones removed.
set -euo pipefail

DEST=/backups
KEEP=${BACKUP_KEEP_DAYS:-14}
TS=$(date +%Y%m%d-%H%M%S)
DUMP="$DEST/${DB_NAME}-${TS}.dump"
FILES="$DEST/${DB_NAME}-${TS}-filestore.tar.gz"

echo "[$(date -Is)] backup start: $DB_NAME"
pg_dump -h db -U odoo -Fc "$DB_NAME" -f "$DUMP.part"
pg_restore -l "$DUMP.part" > /dev/null          # the dump must be readable
mv "$DUMP.part" "$DUMP"

if [ -d "/var/lib/odoo/filestore/$DB_NAME" ]; then
  tar czf "$FILES.part" -C /var/lib/odoo/filestore "$DB_NAME"
  tar tzf "$FILES.part" > /dev/null
  mv "$FILES.part" "$FILES"
else
  echo "no filestore yet for $DB_NAME (nothing to archive)"
fi

find "$DEST" -maxdepth 1 -name "${DB_NAME}-*" -mtime +"$KEEP" -delete
date -Is > "$DEST/last_backup_ok"
echo "[$(date -Is)] backup done: $(basename "$DUMP") ($(du -h "$DUMP" | cut -f1))"
