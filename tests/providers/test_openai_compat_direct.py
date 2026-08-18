"""Direct tests for the shared OpenAI chat-completions transport (openai_compat.py).

Covers transport machinery that provider-specific suites do not exercise:
the extra-reasoning hook, the no-key-pool retry path, key rotation on
key-scoped errors, usage-based key exhaustion, and learned output caps.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import openai
import pytest

from core.anthropic.stream_contracts import (
    assert_anthropic_stream_contract,
    parse_sse_text,
)
from providers.base import ProviderConfig
from providers.openai_compat import OpenAIChatTransport
from tests.provider_request_mocks import make_openai_compat_stream_request


class DirectOpenAIChatTransport(OpenAIChatTransport):
    """Minimal concrete transport: no provider-specific body logic."""

    def __init__(
        self,
        config: ProviderConfig,
        *,
        provider_name: str = "DIRECT_TEST",
        base_url: str = "https://direct.test/v1",
    ):
        super().__init__(
            config,
            provider_name=provider_name,
            base_url=base_url,
            api_key=config.api_key,
        )

    def _build_request_body(self, request, thinking_enabled: bool | None = None):
        return {"model": request.model, "messages": []}


class ExtraReasoningTransport(DirectOpenAIChatTransport):
    """Overrides the designed extra-reasoning hook (e.g. OpenRouter-style fields)."""

    def _handle_extra_reasoning(self, delta, sse, *, thinking_enabled):
        extra = getattr(delta, "extra_reasoning", None)
        if extra and thinking_enabled:
            yield from sse.ensure_thinking_block()
            yield sse.emit_thinking_delta(extra)


class RetryBodyTransport(DirectOpenAIChatTransport):
    """Overrides the designed one-shot retry hook."""

    def _get_retry_request_body(self, error: Exception, body: dict) -> dict | None:
        if isinstance(error, RuntimeError):
            return {**body, "retried": True}
        return None


@pytest.fixture(autouse=True)
def mock_rate_limiter():
    @asynccontextmanager
    async def _slot():
        yield

    with patch("providers.openai_compat.GlobalRateLimiter") as mock:
        instance = mock.get_scoped_instance.return_value

        async def _passthrough(fn, *args, **kwargs):
            return await fn(*args, **kwargs)

        instance.execute_with_retry = AsyncMock(side_effect=_passthrough)
        instance.concurrency_slot.side_effect = _slot
        yield instance


@pytest.fixture
def direct_config():
    return ProviderConfig(
        api_key="key1",
        base_url="https://direct.test/v1",
        rate_limit=10,
        rate_window=60,
        enable_thinking=True,
    )


def _make_provider(
    config: ProviderConfig, transport_type=DirectOpenAIChatTransport
) -> DirectOpenAIChatTransport:
    with (
        patch("providers.openai_compat.httpx.AsyncClient"),
        patch("providers.openai_compat.AsyncOpenAI"),
    ):
        return transport_type(config)


def _auth_error() -> openai.AuthenticationError:
    return openai.AuthenticationError(
        "401 Invalid API key",
        response=httpx.Response(
            401,
            request=httpx.Request("POST", "https://direct.test/v1/chat/completions"),
        ),
        body={"error": {"message": "Invalid API key"}},
    )


def _text_chunk(*, text: str, finish_reason: str | None = None) -> MagicMock:
    delta = MagicMock()
    delta.content = text
    delta.tool_calls = None
    delta.reasoning_content = None
    return MagicMock(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)],
        usage=None,
    )


@pytest.mark.asyncio
async def test_extra_reasoning_hook_emits_thinking_delta(
    direct_config, mock_rate_limiter
):
    """The extra-reasoning hook yields thinking deltas inside the stream loop."""
    provider = _make_provider(direct_config, ExtraReasoningTransport)

    delta = MagicMock()
    delta.content = "answer"
    delta.tool_calls = None
    delta.reasoning_content = None
    delta.extra_reasoning = "EXTRA-REASONING"
    chunk = MagicMock(
        choices=[SimpleNamespace(delta=delta, finish_reason="stop")],
        usage=SimpleNamespace(completion_tokens=5, prompt_tokens=10),
    )

    async def mock_stream():
        yield chunk

    request = make_openai_compat_stream_request()
    with patch.object(
        provider._client.chat.completions, "create", new_callable=AsyncMock
    ) as mock_create:
        mock_create.return_value = mock_stream()
        events = [event async for event in provider.stream_response(request)]

    parsed = parse_sse_text("".join(events))
    assert_anthropic_stream_contract(parsed)
    thinking_deltas = [
        event.data.get("delta", {}).get("thinking")
        for event in parsed
        if event.event == "content_block_delta"
        and event.data.get("delta", {}).get("type") == "thinking_delta"
    ]
    assert "EXTRA-REASONING" in thinking_deltas


@pytest.mark.asyncio
async def test_extra_reasoning_hook_suppressed_when_thinking_disabled(
    direct_config, mock_rate_limiter
):
    """The hook must not emit thinking deltas when thinking is disabled."""
    config = direct_config.model_copy(update={"enable_thinking": False})
    provider = _make_provider(config, ExtraReasoningTransport)

    delta = MagicMock()
    delta.content = "answer"
    delta.tool_calls = None
    delta.reasoning_content = None
    delta.extra_reasoning = "EXTRA-REASONING"
    chunk = MagicMock(
        choices=[SimpleNamespace(delta=delta, finish_reason="stop")],
        usage=SimpleNamespace(completion_tokens=5, prompt_tokens=10),
    )

    async def mock_stream():
        yield chunk

    request = make_openai_compat_stream_request()
    with patch.object(
        provider._client.chat.completions, "create", new_callable=AsyncMock
    ) as mock_create:
        mock_create.return_value = mock_stream()
        events = [event async for event in provider.stream_response(request)]

    blob = "".join(events)
    assert "EXTRA-REASONING" not in blob


@pytest.mark.asyncio
async def test_create_stream_retries_once_with_override_body(
    direct_config, mock_rate_limiter
):
    """Without fallback keys, a single retry uses the override body hook."""
    provider = _make_provider(direct_config, RetryBodyTransport)
    body = {"model": "m", "messages": []}

    async def mock_stream():
        yield _text_chunk(text="ok", finish_reason="stop")

    with patch.object(
        provider._client.chat.completions, "create", new_callable=AsyncMock
    ) as mock_create:
        mock_create.side_effect = [RuntimeError("boom"), mock_stream()]
        _stream, used_body = await provider._create_stream(body)

    assert create_await_kwargs(mock_create, 0)["model"] == "m"
    assert create_await_kwargs(mock_create, 1)["retried"] is True
    assert used_body["retried"] is True
    assert create_await_kwargs(mock_create, 1)["stream"] is True


def create_await_kwargs(mock_create: AsyncMock, index: int) -> dict[str, object]:
    return dict(mock_create.await_args_list[index].kwargs)


@pytest.mark.asyncio
async def test_create_stream_with_key_fallback_rotates_on_auth_error(
    direct_config, mock_rate_limiter
):
    """Key-scoped AuthenticationError rotates to the next configured key."""
    config = direct_config.model_copy(update={"api_keys": ("key1", "key2")})
    provider = _make_provider(config)

    async def mock_stream():
        yield _text_chunk(text="ok", finish_reason="stop")

    with patch.object(
        provider._client.chat.completions, "create", new_callable=AsyncMock
    ) as mock_create:
        mock_create.side_effect = [_auth_error(), mock_stream()]
        stream, _body = await provider._create_stream({"model": "m", "messages": []})

    assert mock_create.await_count == 2
    assert provider._api_key == "key2"
    assert provider._client.api_key == "key2"
    assert [event async for event in stream]


@pytest.mark.asyncio
async def test_create_stream_raises_when_no_key_fallback_available(
    direct_config, mock_rate_limiter
):
    """A single-key transport surfaces the key-scoped error instead of hiding it."""
    provider = _make_provider(direct_config)

    with patch.object(
        provider._client.chat.completions, "create", new_callable=AsyncMock
    ) as mock_create:
        mock_create.side_effect = [_auth_error()]
        with pytest.raises(openai.AuthenticationError):
            await provider._create_stream({"model": "m", "messages": []})

    assert mock_create.await_count == 1


@pytest.mark.asyncio
async def test_create_stream_raises_non_key_scoped_error_without_rotation(
    direct_config, mock_rate_limiter
):
    """Non-key-scoped errors must not rotate keys or retry."""
    config = direct_config.model_copy(update={"api_keys": ("key1", "key2")})
    provider = _make_provider(config)

    with patch.object(
        provider._client.chat.completions, "create", new_callable=AsyncMock
    ) as mock_create:
        mock_create.side_effect = [RuntimeError("boom")]
        with pytest.raises(RuntimeError):
            await provider._create_stream({"model": "m", "messages": []})

    assert mock_create.await_count == 1
    assert provider._api_key == "key1"


@pytest.mark.asyncio
async def test_record_api_key_success_rotates_exhausted_key(
    direct_config, mock_rate_limiter
):
    """Usage-limit exhaustion rotates after a successful request."""
    config = direct_config.model_copy(
        update={"api_keys": ("key1", "key2"), "key_usage_limit": 1}
    )
    provider = _make_provider(config)

    provider._record_api_key_success()

    assert provider._api_key == "key2"
    assert provider._client.api_key == "key2"


@pytest.mark.asyncio
async def test_apply_learned_output_cap_clamps_body(direct_config, mock_rate_limiter):
    """A learned per-model cap is applied proactively on later requests."""
    provider = _make_provider(direct_config)
    provider._model_output_caps["m"] = 100
    body = {"model": "m", "max_tokens": 4096, "messages": []}

    async def mock_stream():
        yield _text_chunk(text="ok", finish_reason="stop")

    with patch.object(
        provider._client.chat.completions, "create", new_callable=AsyncMock
    ) as mock_create:
        mock_create.return_value = mock_stream()
        stream, used_body = await provider._create_stream(body)

    assert used_body["max_tokens"] == 100
    assert create_await_kwargs(mock_create, 0)["max_tokens"] == 100
    assert [event async for event in stream]
