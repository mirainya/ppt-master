"""Redis-backed task queue used by the API and worker."""

from __future__ import annotations

from dataclasses import dataclass
from time import time
from uuid import UUID
from uuid import uuid4

from redis.asyncio import Redis


_ENQUEUE_SCRIPT = """
if redis.call('LPOS', KEYS[1], ARGV[1]) or redis.call('LPOS', KEYS[2], ARGV[1]) then
    return 0
end
redis.call('ZREM', KEYS[3], ARGV[1])
redis.call('HDEL', KEYS[4], ARGV[1])
redis.call('LPUSH', KEYS[1], ARGV[1])
return 1
"""

_RENEW_SCRIPT = """
if redis.call('HGET', KEYS[1], ARGV[1]) ~= ARGV[2] then
    return 0
end
if not redis.call('LPOS', KEYS[2], ARGV[1]) then
    return 0
end
redis.call('ZADD', KEYS[3], ARGV[3], ARGV[1])
return 1
"""

_ACKNOWLEDGE_SCRIPT = """
if redis.call('HGET', KEYS[1], ARGV[1]) ~= ARGV[2] then
    return 0
end
local removed = redis.call('LREM', KEYS[2], 0, ARGV[1])
redis.call('HDEL', KEYS[1], ARGV[1])
redis.call('ZREM', KEYS[3], ARGV[1])
return removed
"""

_RECOVER_SCRIPT = """
local deadline = redis.call('ZSCORE', KEYS[2], ARGV[1])
if not deadline or tonumber(deadline) > tonumber(ARGV[2]) then
    return 0
end
local removed = redis.call('LREM', KEYS[1], 0, ARGV[1])
if removed > 0 and not redis.call('LPOS', KEYS[3], ARGV[1]) then
    redis.call('LPUSH', KEYS[3], ARGV[1])
end
redis.call('ZREM', KEYS[2], ARGV[1])
redis.call('HDEL', KEYS[4], ARGV[1])
return removed
"""


@dataclass(frozen=True)
class JobClaim:
    """One leased task removed from the pending queue by a worker."""

    job_id: UUID
    token: str


class JobQueue:
    """Push and lease durable job identifiers through Redis."""

    def __init__(self, redis_url: str, queue_name: str) -> None:
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.queue_name = queue_name
        self.processing_name = f"{queue_name}:processing"
        self.leases_name = f"{queue_name}:leases"
        self.owners_name = f"{queue_name}:owners"
        self.workers_name = f"{queue_name}:workers"

    async def healthcheck(self) -> None:
        await self.redis.ping()

    async def enqueue(self, job_id: UUID) -> bool:
        added = await self.redis.eval(
            _ENQUEUE_SCRIPT,
            4,
            self.queue_name,
            self.processing_name,
            self.leases_name,
            self.owners_name,
            str(job_id),
        )
        return bool(added)

    async def dequeue(
        self,
        lease_seconds: int,
        timeout_seconds: int = 5,
    ) -> JobClaim | None:
        raw_job_id = await self.redis.brpoplpush(
            self.queue_name,
            self.processing_name,
            timeout=timeout_seconds,
        )
        if raw_job_id is None:
            return None
        token = uuid4().hex
        deadline = time() + lease_seconds
        async with self.redis.pipeline(transaction=True) as pipeline:
            pipeline.hset(self.owners_name, raw_job_id, token)
            pipeline.zadd(self.leases_name, {raw_job_id: deadline})
            await pipeline.execute()
        return JobClaim(job_id=UUID(raw_job_id), token=token)

    async def renew(self, claim: JobClaim, lease_seconds: int) -> bool:
        renewed = await self.redis.eval(
            _RENEW_SCRIPT,
            3,
            self.owners_name,
            self.processing_name,
            self.leases_name,
            str(claim.job_id),
            claim.token,
            str(time() + lease_seconds),
        )
        return bool(renewed)

    async def acknowledge(self, claim: JobClaim) -> bool:
        removed = await self.redis.eval(
            _ACKNOWLEDGE_SCRIPT,
            3,
            self.owners_name,
            self.processing_name,
            self.leases_name,
            str(claim.job_id),
            claim.token,
        )
        return bool(removed)

    async def recover_expired(self) -> int:
        now = time()
        processing = await self.redis.lrange(self.processing_name, 0, -1)
        if processing:
            async with self.redis.pipeline(transaction=False) as pipeline:
                for raw_job_id in processing:
                    pipeline.zscore(self.leases_name, raw_job_id)
                scores = await pipeline.execute()
            orphaned = {
                raw_job_id: now - 1
                for raw_job_id, score in zip(processing, scores, strict=True)
                if score is None
            }
            if orphaned:
                await self.redis.zadd(self.leases_name, orphaned)

        expired = await self.redis.zrangebyscore(self.leases_name, "-inf", now)
        recovered = 0
        for raw_job_id in expired:
            removed = await self.redis.eval(
                _RECOVER_SCRIPT,
                4,
                self.processing_name,
                self.leases_name,
                self.queue_name,
                self.owners_name,
                raw_job_id,
                str(now),
            )
            if removed:
                recovered += 1
        return recovered

    async def heartbeat_worker(self, worker_id: str, ttl_seconds: int) -> None:
        now = time()
        async with self.redis.pipeline(transaction=True) as pipeline:
            pipeline.zadd(self.workers_name, {worker_id: now + ttl_seconds})
            pipeline.zremrangebyscore(self.workers_name, "-inf", now)
            await pipeline.execute()

    async def worker_available(self) -> bool:
        now = time()
        async with self.redis.pipeline(transaction=True) as pipeline:
            pipeline.zremrangebyscore(self.workers_name, "-inf", now)
            pipeline.zcard(self.workers_name)
            _, count = await pipeline.execute()
        return bool(count)

    async def forget_worker(self, worker_id: str) -> None:
        await self.redis.zrem(self.workers_name, worker_id)

    async def close(self) -> None:
        await self.redis.aclose()
