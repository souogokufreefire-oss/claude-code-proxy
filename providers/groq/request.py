"""Request builder for Groq provider (OpenAI-compatible chat completions)."""

from typing import Any

from loguru import logger

from core.anthropic import (
    ReasoningReplayMode,
    build_base_request_body,
    set_if_not_none,
)
from core.anthropic.conversion import OpenAIConversionError
from providers.exceptions import InvalidRequestError
from providers.output_cap import clamp_output_tokens


# Model-specific output limits enforced by Groq.
GROQ_MODEL_OUTPUT_CAPS: dict[str, int] = {
    "qwen/qwen3.6-27b": 16384,
}


def build_request_body(request_data: Any, *, thinking_enabled: bool) -> dict:
    """Build an OpenAI-format request body from an Anthropic Messages request."""
    logger.debug(
        "GROQ_REQUEST: conversion start model={} msgs={}",
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

    # Groq accepts both max_tokens and max_completion_tokens; keep max_tokens
    # for compatibility with the OpenAI Python SDK.

    # Clamp model-specific output limits before sending upstream.
    model_name = str(body.get("model", "")).strip().lower()
    model_cap = GROQ_MODEL_OUTPUT_CAPS.get(model_name)

    if model_cap is not None:
        clamped = clamp_output_tokens(body, model_cap)
        if clamped is not None:
            body = clamped
            logger.debug(
                "GROQ_REQUEST: clamped max output tokens model={} cap={}",
                model_name,
                model_cap,
            )

    # Pass through optional parameters
    set_if_not_none(body, "temperature", getattr(request_data, "temperature", None))
    set_if_not_none(body, "top_p", getattr(request_data, "top_p", None))

    logger.debug(
        "GROQ_REQUEST: conversion done model={} msgs={} tools={}",
        body.get("model"),
        len(body.get("messages", [])),
        len(body.get("tools", [])),
    )
    return body
