#!/bin/sh
# Author: Rajveer Sharma
# © NxtWave
# Date: 16 October 2026
# Weekly off-site copy: restores the newest dump into Neon, so
# a lost VM doesn't mean lost data. Only once the VM is the live database: this
# REPLACES everything in the Neon database it is pointed at.
#
#   NEON_URL      the Neon database (postgresql://...); required
#   DB_NAME / BACKUP_DIR   as for backup.sh
set -eu

: "${NEON_URL:?set NEON_URL to the Neon copy}"
DB="${DB_NAME:-dashboard}"
DIR="${BACKUP_DIR:-/srv/dashboard/backups}"

latest="$(ls -1t "$DIR/$DB"-*.dump 2>/dev/null | head -n 1)"
[ -n "$latest" ] || { echo "no dumps in $DIR" >&2; exit 1; }

pg_restore --clean --if-exists --no-owner --no-privileges --exit-on-error --dbname="$NEON_URL" "$latest"
echo "neon copy ok: $(basename "$latest")"
