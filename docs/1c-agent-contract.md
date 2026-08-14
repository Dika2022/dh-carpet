# Контракт будущего агента 1С

## Назначение

Агент 1С передаёт в dh-carpet полный snapshot одного ковра через:

`POST /api/internal/1c/rugs/upsert`

Прямое чтение внутренних SQL-таблиц 1С запрещено. Endpoint не предназначен для публикации в интернет и дополнительно требует заголовок:

```http
X-Internal-API-Key: <локально настроенный ключ>
```

Ключ загружается из `INTERNAL_API_KEY` либо `INTERNAL_API_KEY_FILE` и не должен попадать в URL, логи или Git.

## Семантика snapshot

- `barcode` обязателен и однозначно определяет ковёр.
- `article` — каноническое имя артикула; во входном JSON также принимается alias `sku`.
- `photos` — полный актуальный набор фотографий источника на момент запроса, а не частичное дополнение.
- `raw_payload` — исходные данные агента, необходимые для трассировки и истории.
- `source_updated_at` должен содержать часовой пояс.
- размеры и цены передаются JSON-числами или десятичными строками без потери точности.

Snapshot канонизируется, после чего вычисляется SHA-256 fingerprint. Повтор идентичного snapshot возвращает `unchanged`. Изменение создаёт новую версию `rug_external_data`, закрывает прежнюю через `valid_to`, синхронизирует текущие фотографии без удаления старых и создаёт `audit_events`.

Если `source_updated_at` старше текущего значения ковра, endpoint возвращает HTTP 409 с кодом `stale_snapshot` без каких-либо записей. Одинаковый timestamp при разных fingerprint возвращает HTTP 409 с кодом `timestamp_conflict`. При отсутствии `source_updated_at` действует обычное сравнение fingerprint.

Возможные значения результата:

- `created` — новый barcode;
- `updated` — состояние изменилось;
- `unchanged` — fingerprint совпал с текущей версией.

## Пример запроса

Все данные ниже вымышлены:

```json
{
  "barcode": "TEST-1C-000042",
  "name": "Демонстрационный ковёр",
  "status": "available",
  "article": "DEMO-RUG-42",
  "country": "Тестовая страна",
  "composition": "80% тестовое волокно, 20% хлопок",
  "width_cm": "160.50",
  "length_cm": "230.25",
  "current_location": "Демонстрационный склад",
  "retail_price": "125000.00",
  "contractor_price": "110000.00",
  "currency": "RUB",
  "source_updated_at": "2026-08-14T12:30:00+03:00",
  "photos": [
    {
      "source": "1c",
      "external_id": "demo-photo-42-1",
      "original_url": "https://example.invalid/rugs/demo-42-1.jpg",
      "sort_order": 0,
      "checksum": "sha256:demo-checksum-not-real"
    }
  ],
  "raw_payload": {
    "source": "fictional-1c-agent",
    "object_version": 7,
    "note": "Вымышленный пример без реальных бизнес-данных"
  }
}
```

Пример ответа:

```json
{
  "result": "created",
  "rug_id": "00000000-0000-4000-8000-000000000042",
  "barcode": "TEST-1C-000042"
}
```

## Атомарность и аудит

Один upsert выполняется целиком в одной PostgreSQL-транзакции. Ошибка записи ковра, версии, фотографии или audit откатывает всю операцию. Автоматические события записываются с `actor_type=system` и `actor_id=1c-sync`; при `unchanged` audit не создаётся.
