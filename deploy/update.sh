#!/usr/bin/env bash
# Обновление VKreger до свежей версии кода. Данные и .env сохраняются.
set -euo pipefail
DIR="${VKREGER_DIR:-/opt/vkreger}"
BRANCH="${VKREGER_BRANCH:-$(git -C "$DIR" rev-parse --abbrev-ref HEAD)}"
cd "$DIR"
bash deploy/backup.sh || echo "(резервную копию сделать не удалось — продолжаю)"
# installs without a domain: close 443 from outside (see docker-compose.prod.yml)
if grep -q '^SITE_ADDRESS=:80' .env; then
  sed -i '/^HTTPS_BIND=/d' .env && echo "HTTPS_BIND=127.0.0.1:8443" >> .env
fi
git fetch -q origin "$BRANCH"
git checkout -q -B "$BRANCH" "origin/$BRANCH"
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --remove-orphans
docker image prune -f >/dev/null
chmod +x deploy/*.sh deploy/vk
ln -sf "$DIR/deploy/vk" /usr/local/bin/vk
echo "Готово: VKreger обновлён."
