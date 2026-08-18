"""Unit tests for ContextManager - message/token trimming for small-context providers."""

from __future__ import annotations

from typing import Any, Literal

import pytest

from api.models.anthropic import (
    ContentBlockImage,
    ContentBlockText,
    ContentBlockToolResult,
    ContentBlockToolUse,
    Message,
    MessagesRequest,
    Tool,
)
from config.settings import Settings
from core.context.context_manager import (
    CONTEXT_MAX_TOKENS_DEFAULT,
    ContextManager,
    ContextResult,
)


def _long_text(seed: int, words: int = 90) -> str:
    """Deterministic filler text, roughly 6-7 tokens per word."""
    return " ".join(f"word{seed}_{i}" for i in range(words))


def _make_message(
    role: Literal["user", "assistant"],
    content: str | list[Any],
    system: str | None = None,
) -> Message:
    """Build a message; system content is expressed via the request-level field."""
    assert system is None, (
        "system prompt must be set on MessagesRequest, not on a message"
    )
    if isinstance(content, str):
        content = [ContentBlockText(type="text", text=content)]
    return Message(role=role, content=content)


def _make_request(
    messages: list[Message],
    system: str | None = None,
    tools: list[Tool] | None = None,
) -> MessagesRequest:
    return MessagesRequest(
        model="groq/llama/3.1",
        messages=messages,
        system=system,
        tools=tools,
    )


def _make_short_request() -> MessagesRequest:
    return _make_request([_make_message("user", "Hello, how are you?")])


def _make_large_request(n: int = 60) -> MessagesRequest:
    """Build a request whose messages clearly exceed the default token budget."""
    messages: list[Message] = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append(_make_message(role, _long_text(i)))
    return _make_request(messages)


def _build_tool_cycle(
    tool_id: str,
    seed: int,
) -> tuple[Message, Message]:
    tool_use = _make_message(
        "assistant",
        [
            ContentBlockText(type="text", text=f"calling {tool_id}"),
            ContentBlockToolUse(
                type="tool_use",
                id=tool_id,
                name="calculator",
                input={"expression": f"{seed}+{seed}"},
            ),
        ],
    )
    tool_result = _make_message(
        "user",
        [ContentBlockToolResult(type="tool_result", tool_use_id=tool_id, content="4")],
    )
    return tool_use, tool_result


class TestContextManagerBudgetWithinLimit:
    def test_request_below_budget_no_trim(self) -> None:
        request = _make_short_request()
        cm = ContextManager(settings=None)
        result: ContextResult = cm.optimize(request)
        assert result.trimmed is False
        assert result.removed_messages == 0
        assert result.removed_tokens == 0
        assert result.request.messages == request.messages
        assert len(result.request.messages) == 1

    def test_request_below_budget_with_system_and_tools_no_trim(self) -> None:
        tools = [Tool(name="t1", description="d"), Tool(name="t2", description="d")]
        request = _make_request(
            [_make_message("user", "Hello"), _make_message("assistant", "Hi")],
            system="You are helpful.",
            tools=tools,
        )
        result = ContextManager(settings=None).optimize(request)
        assert result.trimmed is False
        assert result.request.system == "You are helpful."
        assert len(result.request.tools or []) == 2


