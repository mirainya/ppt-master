"""Runtime-configurable billing pricing backed by the billing_config table."""

from __future__ import annotations

import time
from dataclasses import dataclass
from uuid import UUID, uuid4

from service.database import Database


@dataclass(frozen=True)
class Pricing:
    """Layer-1 unit prices and per-job hold, in credits."""

    price_input_token: float
    price_output_token: float
    price_image: float
    hold_amount: float

    def usage_cost(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        images: int,
    ) -> float:
        """Compute the layer-1 credit cost for one turn's real consumption."""
        return (
            input_tokens * self.price_input_token
            + output_tokens * self.price_output_token
            + images * self.price_image
        )


class BillingRepository:
    """Read and update the single-row billing_config with a short TTL cache."""

    _CACHE_TTL_SECONDS = 30.0

    def __init__(self, database: Database) -> None:
        self.database = database
        self._cached: Pricing | None = None
        self._cached_at = 0.0

    async def get_pricing(self) -> Pricing:
        """Return current pricing, served from cache within the TTL window."""
        now = time.monotonic()
        if self._cached is not None and now - self._cached_at < self._CACHE_TTL_SECONDS:
            return self._cached
        pricing = await self._load()
        self._cached = pricing
        self._cached_at = now
        return pricing

    async def _load(self) -> Pricing:
        record = await self.database.require_pool().fetchrow(
            """
            SELECT price_input_token, price_output_token, price_image, hold_amount
            FROM billing_config
            WHERE id = 1
            """
        )
        if record is None:
            raise RuntimeError("billing_config row is missing; apply migrations")
        return Pricing(
            price_input_token=float(record["price_input_token"]),
            price_output_token=float(record["price_output_token"]),
            price_image=float(record["price_image"]),
            hold_amount=float(record["hold_amount"]),
        )

    async def update_pricing(self, pricing: Pricing) -> Pricing:
        """Persist new pricing and refresh the cache."""
        record = await self.database.require_pool().fetchrow(
            """
            UPDATE billing_config
            SET price_input_token = $1,
                price_output_token = $2,
                price_image = $3,
                hold_amount = $4,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            RETURNING price_input_token, price_output_token, price_image, hold_amount
            """,
            pricing.price_input_token,
            pricing.price_output_token,
            pricing.price_image,
            pricing.hold_amount,
        )
        if record is None:
            raise RuntimeError("billing_config row is missing; apply migrations")
        updated = Pricing(
            price_input_token=float(record["price_input_token"]),
            price_output_token=float(record["price_output_token"]),
            price_image=float(record["price_image"]),
            hold_amount=float(record["hold_amount"]),
        )
        self._cached = updated
        self._cached_at = time.monotonic()
        return updated

    async def hold_credits(self, org_id: UUID, job_id: UUID, amount: float) -> bool:
        """Atomically reserve `amount` credits for a job; False if insufficient.

        Records the hold against the job (credit_transactions.job_id + jobs.held_amount)
        so settlement and release can reconcile the exact amount held. The WHERE guard
        prevents concurrent job creations from overdrawing the balance.
        """
        async with self.database.require_pool().acquire() as connection:
            async with connection.transaction():
                balance_after = await connection.fetchval(
                    """
                    UPDATE organizations
                    SET credit_balance = credit_balance - $2
                    WHERE id = $1 AND credit_balance >= $2 AND status = 'active'
                    RETURNING credit_balance
                    """,
                    org_id,
                    amount,
                )
                if balance_after is None:
                    return False
                updated_job = await connection.fetchval(
                    """
                    UPDATE jobs
                    SET held_amount = $2
                    WHERE id = $1 AND org_id = $3 AND held_amount = 0
                    RETURNING id
                    """,
                    job_id,
                    amount,
                    org_id,
                )
                if updated_job is None:
                    raise RuntimeError(
                        "job already has a hold or belongs to another org"
                    )
                await connection.execute(
                    """
                    INSERT INTO credit_transactions
                        (id, org_id, amount, reason, job_id, balance_after)
                    VALUES ($1, $2, $3, 'hold', $4, $5)
                    """,
                    uuid4(),
                    org_id,
                    -amount,
                    job_id,
                    balance_after,
                )
                return True

    async def release_hold(self, job_id: UUID) -> bool:
        """Refund a job's outstanding hold when it ends without settling. Idempotent.

        Only refunds if held_amount > 0; sets it to 0 so repeated calls (cancel then
        fail, retries) never double-refund. Settlement also zeroes held_amount, so a
        settled job releases nothing here.
        """
        async with self.database.require_pool().acquire() as connection:
            async with connection.transaction():
                job = await connection.fetchrow(
                    "SELECT org_id, held_amount FROM jobs WHERE id = $1 FOR UPDATE",
                    job_id,
                )
                if job is None or job["org_id"] is None:
                    return False
                held = float(job["held_amount"])
                if held <= 0:
                    return False
                balance_after = await connection.fetchval(
                    """
                    UPDATE organizations
                    SET credit_balance = credit_balance + $2
                    WHERE id = $1
                    RETURNING credit_balance
                    """,
                    job["org_id"],
                    held,
                )
                await connection.execute(
                    "UPDATE jobs SET held_amount = 0 WHERE id = $1",
                    job_id,
                )
                await connection.execute(
                    """
                    INSERT INTO credit_transactions
                        (id, org_id, amount, reason, job_id, balance_after)
                    VALUES ($1, $2, $3, 'settle_refund', $4, $5)
                    """,
                    uuid4(),
                    job["org_id"],
                    held,
                    job_id,
                    balance_after,
                )
                return True

    async def topup(self, org_id: UUID, amount: float) -> float:
        """Add credits to an organization balance and return the new balance."""
        async with self.database.require_pool().acquire() as connection:
            async with connection.transaction():
                balance_after = await connection.fetchval(
                    """
                    UPDATE organizations
                    SET credit_balance = credit_balance + $2
                    WHERE id = $1
                    RETURNING credit_balance
                    """,
                    org_id,
                    amount,
                )
                if balance_after is None:
                    raise RuntimeError("organization not found")
                await connection.execute(
                    """
                    INSERT INTO credit_transactions
                        (id, org_id, amount, reason, balance_after)
                    VALUES ($1, $2, $3, 'topup', $4)
                    """,
                    uuid4(),
                    org_id,
                    amount,
                    balance_after,
                )
                return float(balance_after)
