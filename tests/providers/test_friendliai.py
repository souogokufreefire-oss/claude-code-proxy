"""Tests for FriendliAI native Anthropic Messages provider."""

from unittest.mock import MagicMock, patch

import pytest

from api.models.anthropic import Message, MessagesRequest
from providers.base import ProviderConfig

FRIENDLIAI_DEFAULT_BASE = "https://api.friendli.ai/serverless/v1"


@pytest.fixture
def friendliai_config():
    return ProviderConfig(
        api_key="test_friendliai_key",
        base_url=FRIENDLIAI_DEFAULT_BASE,
        rate_limit=10,
        rate_window=60,
        enable_thinking=True,
    )


def test_default_base_url_constant():
    """Verify the canonical default base URL for FriendliAI."""
    from providers.defaults import FRIENDLIAI_DEFAULT_BASE as reexported

    assert FRIENDLIAI_DEFAULT_BASE == "https://api.friendli.ai/serverless/v1"
    assert reexported == FRIENDLIAI_DEFAULT_BASE


def test_provider_construction(friendliai_config):
    """Provider is constructable with correct base URL and API key."""
    from providers.friendliai import FriendliAIProvider

    with patch("httpx.AsyncClient"):
        provider = FriendliAIProvider(friendliai_config)
    assert provider._api_key == "test_friendliai_key"
    assert provider._base_url == "https://api.friendli.ai/serverless/v1"


def test_request_headers_uses_bearer_auth(friendliai_config):
    """FriendliAI uses Authorization: Bearer (not x-api-key)."""
    from providers.friendliai import FriendliAIProvider

    with patch("httpx.AsyncClient"):
        provider = FriendliAIProvider(friendliai_config)
    headers = provider._request_headers()
    assert headers["Authorization"] == "Bearer test_friendliai_key"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "text/event-stream"
    assert "x-api-key" not in headers


def test_build_request_body_passthrough(friendliai_config):
    """Request body is built as standard Anthropic Messages format."""
    from providers.friendliai import FriendliAIProvider

    with patch("httpx.AsyncClient"):
        provider = FriendliAIProvider(friendliai_config)
    request = MessagesRequest(
        model="meta-llama/Llama-4-Maverick-17B-128E-Instruct",
        max_tokens=100,
        messages=[Message(role="user", content="Hello")],
        system="You are helpful.",
    )
    body = provider._build_request_body(request)
    assert body["model"] == "meta-llama/Llama-4-Maverick-17B-128E-Instruct"
    assert body["stream"] is True
    assert body["messages"][0]["role"] == "user"
    assert body["system"] == "You are helpful."
    assert body["max_tokens"] == 100


def test_base_url_override(friendliai_config):
    """Config base_url overrides the provider default."""
    from providers.friendliai import FriendliAIProvider

    custom_url = "https://custom.friendli.ai/v1"
    config = ProviderConfig(
        api_key="key",
        base_url=custom_url,
        rate_limit=10,
        rate_window=60,
    )
    with patch("httpx.AsyncClient"):
        provider = FriendliAIProvider(config)
    assert provider._base_url == custom_url


def test_catalog_descriptor():
    """FriendliAI is registered in the provider catalog with correct metadata."""
    from config.provider_catalog import PROVIDER_CATALOG

    assert "friendliai" in PROVIDER_CATALOG
    desc = PROVIDER_CATALOG["friendliai"]
    assert desc.provider_id == "friendliai"
    assert desc.transport_type == "anthropic_messages"
    assert desc.credential_env == "FRIENDLIAI_API_KEY"
    assert desc.default_base_url == FRIENDLIAI_DEFAULT_BASE
    assert "native_anthropic" in desc.capabilities


def test_factory_creates_correct_type():
    """Registry factory produces FriendliAIProvider."""
    from providers.friendliai import FriendliAIProvider
    from providers.registry import create_provider

    settings = MagicMock()
    settings.friendliai_api_key = "test_key"
    settings.friendliai_api_keys = ()
    settings.friendliai_key_usage_limit = 0
    settings.friendliai_proxy = ""
    settings.provider_rate_limit = 40
    settings.provider_rate_window = 60
    settings.provider_max_concurrency = 5
    settings.http_read_timeout = 300.0
    settings.http_write_timeout = 10.0
    settings.http_connect_timeout = 10.0
    settings.enable_model_thinking = True

    with patch("httpx.AsyncClient"):
        provider = create_provider("friendliai", settings)
    assert isinstance(provider, FriendliAIProvider)
