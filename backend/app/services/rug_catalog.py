import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Rug
from app.repositories.rugs import RugRepository
from app.schemas.rugs import (
    RugDetail,
    RugHistoryInfo,
    RugListResponse,
    RugPhotoRead,
    RugRead,
)


class RugCatalogService:
    def __init__(self, session: AsyncSession) -> None:
        self.rugs = RugRepository(session)

    async def list_rugs(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None,
        barcode: str | None,
        query: str | None,
        current_location: str | None,
    ) -> RugListResponse:
        items, total = await self.rugs.list(
            page=page,
            page_size=page_size,
            status=status,
            barcode=barcode,
            query=query,
            current_location=current_location,
        )
        return RugListResponse(
            items=[RugRead.model_validate(rug) for rug in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def get_by_id(self, rug_id: uuid.UUID) -> RugDetail | None:
        rug = await self.rugs.get_detail_by_id(rug_id)
        return self._detail(rug) if rug is not None else None

    async def get_by_barcode(self, barcode: str) -> RugDetail | None:
        rug = await self.rugs.get_detail_by_barcode(barcode)
        return self._detail(rug) if rug is not None else None

    @staticmethod
    def _detail(rug: Rug) -> RugDetail:
        versions = sorted(rug.external_versions, key=lambda item: item.valid_from)
        current_versions = [item for item in versions if item.valid_to is None]
        current_version = current_versions[-1] if current_versions else None
        photos = sorted(
            rug.photos,
            key=lambda item: (
                not item.is_current,
                item.sort_order,
                item.created_at,
                item.id,
            ),
        )
        base = RugRead.model_validate(rug)
        return RugDetail(
            **base.model_dump(),
            photos=[RugPhotoRead.model_validate(photo) for photo in photos],
            history=RugHistoryInfo(
                version_count=len(versions),
                has_history=len(versions) > 1,
                current_fingerprint=(
                    current_version.fingerprint if current_version is not None else None
                ),
                first_version_at=versions[0].valid_from if versions else None,
                last_version_at=versions[-1].valid_from if versions else None,
            ),
        )
