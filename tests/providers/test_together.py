"""Tests for Together AI provider (OpenAI-compatible chat completions)."""

from unittest.mock import MagicMock, patch

import pytest

from providers.base import ProviderConfig

TOGETHER_DEFAULT_BASE = "https://api.together.xyz/v1"


@pytest.fixture
def together_config():
    return ProviderConfig(
        api_key="test_together_key",
        base_url=TOGETHER_DEFAULT_BASE,
        rate_limit=10,
        rate_window=60,
        enable_thinking=True,
    )


class MockMessage:
    def __init__(self, role, content):
        self.role = role
        self.content = content


class MockRequest:
    def __init__(self, **kwargs):
        self.model = kwargs.get("model", "test-model")
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
    from providers.defaults import TOGETHER_DEFAULT_BASE as reexported

    assert TOGETHER_DEFAULT_BASE == "https://api.together.xyz/v1"
    assert reexported == TOGETHER_DEFAULT_BASE


def test_provider_construction(together_config):
    from providers.together import TogetherProvider

    with patch("providers.openai_compat.AsyncOpenAI"):
        provider = TogetherProvider(together_config)
    assert provider._api_key == "test_together_key"
    assert provider._base_url == TOGETHER_DEFAULT_BASE


def test_build_request_body_basic(together_config):
    from providers.together import TogetherProvider

    with patch("providers.openai_compat.AsyncOpenAI"):
        provider = TogetherProvider(together_config)

    request = MockRequest(
        model="meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
        messages=[MockMessage("user", "Hello")],
        max_tokens=100,
    )
    body = provider._build_request_body(request, thinking_enabled=False)
    assert body["model"] == "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8"


def test_catalog_descriptor():
    from config.provider_catalog import PROVIDER_CATALOG

    assert "together" in PROVIDER_CATALOG
    desc = PROVIDER_CATALOG["together"]
    assert desc.provider_id == "together"
    assert desc.transport_type == "openai_chat"
    assert desc.credential_env == "TOGETHER_API_KEY"
    assert desc.default_base_url == TOGETHER_DEFAULT_BASE


def test_factory_creates_correct_type():
    from providers.registry import create_provider
    from providers.together import TogetherProvider

    settings = MagicMock()
    settings.together_api_key = "test_key"
    settings.together_api_keys = ()
    settings.together_key_usage_limit = 0
    settings.together_proxy = ""
    settings.provider_rate_limit = 40
    settings.provider_rate_window = 60
    settings.provider_max_concurrency = 5
    settings.http_read_timeout = 300.0
    settings.http_write_timeout = 10.0
    settings.http_connect_timeout = 10.0
    settings.enable_model_thinking = True

    with patch("providers.openai_compat.AsyncOpenAI"):
        provider = create_provider("together", settings)
    assert isinstance(provider, TogetherProvider)
