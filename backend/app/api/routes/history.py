import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.security import require_internal_api_key
from app.schemas.stage3 import ExternalPhotoRead, GraphResponse, HistoryResponse, RugLocationRead
from app.services.stage3 import Stage3NotFoundError, TimelineService

router = APIRouter(
    prefix="/rugs",
    tags=["rug-history"],
    dependencies=[Depends(require_internal_api_key)],
)


def _not_found(error: Stage3NotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))


@router.get("/{rug_id}/history", response_model=HistoryResponse)
async def history(
    rug_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    event_type: Annotated[list[str] | None, Query()] = None,
    event_status: Annotated[list[str] | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> HistoryResponse:
    try:
        return await TimelineService(session).history(
            rug_id, date_from=date_from, date_to=date_to, event_types=event_type,
            statuses=event_status, page=page, page_size=page_size, recent=False,
        )
    except Stage3NotFoundError as error:
        raise _not_found(error) from error


@router.get("/{rug_id}/history/recent", response_model=HistoryResponse)
async def recent_history(
    rug_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HistoryResponse:
    try:
        return await TimelineService(session).history(
            rug_id, date_from=None, date_to=None, event_types=None, statuses=None,
            page=1, page_size=20, recent=True,
        )
    except Stage3NotFoundError as error:
        raise _not_found(error) from error


@router.get("/{rug_id}/price-graph", response_model=GraphResponse)
async def price_graph(
    rug_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> GraphResponse:
    end = date_to or datetime.now(UTC)
    start = date_from or end - timedelta(days=365)
    if start > end:
        raise HTTPException(status_code=422, detail="date_from должен быть не позже date_to")
    try:
        return await TimelineService(session).graph(rug_id, start, end)
    except Stage3NotFoundError as error:
        raise _not_found(error) from error


@router.get("/{rug_id}/locations", response_model=list[RugLocationRead])
async def locations(
    rug_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_only: bool = True,
) -> list[RugLocationRead]:
    return await TimelineService(session).locations(rug_id, current_only)


@router.get("/{rug_id}/archive-photos", response_model=list[ExternalPhotoRead])
async def archive_photos(
    rug_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_only: bool = True,
) -> list[ExternalPhotoRead]:
    return await TimelineService(session).photos(rug_id, current_only)
