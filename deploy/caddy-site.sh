#!/usr/bin/env bash
# Add/remove the VKreger site block in an EXISTING Caddy that already owns ports 80/443
# (a systemd service or a Docker container, e.g. another project's reverse proxy).
#   caddy-site.sh add <domain> <upstream-port>
#   caddy-site.sh remove
# The config is backed up, validated and reloaded; on any error the original is restored.
# Files are rewritten in place (same inode) so single-file Docker bind mounts see the change.
set -euo pipefail
ACTION="${1:-}"; DOMAIN="${2:-}"; PORT="${3:-8080}"
SELF_PREFIX="${VKREGER_PROJECT:-vkreger}"

find_target() {
  # 1) a Caddy container (not ours) — prefer one that owns ports 80/443 via host networking
  local c
  for c in $(docker ps --format '{{.Names}}|{{.Image}}' 2>/dev/null | awk -F'|' -v p="$SELF_PREFIX" '$2 ~ /(^|\/)caddy(:|$)/ && $1 !~ "^"p {print $1}'); do
    MODE=docker; CONTAINER="$c"
    CF_IN="/etc/caddy/Caddyfile"
    local src
    src=$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/etc/caddy/Caddyfile"}}{{.Source}}{{end}}{{end}}' "$c")
    if [ -z "$src" ]; then
      src=$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/etc/caddy"}}{{.Source}}{{end}}{{end}}' "$c")
      [ -n "$src" ] && src="$src/Caddyfile"
    fi
    CF="$src"
    [ -n "$CF" ] && [ -f "$CF" ] && return 0
  done
  # 2) systemd service
  if systemctl is-active --quiet caddy 2>/dev/null; then
    MODE=systemd
    CF=$(systemctl cat caddy 2>/dev/null | grep -m1 '^ExecStart=' | grep -o -- '--config [^ ]*' | awk '{print $2}')
    CF=${CF:-/etc/caddy/Caddyfile}
    [ -f "$CF" ] && return 0
  fi
  return 1
}

validate() {
  if [ "$MODE" = docker ]; then docker exec "$CONTAINER" caddy validate --config "$CF_IN" --adapter caddyfile >/dev/null 2>&1
  else caddy validate --config "$CF" --adapter caddyfile >/dev/null 2>&1; fi
}
reload() {
  if [ "$MODE" = docker ]; then docker exec "$CONTAINER" caddy reload --config "$CF_IN" --adapter caddyfile >/dev/null 2>&1
  else systemctl reload caddy; fi
}

[ "$ACTION" = add ] || [ "$ACTION" = remove ] || { echo "usage: $0 add <domain> <port> | remove"; exit 2; }
if ! find_target; then echo "NOTFOUND"; exit 3; fi
echo "Использую Caddy: ${CONTAINER:-systemd} (конфиг $CF)"

BAK="$CF.bak-vkreger-$(date +%Y%m%d%H%M%S)"
cp "$CF" "$BAK"
TMP=$(mktemp)
sed '/# vkreger-begin/,/# vkreger-end/d' "$CF" > "$TMP"
if [ "$ACTION" = add ]; then
  [ -n "$(tail -c1 "$TMP")" ] && echo >> "$TMP"
  printf '# vkreger-begin (managed by: vk hostdomain)\n%s {\n\treverse_proxy 127.0.0.1:%s\n}\n# vkreger-end\n' "$DOMAIN" "$PORT" >> "$TMP"
fi
cat "$TMP" > "$CF"; rm -f "$TMP"

if ! validate; then
  cat "$BAK" > "$CF"; echo "Конфиг не прошёл проверку — вернул как было. Ничего не изменено."; exit 1
fi
if ! reload; then
  cat "$BAK" > "$CF"; reload || true; echo "Caddy не принял изменения — вернул как было."; exit 1
fi
echo "OK. Резервная копия: $BAK"
