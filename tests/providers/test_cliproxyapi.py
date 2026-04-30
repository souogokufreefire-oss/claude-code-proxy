"""Tests for CLIProxyAPI Anthropic Messages provider (x-api-key auth)."""

from unittest.mock import MagicMock, patch

import pytest

from api.models.anthropic import Message, MessagesRequest
from providers.base import ProviderConfig

CLIPROXYAPI_DEFAULT_BASE = "http://localhost:8317/v1"


@pytest.fixture
def cliproxyapi_config():
    return ProviderConfig(
        api_key="dummy",
        base_url=CLIPROXYAPI_DEFAULT_BASE,
        rate_limit=10,
        rate_window=60,
        enable_thinking=True,
    )


def test_default_base_url_constant():
    """Verify the canonical default base URL for CLIProxyAPI."""
    from providers.defaults import CLIPROXYAPI_DEFAULT_BASE as reexported

    assert CLIPROXYAPI_DEFAULT_BASE == "http://localhost:8317/v1"
    assert reexported == CLIPROXYAPI_DEFAULT_BASE


def test_provider_construction(cliproxyapi_config):
    """Provider is constructable with static credential 'dummy'."""
    from providers.cliproxyapi import CLIProxyAPIProvider

    with patch("httpx.AsyncClient"):
        provider = CLIProxyAPIProvider(cliproxyapi_config)
    assert provider._api_key == "dummy"
    assert provider._base_url == "http://localhost:8317/v1"


def test_request_headers_uses_x_api_key_not_bearer(cliproxyapi_config):
    """CLIProxyAPI uses x-api-key header (not Authorization: Bearer)."""
    from providers.cliproxyapi import CLIProxyAPIProvider

    with patch("httpx.AsyncClient"):
        provider = CLIProxyAPIProvider(cliproxyapi_config)
    headers = provider._request_headers()
    assert headers["x-api-key"] == "dummy"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "text/event-stream"
    assert "Authorization" not in headers


def test_build_request_body_passthrough(cliproxyapi_config):
    """Request body uses Claude model names (no special conversion needed)."""
    from providers.cliproxyapi import CLIProxyAPIProvider

    with patch("httpx.AsyncClient"):
        provider = CLIProxyAPIProvider(cliproxyapi_config)
    request = MessagesRequest(
        model="claude-sonnet-4-5-20250929",
        max_tokens=100,
        messages=[Message(role="user", content="Hello")],
        system="You are Claude.",
    )
    body = provider._build_request_body(request)
    assert body["model"] == "claude-sonnet-4-5-20250929"
    assert body["stream"] is True
    assert body["system"] == "You are Claude."


def test_catalog_descriptor():
    """CLIProxyAPI is a local provider with static credential and thinking support."""
    from config.provider_catalog import PROVIDER_CATALOG

    assert "cliproxyapi" in PROVIDER_CATALOG
    desc = PROVIDER_CATALOG["cliproxyapi"]
    assert desc.provider_id == "cliproxyapi"
    assert desc.transport_type == "anthropic_messages"
    assert desc.static_credential == "dummy"
    assert desc.default_base_url == CLIPROXYAPI_DEFAULT_BASE
    assert "local" in desc.capabilities
    assert "thinking" in desc.capabilities


def test_factory_creates_correct_type():
    """Registry factory produces CLIProxyAPIProvider."""
    from providers.cliproxyapi import CLIProxyAPIProvider
    from providers.registry import create_provider

    settings = MagicMock()
    settings.cliproxyapi_base_url = "http://localhost:8317/v1"
    settings.cliproxyapi_proxy = ""
    settings.provider_rate_limit = 40
    settings.provider_rate_window = 60
    settings.provider_max_concurrency = 5
    settings.http_read_timeout = 300.0
    settings.http_write_timeout = 10.0
    settings.http_connect_timeout = 10.0
    settings.enable_model_thinking = True

    with patch("httpx.AsyncClient"):
        provider = create_provider("cliproxyapi", settings)
    assert isinstance(provider, CLIProxyAPIProvider)
