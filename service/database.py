"""PostgreSQL connection lifecycle for the PPT Master API."""

from __future__ import annotations

import json
from pathlib import Path

import asyncpg


async def _configure_connection(connection: asyncpg.Connection) -> None:
    for type_name in ("json", "jsonb"):
        await connection.set_type_codec(
            type_name,
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )


class Database:
    """Own the asyncpg pool used by API and worker processes."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(
            self.database_url,
            min_size=1,
            max_size=10,
            command_timeout=30,
            init=_configure_connection,
        )

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    def require_pool(self) -> asyncpg.Pool:
        if self.pool is None:
            raise RuntimeError("database is not connected")
        return self.pool

    async def healthcheck(self) -> None:
        await self.require_pool().execute("SELECT 1")

    async def verify_schema(self) -> None:
        tables = await self.require_pool().fetchrow(
            """
            SELECT
                to_regclass('public.jobs') AS jobs,
                to_regclass('public.job_messages') AS job_messages,
                to_regclass('public.users') AS users,
                to_regclass('public.user_sessions') AS user_sessions,
                to_regclass('public.user_api_keys') AS user_api_keys
            """
        )
        if tables is None or any(value is None for value in tables.values()):
            migration_dir = (
                Path(__file__).resolve().parent.parent / "database" / "migrations"
            )
            raise RuntimeError(
                f"database schema is missing; apply migrations from {migration_dir}"
            )
