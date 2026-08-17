import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.dependencies import get_request_settings, get_session
from app.core.config import Settings
from app.main import create_app
from app.models.entities import ExternalPhotoFile, MediaItem, Rug, RugEvent, RugLocation
from app.schemas.rugs import RugImportRequest
from app.schemas.stage3 import LalitaEventConfirm, LalitaEventCreate, OneCBulkImportRequest, OneCEventImport
from app.services.photo_archive import PhotoArchiveScanner, article_from_filename
from app.services.rug_sync import RugSyncService
from app.services.stage3 import BulkSyncService, LalitaEventService, OneCEventSyncService, TimelineService

pytestmark = pytest.mark.integration
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest_asyncio.fixture
async def stage3_session() -> AsyncIterator[AsyncSession]:
    if not TEST_DATABASE_URL:
        pytest.skip("Для integration tests требуется TEST_DATABASE_URL")
    url = make_url(TEST_DATABASE_URL)
    if url.get_backend_name() != "postgresql":
        pytest.fail("TEST_DATABASE_URL должен указывать на PostgreSQL")
    engine = create_async_engine(url, poolclass=NullPool)
    connection = await engine.connect()
    transaction = await connection.begin()
    try:
        assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260814_0003"
        session = AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
    finally:
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest_asyncio.fixture
async def stage3_client(stage3_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    application = create_app()

    async def override() -> AsyncIterator[AsyncSession]:
        yield stage3_session

    application.dependency_overrides[get_session] = override
    application.dependency_overrides[get_request_settings] = lambda: Settings()  # type: ignore[call-arg]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
        yield client


def rug_payload(*, category: str = "rug", stock: str = "0", suffix: str | None = None) -> dict:
    marker = suffix or uuid.uuid4().hex
    return {
        "barcode": f"BC-{marker}",
        "article": f"ART{marker}",
        "name": f"Товар {marker}",
        "status": "unknown",
        "category": category,
        "stock_qty": stock,
        "stock_unit": "шт",
        "retail_price_unit": "шт" if category != "carpet" else "м²",
        "attributes": {"colors": ["бежевый"], "pile_height_mm": "8"},
        "source_updated_at": "2026-08-15T10:00:00+03:00",
        "locations": [{"warehouse": "Основной", "cell": "A-1", "qty": stock}],
        "photos": [],
        "raw_payload": {"source": "1c"},
    }


async def create_rug(session: AsyncSession, **kwargs) -> tuple[uuid.UUID, dict]:
    payload = rug_payload(**kwargs)
    result = await RugSyncService(session).upsert(RugImportRequest.model_validate(payload))
    await session.rollback()
    return result.rug_id, payload


async def add_media(session: AsyncSession, suffix: str) -> MediaItem:
    async with session.begin():
        media = MediaItem(source="test", external_id=suffix, media_type="video", published_at=datetime(2026, 8, 1, tzinfo=UTC))
        session.add(media)
        await session.flush()
    return media


async def row_count(session: AsyncSession, model: type, *where) -> int:
    return int(await session.scalar(select(func.count()).select_from(model).where(*where)) or 0)


@pytest.mark.parametrize("category", ["rug", "carpet", "hide"])
async def test_import_categories_zero_stock_and_idempotency(stage3_session: AsyncSession, category: str) -> None:
    payload = rug_payload(category=category, stock="0")
    request = RugImportRequest.model_validate(payload)
    first = await RugSyncService(stage3_session).upsert(request)
    second = await RugSyncService(stage3_session).upsert(request)
    rug = await stage3_session.get(Rug, first.rug_id)
    assert first.result == "created" and second.result == "unchanged"
    assert rug is not None and rug.category == category
    assert rug.stock_qty == 0 and rug.status == "unknown"


async def test_location_snapshot_keeps_history(stage3_session: AsyncSession) -> None:
    rug_id, payload = await create_rug(stage3_session, stock="2")
    payload["source_updated_at"] = "2026-08-15T10:01:00+03:00"
    payload["locations"] = [
        {"warehouse": "Основной", "cell": "A-1", "qty": "1"},
        {"warehouse": "Запасной", "cell": None, "qty": "1"},
    ]
    await RugSyncService(stage3_session).upsert(RugImportRequest.model_validate(payload))
    locations = list((await stage3_session.scalars(select(RugLocation).where(RugLocation.rug_id == rug_id))).all())
    assert len(locations) == 3
    assert sum(item.is_current for item in locations) == 2
    assert all(item.valid_to is not None for item in locations if not item.is_current)


async def test_retail_sales_returns_update_and_unpost(stage3_session: AsyncSession) -> None:
    rug_id, payload = await create_rug(stage3_session)
    barcode = payload["barcode"]
    retail = OneCEventImport(barcode=barcode, event_type="retail_price_change", event_at=datetime(2026, 1, 1, tzinfo=UTC), price="23000", source_ref="price-1", source_line_key="1")
    same = retail.model_copy(update={"source_ref": "price-2"})
    changed = retail.model_copy(update={"event_at": datetime(2026, 2, 1, tzinfo=UTC), "price": Decimal("25000"), "source_ref": "price-3"})
    assert (await OneCEventSyncService(stage3_session).upsert(retail))[0] == "created"
    assert (await OneCEventSyncService(stage3_session).upsert(same))[0] == "unchanged"
    assert (await OneCEventSyncService(stage3_session).upsert(changed))[0] == "created"
    base = dict(barcode=barcode, event_at=datetime(2026, 3, 1, tzinfo=UTC), price="17000", qty="1", unit="шт", counterparty="Покупатель", source_ref="sale-doc")
    sale1 = OneCEventImport(event_type="sale", source_line_key="1", **base)
    sale2 = OneCEventImport(event_type="sale", source_line_key="2", price="18000", **{k: v for k, v in base.items() if k != "price"})
    await OneCEventSyncService(stage3_session).upsert(sale1)
    await OneCEventSyncService(stage3_session).upsert(sale2)
    updated = sale1.model_copy(update={"price": Decimal("17500")})
    assert (await OneCEventSyncService(stage3_session).upsert(updated))[0] == "updated"
    unposted = updated.model_copy(update={"posted": False})
    await OneCEventSyncService(stage3_session).upsert(unposted)
    return1 = OneCEventImport(event_type="customer_return", source_line_key="1", source_ref="return-doc", **{k: v for k, v in base.items() if k not in {"source_ref"}})
    return2 = return1.model_copy(update={"source_line_key": "2", "price": Decimal("16000")})
    await OneCEventSyncService(stage3_session).upsert(return1)
    await OneCEventSyncService(stage3_session).upsert(return2)
    await OneCEventSyncService(stage3_session).upsert(return2.model_copy(update={"posted": False}))
    events = list((await stage3_session.scalars(select(RugEvent).where(RugEvent.rug_id == rug_id))).all())
    assert len([item for item in events if item.event_type == "retail_price_change"]) == 2
    assert len([item for item in events if item.event_type == "sale"]) == 2
    assert len([item for item in events if item.event_type == "customer_return"]) == 2
    assert sum(item.is_visible for item in events if item.event_type in {"sale", "customer_return"}) == 2


async def test_document_snapshot_closes_removed_lines_and_unposted_document(
    stage3_session: AsyncSession,
) -> None:
    rug_id, payload = await create_rug(stage3_session)
    common = {
        "barcode": payload["barcode"],
        "event_type": "sale",
        "event_at": "2026-08-17T12:00:00+03:00",
        "price": "1000",
        "qty": "1",
        "source_ref": "11111111-1111-4111-8111-111111111111",
    }
    first = {**common, "source_line_key": "line-1"}
    second = {**common, "source_line_key": "line-2"}
    initial = OneCBulkImportRequest.model_validate({
        "mode": "incremental",
        "events": [first, second],
        "document_snapshots": [{
            "event_type": "sale",
            "source_ref": common["source_ref"],
            "posted": True,
            "line_keys": ["line-1", "line-2"],
        }],
    })
    assert (await BulkSyncService(stage3_session).import_all(initial)).failed_items == 0

    changed = OneCBulkImportRequest.model_validate({
        "mode": "incremental",
        "events": [{**first, "price": "1100"}],
        "document_snapshots": [{
            "event_type": "sale",
            "source_ref": common["source_ref"],
            "posted": True,
            "line_keys": ["line-1"],
        }],
    })
    assert (await BulkSyncService(stage3_session).import_all(changed)).failed_items == 0
    events = list((await stage3_session.scalars(select(RugEvent).where(
        RugEvent.rug_id == rug_id,
        RugEvent.source_ref == common["source_ref"],
    ))).all())
    assert {item.source_line_key: item.is_visible for item in events} == {
        "line-1": True,
        "line-2": False,
    }

    unposted = OneCBulkImportRequest.model_validate({
        "mode": "incremental",
        "document_snapshots": [{
            "event_type": "sale",
            "source_ref": common["source_ref"],
            "posted": False,
            "line_keys": [],
        }],
    })
    assert (await BulkSyncService(stage3_session).import_all(unposted)).failed_items == 0
    await stage3_session.refresh(next(item for item in events if item.source_line_key == "line-1"))
    assert not any(item.is_visible for item in events)


async def test_bulk_sync_records_per_item_results(stage3_session: AsyncSession) -> None:
    payloads = [rug_payload(category=value) for value in ("rug", "carpet", "hide")]
    request = OneCBulkImportRequest(mode="initial", rugs=[RugImportRequest.model_validate(item) for item in payloads])
    result = await BulkSyncService(stage3_session).import_all(request)
    assert result.total_items == 3 and result.succeeded_items == 3 and result.failed_items == 0


async def test_lalita_discount_lifecycle_and_durations(stage3_session: AsyncSession) -> None:
    rug_id, payload = await create_rug(stage3_session)
    await OneCEventSyncService(stage3_session).upsert(OneCEventImport(
        barcode=payload["barcode"], event_type="retail_price_change",
        event_at=datetime(2026, 1, 1, tzinfo=UTC), price="10000",
        source_ref="price", source_line_key="1",
    ))
    media1 = await add_media(stage3_session, uuid.uuid4().hex)
    media2 = await add_media(stage3_session, uuid.uuid4().hex)
    service = LalitaEventService(stage3_session)
    request = LalitaEventCreate(
        rug_id=rug_id, event_at=datetime(2026, 2, 1, tzinfo=UTC), media_item_id=media1.id,
        discount_type="percent", discount_value="20", duration_expression="на 2–3 дня",
    )
    outcome, first = await service.create(request)
    duplicate, same = await service.create(request)
    assert outcome == "created" and duplicate == "unchanged" and same.id == first.id
    assert first.calculated_price == Decimal("8000.00")
    assert first.valid_until == request.event_at + timedelta(days=3)
    _, second = await service.create(LalitaEventCreate(
        rug_id=rug_id, event_at=datetime(2026, 2, 2, tzinfo=UTC), media_item_id=media2.id,
        discount_type="absolute", discount_value="1500", duration_expression="на несколько дней",
    ))
    assert first.status == "replaced" and second.calculated_price == Decimal("8500.00")
    assert second.valid_until == datetime(2026, 2, 9, tzinfo=UTC)
    confirmed = await service.confirm(second.id, LalitaEventConfirm(price="9000", actor_id="admin-test"))
    assert confirmed.status == "confirmed" and confirmed.price == Decimal("9000")
    await service.reject(second.id, "admin-test")
    assert await stage3_session.get(RugEvent, second.id) is None


async def test_lalita_unknown_retail_and_up_to_percent(stage3_session: AsyncSession) -> None:
    rug_id, _ = await create_rug(stage3_session)
    media = await add_media(stage3_session, uuid.uuid4().hex)
    _, event = await LalitaEventService(stage3_session).create(LalitaEventCreate(
        rug_id=rug_id, event_at=datetime.now(UTC), media_item_id=media.id,
        discount_type="up_to_percent", discount_value="20",
    ))
    assert event.retail_price_at_event is None and event.calculated_price is None
    assert event.status == "pending_confirmation"


async def test_history_graph_recent_and_api_permission(stage3_session: AsyncSession, stage3_client: httpx.AsyncClient) -> None:
    rug_id, payload = await create_rug(stage3_session)
    for index in range(25):
        await OneCEventSyncService(stage3_session).upsert(OneCEventImport(
            barcode=payload["barcode"], event_type="sale",
            event_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index),
            price=str(10000 + index), qty="1", source_ref=f"sale-{index}", source_line_key="1",
        ))
    recent = await TimelineService(stage3_session).history(
        rug_id, date_from=None, date_to=None, event_types=None, statuses=None,
        page=1, page_size=20, recent=True,
    )
    assert len(recent.items) == 20
    graph = await TimelineService(stage3_session).graph(
        rug_id, datetime(2025, 8, 1, tzinfo=UTC), datetime(2026, 8, 1, tzinfo=UTC)
    )
    assert [series.id for series in graph.series] == ["retail_price", "lalita_price", "sale_price"]
    assert len(graph.series[2].points) == 25
    denied = await stage3_client.get(f"/api/rugs/{rug_id}/history")
    allowed = await stage3_client.get(f"/api/rugs/{rug_id}/history", headers={"X-Internal-API-Key": "test-internal-key"})
    assert denied.status_code == 401 and allowed.status_code == 200


