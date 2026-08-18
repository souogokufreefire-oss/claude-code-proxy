"""Integration tests: ContextManager trims only Groq requests via ClaudeProxyService."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import MagicMock

import pytest
from loguru import logger as loguru_logger

from api.model_router import ModelRouter, ResolvedModel, RoutedMessagesRequest
from api.models.anthropic import ContentBlockText, Message, MessagesRequest
from api.services import ClaudeProxyService
from config.settings import Settings


class FixedProviderModelRouter(ModelRouter):
    """Test double: pin ``provider_id`` regardless of model name."""

    def __init__(self, settings: Settings, provider_id: str) -> None:
        super().__init__(settings)
        self._fixed_provider_id = provider_id

    def resolve_messages_request(
        self, request: MessagesRequest
    ) -> RoutedMessagesRequest:
        resolved = ResolvedModel(
            original_model=request.model,
            provider_id=self._fixed_provider_id,
            provider_model=request.model,
            provider_model_ref=f"{self._fixed_provider_id}/{request.model}",
            thinking_enabled=False,
        )
        routed = request.model_copy(deep=True)
        routed.model = resolved.provider_model
        return RoutedMessagesRequest(request=routed, resolved=resolved)


def _long_text(seed: int, words: int = 90) -> str:
    return " ".join(f"word{seed}_{i}" for i in range(words))


def _make_large_request() -> MessagesRequest:
    messages: list[Message] = []
    for i in range(60):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append(
            Message(
                role=role, content=[ContentBlockText(type="text", text=_long_text(i))]
            )
        )
    return MessagesRequest(model="claude-sonnet-4-5", messages=messages)


def _make_capturing_provider(captured: list[MessagesRequest]) -> MagicMock:
    """Provider whose ``stream_response`` records the request it receives."""

    def fake_stream(request: MessagesRequest, **_kwargs: object):
        captured.append(request)

        async def gen():
            yield "event: message_start\ndata: {}\n\n"
            yield "event: message_delta\ndata: {}\n\n"
            yield "event: message_stop\ndata: {}\n\n"

        return gen()

    provider = MagicMock()
    provider.stream_response = fake_stream
    return provider


def _service_for(
    provider_id: str, captured: list[MessagesRequest], settings: Settings
) -> ClaudeProxyService:
    return ClaudeProxyService(
        settings,
        provider_getter=lambda _: _make_capturing_provider(captured),
        model_router=FixedProviderModelRouter(settings, provider_id),
    )


def test_groq_receives_reduced_request() -> None:
    captured: list[MessagesRequest] = []
    request = _make_large_request()
    original_count = len(request.messages)

    _service_for("groq", captured, Settings()).create_message(request)

    assert len(captured) == 1
    assert len(captured[0].messages) < original_count


def test_groq_original_request_not_mutated() -> None:
    captured: list[MessagesRequest] = []
    request = _make_large_request()
    original = request.model_dump()

    _service_for("groq", captured, Settings()).create_message(request)

    assert request.model_dump() == original


def test_non_groq_receives_unchanged_request() -> None:
    captured: list[MessagesRequest] = []
    request = _make_large_request()
    original_count = len(request.messages)

    _service_for("open_router", captured, Settings()).create_message(request)

    assert len(captured) == 1
    assert len(captured[0].messages) == original_count


def test_groq_trimming_disabled_via_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[MessagesRequest] = []
    request = _make_large_request()
    original_count = len(request.messages)
    monkeypatch.setenv("CONTEXT_ENABLED", "false")
    settings = Settings()

    _service_for("groq", captured, settings).create_message(request)

    assert len(captured) == 1
    assert len(captured[0].messages) == original_count


def test_groq_small_request_not_trimmed() -> None:
    captured: list[MessagesRequest] = []
    request = MessagesRequest(
        model="claude-sonnet-4-5",
        messages=[
            Message(role="user", content=[ContentBlockText(type="text", text="hi")])
        ],
    )

    _service_for("groq", captured, Settings()).create_message(request)

    assert len(captured) == 1
    assert len(captured[0].messages) == 1


def _capture_loguru(records: list[str]) -> Callable[[], None]:
    sink_id = loguru_logger.add(lambda message: records.append(message), level="DEBUG")

    def remove() -> None:
        loguru_logger.remove(sink_id)

    return remove


def test_groq_trimmed_logs_info(monkeypatch: pytest.MonkeyPatch) -> None:
    records: list[str] = []
    remove = _capture_loguru(records)
    try:
        _service_for("groq", [], Settings()).create_message(_make_large_request())
    finally:
        remove()

    assert any("CONTEXT_TRIMMED: provider=groq" in r for r in records)


def test_groq_overflow_logs_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_MAX_TOKENS", "100")
    monkeypatch.setenv("CONTEXT_RESERVED_OUTPUT_TOKENS", "10")
    monkeypatch.setenv("CONTEXT_MIN_RECENT_MESSAGES", "10")
    request = MessagesRequest(
        model="claude-sonnet-4-5",
        messages=[
            Message(
                role="user",
                content=[ContentBlockText(type="text", text=_long_text(0, words=400))],
            )
        ],
    )
    records: list[str] = []
    remove = _capture_loguru(records)
    try:
        _service_for("groq", [], Settings()).create_message(request)
    finally:
        remove()

    assert any(
        "CONTEXT_OVERFLOW: provider=groq" in r and "overflow=true" in r for r in records
    )
    assert not any("CONTEXT_TRIMMED" in r for r in records)
