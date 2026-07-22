"""Short-lived, single-use organization SSO tickets backed by Redis."""

from __future__ import annotations

import json
import secrets
from uuid import UUID

from redis.asyncio import Redis

from service.auth import hash_token


_CONSUME_SCRIPT = """
local value = redis.call('GET', KEYS[1])
if not value then
    return nil
end
redis.call('DEL', KEYS[1])
return value
"""


class OrgTicketStore:
    """Issue and atomically consume organization workbench login tickets."""

    TTL_SECONDS = 60
    _KEY_PREFIX = "ppt-master:sso-ticket:"

    def __init__(self, redis_url: str) -> None:
        self.redis = Redis.from_url(redis_url, decode_responses=True)

    async def issue(self, user_id: UUID, org_id: UUID) -> tuple[str, int]:
        """Create a random one-time ticket for one provisioned organization user."""
        payload = json.dumps({"user_id": str(user_id), "org_id": str(org_id)})
        for _ in range(3):
            ticket = secrets.token_urlsafe(32)
            created = await self.redis.set(
                self._key(ticket),
                payload,
                ex=self.TTL_SECONDS,
                nx=True,
            )
            if created:
                return ticket, self.TTL_SECONDS
        raise RuntimeError("could not allocate a unique organization login ticket")

    async def consume(self, ticket: str) -> tuple[UUID, UUID] | None:
        """Return and delete a ticket payload in one Redis operation."""
        raw = await self.redis.eval(_CONSUME_SCRIPT, 1, self._key(ticket))
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            return UUID(payload["user_id"]), UUID(payload["org_id"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    async def close(self) -> None:
        await self.redis.aclose()

    def _key(self, ticket: str) -> str:
        return f"{self._KEY_PREFIX}{hash_token(ticket)}"
