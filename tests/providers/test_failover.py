import httpx
from openai import APIStatusError
import pytest

from providers.failover import (
    fallback_model_for,
    fallback_provider_for,
    is_failover_eligible_error,
)
from providers.exceptions import ProviderFailoverSignal


def _status_error(status: int, body: dict | None = None) -> APIStatusError:
    request = httpx.Request("POST", "https://example.test/v1")
    response = httpx.Response(status, request=request)
    error = APIStatusError(
        f"HTTP {status}",
        response=response,
        body=body,
    )
    return error


def test_open_router_falls_back_to_groq():
    assert fallback_provider_for("open_router") == "groq"
    assert fallback_model_for("open_router") == "groq/openai/gpt-oss-120b"


def test_groq_falls_back_to_open_router():
    assert fallback_provider_for("groq") == "open_router"
    assert fallback_model_for("groq") == "open_router/openrouter/free"


@pytest.mark.parametrize("status", [429])
def test_429_is_failover_eligible(status: int):
    assert is_failover_eligible_error(_status_error(status))


def test_groq_413_rate_limit_exceeded_is_failover_eligible():
    error = _status_error(
        413,
        {
            "error": {
                "message": "TPM exceeded",
                "code": "rate_limit_exceeded",
            }
        },
    )
    assert is_failover_eligible_error(error)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 502, 503, 504])
def test_other_errors_do_not_trigger_failover(status: int):
    assert not is_failover_eligible_error(_status_error(status))


def test_failover_signal_is_internal_exception():
    cause = _status_error(429)
    signal = ProviderFailoverSignal("groq", cause)

    assert signal.provider_id == "groq"
    assert signal.cause is cause
