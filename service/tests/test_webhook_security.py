"""Unit tests for webhook signing, backoff, and SSRF address rejection."""

import hashlib
import hmac
import ipaddress
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service.webhooks import (
    BACKOFF_SECONDS,
    WebhookAddressError,
    _blocked_reason,
    next_backoff_seconds,
    sign_payload,
    validate_callback_url,
)


def test_signature_matches_timestamp_dot_body():
    body = b'{"event_type":"usage.turn"}'
    expected = hmac.new(
        b"topsecret", b"1700000000." + body, hashlib.sha256
    ).hexdigest()
    assert sign_payload("topsecret", 1700000000, body) == f"sha256={expected}"


def test_signature_changes_with_timestamp():
    body = b"{}"
    assert sign_payload("s", 1, body) != sign_payload("s", 2, body)


def test_backoff_ladder_climbs_then_plateaus():
    assert [next_backoff_seconds(n) for n in range(1, 7)] == list(BACKOFF_SECONDS)
    # Attempts past the ladder keep the final interval instead of growing forever.
    assert next_backoff_seconds(7) == BACKOFF_SECONDS[-1]
    assert next_backoff_seconds(99) == BACKOFF_SECONDS[-1]


def test_backoff_clamps_nonpositive_attempts():
    assert next_backoff_seconds(0) == BACKOFF_SECONDS[0]


def test_valid_https_url_is_accepted():
    assert validate_callback_url("  https://acme.example.com/pptm/usage  ") == (
        "https://acme.example.com/pptm/usage"
    )


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://acme.example.com/hook",
        "https://user:pass@acme.example.com/hook",
        "https://acme.example.com:22/hook",
        "https://",
    ],
)
def test_bad_urls_are_rejected(url):
    with pytest.raises(WebhookAddressError):
        validate_callback_url(url)


def test_overlong_url_is_rejected():
    with pytest.raises(WebhookAddressError):
        validate_callback_url("https://acme.example.com/" + "a" * 2100)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.1",
        "172.16.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fc00::1",
        "fe80::1",
        "::ffff:127.0.0.1",
        "::ffff:10.1.2.3",
    ],
)
def test_non_public_addresses_are_blocked(address):
    assert _blocked_reason(ipaddress.ip_address(address)) != ""


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "2001:4860:4860::8888"])
def test_public_addresses_are_allowed(address):
    assert _blocked_reason(ipaddress.ip_address(address)) == ""


def test_repository_recovers_a_key_that_arrived_after_startup(monkeypatch):
    """A worker booted before its env was ready must not stay disabled forever."""
    from cryptography.fernet import Fernet

    from service.webhooks import WebhookRepository

    monkeypatch.delenv("PPT_RUNTIME_CONFIG_KEY", raising=False)
    repository = WebhookRepository(None, SimpleNamespace(runtime_config_key=""))
    assert repository.is_configured is False

    monkeypatch.setenv("PPT_RUNTIME_CONFIG_KEY", Fernet.generate_key().decode())
    assert repository.is_configured is True


def test_repository_rejects_a_malformed_key():
    from service.webhooks import WebhookRepository

    with pytest.raises(RuntimeError):
        WebhookRepository(None, SimpleNamespace(runtime_config_key="not-a-fernet-key"))
