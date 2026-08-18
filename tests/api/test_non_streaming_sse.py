"""Unit tests for SSE-to-MessagesResponse aggregation (non-streaming clients)."""

from __future__ import annotations

import pytest

from api.models.responses import MessagesResponse
from api.services import SSEMessagesResponseBuilder
from providers.exceptions import ProviderError


def _frame(event_type: str, data: dict) -> str:
    import json

    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _content(response: MessagesResponse) -> list[dict]:
    """Content blocks as plain dicts (pydantic coerces them to typed models)."""
    return response.model_dump()["content"]


def test_aggregates_text_stream() -> None:
    builder = SSEMessagesResponseBuilder()
    builder.feed(
        _frame(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": "claude-sonnet-4-5",
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 12, "output_tokens": 0},
                },
            },
        )
    )
    builder.feed(
        _frame(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        )
    )
    builder.feed(
        _frame(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Hello"},
            },
        )
    )
    builder.feed(
        _frame(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": " world"},
            },
        )
    )
    builder.feed(
        _frame("content_block_stop", {"type": "content_block_stop", "index": 0})
    )
    builder.feed(
        _frame(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"input_tokens": 12, "output_tokens": 11},
            },
        )
    )
    builder.feed(_frame("message_stop", {"type": "message_stop"}))

    response = builder.build()

    assert response.id == "msg_1"
    assert response.model == "claude-sonnet-4-5"
    assert response.stop_reason == "end_turn"
    assert response.usage.input_tokens == 12
    assert response.usage.output_tokens == 11
    assert len(response.content) == 1
    assert _content(response)[0]["type"] == "text"
    assert _content(response)[0]["text"] == "Hello world"


def test_aggregates_thinking_with_signature() -> None:
    builder = SSEMessagesResponseBuilder()
    builder.feed(
        _frame(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "thinking", "thinking": ""},
            },
        )
    )
    builder.feed(
        _frame(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "Let me think"},
            },
        )
    )
    builder.feed(
        _frame(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": "sig_abc"},
            },
        )
    )
    builder.feed(
        _frame("content_block_stop", {"type": "content_block_stop", "index": 0})
    )

    response = builder.build()

    assert len(response.content) == 1
    assert _content(response)[0]["type"] == "thinking"
    assert _content(response)[0]["thinking"] == "Let me think"
    assert _content(response)[0]["signature"] == "sig_abc"


def test_aggregates_tool_use_partial_json() -> None:
    builder = SSEMessagesResponseBuilder()
    builder.feed(
        _frame(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "bash",
                    "input": {},
                },
            },
        )
    )
    builder.feed(
        _frame(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"command": "ls"}',
                },
            },
        )
    )
    builder.feed(
        _frame("content_block_stop", {"type": "content_block_stop", "index": 0})
    )

    response = builder.build()

    assert _content(response)[0]["type"] == "tool_use"
    assert _content(response)[0]["id"] == "toolu_1"
    assert _content(response)[0]["name"] == "bash"
    assert _content(response)[0]["input"] == {"command": "ls"}


def test_tool_use_invalid_json_becomes_empty_input() -> None:
    builder = SSEMessagesResponseBuilder()
    builder.feed(
        _frame(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "bash",
                    "input": {},
                },
            },
        )
    )
    builder.feed(
        _frame(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": "{not json"},
            },
        )
    )
    builder.feed(
        _frame("content_block_stop", {"type": "content_block_stop", "index": 0})
    )

    response = builder.build()

    assert _content(response)[0]["input"] == {}


def test_error_event_raises_provider_error() -> None:
    builder = SSEMessagesResponseBuilder()
    builder.feed(_frame("message_start", {"type": "message_start", "message": {}}))
    with pytest.raises(ProviderError) as exc_info:
        builder.feed(
            _frame(
                "error",
                {
                    "type": "error",
                    "error": {"type": "api_error", "message": "upstream broke"},
                },
            )
        )
    assert exc_info.value.status_code == 502
    assert exc_info.value.message == "upstream broke"


def test_malformed_frames_are_skipped() -> None:
    builder = SSEMessagesResponseBuilder()
    builder.feed("[DONE]\n\n")
    builder.feed("\n")
    builder.feed("event: message_stop\ndata: {}\n\n")

    response = builder.build()

    assert response.content == []
    assert response.id == "msg_unknown"
    assert response.usage.output_tokens == 0


def test_multiple_blocks_ordered_by_index() -> None:
    builder = SSEMessagesResponseBuilder()
    builder.feed(
        _frame(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "text", "text": ""},
            },
        )
    )
    builder.feed(
        _frame(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        )
    )
    builder.feed(
        _frame(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "first"},
            },
        )
    )
    builder.feed(
        _frame(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": "second"},
            },
        )
    )
    builder.feed(
        _frame("content_block_stop", {"type": "content_block_stop", "index": 0})
    )
    builder.feed(
        _frame("content_block_stop", {"type": "content_block_stop", "index": 1})
    )

    response = builder.build()

    assert [b["text"] for b in _content(response)] == ["first", "second"]


def test_unknown_block_passthrough_as_dict() -> None:
    builder = SSEMessagesResponseBuilder()
    builder.feed(
        _frame(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "server_tool_use",
                    "id": "st_1",
                    "name": "web_search",
                    "input": {},
                },
            },
        )
    )
    builder.feed(
        _frame("content_block_stop", {"type": "content_block_stop", "index": 0})
    )

    response = builder.build()

    assert _content(response)[0]["type"] == "server_tool_use"


def test_cache_usage_counts_carried_over() -> None:
    builder = SSEMessagesResponseBuilder()
    builder.feed(
        _frame(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "usage": {
                        "input_tokens": 10,
                        "cache_creation_input_tokens": 5,
                        "cache_read_input_tokens": 3,
                    }
                },
            },
        )
    )

    response = builder.build()

    assert response.usage.input_tokens == 10
    assert response.usage.cache_creation_input_tokens == 5
    assert response.usage.cache_read_input_tokens == 3


def test_non_integer_usage_falls_back() -> None:
    builder = SSEMessagesResponseBuilder()
    builder.feed(
        _frame(
            "message_start",
            {"type": "message_start", "message": {"usage": {"input_tokens": "many"}}},
        )
    )
    builder.feed(
        _frame(
            "message_delta",
            {"type": "message_delta", "delta": {}, "usage": {"output_tokens": "many"}},
        )
    )

    response = builder.build()

    assert response.usage.input_tokens == 0
    assert response.usage.output_tokens == 0
