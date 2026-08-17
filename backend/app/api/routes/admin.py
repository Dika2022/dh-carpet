import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.security import require_internal_api_key
from app.schemas.stage3 import LalitaEventConfirm, LalitaEventCreate, LalitaEventReject, RugEventRead
from app.services.stage3 import LalitaEventService, Stage3NotFoundError, _event_read

router = APIRouter(
    prefix="/internal/admin",
    tags=["internal-admin"],
    dependencies=[Depends(require_internal_api_key)],
)


@router.post("/lalita-events", response_model=RugEventRead)
async def create_lalita_event(
    payload: LalitaEventCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RugEventRead:
    try:
        _, event = await LalitaEventService(session).create(payload)
    except Stage3NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return _event_read(event, datetime.now(UTC))


@router.patch("/lalita-events/{event_id}/confirm", response_model=RugEventRead)
async def confirm_lalita_event(
    event_id: uuid.UUID,
    payload: LalitaEventConfirm,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RugEventRead:
    try:
        event = await LalitaEventService(session).confirm(event_id, payload)
    except Stage3NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return _event_read(event, datetime.now(UTC))


@router.delete("/lalita-events/{event_id}", status_code=204)
async def reject_lalita_event(
    event_id: uuid.UUID,
    payload: LalitaEventReject,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    try:
        await LalitaEventService(session).reject(event_id, payload.actor_id)
    except Stage3NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
