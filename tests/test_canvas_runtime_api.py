"""Focused tests for engine.api.canvas_api runtime hardening."""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from engine.api.canvas_api import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_nexus_search_fallback_marks_degraded_state(client: TestClient) -> None:
    """Nexus search fallback must expose degraded runtime metadata."""
    with patch(
        "engine.api.canvas_api._nexus_proxy",
        new=AsyncMock(side_effect=RuntimeError("kms down")),
    ):
        with patch(
            "engine.integrations.rpc_proxy.nexus_search_python",
            return_value={"results": [{"id": "r1"}]},
        ):
            response = client.get("/api/nexus/search", params={"q": "interceptors"})

    assert response.status_code == 200
    data = response.json()
    assert data["results"] == [{"id": "r1"}]
    assert data["degraded"] is True
    assert data["fallback_from"] == "nexus_kms"
    assert data["backend"] == "python"
    assert "kms down" in data["error"]


def test_nexus_rules_surfaces_failure_when_all_backends_unavailable(
    client: TestClient,
) -> None:
    """Rules endpoint must not pretend success when both backends fail."""
    mock_client = MagicMock()
    mock_client.get_rules.side_effect = RuntimeError("python rules down")

    with patch(
        "engine.api.canvas_api._nexus_proxy",
        new=AsyncMock(side_effect=RuntimeError("kms rules down")),
    ):
        with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
            response = client.get("/api/nexus/rules", params={"scope": "coding"})

    assert response.status_code == 200
    data = response.json()
    assert data["rules"] == []
    assert data["scope"] == "coding"
    assert data["degraded"] is True
    assert data["backend"] == "unavailable"
    assert "python rules down" in data["error"]


class _FakeAsyncResponse:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> Dict[str, Any]:
        return self._payload


class _FakeAsyncClient:
    captured_url: str = ""

    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def get(self, url: str) -> _FakeAsyncResponse:
        type(self).captured_url = url
        return _FakeAsyncResponse({"data": [{"id": "qwen3"}]})


def test_lmstudio_models_uses_resolved_service_url(client: TestClient) -> None:
    """LMStudio routes must use the resolved canonical base URL."""
    with patch(
        "engine.api.canvas_api._resolve_lmstudio_base_url",
        return_value="http://lmstudio.internal:4321",
    ):
        with patch("httpx.AsyncClient", _FakeAsyncClient):
            response = client.get("/api/lmstudio/models")

    assert response.status_code == 200
    data = response.json()
    assert data["url"] == "http://lmstudio.internal:4321"
    assert _FakeAsyncClient.captured_url == "http://lmstudio.internal:4321/api/v1/models"


class _AuthCapturingAsyncClient:
    captured_url: str = ""
    captured_headers: Dict[str, str] = {}

    def __init__(self, *_: Any, **kwargs: Any) -> None:
        type(self).captured_headers = dict(kwargs.get("headers", {}))

    async def __aenter__(self) -> "_AuthCapturingAsyncClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def get(self, url: str) -> _FakeAsyncResponse:
        type(self).captured_url = url
        return _FakeAsyncResponse({"data": [{"id": "qwen3"}]})


def test_lmstudio_models_include_auth_header_when_configured(client: TestClient) -> None:
    """LMStudio model probes must forward configured bearer auth."""
    with patch(
        "engine.api.canvas_api._resolve_lmstudio_base_url",
        return_value="http://lmstudio.internal:4321",
    ):
        with patch(
            "engine.api.canvas_api._resolve_lmstudio_headers",
            return_value={"Authorization": "Bearer unit-test"},
        ):
            with patch("httpx.AsyncClient", _AuthCapturingAsyncClient):
                response = client.get("/api/lmstudio/models")

    assert response.status_code == 200
    assert _AuthCapturingAsyncClient.captured_url == "http://lmstudio.internal:4321/api/v1/models"
    assert _AuthCapturingAsyncClient.captured_headers == {"Authorization": "Bearer unit-test"}


def test_send_to_canvas_uses_resolved_canvas_node_url() -> None:
    """Canvas ingest must use the canonical resolved node URL."""

    class _FakeSyncResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> Dict[str, Any]:
            return {"status": "ok", "nodeId": "node-1"}

    with patch(
        "engine.api.canvas_api._resolve_canvas_node_url",
        return_value="http://canvas.internal:5590",
    ):
        with patch("httpx.post", return_value=_FakeSyncResponse()) as mock_post:
            data = __import__("engine.api.canvas_api", fromlist=["send_to_canvas"]).send_to_canvas(
                "hello",
                source="test",
            )

    assert data["status"] == "ok"
    mock_post.assert_called_once()
    assert mock_post.call_args.args[0] == "http://canvas.internal:5590/api/external/ingest"


def test_canvas_push_surfaces_ingest_failure_as_503(client: TestClient) -> None:
    """Canvas push must not return HTTP 200 when ingest fails."""
    with patch(
        "engine.api.canvas_api.send_to_canvas",
        side_effect=RuntimeError("Canvas ingest unavailable"),
    ):
        response = client.post(
            "/api/canvas/push",
            json={"content": "hello", "source": "test", "type": "note", "notebook_id": ""},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Canvas ingest unavailable"
