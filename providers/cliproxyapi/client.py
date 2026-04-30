"""CLIProxyAPI provider implementation (Anthropic Messages via Claude Code OAuth)."""

from providers.anthropic_messages import AnthropicMessagesTransport
from providers.base import ProviderConfig
from providers.defaults import CLIPROXYAPI_DEFAULT_BASE


class CLIProxyAPIProvider(AnthropicMessagesTransport):
    """CLIProxyAPI wrapping Claude Code OAuth as an Anthropic Messages endpoint."""

    def __init__(self, config: ProviderConfig):
        super().__init__(
            config,
            provider_name="CLIPROXYAPI",
            default_base_url=CLIPROXYAPI_DEFAULT_BASE,
        )

    def _request_headers(self) -> dict[str, str]:
        return {
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
        }
