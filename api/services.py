"""Application services for the Claude-compatible API."""

from __future__ import annotations

import json
import traceback
import uuid
from collections.abc import AsyncIterable, AsyncIterator, Callable
from typing import Any, Literal, cast

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger

from config.provider_catalog import OPENAI_CHAT_PROVIDER_IDS
from config.settings import Settings
from core.anthropic import get_token_count, get_user_facing_error_message
from core.anthropic.sse import ANTHROPIC_SSE_RESPONSE_HEADERS
from core.context.context_manager import ContextManager
from core.metrics import MetricsRegistry, OutputTokenTracker, metrics_registry
from providers.base import (
    BaseProvider,
    begin_primary_failover,
    end_primary_failover,
    error_status_code,
    fallback_model_for,
    fallback_provider_for,
)
from providers.exceptions import (
    InvalidRequestError,
    ProviderError,
    ProviderFailoverSignal,
)

from .model_router import ModelRouter
from .models.anthropic import MessagesRequest, TokenCountRequest
from .models.responses import MessagesResponse, TokenCountResponse, Usage
from .optimization_handlers import try_optimizations
from .web_tools.egress import WebFetchEgressPolicy
from .web_tools.request import (
    is_web_server_tool_request,
    openai_chat_upstream_server_tool_error,
)
from .web_tools.streaming import stream_web_server_tool_response

TokenCounter = Callable[[list[Any], str | list[Any] | None, list[Any] | None], int]

ProviderGetter = Callable[[str], BaseProvider]


def anthropic_sse_streaming_response(
    body: AsyncIterator[str],
) -> StreamingResponse:
    """Return a :class:`StreamingResponse` for Anthropic-style SSE streams."""
    return StreamingResponse(
        body,
        media_type="text/event-stream",
        headers=ANTHROPIC_SSE_RESPONSE_HEADERS,
    )


def _http_status_for_unexpected_service_exception(_exc: BaseException) -> int:
    """HTTP status for uncaught non-provider failures (stable client contract)."""
    return 500


def _log_unexpected_service_exception(
    settings: Settings,
    exc: BaseException,
    *,
    context: str,
    request_id: str | None = None,
) -> None:
    """Log service-layer failures without echoing exception text unless opted in."""
    if settings.log_api_error_tracebacks:
        if request_id is not None:
            logger.error("{} request_id={}: {}", context, request_id, exc)
        else:
            logger.error("{}: {}", context, exc)
        logger.error(traceback.format_exc())
        return
    if request_id is not None:
        logger.error(
            "{} request_id={} exc_type={}",
            context,
            request_id,
            type(exc).__name__,
        )
    else:
        logger.error("{} exc_type={}", context, type(exc).__name__)


def _require_non_empty_messages(messages: list[Any]) -> None:
    if not messages:
        raise InvalidRequestError("messages cannot be empty")


async def _messages_response_to_sse_stream(
    response: MessagesResponse,
) -> AsyncIterator[str]:
    """Convert a :class:`MessagesResponse` into an Anthropic SSE event stream.

    Optimization handlers return complete responses, but Claude Code always
    sends ``stream=True`` and expects SSE.  Without this conversion the client
    falls back to non-streaming mode and logs a stream error.
    """

    def _event(event_type: str, data: dict) -> str:
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    stop_reason = response.stop_reason or "end_turn"

    yield _event(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": response.id,
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": response.model,
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": input_tokens, "output_tokens": 0},
            },
        },
    )
    for idx, item in enumerate(response.content):
        # NOTE: optimization handlers currently only return text blocks.
        # If a handler ever returns tool_use or image content, the
        # hardcoded text_delta / text field below must be generalized.
        if isinstance(item, dict):
            block_type = item.get("type", "text")
            text = item.get("text", "")
        elif hasattr(item, "type"):
            block_type = getattr(item, "type", "text")
            text = getattr(item, "text", "")
        else:
            block_type = "text"
            text = str(item)
        yield _event(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": idx,
                "content_block": {"type": block_type, "text": ""},
            },
        )
        yield _event(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": idx,
                "delta": {"type": "text_delta", "text": text},
            },
        )
        yield _event(
            "content_block_stop",
            {"type": "content_block_stop", "index": idx},
        )
    yield _event(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        },
    )
    yield _event("message_stop", {"type": "message_stop"})


