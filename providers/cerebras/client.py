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
        """Retry without reasoning params Cerebras rejects (400)."""
        if not isinstance(error, openai.BadRequestError):
            return None

        error_text = str(error).lower()
        reasoning_keys = ("reasoning_effort", "clear_thinking")
        if not any(key in error_text for key in reasoning_keys):
            return None

        retry_body = deepcopy(body)
        dropped: list[str] = []
        for key in reasoning_keys:
            if key in error_text and key in body:
                retry_body.pop(key, None)
                dropped.append(key)
        if not dropped:
            return None
        logger.warning(
            "CEREBRAS_STREAM: retrying without {} after 400 error",
            ", ".join(dropped),
        )
        return retry_body
