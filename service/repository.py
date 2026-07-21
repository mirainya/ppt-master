"""Durable job, event, confirmation, and file records."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import asyncpg

from service.database import Database
from service.schemas import JobRoute, JobStatus
from service.storage import StoredFile


class JobRepository:
    """Apply task state changes through parameterized PostgreSQL queries."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_job(
        self,
        job_id: UUID,
        owner_id: UUID,
        prompt: str,
        route: JobRoute,
        title: str | None,
    ) -> dict[str, Any]:
        async with self.database.require_pool().acquire() as connection:
            async with connection.transaction():
                record = await connection.fetchrow(
                    """
                    INSERT INTO jobs
                        (id, owner_id, title, prompt, route, status, stage, progress)
                    VALUES ($1, $2, $3, $4, $5, $6, $6, 0)
                    RETURNING *
                    """,
                    job_id,
                    owner_id,
                    title,
                    prompt,
                    route.value,
                    JobStatus.QUEUED.value,
                )
                await self._add_event(
                    connection,
                    job_id,
                    "status",
                    JobStatus.QUEUED.value,
                    "Task accepted",
                    {"progress": 0},
                )
                await self._add_message(connection, job_id, "user", prompt)
        return dict(record)

    async def get_job(self, job_id: UUID) -> dict[str, Any] | None:
        record = await self.database.require_pool().fetchrow(
            "SELECT * FROM jobs WHERE id = $1",
            job_id,
        )
        return dict(record) if record else None

    async def get_job_for_user(
        self,
        job_id: UUID,
        owner_id: UUID,
        *,
        include_unowned: bool,
    ) -> dict[str, Any] | None:
        record = await self.database.require_pool().fetchrow(
            """
            SELECT * FROM jobs
            WHERE id = $1
              AND (owner_id = $2 OR ($3 AND owner_id IS NULL))
            """,
            job_id,
            owner_id,
            include_unowned,
        )
        return dict(record) if record else None

    async def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        records = await self.database.require_pool().fetch(
            """
            SELECT * FROM jobs
            ORDER BY updated_at DESC
            LIMIT $1
            """,
            max(1, min(limit, 100)),
        )
        return [dict(record) for record in records]

    async def list_jobs_for_user(
        self,
        owner_id: UUID,
        limit: int = 50,
        *,
        include_unowned: bool,
    ) -> list[dict[str, Any]]:
        records = await self.database.require_pool().fetch(
            """
            SELECT * FROM jobs
            WHERE owner_id = $1 OR ($2 AND owner_id IS NULL)
            ORDER BY updated_at DESC
            LIMIT $3
            """,
            owner_id,
            include_unowned,
            max(1, min(limit, 100)),
        )
        return [dict(record) for record in records]

    async def set_status(
        self,
        job_id: UUID,
        status: JobStatus,
        progress: int,
        message: str,
        *,
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        progress = max(0, min(progress, 100))
        async with self.database.require_pool().acquire() as connection:
            async with connection.transaction():
                record = await connection.fetchrow(
                    """
                    UPDATE jobs
                    SET status = $2, stage = $2, progress = $3, error = $4,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = $1
                    RETURNING *
                    """,
                    job_id,
                    status.value,
                    progress,
                    error,
                )
                if record:
                    await self._add_event(
                        connection,
                        job_id,
                        "status",
                        status.value,
                        message,
                        {"progress": progress, "error": error},
                    )
        return dict(record) if record else None

    async def list_events(
        self, job_id: UUID, after_id: int = 0
    ) -> list[dict[str, Any]]:
        records = await self.database.require_pool().fetch(
            """
            SELECT * FROM job_events
            WHERE job_id = $1 AND id > $2
            ORDER BY id ASC
            LIMIT 200
            """,
            job_id,
            after_id,
        )
        return [dict(record) for record in records]

    async def list_messages(self, job_id: UUID) -> list[dict[str, Any]]:
        records = await self.database.require_pool().fetch(
            "SELECT * FROM job_messages WHERE job_id = $1 ORDER BY id ASC",
            job_id,
        )
        return [dict(record) for record in records]

    async def add_message(
        self,
        job_id: UUID,
        role: str,
        content: str,
    ) -> dict[str, Any] | None:
        content = content.strip()
        if not content:
            return None
        if role not in {"user", "assistant", "system"}:
            raise ValueError(f"unsupported message role: {role}")
        async with self.database.require_pool().acquire() as connection:
            record = await self._add_message(connection, job_id, role, content)
        return dict(record)

    async def add_asset(self, job_id: UUID, stored_file: StoredFile) -> dict[str, Any]:
        record = await self.database.require_pool().fetchrow(
            """
            INSERT INTO job_assets
                (id, job_id, filename, storage_path, size_bytes, sha256, media_type)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING *
            """,
            stored_file.id,
            job_id,
            stored_file.filename,
            stored_file.relative_path,
            stored_file.size_bytes,
            stored_file.sha256,
            stored_file.media_type,
        )
        return dict(record)

    async def list_assets(self, job_id: UUID) -> list[dict[str, Any]]:
        records = await self.database.require_pool().fetch(
            "SELECT * FROM job_assets WHERE job_id = $1 ORDER BY created_at ASC",
            job_id,
        )
        return [dict(record) for record in records]

    async def set_proposal(
        self,
        job_id: UUID,
        proposal: dict[str, Any],
        assistant_message: str,
    ) -> None:
        async with self.database.require_pool().acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    INSERT INTO job_confirmations (job_id, proposal, status)
                    VALUES ($1, $2, 'pending')
                    ON CONFLICT (job_id) DO UPDATE
                    SET proposal = EXCLUDED.proposal, response = NULL, status = 'pending',
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    job_id,
                    proposal,
                )
                if assistant_message.strip():
                    await self._add_message(
                        connection,
                        job_id,
                        "assistant",
                        assistant_message.strip(),
                    )

    async def get_confirmation(self, job_id: UUID) -> dict[str, Any] | None:
        record = await self.database.require_pool().fetchrow(
            "SELECT * FROM job_confirmations WHERE job_id = $1",
            job_id,
        )
        return dict(record) if record else None

    async def submit_confirmation(
        self,
        job_id: UUID,
        approved: bool,
        message: str,
    ) -> dict[str, Any] | None:
        response = {"approved": approved, "message": message}
        async with self.database.require_pool().acquire() as connection:
            async with connection.transaction():
                record = await connection.fetchrow(
                    """
                    UPDATE job_confirmations
                    SET response = $2, status = $3, updated_at = CURRENT_TIMESTAMP
                    WHERE job_id = $1 AND status = 'pending'
                    RETURNING *
                    """,
                    job_id,
                    response,
                    "approved" if approved else "revision_requested",
                )
                if record:
                    await self._add_message(connection, job_id, "user", message)
        return dict(record) if record else None

    async def consume_confirmation(self, job_id: UUID) -> dict[str, Any] | None:
        record = await self.database.require_pool().fetchrow(
            """
            UPDATE job_confirmations
            SET status = 'consumed', updated_at = CURRENT_TIMESTAMP
            WHERE job_id = $1 AND status IN ('approved', 'revision_requested')
            RETURNING *
            """,
            job_id,
        )
        return dict(record) if record else None

    async def prepare_resume(self, job_id: UUID, message: str) -> dict[str, Any] | None:
        response = {"approved": True, "message": message}
        async with self.database.require_pool().acquire() as connection:
            async with connection.transaction():
                record = await connection.fetchrow(
                    """
                    UPDATE job_confirmations
                    SET response = $2, status = 'approved',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE job_id = $1
                    RETURNING *
                    """,
                    job_id,
                    response,
                )
                if record:
                    await self._add_message(connection, job_id, "user", message)
        return dict(record) if record else None

    async def prepare_restart(self, job_id: UUID, message: str) -> dict[str, Any]:
        """Store an instruction for a failed task that has no resumable thread."""
        response = {"approved": True, "message": message}
        async with self.database.require_pool().acquire() as connection:
            async with connection.transaction():
                record = await connection.fetchrow(
                    """
                    INSERT INTO job_confirmations (job_id, proposal, response, status)
                    VALUES ($1, '{}'::jsonb, $2, 'approved')
                    ON CONFLICT (job_id) DO UPDATE
                    SET response = EXCLUDED.response, status = 'approved',
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING *
                    """,
                    job_id,
                    response,
                )
                await self._add_message(connection, job_id, "user", message)
        return dict(record)

    async def request_cancel(self, job_id: UUID) -> dict[str, Any] | None:
        record = await self.database.require_pool().fetchrow(
            """
            UPDATE jobs
            SET cancel_requested = TRUE, updated_at = CURRENT_TIMESTAMP
            WHERE id = $1 AND status NOT IN ('succeeded', 'failed', 'cancelled')
            RETURNING *
            """,
            job_id,
        )
        return dict(record) if record else None

    async def list_artifacts(self, job_id: UUID) -> list[dict[str, Any]]:
        records = await self.database.require_pool().fetch(
            "SELECT * FROM job_artifacts WHERE job_id = $1 ORDER BY created_at ASC",
            job_id,
        )
        return [dict(record) for record in records]

    async def get_artifact(
        self, job_id: UUID, artifact_id: UUID
    ) -> dict[str, Any] | None:
        record = await self.database.require_pool().fetchrow(
            "SELECT * FROM job_artifacts WHERE job_id = $1 AND id = $2",
            job_id,
            artifact_id,
        )
        return dict(record) if record else None

    async def add_artifact(
        self,
        job_id: UUID,
        kind: str,
        stored_file: StoredFile,
    ) -> dict[str, Any]:
        record = await self.database.require_pool().fetchrow(
            """
            INSERT INTO job_artifacts
                (id, job_id, kind, filename, storage_path, size_bytes, sha256, media_type)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (job_id, storage_path) DO UPDATE
            SET kind = EXCLUDED.kind,
                filename = EXCLUDED.filename,
                size_bytes = EXCLUDED.size_bytes,
                sha256 = EXCLUDED.sha256,
                media_type = EXCLUDED.media_type
            RETURNING *
            """,
            uuid4(),
            job_id,
            kind,
            stored_file.filename,
            stored_file.relative_path,
            stored_file.size_bytes,
            stored_file.sha256,
            stored_file.media_type,
        )
        return dict(record)

    async def set_runner_session(self, job_id: UUID, session_id: str) -> None:
        await self.database.require_pool().execute(
            """
            UPDATE jobs
            SET runner_session_id = $2, updated_at = CURRENT_TIMESTAMP
            WHERE id = $1
            """,
            job_id,
            session_id,
        )

    async def add_event(
        self,
        job_id: UUID,
        event_type: str,
        stage: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        async with self.database.require_pool().acquire() as connection:
            await self._add_event(
                connection,
                job_id,
                event_type,
                stage,
                message,
                data or {},
            )

    @staticmethod
    async def _add_message(
        connection: asyncpg.Connection,
        job_id: UUID,
        role: str,
        content: str,
    ) -> asyncpg.Record:
        return await connection.fetchrow(
            """
            INSERT INTO job_messages (job_id, role, content)
            VALUES ($1, $2, $3)
            RETURNING *
            """,
            job_id,
            role,
            content,
        )

    @staticmethod
    async def _add_event(
        connection: asyncpg.Connection,
        job_id: UUID,
        event_type: str,
        stage: str,
        message: str,
        data: dict[str, Any],
    ) -> None:
        await connection.execute(
            """
            INSERT INTO job_events (job_id, event_type, stage, message, data)
            VALUES ($1, $2, $3, $4, $5)
            """,
            job_id,
            event_type,
            stage,
            message,
            data,
        )
