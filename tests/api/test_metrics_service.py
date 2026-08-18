"""Integration tests for per-provider metrics recording in the service layer."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from api.models.anthropic import Message, MessagesRequest
from api.runtime import AppRuntime, _periodic_metrics_summary
from api.services import ClaudeProxyService
from config.settings import Settings
from core.metrics import MetricsRegistry
from providers.exceptions import ProviderFailoverSignal
from tests.api.test_web_server_tools import FixedProviderModelRouter


def _message_delta_frame(output_tokens: int) -> str:
    data = json.dumps(
        {
            "type": "message_delta",
            "usage": {"input_tokens": 10, "output_tokens": output_tokens},
        }
    )
    return f"event: message_delta\ndata: {data}\n\n"


def _make_request() -> MessagesRequest:
    return MessagesRequest(
        model="claude-3-haiku-20240307",
        max_tokens=10,
        messages=[Message(role="user", content="hello world")],
    )


def _fake_provider(*chunks: str) -> MagicMock:
    provider = MagicMock()

    async def fake_stream(*_args, **_kwargs):
        for chunk in chunks:
            yield chunk

    provider.stream_response = fake_stream
    return provider


@pytest.mark.asyncio
async def test_create_message_records_request_and_output_tokens():
    settings = Settings()
    metrics = MetricsRegistry()
    service = ClaudeProxyService(
        settings,
        provider_getter=lambda _: _fake_provider(_message_delta_frame(42)),
        model_router=FixedProviderModelRouter(settings, "open_router"),
        metrics_registry_=metrics,
    )

    response: StreamingResponse = service.create_message(_make_request())
    async for _chunk in response.body_iterator:
        pass

    entry = metrics.snapshot()["open_router"]
    assert entry.requests == 1
    assert entry.tokens_in > 0
    assert entry.tokens_out == 42
    assert entry.errors == 0
    assert entry.failovers == 0


@pytest.mark.asyncio
async def test_successful_stream_has_no_errors_recorded():
    settings = Settings()
    metrics = MetricsRegistry()
    service = ClaudeProxyService(
        settings,
        provider_getter=lambda _: _fake_provider("event: ping\ndata: {}\n\n"),
        model_router=FixedProviderModelRouter(settings, "open_router"),
        metrics_registry_=metrics,
    )

    response: StreamingResponse = service.create_message(_make_request())
    async for _chunk in response.body_iterator:
        pass

    assert metrics.snapshot()["open_router"].errors == 0


@pytest.mark.asyncio
async def test_failover_records_failover_and_secondary_result():
    settings = Settings()

    def stream_boom(*_args, **_kwargs):
        async def _gen():
            raise ProviderFailoverSignal("open_router", RuntimeError("quota"))
            yield

        return _gen()

    primary = MagicMock()
    primary.stream_response = stream_boom
    secondary = _fake_provider(_message_delta_frame(7))

    metrics = MetricsRegistry()
    service = ClaudeProxyService(
        settings,
        provider_getter=lambda pid: secondary if pid == "groq" else primary,
        metrics_registry_=metrics,
    )

    async for _event in service._stream_with_provider_failover(
        primary_stream=primary.stream_response(),
        provider_id="open_router",
        request=_make_request(),
        input_tokens=100,
        request_id="req_metrics",
        thinking_enabled=False,
    ):
        pass

    snapshot = metrics.snapshot()
    assert snapshot["open_router"].failovers == 1
    assert snapshot["open_router"].errors == 0
    assert snapshot["groq"].tokens_out == 7
    assert snapshot["groq"].requests == 1
    assert snapshot["groq"].errors == 0


@pytest.mark.asyncio
async def test_primary_error_is_recorded_and_reraises():
    settings = Settings()

    def stream_boom(*_args, **_kwargs):
        async def _gen():
            raise RuntimeError("boom")
            yield

        return _gen()

    primary = MagicMock()
    primary.stream_response = stream_boom

    metrics = MetricsRegistry()
    service = ClaudeProxyService(
        settings,
        provider_getter=lambda _: primary,
        metrics_registry_=metrics,
    )

    with pytest.raises(RuntimeError):
        async for _event in service._stream_with_provider_failover(
            primary_stream=primary.stream_response(),
            provider_id="open_router",
            request=_make_request(),
            input_tokens=100,
            request_id="req_metrics",
            thinking_enabled=False,
        ):
            pass

    snapshot = metrics.snapshot()
    assert snapshot["open_router"].errors == 1
    assert snapshot["open_router"].failovers == 0


@pytest.mark.asyncio
async def test_secondary_error_is_recorded_for_secondary():
    settings = Settings()

    def stream_boom(*_args, **_kwargs):
        async def _gen():
            raise ProviderFailoverSignal("open_router", RuntimeError("quota"))
            yield

        return _gen()

    def secondary_boom(*_args, **_kwargs):
        async def _gen():
            raise RuntimeError("secondary down")
            yield

        return _gen()

    primary = MagicMock()
    primary.stream_response = stream_boom
    secondary = MagicMock()
    secondary.stream_response = secondary_boom

    metrics = MetricsRegistry()
    service = ClaudeProxyService(
        settings,
        provider_getter=lambda pid: secondary if pid == "groq" else primary,
        metrics_registry_=metrics,
    )

    with pytest.raises(RuntimeError):
        async for _event in service._stream_with_provider_failover(
            primary_stream=primary.stream_response(),
            provider_id="open_router",
            request=_make_request(),
            input_tokens=100,
            request_id="req_metrics",
            thinking_enabled=False,
        ):
            pass

    snapshot = metrics.snapshot()
    assert snapshot["open_router"].failovers == 1
    assert snapshot["groq"].errors == 1


@pytest.mark.asyncio
async def test_periodic_metrics_summary_logs_and_cancels():
    with patch("api.runtime.metrics_registry.log_summary") as mock_log:
        task = asyncio.create_task(_periodic_metrics_summary(0.01))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert mock_log.call_count >= 1


@pytest.mark.asyncio
async def test_shutdown_logs_metrics_summary():
    app = FastAPI()
    runtime = AppRuntime.for_app(app, Settings())

    with patch("api.runtime.metrics_registry.log_summary") as mock_log:
        await runtime.shutdown()

    mock_log.assert_called_once_with()


@pytest.mark.asyncio
async def test_startup_does_not_start_periodic_task_when_disabled():
    app = FastAPI()
    runtime = AppRuntime.for_app(app, Settings())

    await runtime.startup()

    assert runtime._metrics_task is None
    await runtime.shutdown()
