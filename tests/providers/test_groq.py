"""Tests for Groq provider (OpenAI-compatible chat completions)."""

from unittest.mock import MagicMock, patch

import pytest

from providers.base import ProviderConfig

GROQ_DEFAULT_BASE = "https://api.groq.com/openai/v1"


@pytest.fixture
def groq_config():
    return ProviderConfig(
        api_key="test_groq_key",
        base_url=GROQ_DEFAULT_BASE,
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
    from providers.defaults import GROQ_DEFAULT_BASE as reexported

    assert GROQ_DEFAULT_BASE == "https://api.groq.com/openai/v1"
    assert reexported == GROQ_DEFAULT_BASE


def test_provider_construction(groq_config):
    from providers.groq import GroqProvider

    with patch("providers.openai_compat.AsyncOpenAI"):
        provider = GroqProvider(groq_config)
    assert provider._api_key == "test_groq_key"
    assert provider._base_url == "https://api.groq.com/openai/v1"


def test_build_request_body_basic(groq_config):
    from providers.groq import GroqProvider

    with patch("providers.openai_compat.AsyncOpenAI"):
        provider = GroqProvider(groq_config)

    request = MockRequest(
        model="llama-4-maverick-17b-128e",
        messages=[MockMessage("user", "Hello")],
        max_tokens=100,
        system="You are helpful.",
    )
    body = provider._build_request_body(request, thinking_enabled=False)

    assert body["model"] == "llama-4-maverick-17b-128e"
    assert body["stream"] is True
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][0]["content"] == "You are helpful."
    assert body["messages"][1]["role"] == "user"


def test_build_request_body_with_tools(groq_config):
    from providers.groq import GroqProvider

    with patch("providers.openai_compat.AsyncOpenAI"):
        provider = GroqProvider(groq_config)

    class MockTool:
        def __init__(self, name, description, input_schema):
            self.name = name
            self.description = description
            self.input_schema = input_schema

    request = MockRequest(
        model="llama-4-maverick-17b-128e",
        messages=[MockMessage("user", "search for cats")],
        tools=[MockTool("search", "Search the web", {"type": "object"})],
    )
    body = provider._build_request_body(request, thinking_enabled=False)
    assert "tools" in body
    assert len(body["tools"]) == 1
    assert body["tools"][0]["type"] == "function"


def test_catalog_descriptor():
    from config.provider_catalog import PROVIDER_CATALOG

    assert "groq" in PROVIDER_CATALOG
    desc = PROVIDER_CATALOG["groq"]
    assert desc.provider_id == "groq"
    assert desc.transport_type == "openai_chat"
    assert desc.credential_env == "GROQ_API_KEY"
    assert desc.default_base_url == GROQ_DEFAULT_BASE


def test_factory_creates_correct_type():
    from providers.groq import GroqProvider
    from providers.registry import create_provider

    settings = MagicMock()
    settings.groq_api_key = "test_key"
    settings.groq_api_keys = ()
    settings.groq_key_usage_limit = 0
    settings.groq_proxy = ""
    settings.provider_rate_limit = 40
    settings.provider_rate_window = 60
    settings.provider_max_concurrency = 5
    settings.http_read_timeout = 300.0
    settings.http_write_timeout = 10.0
    settings.http_connect_timeout = 10.0
    settings.enable_model_thinking = True

    with patch("providers.openai_compat.AsyncOpenAI"):
        provider = create_provider("groq", settings)
    assert isinstance(provider, GroqProvider)
