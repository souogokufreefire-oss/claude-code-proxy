"""Tests for Fireworks AI native Anthropic Messages provider."""

from unittest.mock import MagicMock, patch

import pytest

from api.models.anthropic import Message, MessagesRequest
from providers.base import ProviderConfig

FIREWORKS_DEFAULT_BASE = "https://api.fireworks.ai/inference/v1"


@pytest.fixture
def fireworks_config():
    return ProviderConfig(
        api_key="test_fireworks_key",
        base_url=FIREWORKS_DEFAULT_BASE,
        rate_limit=10,
        rate_window=60,
        enable_thinking=True,
    )


def test_default_base_url_constant():
    """Verify the canonical default base URL for Fireworks AI."""
    from providers.defaults import FIREWORKS_DEFAULT_BASE as reexported

    assert FIREWORKS_DEFAULT_BASE == "https://api.fireworks.ai/inference/v1"
    assert reexported == FIREWORKS_DEFAULT_BASE


def test_provider_construction(fireworks_config):
    """Provider is constructable with correct base URL and API key."""
    from providers.fireworks import FireworksProvider

    with patch("httpx.AsyncClient"):
        provider = FireworksProvider(fireworks_config)
    assert provider._api_key == "test_fireworks_key"
    assert provider._base_url == "https://api.fireworks.ai/inference/v1"


def test_request_headers_uses_x_api_key(fireworks_config):
    """Fireworks AI uses x-api-key header (not Authorization: Bearer)."""
    from providers.fireworks import FireworksProvider

    with patch("httpx.AsyncClient"):
        provider = FireworksProvider(fireworks_config)
    headers = provider._request_headers()
    assert headers["x-api-key"] == "test_fireworks_key"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "text/event-stream"
    assert "Authorization" not in headers


def test_build_request_body_passthrough(fireworks_config):
    """Request body is built as standard Anthropic Messages format."""
    from providers.fireworks import FireworksProvider

    with patch("httpx.AsyncClient"):
        provider = FireworksProvider(fireworks_config)
    request = MessagesRequest(
        model="accounts/fireworks/models/llama-v4-maverick-17b",
        max_tokens=100,
        messages=[Message(role="user", content="Hello")],
        system="You are helpful.",
    )
    body = provider._build_request_body(request)
    assert body["model"] == "accounts/fireworks/models/llama-v4-maverick-17b"
    assert body["stream"] is True
    assert body["messages"][0]["role"] == "user"
    assert body["system"] == "You are helpful."


def test_base_url_override():
    """Config base_url overrides the provider default."""
    from providers.fireworks import FireworksProvider

    custom_url = "https://custom.fireworks.ai/v1"
    config = ProviderConfig(
        api_key="key",
        base_url=custom_url,
        rate_limit=10,
        rate_window=60,
    )
    with patch("httpx.AsyncClient"):
        provider = FireworksProvider(config)
    assert provider._base_url == custom_url


def test_catalog_descriptor():
    """Fireworks AI is registered in the provider catalog."""
    from config.provider_catalog import PROVIDER_CATALOG

    assert "fireworks" in PROVIDER_CATALOG
    desc = PROVIDER_CATALOG["fireworks"]
    assert desc.provider_id == "fireworks"
    assert desc.transport_type == "anthropic_messages"
    assert desc.credential_env == "FIREWORKS_API_KEY"
    assert desc.default_base_url == FIREWORKS_DEFAULT_BASE
    assert "native_anthropic" in desc.capabilities


def test_factory_creates_correct_type():
    """Registry factory produces FireworksProvider."""
    from providers.fireworks import FireworksProvider
    from providers.registry import create_provider

    settings = MagicMock()
    settings.fireworks_api_key = "test_key"
    settings.fireworks_api_keys = ()
    settings.fireworks_key_usage_limit = 0
    settings.fireworks_proxy = ""
    settings.provider_rate_limit = 40
    settings.provider_rate_window = 60
    settings.provider_max_concurrency = 5
    settings.http_read_timeout = 300.0
    settings.http_write_timeout = 10.0
    settings.http_connect_timeout = 10.0
    settings.enable_model_thinking = True

    with patch("httpx.AsyncClient"):
        provider = create_provider("fireworks", settings)
    assert isinstance(provider, FireworksProvider)
