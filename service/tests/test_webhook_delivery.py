"""Unit tests for the worker's per-delivery success, retry, and dead-letter paths."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import service.worker as worker
from service.webhooks import DeliveryOutcome, WebhookConfig, next_backoff_seconds

ORG_ID = uuid4()


class _FakeWebhookRepository:
    def __init__(self, *, enabled=True, configured=True):
        self.config = (
            WebhookConfig(
                org_id=ORG_ID,
                callback_url="https://acme.example.com/hook",
                secret="topsecret",
                enabled=enabled,
            )
            if configured
            else None
        )
        self.delivered = []
        self.rescheduled = []
        self.dead = []

    async def get(self, org_id):
        return self.config

    async def mark_delivered(self, delivery_id, response_status):
        self.delivered.append((delivery_id, response_status))

    async def reschedule(self, delivery_id, *, delay_seconds, response_status, error):
        self.rescheduled.append((delivery_id, delay_seconds, response_status, error))

    async def mark_dead(self, delivery_id, *, response_status, error):
        self.dead.append((delivery_id, response_status, error))


def _settings():
    return SimpleNamespace(
        webhook_timeout_seconds=10,
        webhook_max_attempts=8,
        webhook_batch_size=20,
        runtime_config_key="key",
    )


def _delivery(attempts=1):
    return {
        "id": uuid4(),
        "org_id": ORG_ID,
        "payload": {"event_type": "usage.turn"},
        "attempts": attempts,
    }


def _run(monkeypatch, repository, delivery, outcome):
    sent = []

    def _fake_deliver(**kwargs):
        sent.append(kwargs)
        return outcome

    monkeypatch.setattr(worker, "deliver_sync", _fake_deliver)
    asyncio.run(worker._push_delivery(repository, delivery, _settings()))
    return sent


def test_success_marks_delivered(monkeypatch):
    repository = _FakeWebhookRepository()
    delivery = _delivery()
    sent = _run(
        monkeypatch, repository, delivery, DeliveryOutcome(True, 200, "", False)
    )
    assert repository.delivered == [(delivery["id"], 200)]
    assert repository.rescheduled == [] and repository.dead == []
    assert sent[0]["secret"] == "topsecret"
    assert sent[0]["event_id"] == delivery["id"]


def test_non_retryable_status_dies_immediately(monkeypatch):
    repository = _FakeWebhookRepository()
    delivery = _delivery()
    _run(
        monkeypatch,
        repository,
        delivery,
        DeliveryOutcome(False, 400, "HTTP 400", False),
    )
    assert [row[0] for row in repository.dead] == [delivery["id"]]
    assert repository.rescheduled == []


def test_retryable_status_is_rescheduled_on_the_ladder(monkeypatch):
    repository = _FakeWebhookRepository()
    delivery = _delivery(attempts=2)
    _run(
        monkeypatch,
        repository,
        delivery,
        DeliveryOutcome(False, 503, "HTTP 503", True),
    )
    assert repository.dead == []
    assert repository.rescheduled[0][1] == next_backoff_seconds(2)


def test_exhausted_attempts_die_even_when_retryable(monkeypatch):
    repository = _FakeWebhookRepository()
    delivery = _delivery(attempts=8)
    _run(
        monkeypatch,
        repository,
        delivery,
        DeliveryOutcome(False, 503, "HTTP 503", True),
    )
    assert [row[0] for row in repository.dead] == [delivery["id"]]
    assert repository.rescheduled == []


def test_disabled_callback_is_dropped_without_sending(monkeypatch):
    repository = _FakeWebhookRepository(enabled=False)
    delivery = _delivery()
    sent = _run(
        monkeypatch, repository, delivery, DeliveryOutcome(True, 200, "", False)
    )
    assert sent == []
    assert repository.dead[0][2] == "callback is no longer configured"


def test_missing_callback_is_dropped_without_sending(monkeypatch):
    repository = _FakeWebhookRepository(configured=False)
    sent = _run(
        monkeypatch,
        repository,
        _delivery(),
        DeliveryOutcome(True, 200, "", False),
    )
    assert sent == []
    assert len(repository.dead) == 1
