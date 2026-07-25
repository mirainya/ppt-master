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
                to_regclass('public.user_api_keys') AS user_api_keys,
                to_regclass('public.organizations') AS organizations,
                to_regclass('public.org_api_keys') AS org_api_keys,
                to_regclass('public.usage_records') AS usage_records,
                to_regclass('public.credit_transactions') AS credit_transactions,
                to_regclass('public.billing_config') AS billing_config,
                to_regclass('public.service_runtime_config') AS service_runtime_config,
                to_regclass('public.org_webhooks') AS org_webhooks,
                to_regclass('public.webhook_deliveries') AS webhook_deliveries,
                EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'jobs'
                      AND column_name = 'held_amount'
                ) AS jobs_held_amount,
                EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'usage_records'
                      AND column_name = 'turn_id'
                ) AS usage_turn_id,
                EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'usage_records'
                      AND column_name = 'charged_credits'
                ) AS usage_charged_credits
            """
        )
        if tables is None or any(not value for value in tables.values()):
            migration_dir = (
                Path(__file__).resolve().parent.parent / "database" / "migrations"
            )
            raise RuntimeError(
                f"database schema is missing; apply migrations from {migration_dir}"
            )
        pricing_exists = await self.require_pool().fetchval(
            "SELECT EXISTS (SELECT 1 FROM billing_config WHERE id = 1)"
        )
        if not pricing_exists:
            raise RuntimeError("billing_config row is missing; apply migrations")
        runtime_config_exists = await self.require_pool().fetchval(
            "SELECT EXISTS (SELECT 1 FROM service_runtime_config WHERE id = 1)"
        )
        if not runtime_config_exists:
            raise RuntimeError(
                "service_runtime_config row is missing; apply migrations"
            )
