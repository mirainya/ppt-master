"""PostgreSQL records for users, sessions, and user API keys."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from service.auth import AuthenticatedUser
from service.database import Database


class AuthRepository:
    """Persist authentication state through parameterized queries."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_user(
        self,
        username: str,
        password_hash: str,
        *,
        is_admin: bool,
    ) -> dict[str, Any]:
        record = await self.database.require_pool().fetchrow(
            """
            INSERT INTO users (id, username, password_hash, is_admin)
            VALUES ($1, $2, $3, $4)
            RETURNING *
            """,
            uuid4(),
            username,
            password_hash,
            is_admin,
        )
        return dict(record)

    async def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        record = await self.database.require_pool().fetchrow(
            "SELECT * FROM users WHERE username = $1",
            username,
        )
        return dict(record) if record else None

    async def list_local_users(self) -> list[dict[str, Any]]:
        records = await self.database.require_pool().fetch(
            """
            SELECT account.id,
                   account.username,
                   account.is_admin,
                   account.disabled,
                   account.created_at,
                   account.updated_at,
                   COUNT(api_key.id) FILTER (
                       WHERE api_key.revoked_at IS NULL
                   )::INTEGER AS active_api_key_count
            FROM users AS account
            LEFT JOIN user_api_keys AS api_key ON api_key.user_id = account.id
            WHERE account.org_id IS NULL
            GROUP BY account.id
            ORDER BY account.created_at ASC
            """
        )
        return [dict(record) for record in records]

    async def get_local_user(self, user_id: UUID) -> dict[str, Any] | None:
        record = await self.database.require_pool().fetchrow(
            """
            SELECT id, username, is_admin, disabled, created_at, updated_at
            FROM users
            WHERE id = $1 AND org_id IS NULL
            """,
            user_id,
        )
        return dict(record) if record else None

    async def set_local_user_disabled(
        self,
        user_id: UUID,
        disabled: bool,
        *,
        acting_user_id: UUID,
    ) -> dict[str, Any] | None:
        async with self.database.require_pool().acquire() as connection:
            async with connection.transaction():
                record = await connection.fetchrow(
                    """
                    SELECT id, username, is_admin, disabled, created_at, updated_at
                    FROM users
                    WHERE id = $1 AND org_id IS NULL
                    FOR UPDATE
                    """,
                    user_id,
                )
                if record is None:
                    return None
                if disabled and record["id"] == acting_user_id:
                    raise ValueError("cannot disable the current administrator")
                if disabled and record["is_admin"]:
                    active_admins = await connection.fetchval(
                        """
                        SELECT COUNT(*)
                        FROM users
                        WHERE org_id IS NULL
                          AND is_admin = TRUE
                          AND disabled = FALSE
                        """
                    )
                    if active_admins <= 1:
                        raise ValueError("cannot disable the last active administrator")
                updated = await connection.fetchrow(
                    """
                    UPDATE users
                    SET disabled = $2, updated_at = CURRENT_TIMESTAMP
                    WHERE id = $1
                    RETURNING id, username, is_admin, disabled, created_at, updated_at
                    """,
                    user_id,
                    disabled,
                )
                if disabled:
                    await connection.execute(
                        "DELETE FROM user_sessions WHERE user_id = $1",
                        user_id,
                    )
                return dict(updated)

    async def reset_local_user_password(
        self,
        user_id: UUID,
        password_hash: str,
    ) -> bool:
        async with self.database.require_pool().acquire() as connection:
            async with connection.transaction():
                result = await connection.execute(
                    """
                    UPDATE users
                    SET password_hash = $2, updated_at = CURRENT_TIMESTAMP
                    WHERE id = $1 AND org_id IS NULL
                    """,
                    user_id,
                    password_hash,
                )
                if result != "UPDATE 1":
                    return False
                await connection.execute(
                    "DELETE FROM user_sessions WHERE user_id = $1",
                    user_id,
                )
                return True

    async def update_password_hash(self, user_id: UUID, password_hash: str) -> None:
        await self.database.require_pool().execute(
            """
            UPDATE users
            SET password_hash = $2, updated_at = CURRENT_TIMESTAMP
            WHERE id = $1
            """,
            user_id,
            password_hash,
        )

    async def create_session(
        self,
        user_id: UUID,
        token_hash: str,
        duration_days: int,
    ) -> None:
        expires_at = datetime.now(UTC) + timedelta(days=duration_days)
        async with self.database.require_pool().acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "DELETE FROM user_sessions WHERE expires_at <= CURRENT_TIMESTAMP"
                )
                await connection.execute(
                    """
                    INSERT INTO user_sessions (id, user_id, token_hash, expires_at)
                    VALUES ($1, $2, $3, $4)
                    """,
                    uuid4(),
                    user_id,
                    token_hash,
                    expires_at,
                )

    async def authenticate_session(self, token_hash: str) -> AuthenticatedUser | None:
        record = await self.database.require_pool().fetchrow(
            """
            UPDATE user_sessions AS session
            SET last_seen_at = CURRENT_TIMESTAMP
            FROM users AS account
            LEFT JOIN organizations AS org ON org.id = account.org_id
            WHERE session.token_hash = $1
              AND session.expires_at > CURRENT_TIMESTAMP
              AND account.id = session.user_id
              AND account.disabled = FALSE
              AND (account.org_id IS NULL OR org.status = 'active')
            RETURNING account.id,
                      COALESCE(account.external_id, account.username) AS username,
                      account.is_admin,
                      account.org_id
            """,
            token_hash,
        )
        return self._authenticated_user(record)

    async def delete_session(self, token_hash: str) -> None:
        await self.database.require_pool().execute(
            "DELETE FROM user_sessions WHERE token_hash = $1",
            token_hash,
        )

    async def authenticate_api_key(self, token_hash: str) -> AuthenticatedUser | None:
        record = await self.database.require_pool().fetchrow(
            """
            UPDATE user_api_keys AS api_key
            SET last_used_at = CURRENT_TIMESTAMP
            FROM users AS account
            LEFT JOIN organizations AS org ON org.id = account.org_id
            WHERE api_key.token_hash = $1
              AND api_key.revoked_at IS NULL
              AND account.id = api_key.user_id
              AND account.disabled = FALSE
              AND (account.org_id IS NULL OR org.status = 'active')
            RETURNING account.id,
                      COALESCE(account.external_id, account.username) AS username,
                      account.is_admin,
                      account.org_id
            """,
            token_hash,
        )
        return self._authenticated_user(record)

    async def create_api_key(
        self,
        user_id: UUID,
        name: str,
        key_prefix: str,
        token_hash: str,
    ) -> dict[str, Any]:
        record = await self.database.require_pool().fetchrow(
            """
            INSERT INTO user_api_keys
                (id, user_id, name, key_prefix, token_hash)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, name, key_prefix, last_used_at, revoked_at, created_at
            """,
            uuid4(),
            user_id,
            name,
            key_prefix,
            token_hash,
        )
        return dict(record)

    async def list_api_keys(self, user_id: UUID) -> list[dict[str, Any]]:
        records = await self.database.require_pool().fetch(
            """
            SELECT id, name, key_prefix, last_used_at, revoked_at, created_at
            FROM user_api_keys
            WHERE user_id = $1
            ORDER BY created_at DESC
            """,
            user_id,
        )
        return [dict(record) for record in records]

    async def revoke_api_key(self, user_id: UUID, key_id: UUID) -> bool:
        result = await self.database.require_pool().execute(
            """
            UPDATE user_api_keys
            SET revoked_at = CURRENT_TIMESTAMP
            WHERE id = $1 AND user_id = $2 AND revoked_at IS NULL
            """,
            key_id,
            user_id,
        )
        return result == "UPDATE 1"

    @staticmethod
    def _authenticated_user(record: Any) -> AuthenticatedUser | None:
        if record is None:
            return None
        return AuthenticatedUser(
            id=record["id"],
            username=record["username"],
            is_admin=record["is_admin"],
            org_id=record["org_id"] if "org_id" in record else None,
        )

    # ------------------------------------------------------------------
    # Organizations, org API keys, and enterprise end-user provisioning
    # ------------------------------------------------------------------

    SERVICE_EXTERNAL_ID = "__service__"

    async def create_organization(
        self,
        name: str,
        slug: str,
    ) -> dict[str, Any]:
        """Create an organization plus its default service end-user account."""
        org_id = uuid4()
        async with self.database.require_pool().acquire() as connection:
            async with connection.transaction():
                record = await connection.fetchrow(
                    """
                    INSERT INTO organizations (id, name, slug)
                    VALUES ($1, $2, $3)
                    RETURNING *
                    """,
                    org_id,
                    name,
                    slug,
                )
                service_user_id = uuid4()
                await connection.execute(
                    """
                    INSERT INTO users (id, username, password_hash, is_admin,
                                       org_id, external_id)
                    VALUES ($1, $2, NULL, FALSE, $3, $4)
                    """,
                    service_user_id,
                    str(service_user_id),
                    org_id,
                    self.SERVICE_EXTERNAL_ID,
                )
        return dict(record)

    async def authenticate_org_api_key(self, token_hash: str) -> UUID | None:
        """Return the org id for an active, non-revoked org key, else None."""
        record = await self.database.require_pool().fetchrow(
            """
            UPDATE org_api_keys AS api_key
            SET last_used_at = CURRENT_TIMESTAMP
            FROM organizations AS org
            WHERE api_key.token_hash = $1
              AND api_key.revoked_at IS NULL
              AND org.id = api_key.org_id
              AND org.status = 'active'
            RETURNING org.id
            """,
            token_hash,
        )
        return record["id"] if record is not None else None

    async def create_org_api_key(
        self,
        org_id: UUID,
        name: str,
        key_prefix: str,
        token_hash: str,
    ) -> dict[str, Any]:
        record = await self.database.require_pool().fetchrow(
            """
            INSERT INTO org_api_keys (id, org_id, name, key_prefix, token_hash)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, name, key_prefix, last_used_at, revoked_at, created_at
            """,
            uuid4(),
            org_id,
            name,
            key_prefix,
            token_hash,
        )
        return dict(record)

    async def external_id_for_user(self, user_id: UUID) -> str | None:
        """Return the enterprise external id for an end-user, or None."""
        return await self.database.require_pool().fetchval(
            "SELECT external_id FROM users WHERE id = $1",
            user_id,
        )

    async def list_org_api_keys(self, org_id: UUID) -> list[dict[str, Any]]:
        records = await self.database.require_pool().fetch(
            """
            SELECT id, name, key_prefix, last_used_at, revoked_at, created_at
            FROM org_api_keys
            WHERE org_id = $1
            ORDER BY created_at DESC
            """,
            org_id,
        )
        return [dict(record) for record in records]

    async def revoke_org_api_key(self, org_id: UUID, key_id: UUID) -> bool:
        result = await self.database.require_pool().execute(
            """
            UPDATE org_api_keys
            SET revoked_at = CURRENT_TIMESTAMP
            WHERE id = $1 AND org_id = $2 AND revoked_at IS NULL
            """,
            key_id,
            org_id,
        )
        return result == "UPDATE 1"

    async def get_organization(self, org_id: UUID) -> dict[str, Any] | None:
        record = await self.database.require_pool().fetchrow(
            "SELECT * FROM organizations WHERE id = $1",
            org_id,
        )
        return dict(record) if record else None

    async def list_organizations(self) -> list[dict[str, Any]]:
        """List every organization, newest first, for the admin billing console."""
        records = await self.database.require_pool().fetch(
            """
            SELECT id, name, slug, credit_balance, daily_job_limit,
                   max_active_jobs, created_at
            FROM organizations
            ORDER BY created_at DESC
            """
        )
        return [
            {
                "id": record["id"],
                "name": record["name"],
                "slug": record["slug"],
                # credit_balance is NUMERIC(14,4) -> Decimal; coerce to float so
                # the JSON payload matches the frontend Organization type and the
                # other billing endpoints (pricing / usage / topup all use float).
                "credit_balance": float(record["credit_balance"]),
                "daily_job_limit": record["daily_job_limit"],
                "max_active_jobs": record["max_active_jobs"],
                "created_at": record["created_at"],
            }
            for record in records
        ]

    async def provision_end_user(
        self,
        org_id: UUID,
        external_id: str | None,
    ) -> AuthenticatedUser:
        """Find or create the end-user for (org_id, external_id); JIT provision."""
        resolved_external = external_id or self.SERVICE_EXTERNAL_ID
        pool = self.database.require_pool()
        record = await pool.fetchrow(
            """
            SELECT id, username, is_admin, org_id
            FROM users
            WHERE org_id = $1 AND external_id = $2
            """,
            org_id,
            resolved_external,
        )
        if record is None:
            new_id = uuid4()
            record = await pool.fetchrow(
                """
                INSERT INTO users (id, username, password_hash, is_admin,
                                   org_id, external_id)
                VALUES ($1, $2, NULL, FALSE, $3, $4)
                ON CONFLICT (org_id, external_id) DO UPDATE
                    SET external_id = EXCLUDED.external_id
                RETURNING id, username, is_admin, org_id
                """,
                new_id,
                str(new_id),
                org_id,
                resolved_external,
            )
        return AuthenticatedUser(
            id=record["id"],
            username=record["username"],
            is_admin=record["is_admin"],
            org_id=record["org_id"],
        )

    async def get_active_org_user(
        self,
        user_id: UUID,
        org_id: UUID,
    ) -> AuthenticatedUser | None:
        """Resolve a provisioned user only while both account and organization are active."""
        record = await self.database.require_pool().fetchrow(
            """
            SELECT account.id,
                   account.external_id AS username,
                   account.is_admin,
                   account.org_id
            FROM users AS account
            JOIN organizations AS org ON org.id = account.org_id
            WHERE account.id = $1
              AND account.org_id = $2
              AND account.disabled = FALSE
              AND org.status = 'active'
            """,
            user_id,
            org_id,
        )
        return self._authenticated_user(record)
