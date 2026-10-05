#!/usr/bin/env bash
# Резервная копия базы и картинок в /opt/vkreger/backups (хранятся последние 14).
set -euo pipefail
DIR="${VKREGER_DIR:-/opt/vkreger}"
cd "$DIR"
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
env_value() { grep -m1 "^$1=" .env | cut -d= -f2- || true; }
PG_USER=$(env_value POSTGRES_USER); PG_DB=$(env_value POSTGRES_DB)
docker compose exec -T postgres pg_dump -U "${PG_USER:-vk}" "${PG_DB:-vkreger}" | gzip > "backups/db-$STAMP.sql.gz"
docker compose exec -T backend tar -C /data -czf - media > "backups/media-$STAMP.tar.gz" 2>/dev/null || true
cp .env "backups/env-$STAMP"
chmod 600 backups/*
ls -1t backups/db-*.sql.gz | tail -n +15 | xargs -r rm -f
ls -1t backups/media-*.tar.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
ls -1t backups/env-* | tail -n +15 | xargs -r rm -f
echo "Резервная копия: $DIR/backups/db-$STAMP.sql.gz"
