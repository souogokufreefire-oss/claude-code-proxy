from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from providers.nvidia_nim import NvidiaNimProvider

app = create_app()

# Mock provider
mock_provider = MagicMock(spec=NvidiaNimProvider)

# Track stream_response calls for test_model_mapping
_stream_response_calls: list = []


async def _mock_stream_response(*args, **kwargs):
    """Minimal async generator for streaming tests."""
    _stream_response_calls.append((args, kwargs))
    yield "event: message_start\ndata: {}\n\n"
    yield "[DONE]\n\n"


mock_provider.stream_response = _mock_stream_response


@pytest.fixture(scope="module")
def client():
    """HTTP client with provider resolution stubbed; patch only for this file."""
    with (
        patch("api.dependencies.resolve_provider", return_value=mock_provider),
        TestClient(app) as test_client,
    ):
        yield test_client


def test_root(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_models_list(client: TestClient):
    response = client.get("/v1/models")
    assert response.status_code == 200
    data = response.json()
    assert data["has_more"] is False
    ids = [item["id"] for item in data["data"]]
    assert "claude-sonnet-4-20250514" in ids
    assert data["first_id"] == ids[0]
    assert data["last_id"] == ids[-1]


def test_probe_endpoints_return_204_with_allow_headers(client: TestClient):
    responses = [
        client.head("/"),
        client.options("/"),
        client.head("/health"),
        client.options("/health"),
        client.head("/v1/messages"),
        client.options("/v1/messages"),
        client.head("/v1/messages/count_tokens"),
        client.options("/v1/messages/count_tokens"),
    ]

    for response in responses:
        assert response.status_code == 204
        assert "Allow" in response.headers


def test_create_message_stream(client: TestClient):
    """Create message returns streaming response."""
    payload = {
        "model": "claude-3-sonnet",
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 100,
        "stream": True,
    }
    response = client.post("/v1/messages", json=payload)
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    content = b"".join(response.iter_bytes())
    assert b"message_start" in content or b"event:" in content


def test_model_mapping(client: TestClient):
    # Test Haiku mapping
    _stream_response_calls.clear()
    payload_haiku = {
        "model": "claude-3-haiku-20240307",
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 100,
        "stream": True,
    }
    client.post("/v1/messages", json=payload_haiku)
    assert len(_stream_response_calls) == 1
    args = _stream_response_calls[0][0]
    kwargs = _stream_response_calls[0][1]
    assert args[0].model != "claude-3-haiku-20240307"
    assert kwargs["thinking_enabled"] is True


def test_auth_token_model_suffix_overrides_request_model(client: TestClient):
    _stream_response_calls.clear()
    payload = {
        "model": "claude-3-haiku-20240307",
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 100,
        "stream": True,
    }

    response = client.post(
        "/v1/messages",
        json=payload,
        headers={"x-api-key": "freecc:open_router/deepseek/deepseek-r1"},
    )

    assert response.status_code == 200
    args = _stream_response_calls[0][0]
    assert args[0].model == "deepseek/deepseek-r1"


def test_error_fallbacks(client: TestClient):
    from providers.exceptions import (
        AuthenticationError,
        OverloadedError,
        RateLimitError,
    )

    base_payload = {
        "model": "test",
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 10,
        "stream": True,
    }

    def _raise_auth(*args, **kwargs):
        raise AuthenticationError("Invalid Key")

    def _raise_rate_limit(*args, **kwargs):
        raise RateLimitError("Too Many Requests")

    def _raise_overloaded(*args, **kwargs):
        raise OverloadedError("Server Overloaded")

    # 1. Authentication Error (401)
    mock_provider.stream_response = _raise_auth
    response = client.post("/v1/messages", json=base_payload)
    assert response.status_code == 401
    assert response.json()["error"]["type"] == "authentication_error"

    # 2. Rate Limit (429)
    mock_provider.stream_response = _raise_rate_limit
    response = client.post("/v1/messages", json=base_payload)
    assert response.status_code == 429
    assert response.json()["error"]["type"] == "rate_limit_error"

    # 3. Overloaded (529)
    mock_provider.stream_response = _raise_overloaded
    response = client.post("/v1/messages", json=base_payload)
    assert response.status_code == 529
    assert response.json()["error"]["type"] == "overloaded_error"

    # Reset for subsequent tests
    mock_provider.stream_response = _mock_stream_response


def test_generic_exception_returns_500(client: TestClient):
    """Non-ProviderError exceptions are caught and returned as HTTPException(500)."""

    def _raise_runtime(*args, **kwargs):
        raise RuntimeError("unexpected crash")

    mock_provider.stream_response = _raise_runtime
    response = client.post(
        "/v1/messages",
        json={
            "model": "test",
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 10,
            "stream": True,
        },
    )
    assert response.status_code == 500
    mock_provider.stream_response = _mock_stream_response


def test_generic_exception_with_status_code(client: TestClient):
    """Unexpected errors always map to HTTP 500 (ignore ad-hoc status_code attrs)."""

    class ExceptionWithStatus(RuntimeError):
        def __init__(self, msg: str, status_code: int = 500):
            super().__init__(msg)
            self.status_code = status_code

    def _raise_with_status(*args, **kwargs):
        raise ExceptionWithStatus("bad gateway", 502)

    mock_provider.stream_response = _raise_with_status
    response = client.post(
        "/v1/messages",
        json={
            "model": "test",
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 10,
            "stream": True,
        },
    )
    assert response.status_code == 500
    mock_provider.stream_response = _mock_stream_response


def test_generic_exception_empty_message_returns_non_empty_detail(client: TestClient):
    """Exceptions with empty __str__ still return a readable HTTP detail."""

    class SilentError(RuntimeError):
        def __str__(self):
            return ""

    def _raise_silent(*args, **kwargs):
        raise SilentError()

    mock_provider.stream_response = _raise_silent
    response = client.post(
        "/v1/messages",
        json={
            "model": "test",
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 10,
            "stream": True,
        },
    )
    assert response.status_code == 500
    assert response.json()["detail"] != ""
    mock_provider.stream_response = _mock_stream_response


def test_count_tokens_endpoint(client: TestClient):
    """count_tokens endpoint returns token count."""
    response = client.post(
        "/v1/messages/count_tokens",
        json={"model": "test", "messages": [{"role": "user", "content": "Hello"}]},
    )
    assert response.status_code == 200
    assert "input_tokens" in response.json()


def test_stop_endpoint_removed_from_proxy_only_runtime(client: TestClient):
    """POST /stop is not part of the proxy-only HTTP surface."""
    response = client.post("/stop")
    assert response.status_code == 404


async def _rich_sse_stream(*args, **kwargs):
    """Async generator emitting a complete Anthropic-style SSE response."""
    _stream_response_calls.append((args, kwargs))
    yield (
        'event: message_start\ndata: {"type": "message_start", "message": '
        '{"id": "msg_ns_1", "type": "message", "role": "assistant", '
        '"content": [], "model": "claude-3-sonnet", "stop_reason": null, '
        '"stop_sequence": null, "usage": {"input_tokens": 7, "output_tokens": 0}}}\n\n'
    )
    yield (
        'event: content_block_start\ndata: {"type": "content_block_start", '
        '"index": 0, "content_block": {"type": "text", "text": ""}}\n\n'
    )
    yield (
        'event: content_block_delta\ndata: {"type": "content_block_delta", '
        '"index": 0, "delta": {"type": "text_delta", "text": "Hello non-streaming"}}\n\n'
    )
    yield 'event: content_block_stop\ndata: {"type": "content_block_stop", "index": 0}\n\n'
    yield (
        'event: message_delta\ndata: {"type": "message_delta", "delta": '
        '{"stop_reason": "end_turn", "stop_sequence": null}, '
        '"usage": {"input_tokens": 7, "output_tokens": 19}}\n\n'
    )
    yield 'event: message_stop\ndata: {"type": "message_stop"}\n\n'


def _non_streaming_payload() -> dict:
    return {
        "model": "test",
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 10,
        "stream": False,
    }


def test_create_message_non_streaming_returns_json(client: TestClient):
    """stream:false must return a JSON MessagesResponse, not SSE (PR #977)."""
    mock_provider.stream_response = _rich_sse_stream
    try:
        response = client.post("/v1/messages", json=_non_streaming_payload())
    finally:
        mock_provider.stream_response = _mock_stream_response

    assert response.status_code == 200
    assert "application/json" in response.headers.get("content-type", "")
    data = response.json()
    assert data["type"] == "message"
    assert data["id"] == "msg_ns_1"
    assert data["content"][0]["text"] == "Hello non-streaming"
    assert data["usage"]["input_tokens"] == 7
    assert data["usage"]["output_tokens"] == 19
    assert data["stop_reason"] == "end_turn"


def test_create_message_default_stream_stays_sse(client: TestClient):
    """Clients that omit ``stream`` keep the existing SSE behavior."""
    payload = _non_streaming_payload()
    payload.pop("stream")
    response = client.post("/v1/messages", json=payload)
    assert "text/event-stream" in response.headers.get("content-type", "")


def test_create_message_non_streaming_error_event(client: TestClient):
    """A mid-stream ``event: error`` maps to a JSON provider error."""

    async def _error_stream(*args, **kwargs):
        yield 'event: message_start\ndata: {"type": "message_start", "message": {}}\n\n'
        yield (
            'event: error\ndata: {"type": "error", "error": '
            '{"type": "api_error", "message": "upstream broke"}}\n\n'
        )

    mock_provider.stream_response = _error_stream
    try:
        response = client.post("/v1/messages", json=_non_streaming_payload())
    finally:
        mock_provider.stream_response = _mock_stream_response

    assert response.status_code == 502
    assert response.json()["error"]["type"] == "api_error"
    assert response.json()["error"]["message"] == "upstream broke"
