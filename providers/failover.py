"""Cross-provider failover for the configured OpenRouter/Groq pair."""

from __future__ import annotations

import contextlib
import json
from contextvars import ContextVar
from typing import Any

PRIMARY_FAILOVER_PROVIDER: ContextVar[str | None] = ContextVar(
    "primary_failover_provider",
    default=None,
)

FALLBACK_PROVIDER_BY_PROVIDER: dict[str, str] = {
    "open_router": "groq",
    "groq": "open_router",
}

FALLBACK_MODEL_BY_PROVIDER: dict[str, str] = {
    "open_router": "groq/openai/gpt-oss-120b",
    "groq": "open_router/openrouter/free",
}


def is_failover_provider(provider_id: str) -> bool:
    return provider_id.lower() in FALLBACK_PROVIDER_BY_PROVIDER


def fallback_provider_for(provider_id: str) -> str | None:
    return FALLBACK_PROVIDER_BY_PROVIDER.get(provider_id.lower())


def fallback_model_for(provider_id: str) -> str | None:
    return FALLBACK_MODEL_BY_PROVIDER.get(provider_id.lower())


def begin_primary_failover(provider_id: str):
    return PRIMARY_FAILOVER_PROVIDER.set(provider_id.lower())


def end_primary_failover(token) -> None:
    PRIMARY_FAILOVER_PROVIDER.reset(token)


def should_signal_failover(provider_id: str) -> bool:
    normalized = provider_id.lower()
    return (
        normalized in FALLBACK_PROVIDER_BY_PROVIDER
        and PRIMARY_FAILOVER_PROVIDER.get() == normalized
    )


def error_status_code(error: Exception) -> int | None:
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        return status

    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return status

    return None


def _error_text(error: Exception) -> str:
    parts = [str(error)]

    body: Any = getattr(error, "body", None)
    if body is not None:
        try:
            parts.append(json.dumps(body, default=str))
        except Exception:
            parts.append(str(body))

    response = getattr(error, "response", None)
    if response is not None:
        with contextlib.suppress(Exception):
            parts.append(response.text)

    return " ".join(parts).lower()


def is_failover_eligible_error(error: Exception) -> bool:
    """Return True only for quota/rate-limit failures we can safely fail over."""
    status = error_status_code(error)

    if status == 429:
        return True

    # Groq can report TPM exhaustion as HTTP 413 with
    # error.code=rate_limit_exceeded.
    return status == 413 and "rate_limit_exceeded" in _error_text(error)
