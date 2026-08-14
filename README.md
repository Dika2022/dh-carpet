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

Новые изменения схемы создаются только отдельными миграциями Alembic. Каталог ковров добавляется ревизией `20260814_0002`; базовая применённая ревизия `20260814_0001` не изменяется.

## API каталога

- `GET /api/rugs` — пагинация и фильтры `status`, `barcode`, `query`, `current_location`;
- `GET /api/rugs/{id}` — подробная карточка;
- `GET /api/rugs/by-barcode/{barcode}` — карточка по штрихкоду 1С;
- `POST /api/internal/1c/rugs/upsert` — атомарный импорт одного полного snapshot от будущего агента 1С.

Internal endpoint требует заголовок `X-Internal-API-Key`. Ключ читается из `INTERNAL_API_KEY` или, предпочтительно для production, из `INTERNAL_API_KEY_FILE`. Контракт и вымышленный пример запроса приведены в [`docs/1c-agent-contract.md`](docs/1c-agent-contract.md).

## Тесты

Из каталога `backend/`:

```powershell
pytest
```

Unit/API тесты, не требующие БД, запускаются обычным `pytest`. Интеграционные тесты работают только с отдельной PostgreSQL, на которой заранее выполнено `alembic upgrade head` до ревизии `20260814_0002`:

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://<test-user>:<test-password>@127.0.0.1:5432/dhcarpet_test"
pytest -m integration
```

SQLite намеренно не используется. `TEST_DATABASE_URL` запрещено направлять на production.

## Запуск через Docker

Compose запускает только backend и подключает его к уже существующей external-сети `dh-backend`:

```powershell
Copy-Item .env.example .env
New-Item -ItemType Directory -Force secrets
$secretPath = Join-Path (Resolve-Path secrets) "postgres_password"
$internalSecretPath = Join-Path (Resolve-Path secrets) "internal_api_key"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($secretPath, "<локальный пароль>", $utf8NoBom)
[System.IO.File]::WriteAllText($internalSecretPath, "<локальный internal key>", $utf8NoBom)
$env:DH_CARPET_ENV_FILE = (Resolve-Path .env)
$env:POSTGRES_PASSWORD_SECRET_FILE = $secretPath
$env:INTERNAL_API_KEY_SECRET_FILE = $internalSecretPath
docker compose -f deploy/compose.yaml build
docker compose -f deploy/compose.yaml run --rm backend alembic upgrade head
docker compose -f deploy/compose.yaml up -d backend
```

Порт всегда публикуется только на `127.0.0.1:8000`. В production Compose по умолчанию использует `/srv/dh-carpet/infra/app.env`, PostgreSQL secret `/srv/dh-carpet/infra/secrets/postgres_password` и internal API secret `/srv/dh-carpet/infra/secrets/internal_api_key`; реальные секреты в env-файле, Compose и репозитории не хранятся.

Текущий этап содержит каталог ковров и внутренний контракт приёма данных от будущего агента 1С. Прямого подключения к SQL-базе 1С, записи в 1С, обработки Instagram, AI и распознавания изображений нет.
