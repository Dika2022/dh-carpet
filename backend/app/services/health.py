import asyncio
from collections.abc import Awaitable, Callable

from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class HealthService:
    def __init__(
        self,
        engine: AsyncEngine,
        redis_client: Redis,
        qdrant_client: AsyncQdrantClient,
        timeout_seconds: float,
    ) -> None:
        self._engine = engine
        self._redis = redis_client
        self._qdrant = qdrant_client
        self._timeout_seconds = timeout_seconds

    async def check(self) -> dict[str, str]:
        postgres, redis, qdrant = await asyncio.gather(
            self._check_safely(self._check_postgres),
            self._check_safely(self._check_redis),
            self._check_safely(self._check_qdrant),
        )
        return {
            "postgres": postgres,
            "redis": redis,
            "qdrant": qdrant,
        }

    async def _check_safely(self, check: Callable[[], Awaitable[None]]) -> str:
        try:
            await asyncio.wait_for(check(), timeout=self._timeout_seconds)
        except Exception:
            return "error"
        return "ok"

    async def _check_postgres(self) -> None:
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def _check_redis(self) -> None:
        await self._redis.ping()

    async def _check_qdrant(self) -> None:
        await self._qdrant.get_collections()

