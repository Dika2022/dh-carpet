import uuid
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entities import AuditEvent, Rug, RugExternalData, RugPhoto


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class RugRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def acquire_barcode_lock(self, barcode: str) -> None:
        await self.session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(barcode, 0)))
        )

    async def get_by_barcode(
        self, barcode: str, *, for_update: bool = False
    ) -> Rug | None:
        statement = select(Rug).where(Rug.barcode == barcode)
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_detail_by_id(self, rug_id: uuid.UUID) -> Rug | None:
        return await self.session.scalar(
            select(Rug)
            .options(
                selectinload(Rug.photos),
                selectinload(Rug.external_versions),
            )
            .where(Rug.id == rug_id)
        )

    async def get_detail_by_barcode(self, barcode: str) -> Rug | None:
        return await self.session.scalar(
            select(Rug)
            .options(
                selectinload(Rug.photos),
                selectinload(Rug.external_versions),
            )
            .where(Rug.barcode == barcode)
        )

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None,
        barcode: str | None,
        query: str | None,
        current_location: str | None,
    ) -> tuple[list[Rug], int]:
        filters = []
        if status is not None:
            filters.append(Rug.status == status)
        if barcode is not None:
            filters.append(Rug.barcode == barcode)
        if current_location is not None:
            filters.append(Rug.current_location == current_location)
        normalized_query = query.strip() if query else ""
        if normalized_query:
            pattern = f"%{_escape_like(normalized_query)}%"
            filters.append(
                or_(
                    Rug.barcode.ilike(pattern, escape="\\"),
                    Rug.name.ilike(pattern, escape="\\"),
                    Rug.article.ilike(pattern, escape="\\"),
                )
            )

        total = await self.session.scalar(
            select(func.count()).select_from(Rug).where(*filters)
        )
        items = list(
            (
                await self.session.scalars(
                    select(Rug)
                    .where(*filters)
                    .order_by(Rug.created_at.desc(), Rug.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return items, int(total or 0)

    async def add(self, rug: Rug) -> Rug:
        self.session.add(rug)
        await self.session.flush()
        return rug


class RugHistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_current(
        self, rug_id: uuid.UUID, source: str
    ) -> RugExternalData | None:
        return await self.session.scalar(
            select(RugExternalData)
            .where(
                RugExternalData.rug_id == rug_id,
                RugExternalData.source == source,
                RugExternalData.valid_to.is_(None),
            )
            .order_by(RugExternalData.valid_from.desc())
            .limit(1)
            .with_for_update()
        )

    def add(self, version: RugExternalData) -> None:
        self.session.add(version)


class RugPhotoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_current(self, rug_id: uuid.UUID) -> list[RugPhoto]:
        return list(
            (
                await self.session.scalars(
                    select(RugPhoto)
                    .where(RugPhoto.rug_id == rug_id, RugPhoto.is_current.is_(True))
                    .with_for_update()
                )
            ).all()
        )

    def add(self, photo: RugPhoto) -> None:
        self.session.add(photo)


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, event: AuditEvent) -> None:
        self.session.add(event)