def _parse_sse_frame(frame: str) -> tuple[str, dict] | None:
    """Parse one ``event: X\\ndata: {...}\\n\\n`` frame into (event, data)."""
    lines = [ln for ln in frame.splitlines() if ln]
    event_type: str | None = None
    data_lines: list[str] = []
    for ln in lines:
        if ln.startswith("event:"):
            event_type = ln[len("event:") :].strip()
        elif ln.startswith("data:"):
            data_lines.append(ln[len("data:") :].strip())
    if event_type is None or not data_lines:
        return None
    try:
        payload = json.loads("\n".join(data_lines))
    except json.JSONDecodeError:
        return None
    return event_type, payload


class SSEMessagesResponseBuilder:
    """Aggregate Anthropic-style SSE events into a single :class:`MessagesResponse`.

    Used for non-streaming clients (``stream: false``) which expect a JSON
    message body instead of ``text/event-stream`` (PR #977).
    """

    def __init__(self) -> None:
        self.message_id: str | None = None
        self.model: str | None = None
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_creation_input_tokens = 0
        self.cache_read_input_tokens = 0
        self.stop_reason: str | None = None
        self.stop_sequence: str | None = None
        self.blocks: dict[int, dict[str, Any]] = {}

    def feed(self, chunk: str) -> None:
        """Consume one SSE chunk (may hold several frames)."""
        for frame in chunk.split("\n\n"):
            parsed = _parse_sse_frame(frame)
            if parsed is None:
                continue
            event_type, data = parsed
            if event_type == "message_start":
                message = data.get("message", {})
                self.message_id = message.get("id") or self.message_id
                self.model = message.get("model") or self.model
                usage = message.get("usage") or {}
                self.input_tokens = _usage_int(
                    usage.get("input_tokens"), self.input_tokens
                )
                self.cache_creation_input_tokens = _usage_int(
                    usage.get("cache_creation_input_tokens"),
                    self.cache_creation_input_tokens,
                )
                self.cache_read_input_tokens = _usage_int(
                    usage.get("cache_read_input_tokens"),
                    self.cache_read_input_tokens,
                )
            elif event_type == "content_block_start":
                index = data.get("index", 0)
                block = dict(data.get("content_block") or {})
                self.blocks[index] = block
            elif event_type == "content_block_delta":
                index = data.get("index", 0)
                block = self.blocks.get(index)
                if block is None:
                    continue
                delta = data.get("delta") or {}
                delta_type = delta.get("type", "")
                if delta_type in ("text_delta", "thinking_delta"):
                    block["text"] = block.get("text", "") + str(
                        delta.get("text") or delta.get("thinking") or ""
                    )
                elif delta_type == "input_json_delta":
                    block["partial_json"] = block.get("partial_json", "") + str(
                        delta.get("partial_json") or ""
                    )
                elif delta_type == "signature_delta":
                    block["signature"] = delta.get("signature") or block.get(
                        "signature"
                    )
            elif event_type == "message_delta":
                delta = data.get("delta") or {}
                if delta.get("stop_reason") is not None:
                    self.stop_reason = str(delta.get("stop_reason"))
                if delta.get("stop_sequence") is not None:
                    self.stop_sequence = str(delta.get("stop_sequence"))
                usage = data.get("usage") or {}
                self.output_tokens = _usage_int(
                    usage.get("output_tokens"), self.output_tokens
                )
            elif event_type == "error":
                error = data.get("error") or {}
                raise ProviderError(
                    str(error.get("message") or "Upstream streaming error"),
                    status_code=502,
                    error_type=str(error.get("type") or "api_error"),
                )

    def build(self) -> MessagesResponse:
        """Assemble the final response from the consumed events."""
        content: list[Any] = []
        for index in sorted(self.blocks):
            block = self.blocks[index]
            block_type = block.get("type")
            if block_type == "text":
                content.append({"type": "text", "text": str(block.get("text") or "")})
            elif block_type == "thinking":
                content.append(
                    {
                        "type": "thinking",
                        "thinking": str(block.get("text") or ""),
                        "signature": block.get("signature"),
                    }
                )
            elif block_type == "tool_use":
                input_json = block.get("partial_json") or ""
                parsed_input: Any = {}
                if input_json:
                    try:
                        parsed_input = json.loads(input_json)
                    except json.JSONDecodeError:
                        parsed_input = {}
                content.append(
                    {
                        "type": "tool_use",
                        "id": str(block.get("id") or ""),
                        "name": str(block.get("name") or ""),
                        "input": parsed_input,
                    }
                )
            else:
                content.append(block)
        return MessagesResponse(
            id=self.message_id or "msg_unknown",
            model=self.model or "",
            content=content,
            stop_reason=cast(
                Literal["end_turn", "max_tokens", "stop_sequence", "tool_use"] | None,
                self.stop_reason,
            ),
            stop_sequence=self.stop_sequence,
            usage=Usage(
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
                cache_creation_input_tokens=self.cache_creation_input_tokens,
                cache_read_input_tokens=self.cache_read_input_tokens,
            ),
        )


