import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ExternalPhotoFile, Rug, RugEvent, RugLocation


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_source_line(self, source: str, event_type: str, source_ref: str, line_key: str) -> RugEvent | None:
        return await self.session.scalar(
            select(RugEvent).where(
                RugEvent.source == source,
                RugEvent.event_type == event_type,
                RugEvent.source_ref == source_ref,
                RugEvent.source_line_key == line_key,
            ).with_for_update()
        )

    async def latest_retail_price(self, rug_id: uuid.UUID, at: datetime | None = None) -> RugEvent | None:
        filters = [
            RugEvent.rug_id == rug_id,
            RugEvent.event_type == "retail_price_change",
            RugEvent.is_visible.is_(True),
        ]
        if at is not None:
            filters.append(RugEvent.event_at <= at)
        return await self.session.scalar(
            select(RugEvent).where(*filters).order_by(RugEvent.event_at.desc(), RugEvent.id.desc()).limit(1)
        )

    async def list_history(
        self,
        rug_id: uuid.UUID,
        *,
        date_from: datetime | None,
        date_to: datetime | None,
        event_types: list[str] | None,
        statuses: list[str] | None,
        page: int,
        page_size: int,
        recent: bool,
        now: datetime,
    ) -> tuple[list[RugEvent], int]:
        filters = [RugEvent.rug_id == rug_id, RugEvent.is_visible.is_(True)]
        if date_from is not None:
            filters.append(RugEvent.event_at >= date_from)
        if date_to is not None:
            filters.append(RugEvent.event_at <= date_to)
        if event_types:
            filters.append(RugEvent.event_type.in_(event_types))
        if statuses:
            status_filters = [RugEvent.status.in_([s for s in statuses if s != "expired"])]
            if "expired" in statuses:
                status_filters.append(RugEvent.valid_until < now)
            from sqlalchemy import or_
            filters.append(or_(*status_filters))
        if recent:
            filters.extend([
                RugEvent.status != "replaced",
                (RugEvent.valid_until.is_(None) | (RugEvent.valid_until >= now)),
            ])
        total = int(await self.session.scalar(select(func.count()).select_from(RugEvent).where(*filters)) or 0)
        items = list((await self.session.scalars(
            select(RugEvent).where(*filters).order_by(RugEvent.event_at.desc(), RugEvent.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )).all())
        return items, total


class Stage3CatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def rug_exists(self, rug_id: uuid.UUID) -> bool:
        return bool(await self.session.scalar(select(Rug.id).where(Rug.id == rug_id)))

    async def locations(self, rug_id: uuid.UUID, current_only: bool) -> list[RugLocation]:
        filters = [RugLocation.rug_id == rug_id]
        if current_only:
            filters.append(RugLocation.is_current.is_(True))
        return list((await self.session.scalars(select(RugLocation).where(*filters).order_by(RugLocation.valid_from.desc()))).all())

    async def photos(self, rug_id: uuid.UUID, current_only: bool) -> list[ExternalPhotoFile]:
        filters = [ExternalPhotoFile.rug_id == rug_id]
        if current_only:
            filters.append(ExternalPhotoFile.is_current.is_(True))
        return list((await self.session.scalars(select(ExternalPhotoFile).where(*filters).order_by(ExternalPhotoFile.relative_path))).all())
