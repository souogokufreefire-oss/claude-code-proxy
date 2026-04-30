"""
Claude Code Proxy - Entry Point

Minimal entry point that builds the ASGI app via :func:`api.app.create_app`.
Run with: uv run python server.py  (reads HOST/PORT from .env)
Or:      uv run uvicorn server:app --host 0.0.0.0 --port 8082 --timeout-graceful-shutdown 5
"""

from api.app import create_app

app = create_app()

__all__ = ["app", "create_app"]

if __name__ == "__main__":
    import uvicorn

    from config.settings import get_settings

    settings = get_settings()
    # timeout_graceful_shutdown ensures uvicorn doesn't hang on provider cleanup.
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="debug",
        timeout_graceful_shutdown=5,
    )
