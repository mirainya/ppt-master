"""Usage webhook configuration, signing, and SSRF-safe outbound delivery."""

from __future__ import annotations

import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import secrets
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

from service.config import Settings
from service.database import Database


# Retry ladder in seconds, one entry per attempt already made. The last value
# repeats for any further attempts until PPT_WEBHOOK_MAX_ATTEMPTS is reached.
BACKOFF_SECONDS = (10, 30, 120, 600, 3600, 21600)

_ALLOWED_SCHEME = "https"
_MAX_URL_LENGTH = 2048
_MAX_RESPONSE_BYTES = 2048
_SIGNATURE_HEADER = "X-PPTM-Signature"
_TIMESTAMP_HEADER = "X-PPTM-Timestamp"
_EVENT_ID_HEADER = "X-PPTM-Event-Id"


class WebhookAddressError(ValueError):
    """Raised when a callback URL is malformed or resolves to a blocked address."""


@dataclass(frozen=True)
class WebhookConfig:
    """One organization's effective callback configuration."""

    org_id: UUID
    callback_url: str
    secret: str
    enabled: bool


@dataclass(frozen=True)
class DeliveryOutcome:
    """Result of one delivery attempt."""

    delivered: bool
    status: int | None
    error: str
    retryable: bool


def _iso(moment: datetime) -> str:
    """Serialize an aware timestamp as ISO-8601 UTC with a Z suffix."""
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_turn_payload(
    *,
    event_id: UUID,
    org_id: UUID,
    job_id: UUID,
    end_user_id: str | None,
    job_status: str,
    turn_id: str,
    turn_index: int,
    occurred_at: datetime,
    delta: dict[str, Any],
    job_total: dict[str, Any],
) -> dict[str, Any]:
    """Build one per-turn usage event body."""
    return {
        "event_id": str(event_id),
        "event_type": "usage.turn",
        "occurred_at": _iso(occurred_at),
        "org_id": str(org_id),
        "end_user_id": end_user_id,
        "job_id": str(job_id),
        "job_status": job_status,
        "usage_status": "partial",
        "turn": {"index": turn_index, "turn_id": turn_id},
        "delta": {
            "input_tokens": int(delta["input_tokens"]),
            "output_tokens": int(delta["output_tokens"]),
            "images": int(delta["images"]),
            "pages": int(delta["pages"]),
            "our_charge": {"credits": float(delta["credits"])},
        },
        "job_total": _job_total(job_total),
    }


def build_final_payload(
    *,
    event_id: UUID,
    org_id: UUID,
    job_id: UUID,
    end_user_id: str | None,
    job_status: str,
    occurred_at: datetime,
    job_total: dict[str, Any],
) -> dict[str, Any]:
    """Build the terminal usage event body.

    `delta` is null rather than all-zero: the final event marks completion, it is
    not a turn that consumed nothing.
    """
    return {
        "event_id": str(event_id),
        "event_type": "usage.final",
        "occurred_at": _iso(occurred_at),
        "org_id": str(org_id),
        "end_user_id": end_user_id,
        "job_id": str(job_id),
        "job_status": job_status,
        "usage_status": "final",
        "turn": {"index": int(job_total["turns"]), "turn_id": None},
        "delta": None,
        "job_total": _job_total(job_total),
    }


def _job_total(totals: dict[str, Any]) -> dict[str, Any]:
    """Normalize a job's cumulative usage for the wire."""
    return {
        "input_tokens": int(totals["input_tokens"]),
        "output_tokens": int(totals["output_tokens"]),
        "images": int(totals["images"]),
        "pages": int(totals["pages"]),
        "turns": int(totals["turns"]),
        "our_charge": {"credits": float(totals["our_charge"])},
    }


def next_backoff_seconds(attempts: int) -> int:
    """Seconds to wait before the next attempt, given attempts already made."""
    index = min(max(attempts, 1), len(BACKOFF_SECONDS)) - 1
    return BACKOFF_SECONDS[index]


