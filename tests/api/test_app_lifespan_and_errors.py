import importlib
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from config.settings import Settings
from providers.registry import ProviderRegistry


def _app_settings(**kwargs):
    """Minimal settings namespace for proxy AppRuntime tests."""
    data = {
        "uses_process_anthropic_auth_token": lambda: False,
        "log_api_error_tracebacks": False,
        "log_raw_api_payloads": False,
        "log_file": "server.log",
        "model": "nvidia_nim/moonshotai/kimi-k2-thinking",
        "model_opus": None,
        "model_sonnet": "open_router/anthropic/claude-sonnet-4.5",
        "model_haiku": None,
        "metrics_log_interval_seconds": 0,
        **kwargs,
    }
    return SimpleNamespace(**data)


def test_warn_if_process_auth_token_logs_warning():
    api_runtime_mod = importlib.import_module("api.runtime")
    settings = cast(
        Settings, SimpleNamespace(uses_process_anthropic_auth_token=lambda: True)
    )

    with patch.object(api_runtime_mod.logger, "warning") as warning:
        api_runtime_mod.warn_if_process_auth_token(settings)

    warning.assert_called_once()
    assert "ANTHROPIC_AUTH_TOKEN" in warning.call_args.args[0]


def test_warn_if_process_auth_token_skips_explicit_dotenv_config():
    api_runtime_mod = importlib.import_module("api.runtime")
    settings = cast(
        Settings, SimpleNamespace(uses_process_anthropic_auth_token=lambda: False)
    )

    with patch.object(api_runtime_mod.logger, "warning") as warning:
        api_runtime_mod.warn_if_process_auth_token(settings)

    warning.assert_not_called()


def test_log_model_configuration_logs_effective_routing():
    api_runtime_mod = importlib.import_module("api.runtime")
    settings = cast(Settings, _app_settings())

    with patch.object(api_runtime_mod.logger, "info") as info:
        api_runtime_mod.log_model_configuration(settings)

    info.assert_called_once_with(
        "Configured model routing: default={} opus={} sonnet={} haiku={}",
        "nvidia_nim/moonshotai/kimi-k2-thinking",
        "<inherit default>",
        "open_router/anthropic/claude-sonnet-4.5",
        "<inherit default>",
    )


def test_create_app_provider_error_handler_returns_anthropic_format():
    from api.app import create_app
    from providers.exceptions import AuthenticationError

    app = create_app()

    @app.get("/raise_provider")
    async def _raise_provider():
        raise AuthenticationError("bad key")

    api_app_mod = importlib.import_module("api.app")
    settings = _app_settings()
    with (
        patch.object(api_app_mod, "get_settings", return_value=settings),
        patch.object(ProviderRegistry, "cleanup", new=AsyncMock()),
    ):
        with TestClient(app) as client:
            resp = client.get("/raise_provider")
        assert resp.status_code == 401
    body = resp.json()
    assert body["type"] == "error"
    assert body["error"]["type"] == "authentication_error"


def test_create_app_provider_error_default_logs_exclude_provider_message():
    """Provider errors must not log exc.message by default."""
    from api.app import create_app
    from providers.exceptions import AuthenticationError

    app = create_app()
    secret = "provider-upstream-secret-detail"

    @app.get("/raise_provider_secret")
    async def _raise():
        raise AuthenticationError(secret)

    api_app_mod = importlib.import_module("api.app")
    settings = _app_settings(log_api_error_tracebacks=False)
    with (
        patch.object(api_app_mod, "get_settings", return_value=settings),
        patch.object(ProviderRegistry, "cleanup", new=AsyncMock()),
        patch.object(api_app_mod.logger, "error") as log_err,
    ):
        with TestClient(app) as client:
            resp = client.get("/raise_provider_secret")
        assert resp.status_code == 401

    blob = " ".join(str(a) for c in log_err.call_args_list for a in c.args)
    blob += repr([c.kwargs for c in log_err.call_args_list])
    assert secret not in blob
    assert "authentication_error" in blob


def test_create_app_general_exception_handler_returns_500():
    from api.app import create_app

    app = create_app()

    @app.get("/raise_general")
    async def _raise_general():
        raise RuntimeError("boom")

    api_app_mod = importlib.import_module("api.app")
    settings = _app_settings()
    with (
        patch.object(api_app_mod, "get_settings", return_value=settings),
        patch.object(ProviderRegistry, "cleanup", new=AsyncMock()),
    ):
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/raise_general")
        assert resp.status_code == 500
        body = resp.json()
        assert body["type"] == "error"
        assert body["error"]["type"] == "api_error"


def test_create_app_general_exception_default_logs_exclude_exception_message():
    """Unhandled errors must not log exception text by default (may echo user content)."""
    from api.app import create_app

    app = create_app()
    secret = "user-provided-secret-token-xyzzy"

    @app.get("/raise_secret")
    async def _raise_secret():
        raise ValueError(secret)

    api_app_mod = importlib.import_module("api.app")
    settings = _app_settings(log_api_error_tracebacks=False)
    with (
        patch.object(api_app_mod, "get_settings", return_value=settings),
        patch.object(ProviderRegistry, "cleanup", new=AsyncMock()),
        patch.object(api_app_mod.logger, "error") as log_err,
    ):
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/raise_secret")
        assert resp.status_code == 500

    flattened: list[str] = []
    for call in log_err.call_args_list:
        flattened.extend(str(arg) for arg in call.args)
        flattened.append(repr(call.kwargs))
    blob = " ".join(flattened)
    assert secret not in blob
    assert "ValueError" in blob


def test_app_lifespan_sets_provider_registry_and_cleans_up():
    from api.app import create_app

    app = create_app()
    settings = _app_settings()
    api_app_mod = importlib.import_module("api.app")
    registry_cleanup = AsyncMock()

    with (
        patch.object(api_app_mod, "get_settings", return_value=settings),
        patch.object(ProviderRegistry, "cleanup", new=registry_cleanup),
        TestClient(app),
    ):
        assert isinstance(app.state.provider_registry, ProviderRegistry)

    registry_cleanup.assert_awaited_once()


def test_app_lifespan_cleanup_continues_if_provider_cleanup_raises():
    from api.app import create_app

    app = create_app()
    settings = _app_settings()
    api_app_mod = importlib.import_module("api.app")
    registry_cleanup = AsyncMock(side_effect=RuntimeError("cleanup failed"))

    with (
        patch.object(api_app_mod, "get_settings", return_value=settings),
        patch.object(ProviderRegistry, "cleanup", new=registry_cleanup),
        TestClient(app),
    ):
        pass

    registry_cleanup.assert_awaited_once()
