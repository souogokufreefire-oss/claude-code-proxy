"""Application runtime composition and lifecycle ownership."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI
from loguru import logger

from config.settings import Settings, get_settings
from core.metrics import metrics_registry
from providers.registry import ProviderRegistry

_SHUTDOWN_TIMEOUT_S = 5.0


async def _periodic_metrics_summary(interval_s: float) -> None:
    """Log a per-provider metrics summary every ``interval_s`` seconds."""
    while True:
        await asyncio.sleep(interval_s)
        metrics_registry.log_summary()


async def best_effort(
    name: str,
    awaitable: Any,
    timeout_s: float = _SHUTDOWN_TIMEOUT_S,
    *,
    log_verbose_errors: bool = False,
) -> None:
    """Run a shutdown step with timeout; never raise to callers."""
    try:
        await asyncio.wait_for(awaitable, timeout=timeout_s)
    except TimeoutError:
        logger.warning("Shutdown step timed out: {} ({}s)", name, timeout_s)
    except Exception as e:
        if log_verbose_errors:
            logger.warning(
                "Shutdown step failed: {}: {}: {}",
                name,
                type(e).__name__,
                e,
            )
        else:
            logger.warning(
                "Shutdown step failed: {}: exc_type={}",
                name,
                type(e).__name__,
            )


def warn_if_process_auth_token(settings: Settings) -> None:
    """Warn when server auth was implicitly inherited from the shell."""
    if settings.uses_process_anthropic_auth_token():
        logger.warning(
            "ANTHROPIC_AUTH_TOKEN is set in the process environment but not in "
            "a configured .env file. The proxy will require that token. Add "
            "ANTHROPIC_AUTH_TOKEN= to .env to disable proxy auth, or set the "
            "same token in .env to make server auth explicit."
        )


def log_model_configuration(settings: Settings) -> None:
    """Log the resolved Claude-to-provider model routing on startup."""
    logger.info(
        "Configured model routing: default={} opus={} sonnet={} haiku={}",
        settings.model,
        settings.model_opus or "<inherit default>",
        settings.model_sonnet or "<inherit default>",
        settings.model_haiku or "<inherit default>",
    )


@dataclass(slots=True)
class AppRuntime:
    """Own proxy runtime resources."""

    app: FastAPI
    settings: Settings
    _provider_registry: ProviderRegistry | None = field(default=None, init=False)
    _metrics_task: asyncio.Task | None = field(default=None, init=False)

    @classmethod
    def for_app(
        cls,
        app: FastAPI,
        settings: Settings | None = None,
    ) -> AppRuntime:
        return cls(app=app, settings=settings or get_settings())

    async def startup(self) -> None:
        logger.info("Starting Claude Code Proxy...")
        self._provider_registry = ProviderRegistry()
        self.app.state.provider_registry = self._provider_registry
        log_model_configuration(self.settings)
        warn_if_process_auth_token(self.settings)
        interval = self.settings.metrics_log_interval_seconds
        if interval > 0:
            self._metrics_task = asyncio.create_task(
                _periodic_metrics_summary(interval)
            )

    async def shutdown(self) -> None:
        verbose = self.settings.log_api_error_tracebacks
        logger.info("Shutdown requested, cleaning up...")
        if self._metrics_task is not None:
            self._metrics_task.cancel()
            await best_effort(
                "metrics_task.cancel",
                asyncio.gather(self._metrics_task, return_exceptions=True),
            )
        if self._provider_registry is not None:
            await best_effort(
                "provider_registry.cleanup",
                self._provider_registry.cleanup(),
                log_verbose_errors=verbose,
            )
        metrics_registry.log_summary()
        logger.info("Server shut down cleanly")
