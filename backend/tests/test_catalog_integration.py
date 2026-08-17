import os
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.dependencies import get_request_settings, get_session
from app.core.config import Settings
from app.main import create_app
from app.models.entities import AuditEvent, Rug, RugExternalData, RugPhoto
from app.repositories.rugs import AuditRepository
from app.schemas.rugs import RugImportRequest
from app.services.rug_sync import RugSyncService

pytestmark = pytest.mark.integration
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def sample_payload(
    *,
    barcode: str | None = None,
    name: str = "Тестовый ковёр",
    status: str = "available",
) -> dict:
    barcode = barcode or f"TEST-{uuid.uuid4().hex}"
    return {
        "barcode": barcode,
        "name": name,
        "status": status,
        "article": "ART-TEST-01",
        "country": "Тестовая страна",
        "composition": "100% тестовое волокно",
        "width_cm": "160.50",
        "length_cm": "230.25",
        "current_location": "Тестовый склад",
        "retail_price": "125000.00",
        "currency": "RUB",
        "source_updated_at": "2026-08-14T10:00:00+03:00",
        "photos": [
            {
                "source": "1c",
                "external_id": "photo-test-1",
                "original_url": "https://example.invalid/rugs/test-1.jpg",
                "sort_order": 0,
                "checksum": "sha256:test-photo-1",
            }
        ],
        "raw_payload": {
            "test_object": "rug",
            "test_version": 1,
        },
    }


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    if not TEST_DATABASE_URL:
        pytest.skip("Для integration tests требуется TEST_DATABASE_URL")
    url = make_url(TEST_DATABASE_URL)
    if url.get_backend_name() != "postgresql":
        pytest.fail("TEST_DATABASE_URL должен указывать на PostgreSQL, не SQLite")
    if url.drivername not in {"postgresql+psycopg", "postgresql+psycopg_async"}:
        pytest.fail("TEST_DATABASE_URL должен использовать драйвер psycopg")

    engine = create_async_engine(url, poolclass=NullPool)
    connection = await engine.connect()
    outer_transaction = await connection.begin()
    try:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        if revision != "20260814_0003":
            pytest.fail(
                "На тестовой PostgreSQL должна быть применена migration 20260814_0003"
            )
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
    finally:
        await outer_transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest_asyncio.fixture
async def api_client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    application = create_app()

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    settings = Settings()  # type: ignore[call-arg]
    application.dependency_overrides[get_session] = session_override
    application.dependency_overrides[get_request_settings] = lambda: settings
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        yield client


async def count_rows(session: AsyncSession, model: type, *criteria) -> int:
    value = await session.scalar(
        select(func.count()).select_from(model).where(*criteria)
    )
    return int(value or 0)


async def test_create_new_rug_with_history_photo_and_audit(
    db_session: AsyncSession,
) -> None:
    result = await RugSyncService(db_session).upsert(
        RugImportRequest.model_validate(sample_payload())
    )

    assert result.result == "created"
    assert await count_rows(db_session, Rug, Rug.id == result.rug_id) == 1
    assert (
        await count_rows(
            db_session,
            RugExternalData,
            RugExternalData.rug_id == result.rug_id,
        )
        == 1
    )
    assert (
        await count_rows(db_session, RugPhoto, RugPhoto.rug_id == result.rug_id)
        == 1
    )
    assert (
        await count_rows(db_session, AuditEvent, AuditEvent.entity_id == result.rug_id)
        == 1
    )
    event = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.entity_id == result.rug_id)
    )
    assert event is not None
    assert event.actor_type == "system"
    assert event.actor_id == "1c-sync"


async def test_identical_upsert_is_unchanged_and_changed_payload_adds_history(
    db_session: AsyncSession,
) -> None:
    original = RugImportRequest.model_validate(sample_payload())
    created = await RugSyncService(db_session).upsert(original)
    unchanged = await RugSyncService(db_session).upsert(original)

    assert created.rug_id == unchanged.rug_id
    assert unchanged.result == "unchanged"
    assert (
        await count_rows(
            db_session,
            RugExternalData,
            RugExternalData.rug_id == created.rug_id,
        )
        == 1
    )
    assert (
        await count_rows(db_session, AuditEvent, AuditEvent.entity_id == created.rug_id)
        == 1
    )
    await db_session.rollback()

    changed_payload = sample_payload(
        barcode=original.barcode,
        name="Обновлённый тестовый ковёр",
    )
    changed_payload["source_updated_at"] = "2026-08-14T10:00:01+03:00"
    changed_payload["raw_payload"]["test_version"] = 2
    updated = await RugSyncService(db_session).upsert(
        RugImportRequest.model_validate(changed_payload)
    )

    assert updated.result == "updated"
    assert (
        await count_rows(
            db_session,
            RugExternalData,
            RugExternalData.rug_id == created.rug_id,
        )
        == 2
    )
    assert (
        await count_rows(db_session, AuditEvent, AuditEvent.entity_id == created.rug_id)
        == 2
    )
    versions = list(
        (
            await db_session.scalars(
                select(RugExternalData)
                .where(RugExternalData.rug_id == created.rug_id)
                .order_by(RugExternalData.valid_from)
            )
        ).all()
    )
    assert versions[0].valid_to is not None
    assert versions[1].valid_to is None


