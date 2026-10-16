"""Configuration with safe, explicit defaults."""

from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping


class ConfigError(ValueError):
    """Raised when configuration would make the service unsafe or unusable."""


def _bool(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be true or false")


def _int(value: str, name: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _decimal(value: str, name: str, minimum: str, maximum: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ConfigError(f"{name} must be a decimal number") from exc
    if not Decimal(minimum) <= parsed <= Decimal(maximum):
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def load_env_file(path: Path = Path(".env")) -> None:
    """Load simple KEY=VALUE pairs without overriding the process environment."""

    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Config:
    auth_token_hash: str
    host: str
    port: int
    trusted_hosts: tuple[str, ...]
    provider: str
    model: str
    provider_url: str | None
    provider_api_key: str | None
    allow_remote_personal_data: bool
    data_dir: Path
    allowed_root: Path
    monthly_budget_usd_micros: int
    fx_inr_per_usd: Decimal
    input_price_usd_per_million: Decimal
    output_price_usd_per_million: Decimal
    max_input_tokens: int
    max_output_tokens: int
    max_message_chars: int
    max_file_bytes: int
    max_fetch_bytes: int
    fetch_timeout_seconds: int

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        values = os.environ if env is None else env
        token = values.get("JARVIS_AUTH_TOKEN", "").strip()
        if len(token) < 32:
            raise ConfigError("JARVIS_AUTH_TOKEN must contain at least 32 characters")
        if token.lower().startswith("replace-with"):
            raise ConfigError("JARVIS_AUTH_TOKEN must be replaced with a random value")

        host = values.get("JARVIS_HOST", "127.0.0.1").strip()
        allow_non_loopback = _bool(values.get("JARVIS_ALLOW_NON_LOOPBACK_BINDING", "false"), "JARVIS_ALLOW_NON_LOOPBACK_BINDING")
        if host not in {"127.0.0.1", "0.0.0.0"} and not allow_non_loopback:
            raise ConfigError("JARVIS_HOST must be 127.0.0.1 unless non-loopback binding is explicitly enabled")
        if host != "127.0.0.1" and not allow_non_loopback:
            raise ConfigError("non-loopback binding requires JARVIS_ALLOW_NON_LOOPBACK_BINDING=true")
        trusted_hosts = tuple(item.strip().lower() for item in values.get("JARVIS_TRUSTED_HOSTS", "127.0.0.1,localhost").split(",") if item.strip())
        if not trusted_hosts:
            raise ConfigError("JARVIS_TRUSTED_HOSTS must contain at least one host")

        provider = values.get("JARVIS_PROVIDER", "fake").strip().lower()
        if provider not in {"fake", "openai-compatible"}:
            raise ConfigError("JARVIS_PROVIDER must be fake or openai-compatible")
        provider_url = values.get("JARVIS_PROVIDER_URL", "").strip() or None
        provider_key = values.get("JARVIS_PROVIDER_API_KEY", "").strip() or None
        if provider == "openai-compatible" and (not provider_url or not provider_key):
            raise ConfigError("remote provider requires JARVIS_PROVIDER_URL and JARVIS_PROVIDER_API_KEY")

        data_dir = Path(values.get("JARVIS_DATA_DIR", "./data")).expanduser().resolve()
        allowed_root = Path(values.get("JARVIS_ALLOWED_ROOT", "./workspace")).expanduser().resolve()
        if data_dir == allowed_root or allowed_root.is_relative_to(data_dir):
            raise ConfigError("JARVIS_ALLOWED_ROOT must not contain the application data directory")

        fx = _decimal(values.get("JARVIS_FX_INR_PER_USD", "95"), "JARVIS_FX_INR_PER_USD", "0.01", "100000")
        monthly_inr = _decimal(values.get("JARVIS_MONTHLY_BUDGET_INR", "3500"), "JARVIS_MONTHLY_BUDGET_INR", "0", "100000000")
        budget_usd_micros = int((monthly_inr / fx * Decimal(1_000_000)).to_integral_value())

        return cls(
            auth_token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            host=host,
            port=_int(values.get("JARVIS_PORT", "8787"), "JARVIS_PORT", 1024, 65535),
            trusted_hosts=trusted_hosts,
            provider=provider,
            model=values.get("JARVIS_MODEL", "jarvis-local-safe").strip() or "jarvis-local-safe",
            provider_url=provider_url,
            provider_api_key=provider_key,
            allow_remote_personal_data=_bool(values.get("JARVIS_ALLOW_REMOTE_PERSONAL_DATA", "false"), "JARVIS_ALLOW_REMOTE_PERSONAL_DATA"),
            data_dir=data_dir,
            allowed_root=allowed_root,
            monthly_budget_usd_micros=budget_usd_micros,
            fx_inr_per_usd=fx,
            input_price_usd_per_million=_decimal(values.get("JARVIS_INPUT_PRICE_USD_PER_MILLION", "0.75"), "JARVIS_INPUT_PRICE_USD_PER_MILLION", "0", "100000"),
            output_price_usd_per_million=_decimal(values.get("JARVIS_OUTPUT_PRICE_USD_PER_MILLION", "3.75"), "JARVIS_OUTPUT_PRICE_USD_PER_MILLION", "0", "100000"),
            max_input_tokens=_int(values.get("JARVIS_MAX_INPUT_TOKENS", "12000"), "JARVIS_MAX_INPUT_TOKENS", 256, 200000),
            max_output_tokens=_int(values.get("JARVIS_MAX_OUTPUT_TOKENS", "2048"), "JARVIS_MAX_OUTPUT_TOKENS", 128, 32000),
            max_message_chars=_int(values.get("JARVIS_MAX_MESSAGE_CHARS", "12000"), "JARVIS_MAX_MESSAGE_CHARS", 64, 100000),
            max_file_bytes=_int(values.get("JARVIS_MAX_FILE_BYTES", "1048576"), "JARVIS_MAX_FILE_BYTES", 1024, 100000000),
            max_fetch_bytes=_int(values.get("JARVIS_MAX_FETCH_BYTES", "1048576"), "JARVIS_MAX_FETCH_BYTES", 1024, 100000000),
            fetch_timeout_seconds=_int(values.get("JARVIS_FETCH_TIMEOUT_SECONDS", "10"), "JARVIS_FETCH_TIMEOUT_SECONDS", 1, 60),
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.allowed_root.mkdir(parents=True, exist_ok=True)

    def token_for_tests(self) -> str:
        """Generate a valid token for fixtures; never used by production code."""

        return secrets.token_urlsafe(32)
