"""Deterministic configuration loading for MY LAST AI GIRLFRIENDS."""

from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit


class ConfigError(ValueError):
    """Raised when configuration is missing, ambiguous or unsafe."""


LEGACY_ENV_MAP = {
    "JARVIS_AUTH_TOKEN": "MLAG_AUTH_TOKEN",
    "JARVIS_HOST": "MLAG_HOST",
    "JARVIS_PORT": "MLAG_PORT",
    "JARVIS_TRUSTED_HOSTS": "MLAG_TRUSTED_HOSTS",
    "JARVIS_PROVIDER": "MLAG_PROVIDER",
    "JARVIS_MODEL": "MLAG_MODEL",
    "JARVIS_PROVIDER_URL": "MLAG_PROVIDER_BASE_URL",
    "JARVIS_PROVIDER_API_KEY": "MLAG_GEMINI_API_KEY",
    "JARVIS_ALLOW_REMOTE_PERSONAL_DATA": "MLAG_ALLOW_REMOTE_PERSONAL_DATA",
    "JARVIS_MONTHLY_BUDGET_INR": "MLAG_MONTHLY_BUDGET_INR",
    "JARVIS_FX_INR_PER_USD": "MLAG_FX_INR_PER_USD",
    "JARVIS_INPUT_PRICE_USD_PER_MILLION": "MLAG_INPUT_PRICE_USD_PER_MILLION",
    "JARVIS_OUTPUT_PRICE_USD_PER_MILLION": "MLAG_OUTPUT_PRICE_USD_PER_MILLION",
    "JARVIS_MAX_INPUT_TOKENS": "MLAG_MAX_INPUT_TOKENS",
    "JARVIS_MAX_OUTPUT_TOKENS": "MLAG_MAX_OUTPUT_TOKENS",
    "JARVIS_MAX_MESSAGE_CHARS": "MLAG_MAX_MESSAGE_CHARS",
    "JARVIS_MAX_FILE_BYTES": "MLAG_MAX_FILE_BYTES",
    "JARVIS_MAX_FETCH_BYTES": "MLAG_MAX_FETCH_BYTES",
    "JARVIS_FETCH_TIMEOUT_SECONDS": "MLAG_FETCH_TIMEOUT_SECONDS",
    "JARVIS_DATA_DIR": "MLAG_DATA_DIR",
    "JARVIS_ALLOWED_ROOT": "MLAG_ALLOWED_ROOT",
}


@dataclass(frozen=True)
class EnvReport:
    values: dict[str, str]
    source: dict[str, str]
    conflicts: tuple[str, ...]
    dotenv_path: Path


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


def _parse_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] in {"'", '"'} and value[-1:] == value[:1]:
            value = value[1:-1]
        if key:
            result[key] = value
    return result


def load_environment(path: Path = Path(".env"), environ: Mapping[str, str] | None = None) -> EnvReport:
    """Merge process environment over `.env`, with explicit legacy mapping.

    Precedence is process environment > new MLAG dotenv keys > legacy dotenv
    keys > defaults. A conflict is reported when both process and dotenv values
    differ. Values are never printed by the diagnostic.
    """

    process = dict(os.environ if environ is None else environ)
    process_mapped = dict(process)
    legacy_process_keys: set[str] = set()
    for old_key, new_key in LEGACY_ENV_MAP.items():
        if old_key in process and new_key not in process_mapped:
            process_mapped[new_key] = process[old_key]
            legacy_process_keys.add(new_key)
    dotenv = _parse_dotenv(path)
    mapped_dotenv = dict(dotenv)
    legacy_dotenv_keys: set[str] = set()
    for old_key, new_key in LEGACY_ENV_MAP.items():
        if old_key in dotenv and new_key not in mapped_dotenv:
            mapped_dotenv[new_key] = dotenv[old_key]
            legacy_dotenv_keys.add(new_key)

    values: dict[str, str] = {}
    source: dict[str, str] = {}
    conflicts: list[str] = []
    keys = set(mapped_dotenv) | set(process_mapped)
    for key in keys:
        if not (key.startswith("MLAG_") or key in LEGACY_ENV_MAP):
            continue
        dotenv_value = mapped_dotenv.get(key)
        process_value = process_mapped.get(key)
        if dotenv_value is not None and process_value is not None and dotenv_value != process_value:
            conflicts.append(key)
        if process_value is not None:
            values[key] = process_value
            source[key] = "process-legacy" if key in legacy_process_keys else "process"
        elif dotenv_value is not None:
            values[key] = dotenv_value
            source[key] = "dotenv-legacy" if key in legacy_dotenv_keys else "dotenv"
    for old_key, new_key in LEGACY_ENV_MAP.items():
        if old_key in dotenv and new_key in dotenv and dotenv[old_key] != dotenv[new_key]:
            conflicts.append(new_key)
        if old_key in process and new_key in process and process[old_key] != process[new_key]:
            conflicts.append(new_key)
    return EnvReport(values, source, tuple(sorted(set(conflicts))), path)


