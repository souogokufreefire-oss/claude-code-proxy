"""Tests for Kimi / Moonshot provider."""

from unittest.mock import MagicMock, patch

import pytest

from providers.base import ProviderConfig

KIMI_DEFAULT_BASE = "https://api.moonshot.ai/v1"


@pytest.fixture
def kimi_config():
    return ProviderConfig(
        api_key="test_kimi_key",
        base_url=KIMI_DEFAULT_BASE,
        rate_limit=10,
        rate_window=60,
        enable_thinking=True,
    )


class MockMessage:
    def __init__(self, role, content, reasoning_content=None):
        self.role = role
        self.content = content
        self.reasoning_content = reasoning_content


class MockRequest:
    def __init__(self, **kwargs):
        self.model = kwargs.get("model", "kimi-k2.6")
        self.messages = kwargs.get("messages", [MockMessage("user", "Hello")])
        self.max_tokens = kwargs.get("max_tokens", 100)
        self.temperature = kwargs.get("temperature")
        self.top_p = kwargs.get("top_p")
        self.system = kwargs.get("system")
        self.stop_sequences = kwargs.get("stop_sequences")
        self.tools = kwargs.get("tools", [])
        self.extra_body = kwargs.get("extra_body", {})
        self.thinking = kwargs.get("thinking")
        self.top_k = kwargs.get("top_k")


def test_default_base_url_constant():
    from providers.defaults import KIMI_DEFAULT_BASE as reexported

    assert KIMI_DEFAULT_BASE == "https://api.moonshot.ai/v1"
    assert reexported == KIMI_DEFAULT_BASE


def test_provider_construction(kimi_config):
    from providers.kimi import KimiProvider

    with patch("providers.openai_compat.AsyncOpenAI"):
        provider = KimiProvider(kimi_config)
    assert provider._api_key == "test_kimi_key"
    assert provider._base_url == KIMI_DEFAULT_BASE


def test_build_request_body_basic(kimi_config):
    from providers.kimi import KimiProvider

    with patch("providers.openai_compat.AsyncOpenAI"):
        provider = KimiProvider(kimi_config)

    request = MockRequest(
        model="kimi-k2.6",
        messages=[MockMessage("user", "Hello")],
        max_tokens=100,
        system="System prompt",
    )
    body = provider._build_request_body(request, thinking_enabled=False)
    assert body["model"] == "kimi-k2.6"
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["role"] == "user"


def test_build_request_body_replays_reasoning_content_when_thinking_on(kimi_config):
    from providers.kimi import KimiProvider

    with patch("providers.openai_compat.AsyncOpenAI"):
        provider = KimiProvider(kimi_config)

    request = MockRequest(
        messages=[
            MockMessage(
                "assistant",
                [
                    {
                        "type": "thinking",
                        "thinking": "used hidden reasoning",
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "Read",
                        "input": {"file_path": "a.py"},
                    },
                ],
            )
        ]
    )
    body = provider._build_request_body(request, thinking_enabled=True)

    assert body["messages"][0]["role"] == "assistant"
    assert body["messages"][0]["reasoning_content"] == "used hidden reasoning"


def test_catalog_descriptor():
    from config.provider_catalog import PROVIDER_CATALOG

    assert "kimi" in PROVIDER_CATALOG
    desc = PROVIDER_CATALOG["kimi"]
    assert desc.provider_id == "kimi"
    assert desc.transport_type == "openai_chat"
    assert desc.credential_env == "KIMI_API_KEY"
    assert desc.default_base_url == KIMI_DEFAULT_BASE


def test_factory_creates_correct_type():
    from providers.kimi import KimiProvider
    from providers.registry import create_provider

    settings = MagicMock()
    settings.kimi_api_key = "test_key"
    settings.kimi_api_keys = ()
    settings.kimi_key_usage_limit = 0
    settings.kimi_proxy = ""
    settings.provider_rate_limit = 40
    settings.provider_rate_window = 60
    settings.provider_max_concurrency = 5
    settings.provider_max_retries = 8
    settings.provider_retry_base_delay = 2.0
    settings.provider_retry_max_delay = 120.0
    settings.http_read_timeout = None
    settings.http_write_timeout = 10.0
    settings.http_connect_timeout = 10.0
    settings.enable_model_thinking = True
    settings.log_raw_sse_events = False
    settings.log_api_error_tracebacks = False

    with patch("providers.openai_compat.AsyncOpenAI"):
        provider = create_provider("kimi", settings)
    assert isinstance(provider, KimiProvider)
