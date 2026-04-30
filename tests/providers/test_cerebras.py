"""Tests for Cerebras provider (OpenAI-compatible chat completions)."""

from unittest.mock import MagicMock, patch

import pytest

from providers.base import ProviderConfig

CEREBRAS_DEFAULT_BASE = "https://api.cerebras.ai/v1"


@pytest.fixture
def cerebras_config():
    return ProviderConfig(
        api_key="test_cerebras_key",
        base_url=CEREBRAS_DEFAULT_BASE,
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
    from providers.defaults import CEREBRAS_DEFAULT_BASE as reexported

    assert CEREBRAS_DEFAULT_BASE == "https://api.cerebras.ai/v1"
    assert reexported == CEREBRAS_DEFAULT_BASE


def test_provider_construction(cerebras_config):
    from providers.cerebras import CerebrasProvider

    with patch("providers.openai_compat.AsyncOpenAI"):
        provider = CerebrasProvider(cerebras_config)
    assert provider._api_key == "test_cerebras_key"
    assert provider._base_url == CEREBRAS_DEFAULT_BASE


def test_build_request_body_basic(cerebras_config):
    from providers.cerebras import CerebrasProvider

    with patch("providers.openai_compat.AsyncOpenAI"):
        provider = CerebrasProvider(cerebras_config)

    request = MockRequest(
        model="llama-4-maverick-17b",
        messages=[MockMessage("user", "Hello")],
        max_tokens=100,
        system="System prompt",
    )
    body = provider._build_request_body(request, thinking_enabled=False)
    assert body["model"] == "llama-4-maverick-17b"
    assert body["stream"] is True
    assert body["messages"][0]["role"] == "system"


def test_catalog_descriptor():
    from config.provider_catalog import PROVIDER_CATALOG

    assert "cerebras" in PROVIDER_CATALOG
    desc = PROVIDER_CATALOG["cerebras"]
    assert desc.provider_id == "cerebras"
    assert desc.transport_type == "openai_chat"
    assert desc.credential_env == "CEREBRAS_API_KEY"
    assert desc.default_base_url == CEREBRAS_DEFAULT_BASE


def test_factory_creates_correct_type():
    from providers.cerebras import CerebrasProvider
    from providers.registry import create_provider

    settings = MagicMock()
    settings.cerebras_api_key = "test_key"
    settings.cerebras_api_keys = ()
    settings.cerebras_key_usage_limit = 0
    settings.cerebras_proxy = ""
    settings.provider_rate_limit = 40
    settings.provider_rate_window = 60
    settings.provider_max_concurrency = 5
    settings.http_read_timeout = 300.0
    settings.http_write_timeout = 10.0
    settings.http_connect_timeout = 10.0
    settings.enable_model_thinking = True

    with patch("providers.openai_compat.AsyncOpenAI"):
        provider = create_provider("cerebras", settings)
    assert isinstance(provider, CerebrasProvider)
