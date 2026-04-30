"""Request builder for Cerebras provider (OpenAI-compatible chat completions)."""

from typing import Any

from loguru import logger

from core.anthropic import (
    ReasoningReplayMode,
    build_base_request_body,
    set_if_not_none,
)
from core.anthropic.conversion import OpenAIConversionError
from providers.exceptions import InvalidRequestError


def build_request_body(request_data: Any, *, thinking_enabled: bool) -> dict:
    """Build an OpenAI-format request body from an Anthropic Messages request."""
    logger.debug(
        "CEREBRAS_REQUEST: conversion start model={} msgs={}",
        getattr(request_data, "model", "?"),
        len(getattr(request_data, "messages", [])),
    )
    try:
        body = build_base_request_body(
            request_data,
            reasoning_replay=ReasoningReplayMode.REASONING_CONTENT
            if thinking_enabled
            else ReasoningReplayMode.DISABLED,
        )
    except OpenAIConversionError as exc:
        raise InvalidRequestError(str(exc)) from exc

    # Cerebras uses max_completion_tokens (OpenAI naming convention)
    max_tokens = body.pop("max_tokens", None)
    if max_tokens is not None:
        body["max_completion_tokens"] = max_tokens

    # reasoning_effort for thinking control
    if thinking_enabled and "reasoning_effort" not in body:
        body["reasoning_effort"] = "medium"

    set_if_not_none(body, "temperature", getattr(request_data, "temperature", None))
    set_if_not_none(body, "top_p", getattr(request_data, "top_p", None))

    logger.debug(
        "CEREBRAS_REQUEST: conversion done model={} msgs={} tools={}",
        body.get("model"),
        len(body.get("messages", [])),
        len(body.get("tools", [])),
    )
    return body
