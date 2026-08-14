import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

from app.api.dependencies import get_request_settings
from app.core.config import Settings

internal_api_key_header = APIKeyHeader(
    name="X-Internal-API-Key",
    auto_error=False,
)


def require_internal_api_key(
    settings: Annotated[Settings, Depends(get_request_settings)],
    provided_key: Annotated[str | None, Depends(internal_api_key_header)],
) -> None:
    configured_key = settings.internal_api_key
    if configured_key is None or provided_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный ключ internal API",
        )
    if not secrets.compare_digest(configured_key.get_secret_value(), provided_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный ключ internal API",
        )
