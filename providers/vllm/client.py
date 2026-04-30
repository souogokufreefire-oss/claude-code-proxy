"""vLLM provider implementation (native Anthropic Messages)."""

from providers.anthropic_messages import AnthropicMessagesTransport
from providers.base import ProviderConfig
from providers.defaults import VLLM_DEFAULT_BASE


class VllmProvider(AnthropicMessagesTransport):
    """vLLM using native Anthropic Messages API endpoint."""

    def __init__(self, config: ProviderConfig):
        super().__init__(
            config,
            provider_name="VLLM",
            default_base_url=VLLM_DEFAULT_BASE,
        )

    def _request_headers(self) -> dict[str, str]:
        return {
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
