import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service.app import org_usage
from service.auth import AuthenticatedUser

ORG_ID = uuid4()


class _FakeJobRepository:
    def __init__(self):
        self.calls = []

    async def aggregate_org_usage(self, org_id, *, external_id, since, until):
        self.calls.append({"org_id": org_id, "external_id": external_id})
        return [{"end_user_id": external_id or "all", "input_tokens": 1}]


class _FakeAuthRepository:
    def __init__(self, external_id):
        self.external_id = external_id

    async def external_id_for_user(self, user_id):
        return self.external_id


def _request(external_id):
    state = SimpleNamespace(
        repository=_FakeJobRepository(),
        auth_repository=_FakeAuthRepository(external_id),
    )
    return SimpleNamespace(app=SimpleNamespace(state=state))


def _org_user():
    return AuthenticatedUser(
        id=uuid4(), username="acme:cust-42", is_admin=False, org_id=ORG_ID
    )


def _call(request, user, credentials, end_user_id=None):
    return asyncio.run(
        org_usage(
            request,
            user,
            credentials,
            end_user_id=end_user_id,
            since=None,
            until=None,
        )
    )


def test_org_key_reads_whole_tenant():
    request = _request("cust-42")
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials="pptm_org_secret"
    )
    _call(request, _org_user(), credentials)
    assert request.app.state.repository.calls == [
        {"org_id": ORG_ID, "external_id": None}
    ]


def test_session_is_scoped_to_own_end_user():
    request = _request("cust-42")
    _call(request, _org_user(), None)
    assert request.app.state.repository.calls == [
        {"org_id": ORG_ID, "external_id": "cust-42"}
    ]


def test_session_cannot_read_another_end_user():
    request = _request("cust-42")
    with pytest.raises(HTTPException) as excinfo:
        _call(request, _org_user(), None, end_user_id="cust-99")
    assert excinfo.value.status_code == 403
    assert request.app.state.repository.calls == []


def test_session_may_pass_its_own_end_user_id():
    request = _request("cust-42")
    _call(request, _org_user(), None, end_user_id="cust-42")
    assert request.app.state.repository.calls == [
        {"org_id": ORG_ID, "external_id": "cust-42"}
    ]


def test_personal_user_without_org_is_rejected():
    request = _request(None)
    user = AuthenticatedUser(
        id=uuid4(), username="alice", is_admin=False, org_id=None
    )
    with pytest.raises(HTTPException) as excinfo:
        _call(request, user, None)
    assert excinfo.value.status_code == 403
