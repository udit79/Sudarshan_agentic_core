"""Safe environment configuration for optional LinkedIn/social connectors.

The configuration object deliberately stores credential presence, never the
credential values themselves.  Provider adapters can use their own secret
manager at execution time; safe projections and cache metadata should use
``to_safe_dict`` only.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
import re
from typing import Mapping


_PROVIDER_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_DEFAULT_PROVIDER = "manual"
_DEFAULT_CACHE_TTL_SECONDS = 900
_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_MAX_RETRIES = 2
_DEFAULT_RATE_LIMIT_PER_MINUTE = 30


class SocialConfigurationError(ValueError):
    """Raised when optional social configuration has an invalid shape."""


@dataclass(frozen=True, slots=True)
class SocialProviderConfig:
    """Validated, safe configuration for the optional social boundary."""

    provider: str = _DEFAULT_PROVIDER
    cache_ttl_seconds: int = _DEFAULT_CACHE_TTL_SECONDS
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    max_retries: int = _DEFAULT_MAX_RETRIES
    rate_limit_per_minute: int = _DEFAULT_RATE_LIMIT_PER_MINUTE
    connection_id: str | None = None
    credentials_configured: bool = False
    effective_provider: str = _DEFAULT_PROVIDER
    fallback_reason: str | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "SocialProviderConfig":
        values = os.environ if environ is None else environ
        provider = _text(values.get("SUDARSHAN_LINKEDIN_PROVIDER"), _DEFAULT_PROVIDER).lower()
        if not _PROVIDER_PATTERN.fullmatch(provider):
            raise SocialConfigurationError(
                "SUDARSHAN_LINKEDIN_PROVIDER must contain only lowercase letters, digits, '.', '_' or '-'")

        cache_ttl = _integer(
            "SUDARSHAN_LINKEDIN_CACHE_TTL_SECONDS",
            values.get("SUDARSHAN_LINKEDIN_CACHE_TTL_SECONDS"),
            _DEFAULT_CACHE_TTL_SECONDS,
            minimum=0,
        )
        timeout = _number(
            "SUDARSHAN_LINKEDIN_TIMEOUT_SECONDS",
            values.get("SUDARSHAN_LINKEDIN_TIMEOUT_SECONDS"),
            _DEFAULT_TIMEOUT_SECONDS,
            minimum=0.1,
            maximum=900.0,
        )
        max_retries = _integer(
            "SUDARSHAN_LINKEDIN_MAX_RETRIES",
            values.get("SUDARSHAN_LINKEDIN_MAX_RETRIES"),
            _DEFAULT_MAX_RETRIES,
            minimum=0,
            maximum=10,
        )
        rate_limit = _integer(
            "SUDARSHAN_LINKEDIN_RATE_LIMIT_PER_MINUTE",
            values.get("SUDARSHAN_LINKEDIN_RATE_LIMIT_PER_MINUTE"),
            _DEFAULT_RATE_LIMIT_PER_MINUTE,
            minimum=1,
        )

        connection_id = _optional_text(values.get("SUDARSHAN_LINKEDIN_CONNECTION_ID"), maximum=200)
        has_secret = any(
            _optional_text(values.get(name), maximum=4096)
            for name in (
                "SUDARSHAN_LINKEDIN_ACCESS_TOKEN",
                "SUDARSHAN_LINKEDIN_CLIENT_SECRET",
            )
        )
        credentials_configured = provider == _DEFAULT_PROVIDER or has_secret
        effective_provider = provider if credentials_configured else _DEFAULT_PROVIDER
        fallback_reason = None if credentials_configured else "credentials_missing"

        return cls(
            provider=provider,
            cache_ttl_seconds=cache_ttl,
            timeout_seconds=timeout,
            max_retries=max_retries,
            rate_limit_per_minute=rate_limit,
            connection_id=connection_id,
            credentials_configured=credentials_configured,
            effective_provider=effective_provider,
            fallback_reason=fallback_reason,
        )

    def to_safe_dict(self) -> dict[str, object | None]:
        """Return the only configuration shape suitable for logs/projections."""

        return {
            "provider": self.provider,
            "effective_provider": self.effective_provider,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "connection_id": self.connection_id,
            "credentials_configured": self.credentials_configured,
            "fallback_reason": self.fallback_reason,
        }


def _text(value: str | None, default: str) -> str:
    return str(value).strip() if value is not None and str(value).strip() else default


def _optional_text(value: str | None, *, maximum: int) -> str | None:
    text = str(value).strip() if value is not None else ""
    if len(text) > maximum:
        raise SocialConfigurationError(f"social configuration value exceeds {maximum} characters")
    return text or None


def _integer(name: str, value: str | None, default: int, *, minimum: int, maximum: int | None = None) -> int:
    raw = str(value).strip() if value is not None and str(value).strip() else str(default)
    if not raw.isdigit():
        raise SocialConfigurationError(f"{name} must be an integer >= {minimum}")
    parsed = int(raw)
    if parsed < minimum or (maximum is not None and parsed > maximum):
        suffix = f" and <= {maximum}" if maximum is not None else ""
        raise SocialConfigurationError(f"{name} must be an integer >= {minimum}{suffix}")
    return parsed


def _number(name: str, value: str | None, default: float, *, minimum: float, maximum: float) -> float:
    raw = str(value).strip() if value is not None and str(value).strip() else str(default)
    try:
        parsed = float(raw)
    except (TypeError, ValueError) as exc:
        raise SocialConfigurationError(f"{name} must be a number") from exc
    if not math.isfinite(parsed) or parsed < minimum or parsed > maximum:
        raise SocialConfigurationError(f"{name} must be between {minimum} and {maximum}")
    return parsed


__all__ = ["SocialConfigurationError", "SocialProviderConfig"]
