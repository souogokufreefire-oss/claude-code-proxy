"""Fireworks AI provider implementation (native Anthropic Messages)."""

from providers.anthropic_messages import AnthropicMessagesTransport
from providers.base import ProviderConfig
from providers.defaults import FIREWORKS_DEFAULT_BASE


class FireworksProvider(AnthropicMessagesTransport):
    """Fireworks AI using native Anthropic Messages API endpoint."""

    def __init__(self, config: ProviderConfig):
        super().__init__(
            config,
            provider_name="FIREWORKS",
            default_base_url=FIREWORKS_DEFAULT_BASE,
        )

    def _request_headers(self) -> dict[str, str]:
        return {
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
        }
