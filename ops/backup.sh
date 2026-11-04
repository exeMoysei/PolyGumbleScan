#!/bin/sh
# Compressed custom-format dump of PostgreSQL; keeps BACKUP_KEEP_DAYS days. Runs inside the backup service.
set -eu
TS=$(date -u +%Y%m%dT%H%M%SZ)
OUT="/backups/polybot-$TS.dump"
pg_dump -h postgres -U polybot -d polybot -Fc -Z 6 -f "$OUT.tmp"
mv "$OUT.tmp" "$OUT"
pg_restore --list "$OUT" > /dev/null   # integrity check of the archive
find /backups -name 'polybot-*.dump' -mtime +"${BACKUP_KEEP_DAYS:-14}" -delete
echo "backup ok: $OUT"
