#!/usr/bin/env bash
# Deploy a specific image SHA on the VPS: pull, migrate (logged), restart, health-check.
# Usage: ops/deploy.sh <git-sha>
set -euo pipefail
SHA=${1:?usage: deploy.sh <git-sha>}
cd "$(dirname "$0")/.."
export POLYBOT_IMAGE="ghcr.io/exemoysei/polygumblescan:${SHA}"
mkdir -p var/log
docker compose pull ingest scan bot migrate
docker compose run --rm migrate 2>&1 | tee -a "var/log/migrations-$(date -u +%Y%m%d).log"
docker compose up -d --remove-orphans
sleep 20
docker compose ps
for s in ingest scan bot; do
  docker compose exec -T "$s" polybot healthcheck
done
echo "POLYBOT_IMAGE=${POLYBOT_IMAGE}" > var/deployed.env
echo "deployed ${SHA}"