async def test_barcode_is_unique(db_session: AsyncSession) -> None:
    payload = RugImportRequest.model_validate(sample_payload())
    await RugSyncService(db_session).upsert(payload)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                Rug(
                    id=uuid.uuid4(),
                    barcode=payload.barcode,
                    name="Дубликат",
                    status="unknown",
                )
            )
            await db_session.flush()


async def test_duplicate_photos_are_not_created(db_session: AsyncSession) -> None:
    payload = sample_payload()
    payload["photos"].append({**payload["photos"][0], "sort_order": 5})
    request = RugImportRequest.model_validate(payload)

    created = await RugSyncService(db_session).upsert(request)
    await RugSyncService(db_session).upsert(request)

    assert await count_rows(db_session, RugPhoto, RugPhoto.rug_id == created.rug_id) == 1


async def test_replaced_photo_is_kept_as_history(db_session: AsyncSession) -> None:
    initial_payload = sample_payload()
    created = await RugSyncService(db_session).upsert(
        RugImportRequest.model_validate(initial_payload)
    )

    changed_payload = sample_payload(barcode=initial_payload["barcode"])
    changed_payload["photos"] = [
        {
            "source": "1c",
            "external_id": "photo-test-2",
            "original_url": "https://example.invalid/rugs/test-2.jpg",
            "sort_order": 0,
            "checksum": "sha256:test-photo-2",
        }
    ]
    changed_payload["source_updated_at"] = "2026-08-14T10:00:01+03:00"
    changed_payload["raw_payload"]["test_version"] = 2
    await RugSyncService(db_session).upsert(
        RugImportRequest.model_validate(changed_payload)
    )

    photos = list(
        (
            await db_session.scalars(
                select(RugPhoto)
                .where(RugPhoto.rug_id == created.rug_id)
                .order_by(RugPhoto.created_at)
            )
        ).all()
    )
    assert len(photos) == 2
    historical = [photo for photo in photos if not photo.is_current]
    current = [photo for photo in photos if photo.is_current]
    assert len(historical) == 1
    assert historical[0].valid_to is not None
    assert len(current) == 1
    assert current[0].valid_to is None


async def test_catalog_endpoints_filters_and_search(
    db_session: AsyncSession, api_client: httpx.AsyncClient
) -> None:
    marker = uuid.uuid4().hex
    first_payload = sample_payload()
    first_payload["article"] = f"ART-{marker}-1"
    first_payload["current_location"] = f"LOCATION-{marker}"
    first = await RugSyncService(db_session).upsert(
        RugImportRequest.model_validate(first_payload)
    )
    second_payload = sample_payload(
        name="Проданный образец",
        status="sold",
    )
    second_payload["article"] = f"ART-{marker}-2"
    second_payload["current_location"] = f"LOCATION-{marker}"
    second = await RugSyncService(db_session).upsert(
        RugImportRequest.model_validate(second_payload)
    )

    listing = await api_client.get(
        "/api/rugs",
        params={"page": 1, "page_size": 10, "query": marker},
    )
    assert listing.status_code == 200
    assert listing.json()["total"] == 2

    by_id = await api_client.get(f"/api/rugs/{first.rug_id}")
    by_barcode = await api_client.get(f"/api/rugs/by-barcode/{first.barcode}")
    assert by_id.status_code == 200
    assert by_barcode.status_code == 200
    assert by_id.json()["barcode"] == first.barcode
    assert by_id.json()["retail_price"] == "125000.00"
    assert by_barcode.json()["history"]["version_count"] == 1
    assert len(by_barcode.json()["photos"]) == 1

    missing_id = await api_client.get(f"/api/rugs/{uuid.uuid4()}")
    missing_barcode = await api_client.get(
        f"/api/rugs/by-barcode/ABSENT-{uuid.uuid4().hex}"
    )
    assert missing_id.status_code == 404
    assert missing_barcode.status_code == 404
    invalid_id = await api_client.get("/api/rugs/not-a-uuid")
    assert invalid_id.status_code == 422

    filtered = await api_client.get(
        "/api/rugs", params={"status": "sold", "barcode": second.barcode}
    )
    searched = await api_client.get("/api/rugs", params={"query": marker})
    located = await api_client.get(
        "/api/rugs", params={"current_location": f"LOCATION-{marker}"}
    )
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["status"] == "sold"
    assert searched.json()["total"] == 2
    assert located.json()["total"] == 2


