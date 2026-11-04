#!/bin/sh
# Restore drill: restores the newest dump into a throw-away database and checks row counts.
# Usage (on the VPS): docker compose run --rm --entrypoint /bin/sh backup /restore_test.sh
set -eu
LATEST=$(ls -1t /backups/polybot-*.dump | head -n1)
[ -n "$LATEST" ] || { echo "no backups"; exit 1; }
DB=polybot_restore_check
psql -h postgres -U polybot -d postgres -qc "DROP DATABASE IF EXISTS $DB"
psql -h postgres -U polybot -d postgres -qc "CREATE DATABASE $DB"
pg_restore -h postgres -U polybot -d "$DB" --no-owner "$LATEST"
for t in markets market_mappings opportunities outbox subscriptions; do
  printf "%s: " "$t"; psql -h postgres -U polybot -d "$DB" -tAc "select count(*) from $t"
done
psql -h postgres -U polybot -d "$DB" -tAc "select version_num from alembic_version"
psql -h postgres -U polybot -d postgres -qc "DROP DATABASE $DB"
echo "restore ok from $LATEST"
