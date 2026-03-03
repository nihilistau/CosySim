"""Tests for engine.integrations.colab_tunnel_server."""
from __future__ import annotations

import time
from typing import List
from unittest.mock import MagicMock, call, patch

import pytest

from engine.integrations.colab_tunnel_server import (
    INSTALL_CLOUDFLARE_CELL,
    SETUP_CELL,
    SERVER_CELL,
    TUNNEL_CELL_CLOUDFLARE,
    TUNNEL_CELL_NGROK,
    ColabTunnelServer,
    TunnelSession,
    get_tunnel_server,
)


# ──── Helpers ─────────────────────────────────────────────────────────────────


def _make_session(
    tunnel_url: str = "https://test.trycloudflare.com",
    healthy: bool = True,
    session_id: str = "sess-001",
) -> TunnelSession:
    return TunnelSession(
        account_name="test_account",
        tunnel_url=tunnel_url,
        tunnel_type="cloudflare",
        runtime_url="https://rt.colab.com",
        kernel_id="kernel-456",
        session_id=session_id,
        proxy_token="proxy_token_abc",
        hardware="T4",
        started_at=time.time(),
        last_health_check=time.time(),
        healthy=healthy,
    )


def _make_client(
    tunnel_url: str = "https://test.trycloudflare.com",
    use_cloudflare: bool = True,
) -> MagicMock:
    """Build a mock ColabClient configured for a successful deploy."""
    mock_client = MagicMock()
    mock_client.get_or_assign_runtime.return_value = (
        "https://rt.colab.com",
        "proxy_token_abc",
    )
    mock_client.create_kernel_session.return_value = ("sess-001", "kernel-456")
    mock_client._account.name = "test_account"
    mock_client.get_user_info.return_value = {
        "free_tiers": {1: ["T4"]},
        "pro_tiers": {},
    }

    cf_outputs = [
        {"output": "DEPS_INSTALLED\n", "error": None, "status": "ok"},
        {"output": "COSYSIM_SERVER_READY:8765\n", "error": None, "status": "ok"},
        {"output": "CLOUDFLARED_INSTALLED\n", "error": None, "status": "ok"},
        {"output": f"COSYSIM_TUNNEL_URL:{tunnel_url}\n", "error": None, "status": "ok"},
    ]
    ngrok_outputs = [
        {"output": "DEPS_INSTALLED\n", "error": None, "status": "ok"},
        {"output": "COSYSIM_SERVER_READY:8765\n", "error": None, "status": "ok"},
        {"output": f"COSYSIM_TUNNEL_URL:{tunnel_url}\n", "error": None, "status": "ok"},
    ]

    mock_client.execute_code.side_effect = (
        cf_outputs if use_cloudflare else ngrok_outputs
    )
    return mock_client


def _ok_health_mock() -> MagicMock:
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {"status": "ok", "runtime": "colab"}
    return m


# ──── Deploy ──────────────────────────────────────────────────────────────────


def test_deploy_executes_cells_in_order() -> None:
    """deploy() calls execute_code for setup, server, cloudflare-install, and tunnel."""
    mock_client = _make_client()
    server = ColabTunnelServer(colab_client=mock_client, tunnel_type="cloudflare")

    with patch("requests.get", return_value=_ok_health_mock()):
        session = server.deploy()

    assert mock_client.execute_code.call_count == 4
    codes_executed: List[str] = [
        c[0][3] for c in mock_client.execute_code.call_args_list
    ]
    # First cell installs deps
    assert "DEPS_INSTALLED" in codes_executed[0] or "pip" in codes_executed[0]
    # Second cell starts the server
    assert "COSYSIM_SERVER_READY" in codes_executed[1]
    # Third installs cloudflared
    assert "cloudflared" in codes_executed[2]
    # Fourth runs the tunnel
    assert "cloudflared" in codes_executed[3] or "trycloudflare" in codes_executed[3]


def test_parse_tunnel_url_from_output() -> None:
    """deploy() extracts the URL from COSYSIM_TUNNEL_URL:<url> in output."""
    expected_url = "https://random-name.trycloudflare.com"
    mock_client = _make_client(tunnel_url=expected_url)
    server = ColabTunnelServer(colab_client=mock_client, tunnel_type="cloudflare")

    with patch("requests.get", return_value=_ok_health_mock()):
        session = server.deploy()

    assert session.tunnel_url == expected_url


