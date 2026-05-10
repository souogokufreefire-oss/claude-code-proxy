import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.dependencies import get_settings
from config.settings import Settings

app = create_app()


def _extract_text_from_sse(data: str) -> str:
    """Extract concatenated text_delta content from an SSE stream response."""
    parts = []
    for line in data.split("\n"):
        if not line.startswith("data: "):
            continue
        event = json.loads(line[6:])
        delta = event.get("delta", {})
        if delta.get("type") == "text_delta":
            parts.append(delta.get("text", ""))
    return "".join(parts)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_settings():
    settings = Settings()
    settings.fast_prefix_detection = True
    settings.enable_network_probe_mock = True
    settings.enable_title_generation_skip = True
    return settings


def test_create_message_fast_prefix_detection(client, mock_settings):
    app.dependency_overrides[get_settings] = lambda: mock_settings

    payload = {
        "model": "claude-3-sonnet",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": "What is the prefix?"}],
    }

    with (
        patch(
            "api.optimization_handlers.is_prefix_detection_request",
            return_value=(True, "/ask"),
        ),
        patch(
            "api.optimization_handlers.extract_command_prefix",
            return_value="/ask",
        ),
    ):
        response = client.post("/v1/messages", json=payload)

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    text = _extract_text_from_sse(response.text)
    assert "/ask" in text

    app.dependency_overrides.clear()


def test_create_message_quota_check_mock(client, mock_settings):
    app.dependency_overrides[get_settings] = lambda: mock_settings

    payload = {
        "model": "claude-3-sonnet",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": "quota check"}],
    }

    with patch("api.optimization_handlers.is_quota_check_request", return_value=True):
        response = client.post("/v1/messages", json=payload)

    assert response.status_code == 200
    text = _extract_text_from_sse(response.text)
    assert "Quota check passed" in text

    app.dependency_overrides.clear()


def test_create_message_title_generation_skip(client, mock_settings):
    app.dependency_overrides[get_settings] = lambda: mock_settings

    payload = {
        "model": "claude-3-sonnet",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": "generate title"}],
    }

    with patch(
        "api.optimization_handlers.is_title_generation_request", return_value=True
    ):
        response = client.post("/v1/messages", json=payload)

    assert response.status_code == 200
    text = _extract_text_from_sse(response.text)
    assert "Conversation" in text

    app.dependency_overrides.clear()


def test_create_message_empty_messages_returns_400(client):
    """POST /v1/messages with messages: [] returns 400 invalid_request_error."""
    payload = {
        "model": "claude-3-sonnet",
        "max_tokens": 100,
        "messages": [],
    }
    response = client.post("/v1/messages", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert data.get("type") == "error"
    assert data.get("error", {}).get("type") == "invalid_request_error"
    assert "cannot be empty" in data.get("error", {}).get("message", "")


def test_count_tokens_empty_messages_returns_400(client):
    """POST /v1/messages/count_tokens with messages: [] matches messages validation."""
    payload = {"model": "claude-3-sonnet", "messages": []}
    response = client.post("/v1/messages/count_tokens", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert data.get("type") == "error"
    assert data.get("error", {}).get("type") == "invalid_request_error"
    assert "cannot be empty" in data.get("error", {}).get("message", "")


def test_count_tokens_endpoint(client):
    payload = {
        "model": "claude-3-sonnet",
        "messages": [{"role": "user", "content": "hello"}],
    }

    with patch("api.routes.get_token_count", return_value=5):
        response = client.post("/v1/messages/count_tokens", json=payload)

    assert response.status_code == 200
    assert response.json()["input_tokens"] == 5


def test_count_tokens_error_returns_500(client):
    """When get_token_count raises, count_tokens returns 500."""
    payload = {
        "model": "claude-3-sonnet",
        "messages": [{"role": "user", "content": "hello"}],
    }

    with patch("api.routes.get_token_count", side_effect=RuntimeError("token error")):
        response = client.post("/v1/messages/count_tokens", json=payload)

    assert response.status_code == 500
    assert "token error" in response.json()["detail"]