def _validate_provider_base_url(value: str, mode: str, provider: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigError("MLAG_PROVIDER_BASE_URL must be a credential-free absolute HTTP(S) URL")
    if mode == "real" and provider == "gemini" and parsed.scheme != "https":
        raise ConfigError("MLAG_PROVIDER_BASE_URL must use HTTPS in real mode")
    if provider == "ollama" and (parsed.hostname or "").lower() not in {"127.0.0.1", "localhost", "::1"}:
        raise ConfigError("MLAG_PROVIDER_BASE_URL for ollama must target the local machine")
    return value.strip()


def generate_auth_token() -> str:
    """Return a fresh token; callers must store it without logging it."""

    return secrets.token_urlsafe(32)


def token_status(value: str | None) -> str:
    if value is None or not value.strip():
        return "missing"
    normalized = value.strip().lower()
    if normalized in {"deleted", "null", "none", "changeme", "replace-with-a-random-32-byte-token"}:
        return "invalid-placeholder"
    if normalized.startswith("replace-with") or normalized.startswith("your-"):
        return "invalid-placeholder"
    if len(value.strip()) < 32:
        return "too-short"
    return "valid"


def diagnose_environment(report: EnvReport) -> dict:
    token = report.values.get("MLAG_AUTH_TOKEN") or report.values.get("JARVIS_AUTH_TOKEN")
    mode = report.values.get("MLAG_MODE", "offline").strip().lower()
    provider = report.values.get("MLAG_PROVIDER", "gemini").strip().lower()
    model = report.values.get("MLAG_MODEL", "gemini-3.8-flash").strip()
    return {
        "dotenv_path": str(report.dotenv_path),
        "configuration_source": "process" if report.source.get("MLAG_AUTH_TOKEN", "").startswith("process") else "dotenv/default",
        "conflicts": list(report.conflicts),
        "token_status": token_status(token),
        "mode": mode,
        "provider": provider,
        "model": model,
        "ready": token_status(token) == "valid" and mode in {"offline", "real"},
        "api_key_present": bool(report.values.get("MLAG_GEMINI_API_KEY", "").strip()),
    }


@dataclass(frozen=True)
class Config:
    auth_token_hash: str
    host: str
    port: int
    trusted_hosts: tuple[str, ...]
    mode: str
    provider: str
    model: str
    provider_base_url: str
    gemini_api_key: str | None
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
    max_context_messages: int
    max_memory_chars: int
    max_file_bytes: int
    max_fetch_bytes: int
    fetch_timeout_seconds: int
    scheduler_interval_seconds: int

    @classmethod
    def from_report(cls, report: EnvReport) -> "Config":
        values = report.values
        token = values.get("MLAG_AUTH_TOKEN") or values.get("JARVIS_AUTH_TOKEN", "")
        status = token_status(token)
        if status != "valid":
            raise ConfigError(f"MLAG_AUTH_TOKEN is {status}; generate a new local token before starting")

        host = values.get("MLAG_HOST", "127.0.0.1").strip()
        allow_non_loopback = _bool(values.get("MLAG_ALLOW_NON_LOOPBACK_BINDING", "false"), "MLAG_ALLOW_NON_LOOPBACK_BINDING")
        if host != "127.0.0.1" and not allow_non_loopback:
            raise ConfigError("MLAG_HOST must be 127.0.0.1 unless MLAG_ALLOW_NON_LOOPBACK_BINDING=true")
        trusted_hosts = tuple(item.strip().lower() for item in values.get("MLAG_TRUSTED_HOSTS", "127.0.0.1,localhost").split(",") if item.strip())
        if not trusted_hosts:
            raise ConfigError("MLAG_TRUSTED_HOSTS must contain at least one host")

        mode = values.get("MLAG_MODE", "offline").strip().lower()
        if mode not in {"offline", "real"}:
            raise ConfigError("MLAG_MODE must be offline or real")
        provider = values.get("MLAG_PROVIDER", "gemini").strip().lower()
        if provider not in {"gemini", "ollama"}:
            raise ConfigError("MLAG_PROVIDER must be gemini or ollama; use MLAG_MODE=offline for the local demo")
        model = values.get("MLAG_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"
        default_base_url = "http://127.0.0.1:11434" if provider == "ollama" else "https://generativelanguage.googleapis.com/v1beta/openai/"
        base_url = _validate_provider_base_url(
            values.get("MLAG_PROVIDER_BASE_URL", default_base_url), mode, provider,
        )
        api_key = values.get("MLAG_GEMINI_API_KEY", "").strip() or None
        if mode == "real" and provider == "gemini" and not api_key:
            raise ConfigError("MLAG_GEMINI_API_KEY is required for MLAG_MODE=real")

        data_dir = Path(values.get("MLAG_DATA_DIR", "./data")).expanduser().resolve()
        allowed_root = Path(values.get("MLAG_ALLOWED_ROOT", "./workspace")).expanduser().resolve()
        if data_dir == allowed_root or allowed_root.is_relative_to(data_dir):
            raise ConfigError("MLAG_ALLOWED_ROOT must not contain the application data directory")
        fx = _decimal(values.get("MLAG_FX_INR_PER_USD", "95"), "MLAG_FX_INR_PER_USD", "0.01", "100000")
        monthly_inr = _decimal(values.get("MLAG_MONTHLY_BUDGET_INR", "3500"), "MLAG_MONTHLY_BUDGET_INR", "0", "100000000")
        budget_usd_micros = int((monthly_inr / fx * Decimal(1_000_000)).to_integral_value())
        return cls(
            auth_token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            host=host,
            port=_int(values.get("MLAG_PORT", "8787"), "MLAG_PORT", 1024, 65535),
            trusted_hosts=trusted_hosts,
            mode=mode,
            provider=provider,
            model=model,
            provider_base_url=base_url,
            gemini_api_key=api_key,
            allow_remote_personal_data=_bool(values.get("MLAG_ALLOW_REMOTE_PERSONAL_DATA", "false"), "MLAG_ALLOW_REMOTE_PERSONAL_DATA"),
            data_dir=data_dir,
            allowed_root=allowed_root,
            monthly_budget_usd_micros=budget_usd_micros,
            fx_inr_per_usd=fx,
            input_price_usd_per_million=_decimal(values.get("MLAG_INPUT_PRICE_USD_PER_MILLION", "0.75"), "MLAG_INPUT_PRICE_USD_PER_MILLION", "0", "100000"),
            output_price_usd_per_million=_decimal(values.get("MLAG_OUTPUT_PRICE_USD_PER_MILLION", "3.75"), "MLAG_OUTPUT_PRICE_USD_PER_MILLION", "0", "100000"),
            max_input_tokens=_int(values.get("MLAG_MAX_INPUT_TOKENS", "12000"), "MLAG_MAX_INPUT_TOKENS", 256, 200000),
            max_output_tokens=_int(values.get("MLAG_MAX_OUTPUT_TOKENS", "2048"), "MLAG_MAX_OUTPUT_TOKENS", 128, 32000),
            max_message_chars=_int(values.get("MLAG_MAX_MESSAGE_CHARS", "12000"), "MLAG_MAX_MESSAGE_CHARS", 64, 100000),
            max_context_messages=_int(values.get("MLAG_MAX_CONTEXT_MESSAGES", "20"), "MLAG_MAX_CONTEXT_MESSAGES", 2, 100),
            max_memory_chars=_int(values.get("MLAG_MAX_MEMORY_CHARS", "2000"), "MLAG_MAX_MEMORY_CHARS", 64, 20000),
            max_file_bytes=_int(values.get("MLAG_MAX_FILE_BYTES", "1048576"), "MLAG_MAX_FILE_BYTES", 1024, 100000000),
            max_fetch_bytes=_int(values.get("MLAG_MAX_FETCH_BYTES", "1048576"), "MLAG_MAX_FETCH_BYTES", 1024, 100000000),
            fetch_timeout_seconds=_int(values.get("MLAG_FETCH_TIMEOUT_SECONDS", "10"), "MLAG_FETCH_TIMEOUT_SECONDS", 1, 60),
            scheduler_interval_seconds=_int(values.get("MLAG_SCHEDULER_INTERVAL_SECONDS", "30"), "MLAG_SCHEDULER_INTERVAL_SECONDS", 1, 3600),
        )

    @classmethod
    def from_env(cls, path: Path = Path(".env"), environ: Mapping[str, str] | None = None) -> "Config":
        return cls.from_report(load_environment(path, environ))

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.allowed_root.mkdir(parents=True, exist_ok=True)