@pytest.mark.parametrize("provided_key", [None, "wrong-key"])
async def test_internal_api_rejects_missing_or_wrong_key(
    api_client: httpx.AsyncClient,
    provided_key: str | None,
) -> None:
    headers = {"X-Internal-API-Key": provided_key} if provided_key else {}
    response = await api_client.post(
        "/api/internal/1c/rugs/upsert",
        json=sample_payload(),
        headers=headers,
    )
    assert response.status_code == 401


async def test_internal_api_accepts_correct_key(api_client: httpx.AsyncClient) -> None:
    response = await api_client.post(
        "/api/internal/1c/rugs/upsert",
        json=sample_payload(),
        headers={"X-Internal-API-Key": "test-internal-key"},
    )
    assert response.status_code == 200
    assert response.json()["result"] == "created"


@pytest.mark.parametrize(
    ("source_updated_at", "expected_code"),
    [
        ("2026-08-14T09:59:59+03:00", "stale_snapshot"),
        ("2026-08-14T10:00:00+03:00", "timestamp_conflict"),
    ],
)
async def test_internal_api_rejects_source_timestamp_conflicts_without_writes(
    db_session: AsyncSession,
    api_client: httpx.AsyncClient,
    source_updated_at: str,
    expected_code: str,
) -> None:
    initial_payload = sample_payload()
    headers = {"X-Internal-API-Key": "test-internal-key"}
    created = await api_client.post(
        "/api/internal/1c/rugs/upsert",
        json=initial_payload,
        headers=headers,
    )
    assert created.status_code == 200
    rug_id = uuid.UUID(created.json()["rug_id"])

    conflicting_payload = sample_payload(
        barcode=initial_payload["barcode"],
        name="Конфликтующая версия",
    )
    conflicting_payload["source_updated_at"] = source_updated_at
    conflicting_payload["raw_payload"]["test_version"] = 2
    conflict = await api_client.post(
        "/api/internal/1c/rugs/upsert",
        json=conflicting_payload,
        headers=headers,
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == expected_code
    assert conflict.json()["detail"]["barcode"] == initial_payload["barcode"]
    assert (
        await count_rows(
            db_session,
            RugExternalData,
            RugExternalData.rug_id == rug_id,
        )
        == 1
    )
    assert await count_rows(db_session, RugPhoto, RugPhoto.rug_id == rug_id) == 1
    assert await count_rows(db_session, AuditEvent, AuditEvent.entity_id == rug_id) == 1


async def test_same_timestamp_and_identical_fingerprint_is_unchanged(
    api_client: httpx.AsyncClient,
) -> None:
    payload = sample_payload()
    headers = {"X-Internal-API-Key": "test-internal-key"}

    created = await api_client.post(
        "/api/internal/1c/rugs/upsert", json=payload, headers=headers
    )
    unchanged = await api_client.post(
        "/api/internal/1c/rugs/upsert", json=payload, headers=headers
    )

    assert created.status_code == 200
    assert unchanged.status_code == 200
    assert unchanged.json()["result"] == "unchanged"


async def test_upsert_rolls_back_when_audit_write_fails(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected_rug_id = uuid.uuid4()
    payload = sample_payload()

    original_new_rug = RugSyncService._new_rug

    def new_rug_with_known_id(request: RugImportRequest) -> Rug:
        rug = original_new_rug(request)
        rug.id = expected_rug_id
        return rug

    def fail_audit(_repository: AuditRepository, _event: AuditEvent) -> None:
        raise RuntimeError("Искусственная ошибка audit")

    monkeypatch.setattr(
        RugSyncService,
        "_new_rug",
        staticmethod(new_rug_with_known_id),
    )
    monkeypatch.setattr(AuditRepository, "add", fail_audit)

    with pytest.raises(RuntimeError, match="Искусственная ошибка audit"):
        await RugSyncService(db_session).upsert(
            RugImportRequest.model_validate(payload)
        )

    assert await count_rows(db_session, Rug, Rug.id == expected_rug_id) == 0
    assert (
        await count_rows(
            db_session,
            RugExternalData,
            RugExternalData.rug_id == expected_rug_id,
        )
        == 0
    )
    assert (
        await count_rows(db_session, RugPhoto, RugPhoto.rug_id == expected_rug_id)
        == 0
    )
    assert (
        await count_rows(db_session, AuditEvent, AuditEvent.entity_id == expected_rug_id)
        == 0
    )
