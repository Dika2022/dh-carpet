#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "Скрипт необходимо запускать через sudo." >&2
    exit 1
fi

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly APP_DIR="${APP_DIR:-$(dirname "$SCRIPT_DIR")}"
readonly SOURCE_CONFIG="$APP_DIR/deploy/nginx/dh-carpet-lan.conf"
readonly TARGET_CONFIG="/etc/nginx/conf.d/dh-carpet-lan.conf"
readonly DEFAULT_SITE="/etc/nginx/sites-enabled/default"

test -f "$SOURCE_CONFIG"
curl --fail --silent --show-error http://127.0.0.1:8000/api/health >/dev/null

masked_by_script=0
unmask_nginx() {
    if [[ "$masked_by_script" -eq 1 ]]; then
        systemctl unmask nginx.service >/dev/null
    fi
}
trap unmask_nginx EXIT

if ! command -v nginx >/dev/null 2>&1; then
    systemctl mask nginx.service >/dev/null
    masked_by_script=1
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends nginx
fi

if [[ -L "$DEFAULT_SITE" ]]; then
    unlink "$DEFAULT_SITE"
elif [[ -e "$DEFAULT_SITE" ]]; then
    echo "$DEFAULT_SITE существует и не является символической ссылкой; автоматическая установка остановлена." >&2
    exit 1
fi

install -o root -g root -m 0644 "$SOURCE_CONFIG" "$TARGET_CONFIG"

unmask_nginx
masked_by_script=0
nginx -t
systemctl enable --now nginx.service
systemctl reload nginx.service

echo "LAN proxy установлен: http://192.168.10.82:8080"
