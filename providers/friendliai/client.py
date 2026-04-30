"""FriendliAI provider implementation (native Anthropic Messages)."""

from providers.anthropic_messages import AnthropicMessagesTransport
from providers.base import ProviderConfig
from providers.defaults import FRIENDLIAI_DEFAULT_BASE


class FriendliAIProvider(AnthropicMessagesTransport):
    """FriendliAI using native Anthropic Messages API (serverless/dedicated)."""

    def __init__(self, config: ProviderConfig):
        super().__init__(
            config,
            provider_name="FRIENDLIAI",
            default_base_url=FRIENDLIAI_DEFAULT_BASE,
        )

    def _request_headers(self) -> dict[str, str]:
        return {
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
