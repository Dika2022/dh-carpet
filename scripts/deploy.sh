#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly APP_DIR="${APP_DIR:-$(dirname "$SCRIPT_DIR")}"
readonly COMPOSE_FILE="${COMPOSE_FILE:-$APP_DIR/deploy/compose.yaml}"
readonly BACKUP_DIR="${BACKUP_DIR:-/srv/dh-carpet/backups/postgres}"
readonly POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-infra-postgres-1}"
readonly POSTGRES_DB="${POSTGRES_DB:-dhcarpet}"
readonly POSTGRES_USER="${POSTGRES_USER:-dhapp}"
readonly TEST_POSTGRES_IMAGE="${TEST_POSTGRES_IMAGE:-postgres:18}"
readonly BACKEND_IMAGE="${BACKEND_IMAGE:-dh-carpet-backend:local}"
readonly HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/health}"

cd "$APP_DIR"

if [[ -n "$(git status --porcelain)" ]]; then
    echo "Deployment остановлен: рабочее дерево production-репозитория не чистое." >&2
    exit 1
fi

git pull --ff-only

if [[ -n "$(git status --porcelain)" ]]; then
    echo "Deployment остановлен: после git pull появились незакоммиченные изменения." >&2
    exit 1
fi

docker compose -f "$COMPOSE_FILE" build backend

run_id="$(date +%Y%m%d%H%M%S)-$$"
test_network="dh-carpet-test-$run_id"
test_db_container="dh-carpet-test-postgres-$run_id"
test_password="$(openssl rand -hex 24)"

cleanup_test_resources() {
    docker rm -f "$test_db_container" >/dev/null 2>&1 || true
    docker network rm "$test_network" >/dev/null 2>&1 || true
}
trap cleanup_test_resources EXIT

docker network create "$test_network" >/dev/null
docker run -d \
    --name "$test_db_container" \
    --network "$test_network" \
    --network-alias test-postgres \
    -e POSTGRES_DB=dhcarpet_test \
    -e POSTGRES_USER=dhapp_test \
    -e POSTGRES_PASSWORD="$test_password" \
    "$TEST_POSTGRES_IMAGE" >/dev/null

for attempt in $(seq 1 60); do
    if docker exec "$test_db_container" \
        pg_isready -U dhapp_test -d dhcarpet_test >/dev/null 2>&1; then
        break
    fi
    if [[ "$attempt" -eq 60 ]]; then
        echo "Временная PostgreSQL не стала доступна за 60 секунд." >&2
        exit 1
    fi
    sleep 1
done

test_database_url="postgresql+psycopg://dhapp_test:${test_password}@test-postgres:5432/dhcarpet_test"
docker run --rm \
    --user root \
    --network "$test_network" \
    -e APP_ENV=test \
    -e SERVICE_CHECK_TIMEOUT_SECONDS=1 \
    -e POSTGRES_HOST=test-postgres \
    -e POSTGRES_PORT=5432 \
    -e POSTGRES_DB=dhcarpet_test \
    -e POSTGRES_USER=dhapp_test \
    -e POSTGRES_PASSWORD="$test_password" \
    -e REDIS_HOST=redis \
    -e REDIS_PORT=6379 \
    -e QDRANT_HOST=qdrant \
    -e QDRANT_PORT=6333 \
    -e INTERNAL_API_KEY=test-internal-key \
    -e TEST_DATABASE_URL="$test_database_url" \
    "$BACKEND_IMAGE" \
    sh -c 'pip install --disable-pip-version-check -q ".[dev]" && alembic upgrade head && alembic current && pytest -ra'

cleanup_test_resources
trap - EXIT
unset test_password test_database_url

mkdir -p "$BACKUP_DIR"
timestamp="$(date +%Y%m%d-%H%M%S)"
backup_path="$BACKUP_DIR/dhcarpet-${timestamp}-pre-migration.dump"
backup_tmp="${backup_path}.tmp.$$"

cleanup_incomplete_backup() {
    rm -f -- "$backup_tmp"
}
trap cleanup_incomplete_backup EXIT

docker exec "$POSTGRES_CONTAINER" \
    pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$backup_tmp"
test -s "$backup_tmp"
docker exec -i "$POSTGRES_CONTAINER" pg_restore --list < "$backup_tmp" >/dev/null
chmod 0600 "$backup_tmp"
mv -- "$backup_tmp" "$backup_path"
trap - EXIT
echo "Проверенный backup создан: $backup_path"

docker compose -f "$COMPOSE_FILE" run --rm backend alembic upgrade head && \
    docker compose -f "$COMPOSE_FILE" run --rm backend alembic current && \
    docker compose -f "$COMPOSE_FILE" up -d --no-deps backend

for attempt in $(seq 1 30); do
    if health_json="$(curl --fail --silent --show-error "$HEALTH_URL" 2>/dev/null)"; then
        break
    fi
    if [[ "$attempt" -eq 30 ]]; then
        echo "Backend не прошёл HTTP health check за 30 секунд." >&2
        exit 1
    fi
    sleep 1
done

printf '%s' "$health_json" | docker run --rm -i \
    --entrypoint python "$BACKEND_IMAGE" -c '
import json
import sys

health = json.load(sys.stdin)
expected = {"postgres": "ok", "redis": "ok", "qdrant": "ok"}
if health.get("status") != "ok" or health.get("services") != expected:
    raise SystemExit(f"Некорректный health response: {health!r}")
'

echo "Deployment завершён успешно: $health_json"
