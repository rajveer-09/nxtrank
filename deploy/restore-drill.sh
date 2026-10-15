#!/bin/sh
# Author: Rajveer Sharma
# © NxtWave
# Date: 16 October 2026
# Monthly restore drill: "an untested backup isn't a backup".
# Restores the newest dump into a scratch database, checks it has the same tables and
# row counts as the live one, then drops it. Exits non-zero (and the timer's unit
# fails, visible in `systemctl --failed`) if anything is missing.
#
#   DB_NAME / BACKUP_DIR   as for backup.sh
set -eu

DB="${DB_NAME:-dashboard}"
DIR="${BACKUP_DIR:-/srv/dashboard/backups}"
DRILL="${DB}_restore_drill"

latest="$(ls -1t "$DIR/$DB"-*.dump 2>/dev/null | head -n 1)"
[ -n "$latest" ] || { echo "no dumps in $DIR" >&2; exit 1; }

dropdb --if-exists "$DRILL"
createdb "$DRILL"
trap 'dropdb --if-exists "$DRILL"' EXIT
pg_restore --no-owner --exit-on-error --dbname="$DRILL" "$latest"

COUNTS="SELECT 'students', count(*) FROM students UNION ALL SELECT 'contests', count(*) FROM contests
        UNION ALL SELECT 'results', count(*) FROM results UNION ALL SELECT 'problem_results', count(*) FROM problem_results
        UNION ALL SELECT 'users', count(*) FROM users ORDER BY 1"
restored="$(psql -X -At -d "$DRILL" -c "$COUNTS")"
live="$(psql -X -At -d "$DB" -c "$COUNTS")"
echo "restored from $(basename "$latest"):"
echo "$restored" | sed 's/^/  /'

# the dump is from last night, so live may have grown since; it must never have less
echo "$restored" | while IFS='|' read -r table n; do
  now="$(echo "$live" | awk -F'|' -v t="$table" '$1 == t { print $2 }')"
  if [ "$n" -gt "$now" ] || { [ "$table" != "users" ] && [ "$n" -eq 0 ] && [ "$now" -gt 0 ]; }; then
    echo "MISMATCH: $table restored $n, live $now" >&2
    exit 1
  fi
done
echo "restore drill ok"