class TestContextManagerBudgetExceedsLimit:
    def test_request_above_budget_trims_messages(self) -> None:
        request = _make_large_request()
        cm = ContextManager(settings=None)
        result: ContextResult = cm.optimize(request)
        assert result.trimmed is True
        assert result.removed_messages > 0
        assert result.removed_tokens > 0
        assert len(result.request.messages) < len(request.messages)

    def test_trimmed_request_fits_budget(self) -> None:
        request = _make_large_request()
        result = ContextManager(settings=None).optimize(request)
        from core.anthropic.tokens import get_token_count

        tokens = get_token_count(
            result.request.messages, result.request.system, result.request.tools
        )
        budget = CONTEXT_MAX_TOKENS_DEFAULT - 4_096
        assert tokens <= budget

    def test_removed_tokens_equals_before_minus_after(self) -> None:
        request = _make_large_request()
        from core.anthropic.tokens import get_token_count

        before = get_token_count(request.messages, request.system, request.tools)
        result = ContextManager(settings=None).optimize(request)
        after = get_token_count(
            result.request.messages, result.request.system, result.request.tools
        )
        assert result.removed_tokens == before - after

    def test_preserves_system_prompt(self) -> None:
        request = _make_request(
            _make_large_request().messages,
            system="You are a helpful assistant",
        )
        result: ContextResult = ContextManager(settings=None).optimize(request)
        assert result.request.system == "You are a helpful assistant"

    def test_preserves_first_user_message(self) -> None:
        request = _make_large_request()
        first_content = request.messages[0].content
        result: ContextResult = ContextManager(settings=None).optimize(request)
        assert result.request.messages[0].role == "user"
        assert result.request.messages[0].content == first_content

    def test_preserves_recent_messages(self) -> None:
        request = _make_large_request()
        recent_count = 10
        recent = request.messages[-recent_count:]
        result: ContextResult = ContextManager(settings=None).optimize(request)
        assert result.request.messages[-recent_count:] == recent

    def test_preserves_tool_use_tool_result_pairs(self) -> None:
        # Tool cycle in the middle of the conversation: both sides must
        # survive together (or both be dropped), never one without the other.
        tool_use, tool_result = _build_tool_cycle("tool_1", seed=1)
        messages = [
            _make_message("user", _long_text(0)),
            tool_use,
            tool_result,
            *[
                _make_message("user" if i % 2 else "assistant", _long_text(i + 10))
                for i in range(60)
            ],
        ]
        request = _make_request(messages)
        result: ContextResult = ContextManager(settings=None).optimize(request)
        assert result.trimmed is True
        # Assert no orphaned tool_use / tool_result remains.
        use_ids = {
            block.id
            for m in result.request.messages
            for block in (m.content if isinstance(m.content, list) else [])
            if isinstance(block, ContentBlockToolUse)
        }
        result_ids = {
            block.tool_use_id
            for m in result.request.messages
            for block in (m.content if isinstance(m.content, list) else [])
            if isinstance(block, ContentBlockToolResult)
        }
        assert use_ids == result_ids

    def test_preserves_tool_cycle_in_recent_window(self) -> None:
        # A tool cycle inside the protected recent window must survive whole.
        tool_use, tool_result = _build_tool_cycle("tool_2", seed=2)
        messages = [
            *[
                _make_message("user" if i % 2 else "assistant", _long_text(i + 10))
                for i in range(58)
            ],
            tool_use,
            tool_result,
            _make_message("user", _long_text(999)),
        ]
        request = _make_request(messages)
        result: ContextResult = ContextManager(settings=None).optimize(request)
        assert result.trimmed is True
        use_ids = {
            block.id
            for m in result.request.messages
            for block in (m.content if isinstance(m.content, list) else [])
            if isinstance(block, ContentBlockToolUse)
        }
        result_ids = {
            block.tool_use_id
            for m in result.request.messages
            for block in (m.content if isinstance(m.content, list) else [])
            if isinstance(block, ContentBlockToolResult)
        }
        assert use_ids == {"tool_2"}
        assert result_ids == {"tool_2"}

    def test_original_request_not_mutated(self) -> None:
        request = _make_large_request()
        original = request.model_copy(deep=True)
        ContextManager(settings=None).optimize(request)
        assert request.model_dump() == original.model_dump()

    def test_trimming_is_idempotent(self) -> None:
        request = _make_large_request()
        cm = ContextManager(settings=None)
        first: ContextResult = cm.optimize(request)
        assert first.trimmed is True
        second: ContextResult = cm.optimize(first.request)
        assert second.trimmed is False
        assert second.removed_messages == 0

    def test_many_tools_unchanged_by_trimming(self) -> None:
        tools = [Tool(name=f"tool_{i}", description="desc") for i in range(30)]
        request = _make_request(_make_large_request().messages, tools=tools)
        result: ContextResult = ContextManager(settings=None).optimize(request)
        assert len(result.request.tools or []) == 30

    def test_multimodal_message_not_corrupted(self) -> None:
        messages = [
            _make_message(
                "user",
                [
                    ContentBlockText(type="text", text="Here is a diagram"),
                    ContentBlockImage(
                        type="image",
                        source={
                            "type": "base64",
                            "media_type": "image/png",
                            "data": "aGVsbG8=",
                        },
                    ),
                ],
            ),
            *[
                _make_message("user" if i % 2 else "assistant", _long_text(i + 1))
                for i in range(60)
            ],
        ]
        request = _make_request(messages)
        result: ContextResult = ContextManager(settings=None).optimize(request)
        # First user message (with image) must be preserved intact.
        assert result.request.messages[0].role == "user"
        blocks = result.request.messages[0].content
        assert isinstance(blocks, list)
        assert isinstance(blocks[0], ContentBlockText)
        assert isinstance(blocks[1], ContentBlockImage)

    def test_trims_oldest_before_recent(self) -> None:
        request = _make_large_request()
        recent = request.messages[-10:]
        result: ContextResult = ContextManager(settings=None).optimize(request)
        assert result.request.messages[-10:] == recent


