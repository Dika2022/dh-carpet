from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.security import require_internal_api_key
from app.schemas.rugs import RugImportRequest, RugUpsertResponse
from app.schemas.stage3 import OneCBulkImportRequest, SyncRunResponse
from app.services.stage3 import BulkSyncService
from app.services.rug_sync import RugSyncConflictError, RugSyncService

router = APIRouter(
    prefix="/internal/1c",
    tags=["internal-1c"],
    dependencies=[Depends(require_internal_api_key)],
)


@router.post("/rugs/upsert", response_model=RugUpsertResponse)
async def upsert_rug(
    payload: RugImportRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RugUpsertResponse:
    try:
        result = await RugSyncService(session).upsert(payload)
    except RugSyncConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error.as_detail(),
        ) from error
    return RugUpsertResponse(
        result=result.result,
        rug_id=result.rug_id,
        barcode=result.barcode,
    )


@router.post("/bulk", response_model=SyncRunResponse)
async def bulk_import(
    payload: OneCBulkImportRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SyncRunResponse:
    return await BulkSyncService(session).import_all(payload)
