# dh-carpet

Внутренняя система компании «Династия Хан» для распознавания ковров по скриншотам, ведения архива видео и синхронизации данных с 1С.

Планируемый технологический стек: Python и FastAPI для backend, React и TypeScript для frontend, PostgreSQL, Redis, Qdrant, Docker и Docker Compose.

Разработка ведётся локально с хранением изменений в GitHub. Развёртывание выполняется на production-сервер Ubuntu; исходный код и постоянные данные на сервере размещаются раздельно. PostgreSQL является источником истины, Redis используется для очередей и временных данных, Qdrant — как производный векторный индекс. Краткая схема и серверные пути описаны в [`docs/architecture.md`](docs/architecture.md).

## Структура репозитория

- `backend/` — FastAPI-приложение, модели, миграции и тесты.
- `frontend/` — пользовательский интерфейс.
- `deploy/` — конфигурация контейнеризации и развертывания.
- `docs/` — архитектура и другая документация проекта.
- `scripts/` — служебные скрипты разработки и эксплуатации.

## Локальный запуск backend

Требуется Python 3.12. Из корня репозитория:

```powershell
Copy-Item .env.example .env
Set-Location backend
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload --env-file ../.env
```

В локальном `.env` нужно заменить заглушку пароля и при необходимости указать адреса доступных локально сервисов. Файл `.env` не должен попадать в Git. После запуска API доступен по адресу `http://127.0.0.1:8000`, проверка состояния — `GET /api/health`.

## Миграции

Alembic читает настройки из переменных процесса. В PowerShell их можно загрузить из локального `.env`, после чего выполнить миграцию:

```powershell
Get-Content ..\.env | Where-Object { $_ -match '^[^#].+=' } | ForEach-Object { $name, $value = $_ -split '=', 2; Set-Item -Path "Env:$name" -Value $value }
alembic upgrade head
```

Новые изменения схемы создаются только отдельными миграциями Alembic.

## Тесты

Из каталога `backend/`:

```powershell
pytest
```

## Запуск через Docker

Compose запускает только backend и подключает его к уже существующей external-сети `dh-backend`:

```powershell
Copy-Item .env.example .env
New-Item -ItemType Directory -Force secrets
$secretPath = Join-Path (Resolve-Path secrets) "postgres_password"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($secretPath, "<локальный пароль>", $utf8NoBom)
$env:DH_CARPET_ENV_FILE = (Resolve-Path .env)
$env:POSTGRES_PASSWORD_SECRET_FILE = $secretPath
docker compose -f deploy/compose.yaml build
docker compose -f deploy/compose.yaml run --rm backend alembic upgrade head
docker compose -f deploy/compose.yaml up -d backend
```

Порт всегда публикуется только на `127.0.0.1:8000`. В production Compose по умолчанию использует `/srv/dh-carpet/infra/app.env` и Docker secret `/srv/dh-carpet/infra/secrets/postgres_password`; реальные секреты в env-файле, Compose и репозитории не хранятся.

Текущий этап содержит только фундамент backend, health-check и начальную схему данных. Интеграции с 1С, обработка медиа и распознавание ковров пока не реализованы.
