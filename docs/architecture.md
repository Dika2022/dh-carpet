# Архитектура проекта

## Доставка изменений

Основной путь разработки и развёртывания:

`рабочий компьютер → локальный проект в VS Code/Codex → GitHub → production Ubuntu`

Production-сервер Ubuntu доступен по адресу `192.168.10.82`. Исходный код развёрнутого приложения должен находиться в `/srv/dh-carpet/app` и не должен редактироваться на сервере вручную.

## Размещение данных на production-сервере

Постоянные данные хранятся отдельно от исходного кода:

- `/srv/dh-carpet/media` — медиафайлы;
- `/srv/dh-carpet/backups` — резервные копии;
- `/srv/dh-carpet/infra` — серверная инфраструктура и секреты.

PostgreSQL, Redis и Qdrant работают в Docker. PostgreSQL является основной базой данных, Redis предназначен для очередей и временных данных, а Qdrant — для производного векторного индекса.

Backend также запускается в Docker и подключается к существующей external-сети `dh-backend`. Compose-конфигурация приложения не создаёт собственные экземпляры PostgreSQL, Redis или Qdrant. Несекретные настройки передаются через переменные окружения, а пароль PostgreSQL — через отдельный Docker secret.

## Конфигурация production

Не содержащие секретов переменные backend хранятся на сервере в `/srv/dh-carpet/infra/app.env`. Ожидаемое содержимое:

```dotenv
APP_ENV=production
SERVICE_CHECK_TIMEOUT_SECONDS=3
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=dhcarpet
POSTGRES_USER=dhapp
POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password
INTERNAL_API_KEY_FILE=/run/secrets/internal_api_key
REDIS_HOST=redis
REDIS_PORT=6379
QDRANT_HOST=qdrant
QDRANT_PORT=6333
```

Пароль PostgreSQL хранится отдельно в `/srv/dh-carpet/infra/secrets/postgres_password`, а ключ internal API — в `/srv/dh-carpet/infra/secrets/internal_api_key`. Compose подключает их в backend-контейнер через `/run/secrets`. Значения секретов не записываются в `app.env`, Compose или Git.

Production-значения параметров Compose:

```dotenv
DH_CARPET_ENV_FILE=/srv/dh-carpet/infra/app.env
POSTGRES_PASSWORD_SECRET_FILE=/srv/dh-carpet/infra/secrets/postgres_password
INTERNAL_API_KEY_SECRET_FILE=/srv/dh-carpet/infra/secrets/internal_api_key
```

API публикуется только на `127.0.0.1:8000`. Redis и Qdrant сейчас используются внутри Docker-сети без пароля, API key и TLS.

Для интеграции с сервером 1С используется отдельный LAN-only reverse proxy Nginx:

`Windows Server 1С 192.168.10.81 → http://192.168.10.82:8080 → http://127.0.0.1:8000`

Nginx слушает порт `8080` только на LAN-интерфейсе `192.168.10.82` и разрешает запросы только от `192.168.10.81`; для остальных источников действует `deny all`. Публикация Docker backend остаётся `127.0.0.1:8000`. Каноническая конфигурация находится в `deploy/nginx/dh-carpet-lan.conf`, установка выполняется отслеживаемым Git скриптом `sudo /srv/dh-carpet/app/scripts/install-lan-proxy.sh`.

Код поддерживает `INTERNAL_API_KEY` и `INTERNAL_API_KEY_FILE` для защиты `/api/internal/*`. В production ключ подключается как Docker secret; его значение не хранится в репозитории или env-файле.

## Целостность истории

Все внутренние primary key генерируются приложением как UUIDv4. Внешние ключи исторических таблиц используют `ON DELETE RESTRICT`: физическое удаление ковра, медиа или транскрипта блокируется, пока существуют связанные исторические записи. `audit_events` намеренно не имеет внешнего ключа к сущности, поэтому аудит сохраняется независимо; `entity_id` хранится как UUID, а внешний `actor_id` — как строка без связи с таблицей пользователей.

Статусы и источники хранятся в расширяемых `VARCHAR`, а не в PostgreSQL ENUM. Допустимые на текущем этапе значения контролируются приложением.

## Каталог ковров и интеграция с 1С

Штрихкод `rugs.barcode` — уникальный бизнес-идентификатор ковра из 1С. PostgreSQL хранит текущее состояние, версии исходных данных, историю фотографий и audit. Поток будущей интеграции:

`1С / отдельный агент → internal API → Pydantic validation → транзакционный sync-service → PostgreSQL → audit/history`

Backend не читает внутренние SQL-таблицы 1С и не записывает данные обратно в 1С. Один import-запрос обрабатывается в единой транзакции. Advisory lock по barcode сериализует конкурирующие обновления одного ковра.

Канонический snapshot включает нормализованные поля ковра, фотографии и `raw_payload`. Его SHA-256 fingerprint определяет изменение независимо от порядка ключей JSON. Идентичный fingerprint возвращает `unchanged` без новых history, photos и audit. При изменении текущая версия получает `valid_to`, создаётся новая версия, а отсутствующие в полном snapshot фотографии становятся историческими вместо физического удаления.

Запоздавший snapshot с `source_updated_at` меньше текущего либо другой fingerprint с тем же timestamp отклоняется с HTTP 409 до любых изменений в транзакции.

Подробный контракт приведён в [`docs/1c-agent-contract.md`](1c-agent-contract.md).