def test_deploy_registers_session() -> None:
    """deploy() stores the session in _sessions."""
    mock_client = _make_client()
    server = ColabTunnelServer(colab_client=mock_client)

    with patch("requests.get", return_value=_ok_health_mock()):
        session = server.deploy()

    assert session.session_id in server._sessions


def test_deploy_raises_when_no_client() -> None:
    """deploy() raises RuntimeError when no client is available."""
    server = ColabTunnelServer(colab_client=None)
    with pytest.raises(RuntimeError, match="No Colab client"):
        server.deploy()


def test_deploy_raises_when_tunnel_url_missing() -> None:
    """deploy() raises RuntimeError if tunnel URL is not found in output."""
    mock_client = MagicMock()
    mock_client.get_or_assign_runtime.return_value = ("https://rt.colab.com", "tok")
    mock_client.create_kernel_session.return_value = ("s1", "k1")
    mock_client._account.name = "acct"
    mock_client.get_user_info.return_value = {"free_tiers": {}, "pro_tiers": {}}
    mock_client.execute_code.side_effect = [
        {"output": "DEPS_INSTALLED\n", "error": None, "status": "ok"},
        {"output": "COSYSIM_SERVER_READY:8765\n", "error": None, "status": "ok"},
        {"output": "CLOUDFLARED_INSTALLED\n", "error": None, "status": "ok"},
        {"output": "TUNNEL_FAILED\n", "error": None, "status": "ok"},
    ]

    server = ColabTunnelServer(colab_client=mock_client, tunnel_type="cloudflare")

    with patch("requests.get", return_value=_ok_health_mock()):
        with pytest.raises(RuntimeError, match="COSYSIM_TUNNEL_URL"):
            server.deploy()


# ──── Health check ────────────────────────────────────────────────────────────


def test_health_check_marks_session_healthy() -> None:
    """health_check sets session.healthy=True on 200 response."""
    server = ColabTunnelServer(colab_client=None)
    session = _make_session(healthy=False)

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("requests.get", return_value=mock_resp):
        result = server.health_check(session)

    assert result is True
    assert session.healthy is True


def test_health_check_marks_session_unhealthy_on_failure() -> None:
    """health_check sets session.healthy=False on connection error."""
    server = ColabTunnelServer(colab_client=None)
    session = _make_session(healthy=True)

    with patch("requests.get", side_effect=Exception("connection refused")):
        result = server.health_check(session)

    assert result is False
    assert session.healthy is False


def test_health_check_marks_unhealthy_on_non_200() -> None:
    """health_check sets session.healthy=False on non-200 status."""
    server = ColabTunnelServer(colab_client=None)
    session = _make_session(healthy=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 503

    with patch("requests.get", return_value=mock_resp):
        result = server.health_check(session)

    assert result is False


# ──── Inference ───────────────────────────────────────────────────────────────


def test_infer_posts_prompt_and_model() -> None:
    """infer() POSTs to /infer with correct payload and returns response text."""
    server = ColabTunnelServer(colab_client=None)
    session = _make_session()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"response": "hello world", "model": "gemini-2.5-flash-exp"}

    with patch("requests.post", return_value=mock_resp) as mock_post:
        result = server.infer(session, "test prompt", model="gemini-2.5-flash-exp")

    assert result == "hello world"
    payload = mock_post.call_args[1]["json"]
    assert payload["prompt"] == "test prompt"
    assert payload["model"] == "gemini-2.5-flash-exp"


def test_chat_posts_messages() -> None:
    """chat() POSTs to /chat with messages list."""
    server = ColabTunnelServer(colab_client=None)
    session = _make_session()
    messages = [{"role": "user", "content": "hi"}]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"response": "chat reply", "model": "gemini-2.5-flash-exp"}

    with patch("requests.post", return_value=mock_resp) as mock_post:
        result = server.chat(session, messages)

    assert result == "chat reply"
    payload = mock_post.call_args[1]["json"]
    assert payload["messages"] == messages


def test_embed_returns_vectors() -> None:
    """embed() POSTs to /embed and returns list of vectors."""
    server = ColabTunnelServer(colab_client=None)
    session = _make_session()
    texts = ["hello", "world"]
    expected_embeddings = [[0.1, 0.2], [0.3, 0.4]]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "embeddings": expected_embeddings,
        "model": "text-embedding-004",
    }

    with patch("requests.post", return_value=mock_resp) as mock_post:
        result = server.embed(session, texts)

    assert result == expected_embeddings
    payload = mock_post.call_args[1]["json"]
    assert payload["texts"] == texts


