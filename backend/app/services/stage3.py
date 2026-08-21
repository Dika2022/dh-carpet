import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import AuditEvent, MediaItem, Rug, RugEvent, SyncItem, SyncRun
from app.models.enums import DiscountType, RugEventStatus
from app.repositories.rugs import RugRepository
from app.repositories.stage3 import EventRepository, Stage3CatalogRepository
from app.schemas.stage3 import (
    ExternalPhotoRead,
    GraphPoint,
    GraphResponse,
    GraphSeries,
    HistoryResponse,
    LalitaEventConfirm,
    LalitaEventCreate,
    OneCBulkImportRequest,
    OneCDocumentSnapshot,
    OneCEventImport,
    RugEventRead,
    RugLocationRead,
    SyncItemResult,
    SyncRunResponse,
)
from app.services.fingerprints import payload_fingerprint, to_jsonable
from app.services.rug_sync import RugSyncConflictError, RugSyncService


class Stage3NotFoundError(Exception):
    pass


def _event_read(event: RugEvent, now: datetime) -> RugEventRead:
    return RugEventRead.model_validate(
        {**event.__dict__, "expired": event.valid_until is not None and event.valid_until < now}
    )


class OneCEventSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.events = EventRepository(session)

    async def upsert(self, request: OneCEventImport) -> tuple[str, uuid.UUID | None]:
        fingerprint = payload_fingerprint(request.model_dump(mode="json"))
        async with self.session.begin():
            await RugRepository(self.session).acquire_barcode_lock(request.barcode)
            rug = await self.session.scalar(
                select(Rug).where(Rug.barcode == request.barcode).with_for_update()
            )
            if rug is None:
                raise Stage3NotFoundError(f"Ковёр со штрихкодом {request.barcode} не найден")
            existing = await self.events.by_source_line(
                "1c", request.event_type, request.source_ref, request.source_line_key
            )
            if existing is None and not request.posted:
                return "unchanged", None
            if existing is not None:
                if existing.fingerprint == fingerprint and existing.is_visible == request.posted:
                    return "unchanged", existing.id
                self._assign_one_c_event(existing, request, fingerprint)
                return "updated", existing.id

            if request.event_type == "retail_price_change":
                latest = await self.events.latest_retail_price(rug.id, request.event_at)
                if latest is not None and latest.price == request.price:
                    return "unchanged", latest.id
                old_price = request.old_price if request.old_price is not None else (latest.price if latest else None)
            else:
                old_price = request.old_price
            event = RugEvent(
                rug_id=rug.id,
                event_type=request.event_type,
                source="1c",
                event_at=request.event_at,
                price=request.price,
                old_price=old_price,
                qty=request.qty,
                unit=request.unit,
                counterparty=request.counterparty,
                status=RugEventStatus.ACTIVE.value,
                is_visible=request.posted,
                source_ref=request.source_ref,
                source_line_key=request.source_line_key,
                document_number=request.document_number,
                fingerprint=fingerprint,
                payload=request.payload,
            )
            self.session.add(event)
            await self.session.flush()
            return "created", event.id

    @staticmethod
    def _assign_one_c_event(event: RugEvent, request: OneCEventImport, fingerprint: str) -> None:
        for field in (
            "event_at", "price", "old_price", "qty", "unit", "counterparty",
            "document_number", "payload",
        ):
            setattr(event, field, getattr(request, field))
        event.is_visible = request.posted
        event.fingerprint = fingerprint


class OneCDocumentSnapshotService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.events = EventRepository(session)

    async def reconcile(self, request: OneCDocumentSnapshot) -> str:
        active_keys = set(request.line_keys) if request.posted else set()
        changed = False
        async with self.session.begin():
            existing = await self.events.by_document(
                "1c", request.event_type, request.source_ref
            )
            for event in existing:
                should_be_visible = event.source_line_key in active_keys
                if event.is_visible != should_be_visible:
                    event.is_visible = should_be_visible
                    changed = True
        return "updated" if changed else "unchanged"


class BulkSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def import_all(self, request: OneCBulkImportRequest) -> SyncRunResponse:
        total_items = len(request.rugs) + len(request.events) + len(request.document_snapshots)
        run = SyncRun(
            source="1c",
            mode=request.mode,
            status="running",
            total_items=total_items,
        )
        async with self.session.begin():
            self.session.add(run)
            await self.session.flush()
            run_id = run.id

        results: list[SyncItemResult] = []
        try:
            for rug in request.rugs:
                try:
                    outcome = await RugSyncService(self.session).upsert(rug)
                    item = SyncItemResult(entity_type="rug", source_key=rug.barcode, status="succeeded", result=outcome.result)
                except RugSyncConflictError as error:
                    item = SyncItemResult(entity_type="rug", source_key=rug.barcode, status="failed", error_code=error.code)
                except Exception as error:
                    item = SyncItemResult(entity_type="rug", source_key=rug.barcode, status="failed", error_code=type(error).__name__)
                await self._save_item(run_id, item)
                results.append(item)

            event_results: list[tuple[OneCEventImport, SyncItemResult]] = []
            for event in sorted(request.events, key=lambda item: item.event_at):
                key = f"{event.event_type}:{event.source_ref}:{event.source_line_key}"
                try:
                    outcome, _ = await OneCEventSyncService(self.session).upsert(event)
                    item = SyncItemResult(entity_type=event.event_type, source_key=key, status="succeeded", result=outcome)
                except Exception as error:
                    item = SyncItemResult(entity_type=event.event_type, source_key=key, status="failed", error_code=type(error).__name__)
                await self._save_item(run_id, item)
                results.append(item)
                event_results.append((event, item))

            failed_documents = {
                (event.event_type, event.source_ref)
                for event, result in event_results
                if result.status == "failed"
            }
            for snapshot in request.document_snapshots:
                key = f"{snapshot.event_type}:{snapshot.source_ref}"
                if (snapshot.event_type, snapshot.source_ref) in failed_documents:
                    item = SyncItemResult(
                        entity_type=f"{snapshot.event_type}_snapshot",
                        source_key=key,
                        status="failed",
                        error_code="document_event_failed",
                    )
                else:
                    try:
                        outcome = await OneCDocumentSnapshotService(self.session).reconcile(snapshot)
                        item = SyncItemResult(
                            entity_type=f"{snapshot.event_type}_snapshot",
                            source_key=key,
                            status="succeeded",
                            result=outcome,
                        )
                    except Exception as error:
                        item = SyncItemResult(
                            entity_type=f"{snapshot.event_type}_snapshot",
                            source_key=key,
                            status="failed",
                            error_code=type(error).__name__,
                        )
                await self._save_item(run_id, item)
                results.append(item)

            succeeded = sum(item.status == "succeeded" for item in results)
            failed = len(results) - succeeded
            run_status = "completed" if failed == 0 else "completed_with_errors"
            await self._finish_run(
                run_id,
                status=run_status,
                succeeded_items=succeeded,
                failed_items=failed,
            )
        except Exception as error:
            await self.session.rollback()
            succeeded = sum(item.status == "succeeded" for item in results)
            await self._finish_run(
                run_id,
                status="failed",
                succeeded_items=succeeded,
                failed_items=total_items - succeeded,
                error=type(error).__name__,
            )
            raise

        return SyncRunResponse(
            run_id=run_id,
            status=run_status,
            total_items=len(results),
            succeeded_items=succeeded,
            failed_items=failed,
            items=results,
        )

    async def _save_item(self, run_id: uuid.UUID, result: SyncItemResult) -> None:
        async with self.session.begin():
            self.session.add(SyncItem(
                sync_run_id=run_id,
                entity_type=result.entity_type,
                source_key=result.source_key,
                status=result.status,
                result=result.result,
                error=result.error_code,
            ))

    async def _finish_run(
        self,
        run_id: uuid.UUID,
        *,
        status: str,
        succeeded_items: int,
        failed_items: int,
        error: str | None = None,
    ) -> None:
        async with self.session.begin():
            stored = await self.session.get(SyncRun, run_id, with_for_update=True)
            assert stored is not None
            stored.succeeded_items = succeeded_items
            stored.failed_items = failed_items
            stored.status = status
            stored.error = error
            stored.finished_at = datetime.now(UTC)


