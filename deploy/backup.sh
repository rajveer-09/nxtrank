#!/bin/sh
# Author: Rajveer Sharma
# © NxtWave
# Date: 16 October 2026
# Nightly backup: a compressed dump of the dashboard database,
# checked readable, kept 14 days on the VM and (with OCI_BUCKET set) copied to Oracle
# Object Storage. Run by dashboard-backup.timer; safe to run by hand.
#
#   DB_NAME       database to dump                (default dashboard)
#   BACKUP_DIR    where dumps are kept            (default /srv/dashboard/backups)
#   KEEP_DAYS     local retention                 (default 14)
#   OCI_BUCKET    Object Storage bucket (optional; give the bucket a 14-day
#                 lifecycle rule so it prunes itself)
set -eu

DB="${DB_NAME:-dashboard}"
DIR="${BACKUP_DIR:-/srv/dashboard/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"

mkdir -p "$DIR"
stamp="$(date -u +%Y%m%dT%H%MZ)"
file="$DIR/$DB-$stamp.dump"

# custom format: compressed, and restorable table by table
pg_dump --format=custom --compress=9 --no-owner --dbname="$DB" --file="$file.part"
pg_restore --list "$file.part" >/dev/null # a dump that can't be read isn't a backup
mv "$file.part" "$file"

if [ -n "${OCI_BUCKET:-}" ]; then
  oci os object put --bucket-name "$OCI_BUCKET" --file "$file" --name "$(basename "$file")" --no-overwrite
fi

find "$DIR" -name "$DB-*.dump" -mtime +"$KEEP_DAYS" -delete
echo "backup ok: $file ($(du -h "$file" | cut -f1))"
