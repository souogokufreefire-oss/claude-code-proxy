"""Tests for vLLM native Anthropic Messages provider."""

from unittest.mock import MagicMock, patch

import pytest

from api.models.anthropic import Message, MessagesRequest
from providers.base import ProviderConfig

VLLM_DEFAULT_BASE = "http://localhost:8000/v1"


@pytest.fixture
def vllm_config():
    return ProviderConfig(
        api_key="vllm",
        base_url=VLLM_DEFAULT_BASE,
        rate_limit=10,
        rate_window=60,
        enable_thinking=True,
    )


def test_default_base_url_constant():
    """Verify the canonical default base URL for vLLM."""
    from providers.defaults import VLLM_DEFAULT_BASE as reexported

    assert VLLM_DEFAULT_BASE == "http://localhost:8000/v1"
    assert reexported == VLLM_DEFAULT_BASE


def test_provider_construction(vllm_config):
    """Provider is constructable with correct base URL and static credential."""
    from providers.vllm import VllmProvider

    with patch("httpx.AsyncClient"):
        provider = VllmProvider(vllm_config)
    assert provider._api_key == "vllm"
    assert provider._base_url == "http://localhost:8000/v1"


def test_request_headers_uses_bearer_auth(vllm_config):
    """vLLM uses Authorization: Bearer with the static credential."""
    from providers.vllm import VllmProvider

    with patch("httpx.AsyncClient"):
        provider = VllmProvider(vllm_config)
    headers = provider._request_headers()
    assert headers["Authorization"] == "Bearer vllm"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "text/event-stream"


def test_build_request_body_passthrough(vllm_config):
    """Request body is built as standard Anthropic Messages format."""
    from providers.vllm import VllmProvider

    with patch("httpx.AsyncClient"):
        provider = VllmProvider(vllm_config)
    request = MessagesRequest(
        model="meta-llama/Llama-4-Maverick-17B-128E-Instruct",
        max_tokens=100,
        messages=[Message(role="user", content="Hello")],
    )
    body = provider._build_request_body(request)
    assert body["model"] == "meta-llama/Llama-4-Maverick-17B-128E-Instruct"
    assert body["stream"] is True
    assert body["messages"][0]["role"] == "user"


def test_base_url_override():
    """Config base_url overrides the provider default."""
    from providers.vllm import VllmProvider

    custom_url = "http://custom:9999/v1"
    config = ProviderConfig(
        api_key="vllm",
        base_url=custom_url,
        rate_limit=10,
        rate_window=60,
    )
    with patch("httpx.AsyncClient"):
        provider = VllmProvider(config)
    assert provider._base_url == custom_url


def test_catalog_descriptor():
    """vLLM is registered in the provider catalog with local capabilities."""
    from config.provider_catalog import PROVIDER_CATALOG

    assert "vllm" in PROVIDER_CATALOG
    desc = PROVIDER_CATALOG["vllm"]
    assert desc.provider_id == "vllm"
    assert desc.transport_type == "anthropic_messages"
    assert desc.static_credential == "vllm"
    assert desc.default_base_url == VLLM_DEFAULT_BASE
    assert "local" in desc.capabilities
    assert "native_anthropic" in desc.capabilities


def test_factory_creates_correct_type():
    """Registry factory produces VllmProvider."""
    from providers.registry import create_provider
    from providers.vllm import VllmProvider

    settings = MagicMock()
    settings.vllm_base_url = "http://localhost:8000/v1"
    settings.vllm_proxy = ""
    settings.provider_rate_limit = 40
    settings.provider_rate_window = 60
    settings.provider_max_concurrency = 5
    settings.http_read_timeout = 300.0
    settings.http_write_timeout = 10.0
    settings.http_connect_timeout = 10.0
    settings.enable_model_thinking = True

    with patch("httpx.AsyncClient"):
        provider = create_provider("vllm", settings)
    assert isinstance(provider, VllmProvider)