class LalitaEventService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.events = EventRepository(session)

    async def create(self, request: LalitaEventCreate) -> tuple[str, RugEvent]:
        now = datetime.now(UTC)
        async with self.session.begin():
            rug = await self.session.get(Rug, request.rug_id, with_for_update=True)
            media = await self.session.get(MediaItem, request.media_item_id)
            if rug is None or media is None:
                raise Stage3NotFoundError("Ковёр или media item не найден")
            retail_event = await self.events.latest_retail_price(rug.id, request.event_at)
            retail_price = retail_event.price if retail_event is not None else None
            calculated = self._calculate_price(request, retail_price)
            fingerprint = payload_fingerprint({
                "rug_id": request.rug_id,
                "media_item_id": request.media_item_id,
                "price": request.price,
                "discount_type": request.discount_type,
                "discount_value": request.discount_value,
            })
            duplicate = await self.session.scalar(select(RugEvent).where(
                RugEvent.rug_id == rug.id,
                RugEvent.event_type == "lalita_price",
                RugEvent.media_item_id == request.media_item_id,
                RugEvent.fingerprint == fingerprint,
            ).limit(1))
            if duplicate is not None:
                return "unchanged", duplicate
            previous = list((await self.session.scalars(select(RugEvent).where(
                RugEvent.rug_id == rug.id,
                RugEvent.event_type == "lalita_price",
                RugEvent.status.in_(["pending_confirmation", "confirmed"]),
                RugEvent.media_item_id != request.media_item_id,
                RugEvent.is_visible.is_(True),
            ).with_for_update())).all())
            for item in previous:
                item.status = RugEventStatus.REPLACED.value
            event = RugEvent(
                rug_id=rug.id,
                event_type="lalita_price",
                source="lalita_ai",
                event_at=request.event_at,
                price=request.price,
                status=RugEventStatus.PENDING_CONFIRMATION.value,
                is_visible=True,
                media_item_id=request.media_item_id,
                start_seconds=request.start_seconds,
                end_seconds=request.end_seconds,
                discount_type=request.discount_type.value if request.discount_type else None,
                discount_value=request.discount_value,
                retail_price_at_event=retail_price,
                calculated_price=calculated,
                valid_until=self._valid_until(request.event_at, request.duration_expression),
                page_path=request.page_path,
                fingerprint=fingerprint,
                payload=request.payload,
            )
            self.session.add(event)
            await self.session.flush()
            return "created", event

    async def confirm(self, event_id: uuid.UUID, request: LalitaEventConfirm) -> RugEvent:
        async with self.session.begin():
            event = await self.session.get(RugEvent, event_id, with_for_update=True)
            if event is None or event.event_type != "lalita_price":
                raise Stage3NotFoundError("Событие Лалиты не найдено")
            old_data = to_jsonable({"price": event.price, "status": event.status})
            if request.price is not None:
                event.price = request.price
                event.calculated_price = request.price
            event.status = RugEventStatus.CONFIRMED.value
            self.session.add(AuditEvent(
                entity_type="rug_event", entity_id=event.id, action="confirmed",
                actor_type="admin", actor_id=request.actor_id, old_data=old_data,
                new_data=to_jsonable({"price": event.price, "status": event.status}),
            ))
            return event

    async def reject(self, event_id: uuid.UUID, actor_id: str) -> None:
        async with self.session.begin():
            event = await self.session.get(RugEvent, event_id, with_for_update=True)
            if event is None or event.event_type != "lalita_price":
                raise Stage3NotFoundError("Событие Лалиты не найдено")
            self.session.add(AuditEvent(
                entity_type="rug_event", entity_id=event.id, action="deleted_rejected",
                actor_type="admin", actor_id=actor_id,
                old_data=to_jsonable({
                    "price": event.price,
                    "status": event.status,
                    "fingerprint": event.fingerprint,
                }),
                new_data=None,
            ))
            await self.session.delete(event)

    @staticmethod
    def _calculate_price(request: LalitaEventCreate, retail: Decimal | None) -> Decimal | None:
        if request.price is not None:
            return request.price
        if retail is None or request.discount_type == DiscountType.UP_TO_PERCENT:
            return None
        assert request.discount_value is not None
        if request.discount_type == DiscountType.PERCENT:
            result = retail * (Decimal("1") - request.discount_value / Decimal("100"))
        else:
            result = max(Decimal("0"), retail - request.discount_value)
        return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def _valid_until(published_at: datetime, expression: str | None) -> datetime | None:
        if not expression:
            return None
        value = expression.strip().lower().replace("–", "-")
        if value == "только сегодня":
            return published_at.replace(hour=23, minute=59, second=59, microsecond=999999)
        if value == "до завтра":
            tomorrow = published_at + timedelta(days=1)
            return tomorrow.replace(hour=23, minute=59, second=59, microsecond=999999)
        if value == "до конца недели":
            return (published_at + timedelta(days=6 - published_at.weekday())).replace(hour=23, minute=59, second=59, microsecond=999999)
        if value in {"на несколько дней", "несколько дней"}:
            return published_at + timedelta(days=7)
        import re
        match = re.fullmatch(r"(?:на )?(\d+)(?:-(\d+))? дня?", value)
        if match:
            return published_at + timedelta(days=int(match.group(2) or match.group(1)))
        months = {
            "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
            "мая": 5, "июня": 6, "июля": 7, "августа": 8,
            "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
        }
        match = re.fullmatch(r"до (\d{1,2}) ([а-яё]+)", value)
        if match and match.group(2) in months:
            year = published_at.year
            candidate = published_at.replace(
                year=year, month=months[match.group(2)], day=int(match.group(1)),
                hour=23, minute=59, second=59, microsecond=999999,
            )
            if candidate < published_at:
                candidate = candidate.replace(year=year + 1)
            return candidate
        return None