def test_archive_filename_parser_is_exact() -> None:
    assert article_from_filename("ABC123.jpg") == "ABC123"
    assert article_from_filename("ABC123_30.WEBP") == "ABC123"
    assert article_from_filename("ABC_123_bad.jpg") is None
    assert article_from_filename("ABC123.txt") is None


async def test_archive_scan_deduplicates_and_unavailable_mount_keeps_index(stage3_session: AsyncSession, tmp_path: Path) -> None:
    rug_id, payload = await create_rug(stage3_session)
    root = tmp_path / "archive"
    (root / "nested").mkdir(parents=True)
    first = root / f"{payload['article']}.png"
    duplicate = root / "nested" / f"{payload['article']}_2.png"
    Image.new("RGB", (12, 8), "red").save(first)
    duplicate.write_bytes(first.read_bytes())
    result = await PhotoArchiveScanner(stage3_session).scan(root)
    assert result.scanned_files == 2 and result.created == 1
    repeated = await PhotoArchiveScanner(stage3_session).scan(root)
    assert repeated.created == 0 and repeated.unchanged == 1
    with pytest.raises(FileNotFoundError):
        await PhotoArchiveScanner(stage3_session).scan(tmp_path / "missing")
    records = list((await stage3_session.scalars(select(ExternalPhotoFile).where(ExternalPhotoFile.rug_id == rug_id))).all())
    assert len(records) == 1 and records[0].is_current
    assert records[0].width == 12 and records[0].height == 8