def test_execute_posts_code() -> None:
    """execute() POSTs to /execute with code and returns result dict."""
    server = ColabTunnelServer(colab_client=None)
    session = _make_session()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "stdout": "42\n",
        "stderr": "",
        "returncode": 0,
        "status": "ok",
    }

    with patch("requests.post", return_value=mock_resp) as mock_post:
        result = server.execute(session, "print(42)")

    assert result["stdout"] == "42\n"
    assert result["status"] == "ok"
    payload = mock_post.call_args[1]["json"]
    assert payload["code"] == "print(42)"


# ──── Teardown ────────────────────────────────────────────────────────────────


def test_teardown_closes_session() -> None:
    """teardown() calls close_session on the client and removes from _sessions."""
    mock_client = MagicMock()
    server = ColabTunnelServer(colab_client=mock_client)
    session = _make_session()
    server._sessions[session.session_id] = session

    server.teardown(session)

    mock_client.close_session.assert_called_once_with(
        session.runtime_url, session.session_id, session.proxy_token
    )
    assert session.session_id not in server._sessions


def test_teardown_tolerates_close_error() -> None:
    """teardown() still removes session from _sessions even if close_session raises."""
    mock_client = MagicMock()
    mock_client.close_session.side_effect = Exception("kernel gone")
    server = ColabTunnelServer(colab_client=mock_client)
    session = _make_session()
    server._sessions[session.session_id] = session

    server.teardown(session)  # Should not raise

    assert session.session_id not in server._sessions


# ──── get_active_sessions ─────────────────────────────────────────────────────


def test_get_active_sessions_filters_unhealthy() -> None:
    """get_active_sessions returns only healthy sessions."""
    server = ColabTunnelServer(colab_client=None)

    healthy = _make_session(tunnel_url="https://a.trycloudflare.com", session_id="s1")
    unhealthy = _make_session(
        tunnel_url="https://b.trycloudflare.com", healthy=False, session_id="s2"
    )
    server._sessions = {"s1": healthy, "s2": unhealthy}

    def mock_health(session: TunnelSession) -> bool:
        return session.healthy

    # Patch health_check to avoid real HTTP calls
    with patch.object(server, "health_check", side_effect=mock_health):
        active = server.get_active_sessions()

    assert len(active) == 1
    assert active[0].session_id == "s1"


# ──── Tunnel type selection ───────────────────────────────────────────────────


def test_cloudflare_cell_used_when_type_cloudflare() -> None:
    """With tunnel_type='cloudflare', cloudflared cell is executed (not ngrok tunnel)."""
    mock_client = _make_client(use_cloudflare=True)
    server = ColabTunnelServer(colab_client=mock_client, tunnel_type="cloudflare")

    with patch("requests.get", return_value=_ok_health_mock()):
        server.deploy()

    all_codes = [c[0][3] for c in mock_client.execute_code.call_args_list]
    # cloudflared tunnel cell should be present
    assert any("cloudflared" in code for code in all_codes)
    # ngrok.connect is specific to the ngrok tunnel cell (SETUP_CELL has pyngrok as pip dep)
    assert not any("ngrok.connect" in code for code in all_codes)


def test_ngrok_cell_used_when_type_ngrok() -> None:
    """With tunnel_type='ngrok', pyngrok cell is executed (not cloudflare)."""
    mock_client = _make_client(use_cloudflare=False)
    server = ColabTunnelServer(colab_client=mock_client, tunnel_type="ngrok")

    with patch("requests.get", return_value=_ok_health_mock()):
        server.deploy()

    all_codes = [c[0][3] for c in mock_client.execute_code.call_args_list]
    assert any("pyngrok" in code for code in all_codes)


# ──── Singleton ───────────────────────────────────────────────────────────────


def test_get_tunnel_server_returns_singleton() -> None:
    """get_tunnel_server returns the same instance on repeated calls."""
    import engine.integrations.colab_tunnel_server as mod
    mod._tunnel_server_instance = None  # reset for test isolation

    with patch(
        "engine.integrations.colab_client.get_colab_client", return_value=None
    ):
        s1 = get_tunnel_server()
        s2 = get_tunnel_server()

    assert s1 is s2
    mod._tunnel_server_instance = None