class TimelineService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.events = EventRepository(session)
        self.catalog = Stage3CatalogRepository(session)

    async def history(self, rug_id: uuid.UUID, **filters) -> HistoryResponse:
        if not await self.catalog.rug_exists(rug_id):
            raise Stage3NotFoundError("Ковёр не найден")
        now = datetime.now(UTC)
        items, total = await self.events.list_history(rug_id, now=now, **filters)
        return HistoryResponse(items=[_event_read(item, now) for item in items], total=total, page=filters["page"], page_size=filters["page_size"])

    async def graph(self, rug_id: uuid.UUID, date_from: datetime, date_to: datetime) -> GraphResponse:
        history = await self.history(
            rug_id, date_from=date_from, date_to=date_to,
            event_types=["retail_price_change", "lalita_price", "sale"], statuses=None,
            page=1, page_size=10000, recent=False,
        )
        mapping = {"retail_price_change": "retail_price", "lalita_price": "lalita_price", "sale": "sale_price"}
        grouped: dict[str, list[GraphPoint]] = {value: [] for value in mapping.values()}
        for item in reversed(history.items):
            value = item.calculated_price if item.event_type == "lalita_price" and item.calculated_price is not None else item.price
            if value is not None:
                grouped[mapping[item.event_type]].append(GraphPoint(event_id=item.id, at=item.event_at, value=value, status=item.status, valid_until=item.valid_until))
        rendering = {"retail_price": "step", "lalita_price": "offer_period", "sale_price": "line"}
        return GraphResponse(
            date_from=date_from,
            date_to=date_to,
            series=[GraphSeries(id=key, rendering=rendering[key], points=value) for key, value in grouped.items()],
        )

    async def locations(self, rug_id: uuid.UUID, current_only: bool) -> list[RugLocationRead]:
        return [RugLocationRead.model_validate(item) for item in await self.catalog.locations(rug_id, current_only)]

    async def photos(self, rug_id: uuid.UUID, current_only: bool) -> list[ExternalPhotoRead]:
        return [ExternalPhotoRead.model_validate(item) for item in await self.catalog.photos(rug_id, current_only)]
