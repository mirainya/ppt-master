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
            WHERE session.token_hash = $1
              AND session.expires_at > CURRENT_TIMESTAMP
              AND account.id = session.user_id
              AND account.disabled = FALSE
            RETURNING account.id, account.username, account.is_admin
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
            WHERE api_key.token_hash = $1
              AND api_key.revoked_at IS NULL
              AND account.id = api_key.user_id
              AND account.disabled = FALSE
            RETURNING account.id, account.username, account.is_admin
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
        )
