"""Cerebras provider implementation (OpenAI-compatible chat completions)."""

from copy import deepcopy
from typing import Any

import openai
from loguru import logger

from providers.base import ProviderConfig
from providers.defaults import CEREBRAS_DEFAULT_BASE
from providers.openai_compat import OpenAIChatTransport

from .request import build_request_body


class CerebrasProvider(OpenAIChatTransport):
    """Cerebras using OpenAI-compatible /chat/completions endpoint."""

    def __init__(self, config: ProviderConfig):
        super().__init__(
            config,
            provider_name="CEREBRAS",
            base_url=config.base_url or CEREBRAS_DEFAULT_BASE,
            api_key=config.api_key,
        )

    def _build_request_body(
        self, request: Any, thinking_enabled: bool | None = None
    ) -> dict:
        return build_request_body(
            request,
            thinking_enabled=self._is_thinking_enabled(request, thinking_enabled),
        )

    def _get_retry_request_body(self, error: Exception, body: dict) -> dict | None:
        """Retry without reasoning_effort when Cerebras rejects it (400)."""
        if not isinstance(error, openai.BadRequestError):
            return None

        error_text = str(error).lower()
        if "reasoning_effort" not in error_text:
            return None

        if "reasoning_effort" not in body:
            return None

        retry_body = deepcopy(body)
        retry_body.pop("reasoning_effort", None)
        logger.warning(
            "CEREBRAS_STREAM: retrying without reasoning_effort after 400 error"
        )
        return retry_body
