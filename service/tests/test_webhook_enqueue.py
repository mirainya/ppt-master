"""Unit tests for queueing usage callbacks alongside billing and status writes."""

import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service.repository import JobRepository

ORG_ID = uuid4()
JOB_ID = uuid4()


class _FakeConnection:
    """Minimal asyncpg connection stand-in recording executes and savepoints."""

    def __init__(self, *, enabled=True, fail_insert=False):
        self.enabled = enabled
        self.fail_insert = fail_insert
        self.executes = []
        self.savepoints = 0

    async def fetchval(self, query, *args):
        if "enabled FROM org_webhooks" in query:
            return self.enabled
        if "external_id FROM users" in query:
            return "cust-42"
        return None

    async def fetchrow(self, query, *args):
        if "FROM usage_records" in query:
            return {
                "input_tokens": 12000,
                "output_tokens": 3400,
                "images": 5,
                "pages": 9,
                "charged_credits": 0.2736,
                "turns": 3,
            }
        if "status, owner_id FROM jobs" in query:
            return {"status": "executing", "owner_id": uuid4()}
        return None

    async def execute(self, query, *args):
        if self.fail_insert and "webhook_deliveries" in query:
            raise RuntimeError("simulated insert failure")
        self.executes.append((query, args))

    @asynccontextmanager
    async def transaction(self):
        self.savepoints += 1
        yield


def _delivery_inserts(connection):
    return [
        args for query, args in connection.executes if "webhook_deliveries" in query
    ]


def test_target_is_false_without_org():
    connection = _FakeConnection()
    assert asyncio.run(JobRepository._webhook_target(connection, None)) is False


def test_target_reflects_enabled_flag():
    assert asyncio.run(JobRepository._webhook_target(_FakeConnection(), ORG_ID)) is True
    disabled = _FakeConnection(enabled=False)
    assert asyncio.run(JobRepository._webhook_target(disabled, ORG_ID)) is False


def test_enqueue_inserts_the_delivery_row():
    connection = _FakeConnection()
    asyncio.run(
        JobRepository._enqueue_webhook(
            connection,
            org_id=ORG_ID,
            job_id=JOB_ID,
            event_type="usage.turn",
            event_key="turn-1",
            payload={"event_type": "usage.turn"},
        )
    )
    inserts = _delivery_inserts(connection)
    assert len(inserts) == 1
    assert inserts[0][3] == "usage.turn"
    assert inserts[0][4] == "turn-1"


def test_turn_failure_is_contained_in_a_savepoint():
    """A broken callback table must not roll back the charge it rode with."""
    connection = _FakeConnection(fail_insert=True)
    repository = JobRepository.__new__(JobRepository)
    record = {
        "turn_id": "turn-7",
        "input_tokens": 1,
        "output_tokens": 1,
        "images": 0,
        "pages": 0,
        "charged_credits": 0.1,
        "created_at": datetime(2026, 7, 25, 9, 0, 0, tzinfo=UTC),
        "end_user_id": uuid4(),
    }
    asyncio.run(
        repository._try_enqueue_turn_webhook(connection, record, JOB_ID, ORG_ID)
    )
    assert _delivery_inserts(connection) == []
    # The savepoint wraps the enabled-check and payload reads too, not just the insert.
    assert connection.savepoints == 1


def test_final_failure_is_contained_in_a_savepoint():
    connection = _FakeConnection(fail_insert=True)
    repository = JobRepository.__new__(JobRepository)
    job = {
        "id": JOB_ID,
        "org_id": ORG_ID,
        "owner_id": uuid4(),
        "status": "succeeded",
        "updated_at": datetime(2026, 7, 25, 10, 0, 0, tzinfo=UTC),
        "billed_turns": 3,
    }
    asyncio.run(repository._try_enqueue_final_webhook(connection, job))
    assert _delivery_inserts(connection) == []
    assert connection.savepoints == 1


def test_disabled_org_is_not_queried_for_payload():
    connection = _FakeConnection(enabled=False)
    repository = JobRepository.__new__(JobRepository)
    job = {
        "id": JOB_ID,
        "org_id": ORG_ID,
        "owner_id": uuid4(),
        "status": "succeeded",
        "updated_at": datetime(2026, 7, 25, 10, 0, 0, tzinfo=UTC),
        "billed_turns": 3,
    }
    asyncio.run(repository._try_enqueue_final_webhook(connection, job))
    assert _delivery_inserts(connection) == []


def test_turn_event_snapshots_totals_and_delta():
    connection = _FakeConnection()
    record = {
        "turn_id": "turn-7",
        "input_tokens": 4200,
        "output_tokens": 1100,
        "images": 2,
        "pages": 3,
        "charged_credits": 0.1084,
        "created_at": datetime(2026, 7, 25, 9, 12, 3, tzinfo=UTC),
        "end_user_id": uuid4(),
    }
    repository = JobRepository.__new__(JobRepository)
    asyncio.run(
        repository._enqueue_turn_webhook(connection, record, JOB_ID, ORG_ID)
    )
    payload = _delivery_inserts(connection)[0][5]
    assert payload["event_type"] == "usage.turn"
    assert payload["usage_status"] == "partial"
    assert payload["end_user_id"] == "cust-42"
    assert payload["turn"] == {"index": 3, "turn_id": "turn-7"}
    assert payload["delta"]["input_tokens"] == 4200
    assert payload["delta"]["our_charge"]["credits"] == 0.1084
    assert payload["job_total"]["turns"] == 3
    assert payload["job_total"]["our_charge"]["credits"] == 0.2736
    assert payload["occurred_at"].endswith("Z")


def test_final_event_is_keyed_on_billed_turns():
    connection = _FakeConnection()
    job = {
        "id": JOB_ID,
        "org_id": ORG_ID,
        "owner_id": uuid4(),
        "status": "succeeded",
        "updated_at": datetime(2026, 7, 25, 10, 0, 0, tzinfo=UTC),
        "billed_turns": 3,
    }
    repository = JobRepository.__new__(JobRepository)
    asyncio.run(repository._enqueue_final_webhook(connection, job))
    args = _delivery_inserts(connection)[0]
    assert args[3] == "usage.final"
    # Keyed on billed_turns so a resumed job emits a fresh final event.
    assert args[4] == "3"
    payload = args[5]
    assert payload["usage_status"] == "final"
    assert payload["delta"] is None
    assert payload["turn"] == {"index": 3, "turn_id": None}
