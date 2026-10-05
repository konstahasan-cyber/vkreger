#!/usr/bin/env bash
# VKreger: установка на сервер Ubuntu 22.04/24.04 одной командой.
#   curl -fsSL https://raw.githubusercontent.com/konstahasan-cyber/vkreger/claude/clever-wozniak-kwdwzl/deploy/install.sh | sudo bash
# Повторный запуск безопасен: ключи и данные сохраняются, код обновляется.
set -euo pipefail

REPO="https://github.com/konstahasan-cyber/vkreger.git"
BRANCH="${VKREGER_BRANCH:-claude/clever-wozniak-kwdwzl}"
DIR="${VKREGER_DIR:-/opt/vkreger}"

say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ask() { local prompt="$1" var; read -r -p "$prompt" var </dev/tty; printf '%s' "$var"; }
ask_secret() { local prompt="$1" var; read -r -s -p "$prompt" var </dev/tty; echo >/dev/tty; printf '%s' "$var"; }

if [ "$(id -u)" -ne 0 ]; then echo "Запустите через sudo"; exit 1; fi

say "Устанавливаю системные пакеты"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git curl ca-certificates openssl >/dev/null

if ! command -v docker >/dev/null 2>&1; then
  say "Устанавливаю Docker"
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker >/dev/null

# Сборка фронтенда требует ~2 ГБ памяти: на маленьких серверах добавляем swap.
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [ "$MEM_MB" -lt 2500 ] && ! swapon --show | grep -q .; then
  say "Мало памяти (${MEM_MB} МБ) — создаю swap 2 ГБ"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

say "Скачиваю код в $DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch -q origin "$BRANCH"
  git -C "$DIR" checkout -q -B "$BRANCH" "origin/$BRANCH"
else
  git clone -q --branch "$BRANCH" "$REPO" "$DIR"
fi
cd "$DIR"

if [ ! -f .env ]; then
  say "Первичная настройка"
  SERVER_IP=$(curl -fsS -4 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')
  echo "IP сервера: $SERVER_IP"
  DOMAIN=$(ask "Домен для панели (например panel.example.ru). Если домена нет — просто Enter: ")
  ADMIN_EMAIL=$(ask "Email для входа в панель: ")
  while :; do
    ADMIN_PASSWORD=$(ask_secret "Пароль для входа (минимум 10 символов): ")
    [ "${#ADMIN_PASSWORD}" -ge 10 ] && break
    echo "Слишком короткий пароль"
  done
  OPENAI_API_KEY=$(ask_secret "Ключ OpenAI (sk-..., можно оставить пустым и добавить позже): ")

  if [ -n "$DOMAIN" ]; then SITE_ADDRESS="$DOMAIN"; PUBLIC_URL="https://$DOMAIN"; else SITE_ADDRESS=":80"; PUBLIC_URL="http://$SERVER_IP"; fi
  SECRET_KEY=$(openssl rand -base64 48 | tr -d '\n=+/')
  ENCRYPTION_KEY=$(openssl rand -base64 32 | tr '+/' '-_')
  PG_PASSWORD=$(openssl rand -hex 24)

  cp .env.example .env
  set_env() { # set_env KEY VALUE
    local key="$1" value="$2"
    if grep -q "^${key}=" .env; then
      python3 - "$key" "$value" <<'PY'
import sys
key, value = sys.argv[1], sys.argv[2]
lines = open(".env", encoding="utf-8").read().splitlines()
lines = [f"{key}={value}" if l.startswith(key + "=") else l for l in lines]
open(".env", "w", encoding="utf-8").write("\n".join(lines) + "\n")
PY
    else
      echo "${key}=${value}" >> .env
    fi
  }
  set_env ENVIRONMENT production
  set_env PUBLIC_BASE_URL "$PUBLIC_URL"
  set_env CORS_ORIGINS "$PUBLIC_URL"
  set_env SECRET_KEY "$SECRET_KEY"
  set_env ENCRYPTION_KEYS "$ENCRYPTION_KEY"
  set_env ADMIN_EMAIL "$ADMIN_EMAIL"
  set_env ADMIN_PASSWORD "$ADMIN_PASSWORD"
  set_env POSTGRES_PASSWORD "$PG_PASSWORD"
  set_env OPENAI_API_KEY "$OPENAI_API_KEY"
  set_env SITE_ADDRESS "$SITE_ADDRESS"
  chmod 600 .env
  CREATED_ENV=1
else
  say ".env уже есть — оставляю ключи и пароли как есть"
  CREATED_ENV=0
fi

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  say "Открываю порты 80 и 443 в ufw"
  ufw allow 80/tcp >/dev/null && ufw allow 443/tcp >/dev/null
fi

chmod +x deploy/*.sh deploy/vk
ln -sf "$DIR/deploy/vk" /usr/local/bin/vk

say "Собираю и запускаю (первый раз 5-15 минут)"
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --remove-orphans

say "Жду, пока панель поднимется"
for _ in $(seq 1 60); do
  if docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T backend \
       python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" >/dev/null 2>&1; then
    break
  fi
  sleep 5
done

URL=$(grep '^PUBLIC_BASE_URL=' .env | cut -d= -f2-)
echo
echo "============================================================"
echo " VKreger запущен: $URL"
[ "$CREATED_ENV" = 1 ] && echo " Вход: $ADMIN_EMAIL и ваш пароль"
echo
echo " Управление: команда vk (vk update, vk restart, vk logs, vk status, vk env)"
echo
echo " ВАЖНО: сохраните копию файла $DIR/.env в надёжном месте."
echo " В нём ключ шифрования токенов (ENCRYPTION_KEYS): без него"
echo " сохранённые токены VK не восстановить."
echo "============================================================"
