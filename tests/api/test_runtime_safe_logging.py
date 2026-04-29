"""Tests for safe default logging in :mod:`api.runtime`."""

import importlib
import logging

import pytest


@pytest.mark.asyncio
async def test_best_effort_default_logs_exclude_exception_text(caplog):
    api_runtime_mod = importlib.import_module("api.runtime")

    async def boom():
        raise ValueError("SECRET_SHUTDOWN")

    with caplog.at_level(logging.WARNING):
        await api_runtime_mod.best_effort("test_step", boom(), log_verbose_errors=False)

    blob = " | ".join(r.getMessage() for r in caplog.records)
    assert "SECRET_SHUTDOWN" not in blob
    assert "exc_type=ValueError" in blob


@pytest.mark.asyncio
async def test_best_effort_verbose_includes_exception_text(caplog):
    api_runtime_mod = importlib.import_module("api.runtime")

    async def boom():
        raise ValueError("VISIBLE_SHUTDOWN")

    with caplog.at_level(logging.WARNING):
        await api_runtime_mod.best_effort("test_step", boom(), log_verbose_errors=True)

    blob = " | ".join(r.getMessage() for r in caplog.records)
    assert "VISIBLE_SHUTDOWN" in blob
