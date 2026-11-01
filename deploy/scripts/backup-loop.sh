#!/bin/bash
# Runs backup.sh every night at BACKUP_HOUR (container time zone = TZ).
# A failed run is logged and retried the next night; the last_backup_ok file only changes on success.
HOUR=${BACKUP_HOUR:-2}
while true; do
  now=$(date +%s)
  next=$(date -d "today ${HOUR}:00" +%s)
  [ "$next" -le "$now" ] && next=$(date -d "tomorrow ${HOUR}:00" +%s)
  echo "[$(date -Is)] next backup at $(date -d @"$next" -Is)"
  sleep $((next - now))
  /bin/bash /scripts/backup.sh || echo "[$(date -Is)] BACKUP FAILED"
done
