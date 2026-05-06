"""Kimi / Moonshot provider implementation (OpenAI-compatible chat completions)."""

from typing import Any

from providers.base import ProviderConfig
from providers.defaults import KIMI_DEFAULT_BASE
from providers.openai_compat import OpenAIChatTransport

from .request import build_request_body


class KimiProvider(OpenAIChatTransport):
    """Kimi using Moonshot's OpenAI-compatible /chat/completions endpoint."""

    def __init__(self, config: ProviderConfig):
        super().__init__(
            config,
            provider_name="KIMI",
            base_url=config.base_url or KIMI_DEFAULT_BASE,
            api_key=config.api_key,
        )

    def _build_request_body(
        self, request: Any, thinking_enabled: bool | None = None
    ) -> dict:
        return build_request_body(
            request,
            thinking_enabled=self._is_thinking_enabled(request, thinking_enabled),
        )
