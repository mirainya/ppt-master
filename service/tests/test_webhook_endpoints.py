"""Unit tests for webhook endpoint auth scope and secret non-disclosure."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service.app import _org_webhook_read, org_webhook, require_org_key
from service.webhooks import WebhookConfig

ORG_ID = uuid4()


class _FakeAuthRepository:
    def __init__(self, org_id=ORG_ID):
        self.org_id = org_id
        self.provisioned = []

    async def authenticate_org_api_key(self, token_hash):
        return self.org_id

    async def provision_end_user(self, org_id, external_id):
        self.provisioned.append((org_id, external_id))
        raise AssertionError("org-scoped reads must not provision an end-user")


class _FakeWebhookRepository:
    def __init__(self, config):
        self.config = config
        self.queried = []

    async def get(self, org_id):
        self.queried.append(org_id)
        return self.config


def _config():
    return WebhookConfig(
        org_id=ORG_ID,
        callback_url="https://acme.example.com/hook",
        secret="topsecret",
        enabled=True,
    )


def _request(webhook_config=None, auth=None):
    state = SimpleNamespace(
        webhook_repository=_FakeWebhookRepository(webhook_config),
        auth_repository=auth or _FakeAuthRepository(),
    )
    return SimpleNamespace(app=SimpleNamespace(state=state))


def _org_credentials(token="pptm_org_secret"):
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_org_key_resolves_to_org_id_without_provisioning():
    auth = _FakeAuthRepository()
    request = _request(auth=auth)
    resolved = asyncio.run(require_org_key(request, _org_credentials()))
    assert resolved == ORG_ID
    # Provisioning would create a users row just for reading config.
    assert auth.provisioned == []


def test_session_cookie_cannot_reach_org_key_endpoints():
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(require_org_key(_request(), None))
    assert excinfo.value.status_code == 401


def test_personal_key_is_rejected():
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(require_org_key(_request(), _org_credentials("pptm_user_abc")))
    assert excinfo.value.status_code == 401


def test_unknown_org_key_is_rejected():
    auth = _FakeAuthRepository(org_id=None)
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(require_org_key(_request(auth=auth), _org_credentials()))
    assert excinfo.value.status_code == 401


def test_read_shape_hides_the_secret():
    shaped = _org_webhook_read(_config())
    assert shaped == {
        "org_id": ORG_ID,
        "callback_url": "https://acme.example.com/hook",
        "enabled": True,
        "secret_configured": True,
    }
    assert "secret" not in shaped


def test_endpoint_scopes_the_query_to_the_caller_org():
    request = _request(webhook_config=_config())
    result = asyncio.run(org_webhook(request, ORG_ID))
    assert request.app.state.webhook_repository.queried == [ORG_ID]
    assert result["secret_configured"] is True


def test_unconfigured_org_gets_404():
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(org_webhook(_request(webhook_config=None), ORG_ID))
    assert excinfo.value.status_code == 404
