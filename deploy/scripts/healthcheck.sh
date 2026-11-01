#!/bin/bash
# Quick health report; exit code 1 if anything is wrong. Run from deploy/ (cron every 5 min is fine).
# Optional: put a webhook / healthchecks.io URL in ALERT_URL in .env to be pinged on failure.
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
bad=0
say() { echo "$1"; }

for s in db odoo caddy backup; do
  st=$(docker compose ps --format '{{.Service}} {{.State}} {{.Health}}' | awk -v s=$s '$1==s{print $2" "$3}')
  case "$st" in running*healthy*|"running ") say "OK   $s ($st)";; running*) say "OK   $s ($st)";; *) say "FAIL $s ($st)"; bad=1;; esac
done

code=$(curl -ks -o /dev/null -w '%{http_code}' --max-time 10 "https://${DOMAIN}/web/login")
[ "$code" = "200" ] && say "OK   website https://${DOMAIN} ($code)" || { say "FAIL website ($code)"; bad=1; }

f="${BACKUP_DIR:-./backups}/last_backup_ok"
if [ -f "$f" ]; then
  age=$(( ( $(date +%s) - $(date -r "$f" +%s) ) / 3600 ))
  [ "$age" -le 26 ] && say "OK   last backup ${age}h ago" || { say "FAIL last backup ${age}h ago"; bad=1; }
else
  say "FAIL no successful backup yet"; bad=1
fi

use=$(df -P . | awk 'NR==2{gsub("%","");print $5}')
[ "$use" -lt 85 ] && say "OK   disk ${use}% used" || { say "FAIL disk ${use}% used"; bad=1; }

[ "$bad" -ne 0 ] && [ -n "${ALERT_URL:-}" ] && curl -fs -m 10 "$ALERT_URL" >/dev/null
exit $bad
