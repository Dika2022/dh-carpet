from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis

from app.api.router import api_router
from app.core.config import get_settings
from app.db.session import create_database_engine, create_session_factory
from app.services.health import HealthService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    redis_client = Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        decode_responses=True,
    )
    qdrant_client = AsyncQdrantClient(
        host=settings.qdrant_host,
        port=settings.qdrant_port,
    )

    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.health_service = HealthService(
        engine=engine,
        redis_client=redis_client,
        qdrant_client=qdrant_client,
        timeout_seconds=settings.service_check_timeout_seconds,
    )

    try:
        yield
    finally:
        await engine.dispose()
        with suppress(Exception):
            await redis_client.aclose()
        with suppress(Exception):
            await qdrant_client.close()


def create_app() -> FastAPI:
    application = FastAPI(title="dh-carpet API", lifespan=lifespan)
    application.include_router(api_router)
    return application


app = create_app()
