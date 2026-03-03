"""Tests for JIT Compute Lifecycle in ComputeRouter."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from engine.integrations.compute_router import (
    ComputeRouter,
    ComputeUnavailableError,
    JITSession,
    MAX_JIT_SESSIONS,
    JIT_CONFIG_PATH,
)


# -- Fixtures -----------------------------------------------------------------


@pytest.fixture()
def patched_config_path(tmp_path, monkeypatch):
    """Redirect JIT_CONFIG_PATH into a temp directory."""
    cfg_path = tmp_path / "jit_config.json"
    monkeypatch.setattr("engine.integrations.compute_router.JIT_CONFIG_PATH", cfg_path)
    return cfg_path


@pytest.fixture()
def router(patched_config_path):
    """Plain ComputeRouter (no heavy init side-effects)."""
    return ComputeRouter()


# -- configure_jit() ----------------------------------------------------------


def test_configure_jit_saves_config(router, patched_config_path):
    """configure_jit() writes all settings to JIT_CONFIG_PATH as JSON."""
    router.configure_jit(min_delay_s=1.0, max_delay_s=3.0, max_session_minutes=20)

    assert patched_config_path.exists()
    data = json.loads(patched_config_path.read_text())
    assert data["min_delay_s"] == 1.0
    assert data["max_delay_s"] == 3.0
    assert data["max_session_minutes"] == 20


def test_configure_jit_updates_instance_state(router):
    """configure_jit() reflects changes in _jit_config immediately."""
    router.configure_jit(min_delay_s=0.5, max_delay_s=1.5)

    assert router._jit_config["min_delay_s"] == 0.5
    assert router._jit_config["max_delay_s"] == 1.5


def test_load_jit_config_reads_existing_file(tmp_path, monkeypatch):
    """ComputeRouter.__init__ loads pre-existing jit_config.json on startup."""
    config_path = tmp_path / "jit_config.json"
    config_path.write_text(json.dumps({"min_delay_s": 2.0, "max_delay_s": 5.0}))
    monkeypatch.setattr("engine.integrations.compute_router.JIT_CONFIG_PATH", config_path)

    r = ComputeRouter()

    assert r._jit_config["min_delay_s"] == 2.0
    assert r._jit_config["max_delay_s"] == 5.0


# -- jit_infer() --------------------------------------------------------------


def test_jit_infer_respects_max_sessions(router):
    """jit_infer() raises ComputeUnavailableError when at session limit."""
    router._active_jit_sessions = MAX_JIT_SESSIONS

    with pytest.raises(ComputeUnavailableError):
        router.jit_infer("hello", model="gemini-flash")


def test_jit_infer_returns_jit_flag(router):
    """jit_infer() sets jit=True on the result dict."""
    router._active_jit_sessions = 0

    fake_result = {"response": "AI output", "backend": "colab", "model": "gemini"}
    with patch.object(router, "route_inference", return_value=fake_result):
        result = router.jit_infer("hello", model="gemini-flash", human_delay=False)

    assert result["jit"] is True


def test_jit_infer_decrements_counter_on_error(router):
    """_active_jit_sessions is decremented even when route_inference raises."""
    router._active_jit_sessions = 0

    with patch.object(router, "route_inference", side_effect=ComputeUnavailableError("no backend")):
        with pytest.raises(ComputeUnavailableError):
            router.jit_infer("hello", human_delay=False)

    assert router._active_jit_sessions == 0


def test_jit_infer_calls_human_delay(router):
    """jit_infer() calls _jit_human_delay() when human_delay=True."""
    router._active_jit_sessions = 0
    fake_result = {"response": "ok", "backend": "colab", "model": "gemini"}

    with patch.object(router, "_jit_human_delay") as mock_delay, \
         patch.object(router, "route_inference", return_value=fake_result):
        router.jit_infer("hello", human_delay=True)

    mock_delay.assert_called_once()


def test_jit_infer_no_delay_when_disabled(router):
    """jit_infer(human_delay=False) skips _jit_human_delay entirely."""
    router._active_jit_sessions = 0
    fake_result = {"response": "ok", "backend": "colab", "model": "gemini"}

    with patch.object(router, "_jit_human_delay") as mock_delay, \
         patch.object(router, "route_inference", return_value=fake_result):
        router.jit_infer("hello", human_delay=False)

    mock_delay.assert_not_called()


def test_jit_infer_raises_when_route_fails(router):
    """jit_infer() propagates ComputeUnavailableError from route_inference."""
    router._active_jit_sessions = 0

    with patch.object(router, "route_inference", side_effect=ComputeUnavailableError("no backend")):
        with pytest.raises(ComputeUnavailableError):
            router.jit_infer("hello", human_delay=False)


# -- jit_execute() ------------------------------------------------------------


def test_jit_execute_uses_healthy_tunnel(router):
    """jit_execute() POSTs to a healthy tunnel session when one exists."""
    mock_session = MagicMock()
    mock_session.healthy = True
    mock_session.tunnel_url = "http://localhost:9000"
    mock_session.account_name = "acc1"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"stdout": "42", "stderr": "", "returncode": 0}

    with patch("engine.integrations.colab_tunnel_server.get_tunnel_server") as mock_ts, \
         patch("engine.integrations.compute_router.requests.post", return_value=mock_resp), \
         patch.object(router, "_jit_human_delay"):
        mock_ts.return_value._sessions = {"acc1": mock_session}
        result = router.jit_execute("print(42)")

    assert result["backend"] == "tunnel"
    assert result["stdout"] == "42"


def test_jit_execute_falls_back_when_no_tunnel(router):
    """jit_execute() falls back to colab_client when no healthy tunnel exists."""
    mock_client = MagicMock()
    mock_client.run_python.return_value = {"stdout": "done", "stderr": "", "returncode": 0}

    mock_account = MagicMock()
    mock_account.name = "acc1"

    with patch("engine.integrations.colab_tunnel_server.get_tunnel_server") as mock_ts, \
         patch("engine.integrations.colab_client.get_colab_client", return_value=mock_client), \
         patch.object(router, "_jit_human_delay"), \
         patch.object(router, "get_best_account_for_tier", return_value=mock_account):
        mock_ts.return_value._sessions = {}
        result = router.jit_execute("x = 1")

    assert result["backend"] == "colab_agent"


def test_jit_execute_respects_max_sessions(router):
    """jit_execute() raises ComputeUnavailableError when at session limit."""
    router._active_jit_sessions = MAX_JIT_SESSIONS

    with pytest.raises(ComputeUnavailableError):
        router.jit_execute("print(1)")


# -- JITSession context manager -----------------------------------------------


def test_jit_session_enter_returns_none_when_no_tunnel(router):
    """JITSession.__enter__ returns None when no healthy tunnel session exists."""
    with patch("engine.integrations.colab_tunnel_server.get_tunnel_server") as mock_ts:
        mock_ts.return_value._sessions = {}
        with JITSession(router) as sess:
            assert sess is None


def test_jit_session_enter_returns_tunnel_session(router):
    """JITSession.__enter__ returns a TunnelSession when one is healthy."""
    mock_session = MagicMock()
    mock_session.healthy = True

    with patch("engine.integrations.colab_tunnel_server.get_tunnel_server") as mock_ts:
        mock_ts.return_value._sessions = {"acc1": mock_session}
        with JITSession(router) as sess:
            assert sess is mock_session


def test_jit_session_exit_clears_state(router):
    """JITSession.__exit__ resets _session and _owned to initial values."""
    mock_session = MagicMock()
    mock_session.healthy = True
    mock_session.account_name = "acc1"

    with patch("engine.integrations.colab_tunnel_server.get_tunnel_server") as mock_ts:
        mock_ts.return_value._sessions = {"acc1": mock_session}
        sess_ctx = JITSession(router)
        with sess_ctx:
            pass
        assert sess_ctx._session is None
        assert sess_ctx._owned is False


def test_jit_session_does_not_teardown_borrowed_session(router):
    """JITSession.__exit__ does not remove a borrowed (pre-existing) tunnel session."""
    mock_session = MagicMock()
    mock_session.healthy = True
    mock_session.account_name = "acc1"

    with patch("engine.integrations.colab_tunnel_server.get_tunnel_server") as mock_ts:
        server = MagicMock()
        server._sessions = {"acc1": mock_session}
        mock_ts.return_value = server
        with JITSession(router):
            pass
        # Session should still be in the pool; we borrowed, not owned it
        assert "acc1" in server._sessions

