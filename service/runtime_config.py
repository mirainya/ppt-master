"""Runtime provider settings shared by the API and worker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

from service.config import Settings
from service.database import Database


@dataclass(frozen=True)
class RuntimeConfig:
    """Effective Codex and image-provider settings for one worker turn."""

    codex_base_url: str
    codex_api_key: str
    codex_model: str
    image_base_url: str
    image_api_key: str
    image_model: str
    image_size: str
    image_concurrency: int | None
    updated_at: datetime | None

    @property
    def image_generation_enabled(self) -> bool:
        values = (self.image_api_key, self.image_base_url, self.image_model)
        return all(values)

    @property
    def codex_fingerprint(self) -> tuple[str, str, str]:
        return self.codex_base_url, self.codex_api_key, self.codex_model

    @property
    def process_fingerprint(self) -> tuple[object, ...]:
        return (
            *self.codex_fingerprint,
            self.image_base_url,
            self.image_api_key,
            self.image_model,
            self.image_size,
            self.image_concurrency,
        )

    def validate(self) -> None:
        if self.codex_base_url:
            parsed = urlparse(self.codex_base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("Codex base URL must be an HTTP(S) URL")

        if self.image_api_key and not (self.image_base_url and self.image_model):
            raise ValueError("image API key, base URL, and model must be set together")
        if self.image_base_url:
            parsed = urlparse(self.image_base_url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError("image base URL must be an HTTPS URL")
        if self.image_generation_enabled:
            try:
                width_text, height_text = self.image_size.lower().split("x", 1)
                width, height = int(width_text), int(height_text)
            except ValueError as exc:
                raise ValueError("image size must use WIDTHxHEIGHT") from exc
            if width <= 0 or height <= 0 or width > 8192 or height > 8192:
                raise ValueError("image size is outside the supported range")


class RuntimeConfigRepository:
    """Read and update the singleton runtime-provider configuration."""

    def __init__(self, database: Database, defaults: Settings) -> None:
        self.database = database
        self.defaults = defaults
        try:
            self._fernet = (
                Fernet(defaults.runtime_config_key.encode("ascii"))
                if defaults.runtime_config_key
                else None
            )
        except (UnicodeEncodeError, ValueError) as exc:
            raise RuntimeError(
                "PPT_RUNTIME_CONFIG_KEY must be a valid Fernet key"
            ) from exc

    async def get(self) -> RuntimeConfig:
        row = await self.database.require_pool().fetchrow(
            "SELECT * FROM service_runtime_config WHERE id = 1"
        )
        if row is None:
            raise RuntimeError("service_runtime_config row is missing")
        config = self._resolve(dict(row))
        config.validate()
        return config

    async def update(
        self,
        *,
        codex_base_url: str,
        codex_api_key: str | None,
        clear_codex_api_key: bool,
        codex_model: str,
        image_base_url: str,
        image_api_key: str | None,
        clear_image_api_key: bool,
        image_model: str,
        image_size: str,
        image_concurrency: int | None,
    ) -> RuntimeConfig:
        current = await self.database.require_pool().fetchrow(
            "SELECT * FROM service_runtime_config WHERE id = 1"
        )
        if current is None:
            raise RuntimeError("service_runtime_config row is missing")

        next_codex_key = current["codex_api_key_encrypted"]
        if clear_codex_api_key:
            next_codex_key = self._encrypt("")
        elif codex_api_key is not None:
            next_codex_key = self._encrypt(codex_api_key)

        next_image_key = current["image_api_key_encrypted"]
        if clear_image_api_key:
            next_image_key = self._encrypt("")
        elif image_api_key is not None:
            next_image_key = self._encrypt(image_api_key)

        candidate = {
            **dict(current),
            "codex_base_url": self._nullable(codex_base_url),
            "codex_api_key_encrypted": next_codex_key,
            "codex_model": self._nullable(codex_model),
            "image_base_url": self._nullable(image_base_url),
            "image_api_key_encrypted": next_image_key,
            "image_model": self._nullable(image_model),
            "image_size": self._nullable(image_size),
            "image_concurrency": image_concurrency,
        }
        self._resolve(candidate).validate()

        row = await self.database.require_pool().fetchrow(
            """
            UPDATE service_runtime_config
            SET codex_base_url = $1,
                codex_api_key_encrypted = $2,
                codex_model = $3,
                image_base_url = $4,
                image_api_key_encrypted = $5,
                image_model = $6,
                image_size = $7,
                image_concurrency = $8,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            RETURNING *
            """,
            self._nullable(codex_base_url),
            next_codex_key,
            self._nullable(codex_model),
            self._nullable(image_base_url),
            next_image_key,
            self._nullable(image_model),
            self._nullable(image_size),
            image_concurrency,
        )
        if row is None:
            raise RuntimeError("service_runtime_config row is missing")
        config = self._resolve(dict(row))
        config.validate()
        return config

    def _resolve(self, row: dict[str, Any]) -> RuntimeConfig:
        return RuntimeConfig(
            codex_base_url=self._value(row["codex_base_url"], self.defaults.runner_base_url),
            codex_api_key=self._secret(
                row["codex_api_key_encrypted"], self.defaults.runner_api_key
            ),
            codex_model=self._value(row["codex_model"], self.defaults.runner_model),
            image_base_url=self._value(row["image_base_url"], self.defaults.image_base_url),
            image_api_key=self._secret(
                row["image_api_key_encrypted"], self.defaults.image_api_key
            ),
            image_model=self._value(row["image_model"], self.defaults.image_model),
            image_size=self._value(row["image_size"], self.defaults.image_size),
            image_concurrency=(
                row["image_concurrency"]
                if row["image_concurrency"] is not None
                else self.defaults.image_concurrency
            ),
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _nullable(value: str) -> str | None:
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _value(value: str | None, fallback: str) -> str:
        return fallback if value is None else value.strip()

    def _encrypt(self, value: str) -> str:
        if self._fernet is None:
            raise RuntimeError("PPT_RUNTIME_CONFIG_KEY is required to save API keys")
        return self._fernet.encrypt(value.strip().encode("utf-8")).decode("ascii")

    def _secret(self, encrypted: str | None, fallback: str) -> str:
        if encrypted is None:
            return fallback
        if self._fernet is None:
            raise RuntimeError("PPT_RUNTIME_CONFIG_KEY is required to read API keys")
        try:
            return self._fernet.decrypt(encrypted.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError("runtime API key encryption is invalid") from exc
