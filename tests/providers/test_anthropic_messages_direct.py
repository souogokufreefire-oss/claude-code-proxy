"""Direct tests for native Anthropic Messages transport edge behavior.

Covers event chunk mode, capped error-body preview logging, and the
cross-provider failover signal gate.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from providers.anthropic_messages import AnthropicMessagesTransport
from providers.base import ProviderConfig
from providers.exceptions import ProviderFailoverSignal
from providers.failover import begin_primary_failover, end_primary_failover
from tests.stream_contract import assert_canonical_stream_error_envelope


class EventModeProvider(AnthropicMessagesTransport):
    stream_chunk_mode = "event"

    def __init__(self, config: ProviderConfig, *, provider_name: str = "TEST_NATIVE"):
        super().__init__(
            config,
            provider_name=provider_name,
            default_base_url="https://example.test/v1",
        )


class NativeProvider(AnthropicMessagesTransport):
    def __init__(self, config: ProviderConfig, *, provider_name: str = "TEST_NATIVE"):
        super().__init__(
            config,
            provider_name=provider_name,
            default_base_url="https://example.test/v1",
        )

    def _request_headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json", "X-Test": "1"}


class MockRequest:
    model = "test-model"

    def __init__(self, *, thinking_enabled: bool = True):
        self.thinking = MagicMockLike(thinking_enabled)
        self._body = {
            "model": self.model,
            "messages": [{"role": "user", "content": "Hello"}],
            "thinking": {"enabled": thinking_enabled},
        }

    def model_dump(self, exclude_none=True):
        return dict(self._body)


class MagicMockLike:
    def __init__(self, enabled: bool):
        self.enabled = enabled


class FakeResponse:
    def __init__(
        self,
        *,
        status_code=200,
        lines=None,
        text="",
    ):
        self.status_code = status_code
        self._lines = lines or []
        self._text = text
        self.is_closed = False
        self.request = httpx.Request("POST", "https://example.test/v1/messages")
        self.headers = httpx.Headers()

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        return self._text.encode()

    def raise_for_status(self):
        response = httpx.Response(
            self.status_code,
            request=self.request,
            text=self._text,
        )
        response.raise_for_status()

    async def aclose(self):
        self.is_closed = True

    async def aiter_bytes(self, chunk_size: int = 65_536):
        data = self._text.encode("utf-8")
        for offset in range(0, len(data), chunk_size):
            yield data[offset : offset + chunk_size]


@pytest.fixture
def provider_config():
    return ProviderConfig(
        api_key="test-key",
        rate_limit=10,
        rate_window=60,
        http_read_timeout=600.0,
        http_write_timeout=15.0,
        http_connect_timeout=5.0,
    )


@pytest.fixture(autouse=True)
def mock_rate_limiter():
    @asynccontextmanager
    async def _slot():
        yield

    with patch("providers.anthropic_messages.GlobalRateLimiter") as mock:
        instance = mock.get_scoped_instance.return_value

        async def _passthrough(fn, *args, **kwargs):
            return await fn(*args)

        instance.execute_with_retry = AsyncMock(side_effect=_passthrough)
        instance.concurrency_slot.side_effect = _slot
        yield instance


def _make_provider(
    config: ProviderConfig,
    transport_type,
    *,
    provider_name: str = "TEST_NATIVE",
):
    with patch("httpx.AsyncClient"):
        return transport_type(config, provider_name=provider_name)


@pytest.mark.asyncio
async def test_event_chunk_mode_groups_lines_into_events(
    provider_config, mock_rate_limiter
):
    """Event chunk mode yields whole grouped SSE events, not individual lines."""
    provider = _make_provider(provider_config, EventModeProvider)
    response = FakeResponse(
        lines=[
            "event: message_start",
            'data: {"type":"message_start"}',
            "",
            "event: message_stop",
            'data: {"type":"message_stop"}',
            "",
        ]
    )
    request = MockRequest()

    with patch.object(provider._client, "send", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = response
        events = [event async for event in provider.stream_response(request)]

    blob = "".join(events)
    assert 'event: message_start\ndata: {"type":"message_start"}\n\n' in blob
    assert 'event: message_stop\ndata: {"type":"message_stop"}\n\n' in blob
    assert "event: message_start" in blob


@pytest.mark.asyncio
async def test_event_chunk_mode_skips_block_policy_state(provider_config):
    """Event mode must not build a line-policy state for event transformation."""
    provider = _make_provider(provider_config, EventModeProvider)

    assert provider.stream_chunk_mode == "event"
    assert provider._new_stream_state(MockRequest(), thinking_enabled=True) is None


@pytest.mark.asyncio
async def test_read_error_body_preview_truncates_at_cap(provider_config):
    """Error-body previews are capped to max_bytes with a truncation flag."""
    provider = _make_provider(provider_config, NativeProvider)
    response = FakeResponse(text="x" * 5000)

    preview, truncated = await provider._read_error_body_preview(response, 100)

    assert preview == b"x" * 100
    assert truncated is True


@pytest.mark.asyncio
async def test_read_error_body_preview_under_cap_not_truncated(provider_config):
    """Small error bodies are returned whole without a truncation flag."""
    provider = _make_provider(provider_config, NativeProvider)
    response = FakeResponse(text="short error")

    preview, truncated = await provider._read_error_body_preview(response, 100)

    assert preview == b"short error"
    assert truncated is False


@pytest.mark.asyncio
async def test_failover_signal_raised_before_any_event_when_eligible(
    provider_config, mock_rate_limiter
):
    """An eligible 429 in an active primary-failover context raises the signal."""
    provider = _make_provider(
        provider_config, NativeProvider, provider_name="open_router"
    )
    request = MockRequest()
    response = FakeResponse(status_code=429, text="rate limited")

    token = begin_primary_failover("open_router")
    try:
        with patch.object(
            provider._client, "send", new_callable=AsyncMock
        ) as mock_send:
            mock_send.return_value = response
            with pytest.raises(ProviderFailoverSignal):
                [event async for event in provider.stream_response(request)]
    finally:
        end_primary_failover(token)

    assert response.is_closed


@pytest.mark.asyncio
async def test_failover_not_signaled_outside_primary_context(
    provider_config, mock_rate_limiter
):
    """Without an active failover context the same 429 yields an error envelope."""
    provider = _make_provider(
        provider_config, NativeProvider, provider_name="open_router"
    )
    request = MockRequest()
    response = FakeResponse(status_code=429, text="rate limited")

    with patch.object(provider._client, "send", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = response
        events = [event async for event in provider.stream_response(request)]

    assert_canonical_stream_error_envelope(
        events, user_message_substr="Provider rate limit reached"
    )
    assert response.is_closed