def sign_payload(secret: str, timestamp: int, body: bytes) -> str:
    """Return the sha256=<hex> signature over "<timestamp>.<body>"."""
    message = f"{timestamp}.".encode("ascii") + body
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def validate_callback_url(url: str) -> str:
    """Check a callback URL's shape at configuration time. Returns it normalized.

    Shape-only: the address itself is re-resolved and re-checked before every
    send, because DNS can change after the URL is stored.
    """
    candidate = url.strip()
    if not candidate:
        raise WebhookAddressError("callback URL is required")
    if len(candidate) > _MAX_URL_LENGTH:
        raise WebhookAddressError("callback URL is too long")
    parsed = urlparse(candidate)
    if parsed.scheme != _ALLOWED_SCHEME:
        raise WebhookAddressError("callback URL must use HTTPS")
    if not parsed.hostname:
        raise WebhookAddressError("callback URL must include a host")
    if parsed.username or parsed.password:
        raise WebhookAddressError("callback URL must not embed credentials")
    port = parsed.port
    if port is not None and port != 443 and port <= 1024:
        raise WebhookAddressError("callback URL port is not allowed")
    return candidate


def _blocked_reason(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    """Return why an address is not a valid callback target, or "" when allowed."""
    resolved = address
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        resolved = mapped
    if resolved.is_loopback:
        return "loopback address"
    if resolved.is_private:
        return "private address"
    if resolved.is_link_local:
        return "link-local address"
    if resolved.is_reserved:
        return "reserved address"
    if resolved.is_multicast:
        return "multicast address"
    if resolved.is_unspecified:
        return "unspecified address"
    return ""


def resolve_public_addresses(host: str, port: int) -> list[tuple[int, str]]:
    """Resolve a host to (family, ip) pairs, rejecting any non-public address.

    Every resolved address must be public: if a name resolves to a mix, the whole
    target is refused rather than silently using the public one, since a later
    lookup could return the internal address instead.
    """
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise WebhookAddressError(f"could not resolve {host}") from exc
    if not infos:
        raise WebhookAddressError(f"could not resolve {host}")
    addresses: list[tuple[int, str]] = []
    for family, _type, _proto, _canonname, sockaddr in infos:
        ip_text = sockaddr[0]
        reason = _blocked_reason(ipaddress.ip_address(ip_text))
        if reason:
            raise WebhookAddressError(f"callback host resolves to a {reason}")
        addresses.append((family, ip_text))
    return addresses


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that dials a pre-validated IP but keeps SNI on the host.

    Pinning closes the DNS-rebinding window between validating the resolved
    address and opening the socket. Certificate verification still targets the
    original hostname, so pinning never weakens TLS.
    """

    def __init__(
        self,
        host: str,
        port: int,
        *,
        pinned_family: int,
        pinned_ip: str,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(host, port, timeout=timeout, context=context)
        self._pinned_family = pinned_family
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        raw_socket = socket.socket(self._pinned_family, socket.SOCK_STREAM)
        try:
            raw_socket.settimeout(self.timeout)
            raw_socket.connect((self._pinned_ip, self.port))
        except OSError:
            raw_socket.close()
            raise
        self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)


def deliver_sync(
    *,
    callback_url: str,
    secret: str,
    event_id: UUID,
    payload: dict,
    timeout_seconds: float,
) -> DeliveryOutcome:
    """POST one signed event, blocking. Call through asyncio.to_thread.

    Mirrors the outbound style already used for the image-capabilities probe in
    service/app.py: stdlib client, explicit timeout, every failure degraded into
    a return value instead of an exception.
    """
    parsed = urlparse(callback_url)
    host = parsed.hostname or ""
    port = parsed.port or 443
    try:
        addresses = resolve_public_addresses(host, port)
    except WebhookAddressError as exc:
        # Address problems are configuration problems; retrying cannot fix them.
        return DeliveryOutcome(False, None, str(exc), retryable=False)

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    timestamp = int(time.time())
    headers = {
        "Content-Type": "application/json",
        _EVENT_ID_HEADER: str(event_id),
        _TIMESTAMP_HEADER: str(timestamp),
        _SIGNATURE_HEADER: sign_payload(secret, timestamp, body),
    }
    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"
    family, pinned_ip = addresses[0]
    connection = _PinnedHTTPSConnection(
        host,
        port,
        pinned_family=family,
        pinned_ip=pinned_ip,
        timeout=timeout_seconds,
        context=ssl.create_default_context(),
    )
    try:
        connection.request("POST", target, body=body, headers=headers)
        response = connection.getresponse()
        status = response.status
        # Bounded read: the body is never used, but it must be drained enough to
        # keep a hostile or broken endpoint from streaming us out of memory.
        response.read(_MAX_RESPONSE_BYTES)
    except (OSError, http.client.HTTPException) as exc:
        return DeliveryOutcome(False, None, f"{type(exc).__name__}: {exc}", True)
    finally:
        connection.close()

    if 200 <= status < 300:
        return DeliveryOutcome(True, status, "", retryable=False)
    # 4xx means the endpoint rejected the event itself, so retrying wastes
    # attempts — except 408/429, which explicitly invite another try.
    retryable = status >= 500 or status in {408, 429}
    return DeliveryOutcome(False, status, f"HTTP {status}", retryable)


class WebhookRepository:
    """Read and update per-organization callback configuration."""

    def __init__(self, database: Database, defaults: Settings) -> None:
        self.database = database
        self.defaults = defaults
        self._fernet = self._build_fernet(defaults.runtime_config_key)

    @staticmethod
    def _build_fernet(key: str) -> Fernet | None:
        if not key:
            return None
        try:
            return Fernet(key.encode("ascii"))
        except (UnicodeEncodeError, ValueError) as exc:
            raise RuntimeError(
                "PPT_RUNTIME_CONFIG_KEY must be a valid Fernet key"
            ) from exc

    @property
    def is_configured(self) -> bool:
        """Whether a signing key is available, re-reading the environment if not.

        The Settings snapshot is taken once at startup, so a process that booted
        before its key was in place would stay broken forever. Re-checking lets
        that one recoverable case heal instead of silently parking every event.
        """
        if self._fernet is None:
            self._fernet = self._build_fernet(
                os.environ.get("PPT_RUNTIME_CONFIG_KEY", "").strip()
            )
        return self._fernet is not None

    async def count_pending(self) -> int:
        """How many events are waiting to be delivered, for operator visibility."""
        return await self.database.require_pool().fetchval(
            """
            SELECT count(*) FROM webhook_deliveries
            WHERE delivered_at IS NULL AND dead_at IS NULL
            """
        )

    async def get(self, org_id: UUID) -> WebhookConfig | None:
        record = await self.database.require_pool().fetchrow(
            """
            SELECT org_id, callback_url, secret_encrypted, enabled
            FROM org_webhooks
            WHERE org_id = $1
            """,
            org_id,
        )
        if record is None:
            return None
        return WebhookConfig(
            org_id=record["org_id"],
            callback_url=record["callback_url"],
            secret=self._decrypt(record["secret_encrypted"]),
            enabled=record["enabled"],
        )

    async def upsert(
        self,
        org_id: UUID,
        *,
        callback_url: str,
        enabled: bool,
        rotate_secret: bool,
    ) -> tuple[WebhookConfig, str | None]:
        """Write one org's callback config; returns it plus any new plaintext secret.

        The secret is server-generated so a weak one can never be configured. It
        is returned in plaintext only on the call that creates or rotates it.
        """
        normalized_url = validate_callback_url(callback_url)
        existing = await self.get(org_id)
        new_secret: str | None = None
        if existing is None or rotate_secret:
            new_secret = secrets.token_urlsafe(32)
            secret = new_secret
        else:
            secret = existing.secret
        await self.database.require_pool().execute(
            """
            INSERT INTO org_webhooks
                (org_id, callback_url, secret_encrypted, enabled)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (org_id) DO UPDATE
                SET callback_url = EXCLUDED.callback_url,
                    secret_encrypted = EXCLUDED.secret_encrypted,
                    enabled = EXCLUDED.enabled,
                    updated_at = CURRENT_TIMESTAMP
            """,
            org_id,
            normalized_url,
            self._encrypt(secret),
            enabled,
        )
        config = WebhookConfig(
            org_id=org_id,
            callback_url=normalized_url,
            secret=secret,
            enabled=enabled,
        )
        return config, new_secret

    async def claim_due(self, batch_size: int, lease_seconds: int) -> list[dict]:
        """Take a batch of due deliveries, reserving each one's next attempt.

        SKIP LOCKED keeps concurrent workers on disjoint batches, and pushing
        next_attempt_at forward in the same statement means a worker that dies
        mid-send simply lets the row come due again — no lease table, no
        "sending" state to get stuck in. Delivery is therefore at-least-once and
        consumers de-duplicate on the event id.
        """
        records = await self.database.require_pool().fetch(
            """
            WITH due AS (
                SELECT id FROM webhook_deliveries
                WHERE delivered_at IS NULL
                  AND dead_at IS NULL
                  AND next_attempt_at <= CURRENT_TIMESTAMP
                ORDER BY next_attempt_at
                LIMIT $1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE webhook_deliveries AS d
            SET attempts = d.attempts + 1,
                next_attempt_at = CURRENT_TIMESTAMP + ($2 || ' seconds')::interval
            FROM due
            WHERE d.id = due.id
            RETURNING d.*
            """,
            batch_size,
            str(lease_seconds),
        )
        return [dict(record) for record in records]

    async def mark_delivered(self, delivery_id: UUID, response_status: int) -> None:
        await self.database.require_pool().execute(
            """
            UPDATE webhook_deliveries
            SET delivered_at = CURRENT_TIMESTAMP,
                response_status = $2,
                last_error = NULL
            WHERE id = $1
            """,
            delivery_id,
            response_status,
        )

    async def reschedule(
        self,
        delivery_id: UUID,
        *,
        delay_seconds: int,
        response_status: int | None,
        error: str,
    ) -> None:
        await self.database.require_pool().execute(
            """
            UPDATE webhook_deliveries
            SET next_attempt_at = CURRENT_TIMESTAMP + ($2 || ' seconds')::interval,
                response_status = $3,
                last_error = $4
            WHERE id = $1
            """,
            delivery_id,
            str(delay_seconds),
            response_status,
            error[:500],
        )

    async def mark_dead(
        self,
        delivery_id: UUID,
        *,
        response_status: int | None,
        error: str,
    ) -> None:
        await self.database.require_pool().execute(
            """
            UPDATE webhook_deliveries
            SET dead_at = CURRENT_TIMESTAMP,
                response_status = $2,
                last_error = $3
            WHERE id = $1
            """,
            delivery_id,
            response_status,
            error[:500],
        )

    async def list_deliveries(self, org_id: UUID, limit: int) -> list[dict]:
        records = await self.database.require_pool().fetch(
            """
            SELECT id, job_id, event_type, event_key, payload, attempts,
                   next_attempt_at, delivered_at, dead_at, response_status,
                   last_error, created_at
            FROM webhook_deliveries
            WHERE org_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            org_id,
            max(1, min(limit, 200)),
        )
        return [dict(record) for record in records]

    def _encrypt(self, value: str) -> str:
        if self._fernet is None:
            raise RuntimeError(
                "PPT_RUNTIME_CONFIG_KEY is required to save webhook secrets"
            )
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def _decrypt(self, encrypted: str) -> str:
        if self._fernet is None:
            raise RuntimeError(
                "PPT_RUNTIME_CONFIG_KEY is required to read webhook secrets"
            )
        try:
            return self._fernet.decrypt(encrypted.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError("webhook secret encryption is invalid") from exc
