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
REDIS_HOST=redis
REDIS_PORT=6379
QDRANT_HOST=qdrant
QDRANT_PORT=6333
```

Пароль PostgreSQL хранится отдельно в `/srv/dh-carpet/infra/secrets/postgres_password`. Compose подключает этот файл в backend-контейнер как `/run/secrets/postgres_password`. Значение пароля не записывается в `app.env`, Compose или Git.

Production-значения параметров Compose:

```dotenv
DH_CARPET_ENV_FILE=/srv/dh-carpet/infra/app.env
POSTGRES_PASSWORD_SECRET_FILE=/srv/dh-carpet/infra/secrets/postgres_password
```

API публикуется только на `127.0.0.1:8000`. Redis и Qdrant сейчас используются внутри Docker-сети без пароля, API key и TLS.

## Целостность истории

Все внутренние primary key генерируются приложением как UUIDv4. Внешние ключи исторических таблиц используют `ON DELETE RESTRICT`: физическое удаление ковра, медиа или транскрипта блокируется, пока существуют связанные исторические записи. `audit_events` намеренно не имеет внешнего ключа к сущности, поэтому аудит сохраняется независимо; `entity_id` хранится как UUID, а внешний `actor_id` — как строка без связи с таблицей пользователей.

Статусы и источники хранятся в расширяемых `VARCHAR`, а не в PostgreSQL ENUM. Допустимые на текущем этапе значения контролируются приложением.