class TestContextManagerCustomSettings:
    def test_respects_custom_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONTEXT_MAX_TOKENS", "1000")
        monkeypatch.setenv("CONTEXT_RESERVED_OUTPUT_TOKENS", "100")
        monkeypatch.setenv("CONTEXT_MIN_RECENT_MESSAGES", "2")
        cm = ContextManager(Settings())
        assert cm._budget == 900
        # A single short message fits a 900-token budget: no trim.
        request = _make_request([_make_message("user", "Hello")])
        result: ContextResult = cm.optimize(request)
        assert result.trimmed is False
        # A message that exceeds the custom budget must be trimmed down.
        large = _make_request([_make_message("user", _long_text(0, words=400))])
        result = cm.optimize(large)
        assert result.trimmed is True

    def test_respects_min_recent_messages(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CONTEXT_MAX_TOKENS", "1000")
        monkeypatch.setenv("CONTEXT_RESERVED_OUTPUT_TOKENS", "100")
        monkeypatch.setenv("CONTEXT_MIN_RECENT_MESSAGES", "4")
        messages = [
            _make_message("user", _long_text(0)),
            _make_message("assistant", _long_text(1)),
            _make_message("user", _long_text(2)),
            _make_message("assistant", _long_text(3)),
            _make_message("user", _long_text(4)),
        ]
        result: ContextResult = ContextManager(Settings()).optimize(
            _make_request(messages)
        )
        if result.trimmed:
            recent = messages[-4:]
            assert result.request.messages[-4:] == recent

    def test_negative_or_zero_settings_fall_back_to_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CONTEXT_MAX_TOKENS", "0")
        monkeypatch.setenv("CONTEXT_RESERVED_OUTPUT_TOKENS", "0")
        monkeypatch.setenv("CONTEXT_MIN_RECENT_MESSAGES", "0")
        cm = ContextManager(Settings())
        assert cm._max_tokens == CONTEXT_MAX_TOKENS_DEFAULT
        assert cm._budget == CONTEXT_MAX_TOKENS_DEFAULT - 4_096

    def test_enabled_setting_defaults(self) -> None:
        assert Settings().context_enabled is True
        assert Settings().context_max_tokens == 24_000
        assert Settings().context_reserved_output_tokens == 4_096
        assert Settings().context_min_recent_messages == 10


class TestContextResult:
    def test_context_result_fields(self) -> None:
        req = MessagesRequest(model="test", messages=[])
        result = ContextResult(
            request=req, removed_messages=2, removed_tokens=50, trimmed=True
        )
        assert result.request is req
        assert result.removed_messages == 2
        assert result.removed_tokens == 50
        assert result.trimmed is True
        assert result.budget_tokens == 0
        assert result.overflow is False

    def test_context_result_no_trim(self) -> None:
        req = MessagesRequest(model="test", messages=[])
        result = ContextResult(
            request=req, removed_messages=0, removed_tokens=0, trimmed=False
        )
        assert result.trimmed is False
        assert result.removed_messages == 0
        assert result.removed_tokens == 0
        assert result.overflow is False


class TestContextManagerOverflow:
    def test_overflow_when_protected_core_exceeds_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A single protected message over budget cannot be trimmed: overflow."""
        monkeypatch.setenv("CONTEXT_MAX_TOKENS", "100")
        monkeypatch.setenv("CONTEXT_RESERVED_OUTPUT_TOKENS", "10")
        monkeypatch.setenv("CONTEXT_MIN_RECENT_MESSAGES", "10")
        cm = ContextManager(Settings())
        request = _make_request([_make_message("user", _long_text(0, words=400))])

        result: ContextResult = cm.optimize(request)

        assert result.trimmed is True
        assert result.removed_messages == 0
        assert result.overflow is True
        assert result.budget_tokens == 90

    def test_overflow_false_when_trim_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Trimming that fits the budget must not flag overflow."""
        monkeypatch.setenv("CONTEXT_MAX_TOKENS", "600")
        monkeypatch.setenv("CONTEXT_RESERVED_OUTPUT_TOKENS", "10")
        monkeypatch.setenv("CONTEXT_MIN_RECENT_MESSAGES", "2")
        cm = ContextManager(Settings())
        request = _make_request(
            [
                _make_message("user", _long_text(0, words=20)),
                _make_message("assistant", _long_text(1, words=400)),
                _make_message("user", _long_text(2, words=400)),
                _make_message("assistant", _long_text(3, words=400)),
                _make_message("user", _long_text(4, words=400)),
                _make_message("assistant", _long_text(5, words=400)),
                _make_message("user", _long_text(6, words=400)),
                _make_message("assistant", _long_text(7, words=400)),
                _make_message("user", _long_text(8, words=50)),
                _make_message("assistant", _long_text(9, words=50)),
            ]
        )

        result: ContextResult = cm.optimize(request)

        assert result.trimmed is True
        assert result.removed_messages > 0
        assert result.overflow is False

    def test_no_overflow_when_within_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CONTEXT_MAX_TOKENS", "1000")
        monkeypatch.setenv("CONTEXT_RESERVED_OUTPUT_TOKENS", "100")
        cm = ContextManager(Settings())
        request = _make_request([_make_message("user", "Hello")])

        result: ContextResult = cm.optimize(request)

        assert result.trimmed is False
        assert result.overflow is False
        assert result.budget_tokens == 900