def _usage_int(value: object, fallback: int) -> int:
    """Coerce streamed usage counters to int; non-integers keep the fallback."""
    return value if isinstance(value, int) else fallback


async def _aggregate_sse_to_messages_response(
    stream: AsyncIterable[Any],
) -> MessagesResponse:
    """Consume an Anthropic-style SSE stream into a single :class:`MessagesResponse`."""
    builder = SSEMessagesResponseBuilder()
    async for chunk in stream:
        if isinstance(chunk, (bytes, memoryview)):
            text = bytes(chunk).decode("utf-8", errors="replace")
        else:
            text = str(chunk)
        builder.feed(text)
    return builder.build()


class ClaudeProxyService:
    """Coordinate request optimization, model routing, token count, and providers."""

    def __init__(
        self,
        settings: Settings,
        provider_getter: ProviderGetter,
        model_router: ModelRouter | None = None,
        token_counter: TokenCounter = get_token_count,
        metrics_registry_: MetricsRegistry | None = None,
    ):
        self._settings = settings
        self._provider_getter = provider_getter
        self._model_router = model_router or ModelRouter(settings)
        self._token_counter = token_counter
        self._metrics = metrics_registry_ or metrics_registry

    def create_message(self, request_data: MessagesRequest) -> StreamingResponse:
        """Create a message response or streaming response."""
        try:
            _require_non_empty_messages(request_data.messages)

            routed = self._model_router.resolve_messages_request(request_data)
            if routed.resolved.provider_id in OPENAI_CHAT_PROVIDER_IDS:
                tool_err = openai_chat_upstream_server_tool_error(
                    routed.request,
                    web_tools_enabled=self._settings.enable_web_server_tools,
                )
                if tool_err is not None:
                    raise InvalidRequestError(tool_err)

            if self._settings.enable_web_server_tools and is_web_server_tool_request(
                routed.request
            ):
                input_tokens = self._token_counter(
                    routed.request.messages, routed.request.system, routed.request.tools
                )
                logger.info("Optimization: Handling Anthropic web server tool")
                egress = WebFetchEgressPolicy(
                    allow_private_network_targets=self._settings.web_fetch_allow_private_networks,
                    allowed_schemes=self._settings.web_fetch_allowed_scheme_set(),
                )
                return anthropic_sse_streaming_response(
                    stream_web_server_tool_response(
                        routed.request,
                        input_tokens=input_tokens,
                        web_fetch_egress=egress,
                        verbose_client_errors=self._settings.log_api_error_tracebacks,
                    ),
                )

            optimized = try_optimizations(routed.request, self._settings)
            if optimized is not None:
                return anthropic_sse_streaming_response(
                    _messages_response_to_sse_stream(optimized)
                )
            logger.debug("No optimization matched, routing to provider")

            # --- Context Window Manager (Groq-only) ---
            provider_id = routed.resolved.provider_id
            before_tokens = self._token_counter(
                routed.request.messages, routed.request.system, routed.request.tools
            )
            context_manager: ContextManager | None = None
            if provider_id == "groq" and self._settings.context_enabled:
                context_manager = ContextManager(self._settings)
            # If not Groq, use the request as-is
            if context_manager is not None:
                context_result = context_manager.optimize(routed.request)
                routed_request: MessagesRequest = context_result.request
                after_tokens = self._token_counter(
                    routed_request.messages, routed_request.system, routed_request.tools
                )
                removed_messages = context_result.removed_messages
                removed_tokens = context_result.removed_tokens
                trimmed = context_result.trimmed
                budget_tokens = context_result.budget_tokens
                overflow = context_result.overflow
            else:
                routed_request = routed.request
                after_tokens = before_tokens
                removed_messages = 0
                removed_tokens = 0
                trimmed = False
                budget_tokens = 0
                overflow = False
            logger.debug(
                "CONTEXT_MANAGER: provider={} before_tokens={} after_tokens={} "
                "removed_messages={} removed_tokens={} trimmed={}",
                provider_id,
                before_tokens,
                after_tokens,
                removed_messages,
                removed_tokens,
                trimmed,
            )
            if overflow:
                logger.warning(
                    "CONTEXT_OVERFLOW: provider={} before_tokens={} after_tokens={} "
                    "budget={} removed_messages={} removed_tokens={} overflow=true",
                    provider_id,
                    before_tokens,
                    after_tokens,
                    budget_tokens,
                    removed_messages,
                    removed_tokens,
                )
            elif trimmed:
                logger.info(
                    "CONTEXT_TRIMMED: provider={} before_tokens={} after_tokens={} "
                    "budget={} removed_messages={} removed_tokens={}",
                    provider_id,
                    before_tokens,
                    after_tokens,
                    budget_tokens,
                    removed_messages,
                    removed_tokens,
                )
            # -------------------------------------------

            provider = self._provider_getter(routed.resolved.provider_id)
            provider.preflight_stream(
                routed_request,
                thinking_enabled=routed.resolved.thinking_enabled,
            )

            request_id = f"req_{uuid.uuid4().hex[:12]}"
            logger.info(
                "API_REQUEST: request_id={} model={} messages={}",
                request_id,
                routed_request.model,
                len(routed_request.messages),
            )
            if self._settings.log_raw_api_payloads:
                logger.debug(
                    "FULL_PAYLOAD [{}]: {}", request_id, routed_request.model_dump()
                )

            input_tokens = self._token_counter(
                routed_request.messages, routed_request.system, routed_request.tools
            )
            self._metrics.record_request(provider_id, input_tokens)
            primary_stream = provider.stream_response(
                routed_request,
                input_tokens=input_tokens,
                request_id=request_id,
                thinking_enabled=routed.resolved.thinking_enabled,
            )

            return anthropic_sse_streaming_response(
                self._stream_with_provider_failover(
                    primary_stream=primary_stream,
                    provider_id=routed.resolved.provider_id,
                    request=routed_request,
                    input_tokens=input_tokens,
                    request_id=request_id,
                    thinking_enabled=routed.resolved.thinking_enabled,
                ),
            )

        except ProviderError:
            raise
        except Exception as e:
            _log_unexpected_service_exception(
                self._settings, e, context="CREATE_MESSAGE_ERROR"
            )
            raise HTTPException(
                status_code=_http_status_for_unexpected_service_exception(e),
                detail=get_user_facing_error_message(e),
            ) from e

    async def create_message_non_streaming(
        self, request_data: MessagesRequest
    ) -> MessagesResponse:
        """Create a single JSON :class:`MessagesResponse` for ``stream: false``.

        Runs the same pipeline as :meth:`create_message` (optimizations, CWM,
        failover) and aggregates the SSE stream into one response body.
        """
        response = self.create_message(request_data)
        return await _aggregate_sse_to_messages_response(response.body_iterator)

    async def _stream_with_provider_failover(
        self,
        *,
        primary_stream: AsyncIterator[str],
        provider_id: str,
        request: MessagesRequest,
        input_tokens: int,
        request_id: str,
        thinking_enabled: bool,
    ) -> AsyncIterator[str]:
        """Stream from the primary provider and fail over before useful SSE is released."""

        first_event: str | None = None
        signal: ProviderFailoverSignal | None = None
        token = begin_primary_failover(provider_id)
        token_tracker = OutputTokenTracker()

        try:
            try:
                async for event in primary_stream:
                    # Hold only the very first SSE event. Both transports emit
                    # message_start before the upstream result is known.
                    # If a failover signal occurs, this event is discarded.
                    token_tracker.feed(event)
                    if first_event is None:
                        first_event = event
                        continue

                    yield first_event
                    first_event = None
                    yield event

                if first_event is not None:
                    yield first_event

            except ProviderFailoverSignal as exc:
                signal = exc
            except Exception:
                self._metrics.record_stream_result(provider_id, error=True)
                raise
        finally:
            end_primary_failover(token)

        if signal is None:
            self._metrics.record_stream_result(
                provider_id, output_tokens=token_tracker.output_tokens
            )
            return

        self._metrics.record_failover(provider_id)
        secondary_provider_id = fallback_provider_for(provider_id)
        secondary_model = fallback_model_for(provider_id)
        if secondary_provider_id is None or secondary_model is None:
            raise signal.cause

        self._metrics.record_request(secondary_provider_id, input_tokens)

        logger.warning(
            "PROVIDER_FAILOVER: primary={} secondary={} status={} request_id={}",
            provider_id,
            secondary_provider_id,
            error_status_code(signal.cause),
            request_id,
        )

        secondary_provider = self._provider_getter(secondary_provider_id)
        secondary_request = request.model_copy(deep=True)
        secondary_request.model = secondary_model

        secondary_provider.preflight_stream(
            secondary_request,
            thinking_enabled=thinking_enabled,
        )

        secondary_token_tracker = OutputTokenTracker()
        try:
            async for event in secondary_provider.stream_response(
                secondary_request,
                input_tokens=input_tokens,
                request_id=request_id,
                thinking_enabled=thinking_enabled,
            ):
                secondary_token_tracker.feed(event)
                yield event
        except Exception:
            self._metrics.record_stream_result(secondary_provider_id, error=True)
            raise
        self._metrics.record_stream_result(
            secondary_provider_id,
            output_tokens=secondary_token_tracker.output_tokens,
        )

    def count_tokens(self, request_data: TokenCountRequest) -> TokenCountResponse:
        """Count tokens for a request after applying configured model routing."""
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        with logger.contextualize(request_id=request_id):
            try:
                _require_non_empty_messages(request_data.messages)
                routed = self._model_router.resolve_token_count_request(request_data)
                tokens = self._token_counter(
                    routed.request.messages, routed.request.system, routed.request.tools
                )
                logger.info(
                    "COUNT_TOKENS: request_id={} model={} messages={} input_tokens={}",
                    request_id,
                    routed.request.model,
                    len(routed.request.messages),
                    tokens,
                )
                return TokenCountResponse(input_tokens=tokens)
            except ProviderError:
                raise
            except Exception as e:
                _log_unexpected_service_exception(
                    self._settings,
                    e,
                    context="COUNT_TOKENS_ERROR",
                    request_id=request_id,
                )
                raise HTTPException(
                    status_code=_http_status_for_unexpected_service_exception(e),
                    detail=get_user_facing_error_message(e),
                ) from e
