import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.models.enums import RugStatus
from app.schemas.rugs import RugDetail, RugListResponse
from app.services.rug_catalog import RugCatalogService

router = APIRouter(prefix="/rugs", tags=["rugs"])


@router.get("", response_model=RugListResponse)
async def list_rugs(
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    rug_status: Annotated[RugStatus | None, Query(alias="status")] = None,
    barcode: Annotated[str | None, Query(max_length=64)] = None,
    query: Annotated[str | None, Query(max_length=200)] = None,
    current_location: Annotated[str | None, Query(max_length=255)] = None,
) -> RugListResponse:
    return await RugCatalogService(session).list_rugs(
        page=page,
        page_size=page_size,
        status=rug_status.value if rug_status is not None else None,
        barcode=barcode,
        query=query,
        current_location=current_location,
    )


@router.get("/by-barcode/{barcode}", response_model=RugDetail)
async def get_rug_by_barcode(
    barcode: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RugDetail:
    rug = await RugCatalogService(session).get_by_barcode(barcode)
    if rug is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ковёр не найден",
        )
    return rug

@router.get("/{rug_id}", response_model=RugDetail)
async def get_rug_by_id(
    rug_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RugDetail:
    rug = await RugCatalogService(session).get_by_id(rug_id)
    if rug is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ковёр не найден",
        )
    return rug
