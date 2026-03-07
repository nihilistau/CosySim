"""Tests for engine.integrations.compute_router."""
from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from engine.integrations.compute_router import (
    LIMITS_FREE,
    LIMITS_PRO,
    MODELS_FREE,
    MODELS_PRO,
    TIER_FREE_HARDWARE,
    TIER_PRO_HARDWARE,
    AccountTier,
    ComputeRouter,
    ComputeUnavailableError,
    _resolve_lmstudio_base_url,
    _resolve_lmstudio_headers,
    get_compute_router,
)
from engine.integrations.google_account_pool import GoogleAccount


# ──── Helpers ─────────────────────────────────────────────────────────────────


def _make_account(name: str = "test_account", tier: str = "free") -> GoogleAccount:
    return GoogleAccount(name=name, services=["colab"])


def _make_account_tier(
    name: str = "test_account",
    tier: str = "free",
    hardware: list | None = None,
) -> AccountTier:
    hw = hardware or (["T4"] if tier == "free" else ["H100"])
    models = MODELS_PRO if tier == "pro" else MODELS_FREE
    limits = LIMITS_PRO.copy() if tier == "pro" else LIMITS_FREE.copy()
    return AccountTier(
        account_name=name,
        tier=tier,
        hardware=hw,
        available_models=models,
        limits=limits,
        usage={k: 0.0 for k in limits},
    )


def _mock_client_with_hardware(pro_hw: list, free_hw: list) -> MagicMock:
    client = MagicMock()
    client.get_user_info.return_value = {
        "free_tiers": {1: free_hw},
        "pro_tiers": {1: pro_hw},
    }
    return client


# ──── Tier detection ──────────────────────────────────────────────────────────


def test_detect_tier_pro_from_hardware() -> None:
    """H100 in pro hardware list → tier='pro'."""
    router = ComputeRouter()
    account = _make_account()
    mock_client = _mock_client_with_hardware(pro_hw=["H100"], free_hw=["T4"])

    with patch(
        "engine.integrations.colab_client.get_colab_client", return_value=mock_client
    ):
        tier = router.detect_tier(account)

    assert tier.tier == "pro"
    assert "H100" in tier.hardware


def test_detect_tier_free_from_hardware() -> None:
    """T4 in free hardware, no pro hardware → tier='free'."""
    router = ComputeRouter()
    account = _make_account()
    mock_client = _mock_client_with_hardware(pro_hw=[], free_hw=["T4"])

    with patch(
        "engine.integrations.colab_client.get_colab_client", return_value=mock_client
    ):
        tier = router.detect_tier(account)

    assert tier.tier == "free"


def test_detect_tier_defaults_free_on_error() -> None:
    """If get_user_info raises, default to free tier."""
    router = ComputeRouter()
    account = _make_account()
    mock_client = MagicMock()
    mock_client.get_user_info.side_effect = RuntimeError("network error")

    with patch(
        "engine.integrations.colab_client.get_colab_client", return_value=mock_client
    ):
        tier = router.detect_tier(account)

    assert tier.tier == "free"


def test_detect_tier_stores_in_tiers_dict() -> None:
    """detect_tier stores the result in _tiers."""
    router = ComputeRouter()
    account = _make_account()
    mock_client = _mock_client_with_hardware(pro_hw=["A100"], free_hw=[])

    with patch(
        "engine.integrations.colab_client.get_colab_client", return_value=mock_client
    ):
        tier = router.detect_tier(account)

    assert account.name in router._tiers
    assert router._tiers[account.name].tier == "pro"


# ──── Models list ─────────────────────────────────────────────────────────────


def test_pro_models_list_includes_3_1() -> None:
    """gemini-3.1-pro must be in MODELS_PRO."""
    assert "gemini-3.1-pro" in MODELS_PRO


def test_free_models_does_not_include_pro_only() -> None:
    """gemini-3.1-pro should not appear in MODELS_FREE."""
    assert "gemini-3.1-pro" not in MODELS_FREE


def test_get_available_models_pro() -> None:
    router = ComputeRouter()
    models = router.get_available_models("pro")
    assert "gemini-3.1-pro" in models


def test_get_available_models_free() -> None:
    router = ComputeRouter()
    models = router.get_available_models("free")
    assert "gemini-2.5-flash-exp" in models


# ──── Usage tracking ──────────────────────────────────────────────────────────


def test_track_usage_increments() -> None:
    """track_usage adds units to the counter."""
    router = ComputeRouter()
    router.track_usage("account1", "colab_requests_per_day", 3.0)
    router.track_usage("account1", "colab_requests_per_day", 2.0)
    assert router._usage["account1"]["colab_requests_per_day"] == 5.0


def test_track_usage_creates_account_entry() -> None:
    """track_usage initialises the account entry if not present."""
    router = ComputeRouter()
    router.track_usage("new_account", "nlm_queries_per_day")
    assert router._usage["new_account"]["nlm_queries_per_day"] == 1.0


def test_check_limit_returns_used_and_max() -> None:
    """check_limit returns (used, limit) for a known service."""
    router = ComputeRouter()
    router.track_usage("account1", "colab_requests_per_day", 5.0)
    used, limit = router.check_limit("account1", "colab_requests_per_day")
    assert used == 5.0
    assert limit == LIMITS_FREE["colab_requests_per_day"]


def test_check_limit_uses_pro_limits_when_tier_pro() -> None:
    """check_limit uses pro limits when tier is pro."""
    router = ComputeRouter()
    router._tiers["pro_acct"] = _make_account_tier("pro_acct", "pro")
    _, limit = router.check_limit("pro_acct", "colab_requests_per_day")
    assert limit == LIMITS_PRO["colab_requests_per_day"]


# ──── Rate limiting / account selection ───────────────────────────────────────


def test_rate_limited_account_skipped() -> None:
    """Account over daily limit should not be returned by get_best_account_for_tier."""
    router = ComputeRouter()
    account = _make_account("over_limit")

    mock_pool = MagicMock()
    mock_pool.list_accounts.return_value = [
        {"name": "over_limit", "services": ["colab"]}
    ]
    mock_pool.get_by_name.return_value = account

    router._usage["over_limit"] = {"colab_requests_per_day": 200.0}
    router._tiers["over_limit"] = _make_account_tier("over_limit", "free")

    with patch(
        "engine.integrations.google_account_pool.get_account_pool", return_value=mock_pool
    ):
        result = router.get_best_account_for_tier("free")

    assert result is None


def test_get_best_account_returns_none_when_no_colab_accounts() -> None:
    """No colab accounts → None."""
    router = ComputeRouter()
    mock_pool = MagicMock()
    mock_pool.list_accounts.return_value = [
        {"name": "nlm_only", "services": ["notebooklm"]}
    ]

    with patch(
        "engine.integrations.google_account_pool.get_account_pool", return_value=mock_pool
    ):
        result = router.get_best_account_for_tier("free")

    assert result is None


# ──── Limit / feature configuration ──────────────────────────────────────────


def test_configure_limits_overrides_default() -> None:
    """configure_limits stores a custom limit."""
    router = ComputeRouter()
    router.configure_limits("acct1", "colab_requests_per_day", 500.0)
    _, limit = router.check_limit("acct1", "colab_requests_per_day")
    assert limit == 500.0


def test_set_unlimited_overrides_limit() -> None:
    """Setting inf as limit makes check_limit return inf."""
    router = ComputeRouter()
    router.configure_limits("acct1", "nlm_queries_per_day", float("inf"))
    _, limit = router.check_limit("acct1", "nlm_queries_per_day")
    assert limit == float("inf")


def test_feature_unlock_is_persisted() -> None:
    """set_feature_config stores features; is_feature_unlocked reads them back."""
    router = ComputeRouter()
    router.set_feature_config("acct1", ["pro_models", "unlimited_nlm"])
    assert router.is_feature_unlocked("acct1", "pro_models") is True
    assert router.is_feature_unlocked("acct1", "unlimited_nlm") is True
    assert router.is_feature_unlocked("acct1", "missing_feature") is False


def test_feature_not_unlocked_by_default() -> None:
    """Unknown account has no features unlocked."""
    router = ComputeRouter()
    assert router.is_feature_unlocked("nobody", "pro_models") is False


# ──── Inference routing ───────────────────────────────────────────────────────


def test_route_prefers_tunnel_when_active() -> None:
    """When a healthy tunnel session exists, route_inference uses it."""
    router = ComputeRouter()

    mock_session = MagicMock()
    mock_session.healthy = True
    mock_session.tunnel_url = "https://abc.trycloudflare.com"
    mock_session.account_name = "tunnel_account"

    mock_server = MagicMock()
    mock_server._sessions = {"sess1": mock_session}

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "response": "tunnel response",
        "model": "gemini-2.5-flash-exp",
    }

    with patch(
        "engine.integrations.colab_tunnel_server.get_tunnel_server",
        return_value=mock_server,
    ):
        with patch("requests.post", return_value=mock_resp):
            result = router.route_inference("hello")

    assert result["backend"] == "tunnel"
    assert result["response"] == "tunnel response"


def test_route_falls_back_to_lmstudio() -> None:
    """No tunnel, no colab account → uses LMStudio."""
    router = ComputeRouter()

    mock_server = MagicMock()
    mock_server._sessions = {}

    models_resp = MagicMock()
    models_resp.status_code = 200
    models_resp.json.return_value = {"data": [{"id": "qwen3"}]}

    chat_resp = MagicMock()
    chat_resp.status_code = 200
    chat_resp.json.return_value = {
        "output": [{"type": "message", "content": "local response"}]
    }

    with patch(
        "engine.integrations.colab_tunnel_server.get_tunnel_server",
        return_value=mock_server,
    ):
        with patch(
            "engine.integrations.colab_client.get_colab_client", return_value=None
        ):
            with patch(
                "engine.integrations.compute_router._resolve_lmstudio_base_url",
                return_value="http://lmstudio.internal:4321",
            ):
                with patch(
                    "engine.integrations.compute_router._resolve_lmstudio_headers",
                    return_value={},
                ):
                    with patch("requests.get", return_value=models_resp) as mock_get:
                        with patch("requests.post", return_value=chat_resp) as mock_post:
                            result = router.route_inference("hello", fallback_to_local=True)

    assert result["backend"] == "lmstudio"
    assert result["response"] == "local response"
    assert result["degraded"] is True
    assert any("copilot unavailable" in item for item in result["degraded_backends"])
    assert any("colab_agent unavailable" in item for item in result["degraded_backends"])
    mock_get.assert_called_once_with("http://lmstudio.internal:4321/api/v1/models", timeout=2)
    mock_post.assert_called_once_with(
        "http://lmstudio.internal:4321/api/v1/chat",
        json={"model": "qwen3", "input": "hello", "stream": False},
        timeout=60,
    )


def test_route_raises_when_all_unavailable() -> None:
    """ComputeUnavailableError when no backend is reachable."""
    router = ComputeRouter()

    mock_server = MagicMock()
    mock_server._sessions = {}

    with patch.object(
        router,
        "_try_copilot",
        return_value=(None, "copilot unavailable: no github account with valid cookies"),
    ):
        with patch(
            "engine.integrations.colab_tunnel_server.get_tunnel_server",
            return_value=mock_server,
        ):
            with patch(
                "engine.integrations.colab_client.get_colab_client", return_value=None
            ):
                with patch("requests.get", side_effect=Exception("no lmstudio")):
                    with pytest.raises(ComputeUnavailableError):
                        router.route_inference("hello")


def test_try_copilot_uses_service_account_without_hardcoded_username() -> None:
    """Copilot routing should prefer the service-selected GitHub account."""
    router = ComputeRouter()
    github_account = GoogleAccount(
        name="github-primary",
        services=["github"],
        cookies={"session": "cookie"},
    )
    pool = MagicMock()
    pool.get_account.return_value = github_account
    pool.get_by_name.return_value = None
    client = MagicMock()
    client.ask.return_value = "copilot reply"

    with patch("engine.integrations.google_account_pool.get_account_pool", return_value=pool):
        with patch(
            "engine.integrations.github_copilot_client.get_copilot_client",
            return_value=client,
        ):
            result, error = router._try_copilot("hello", "balanced")

    assert error is None
    assert result is not None
    assert result["account"] == "github-primary"
    assert result["model"] == "claude-sonnet-4.6"


def test_try_copilot_returns_explicit_failure_reason_when_no_account() -> None:
    """Copilot misses should feed degraded_backends with a concrete reason."""
    router = ComputeRouter()
    pool = MagicMock()
    pool.get_account.return_value = None
    pool.get_by_name.return_value = None

    with patch("engine.integrations.google_account_pool.get_account_pool", return_value=pool):
        result, error = router._try_copilot("hello", "auto")

    assert result is None
    assert error == "copilot unavailable: no github account with valid cookies"


# ──── Tunnel-related tests ────────────────────────────────────────────────────


def test_tunnel_deploy_extracts_url_from_output() -> None:
    """ColabTunnelServer.deploy parses COSYSIM_TUNNEL_URL from output."""
    from engine.integrations.colab_tunnel_server import ColabTunnelServer

    mock_client = MagicMock()
    mock_client.get_or_assign_runtime.return_value = (
        "https://rt.colab.com",
        "proxy_token",
    )
    mock_client.create_kernel_session.return_value = ("session-123", "kernel-456")
    mock_client._account.name = "test_account"
    mock_client.get_user_info.return_value = {
        "free_tiers": {1: ["T4"]},
        "pro_tiers": {},
    }
    mock_client.execute_code.side_effect = [
        {"output": "DEPS_INSTALLED\n", "error": None, "status": "ok"},
        {"output": "COSYSIM_SERVER_READY:8765\n", "error": None, "status": "ok"},
        {"output": "CLOUDFLARED_INSTALLED\n", "error": None, "status": "ok"},
        {
            "output": "COSYSIM_TUNNEL_URL:https://xyz.trycloudflare.com\n",
            "error": None,
            "status": "ok",
        },
    ]

    server = ColabTunnelServer(colab_client=mock_client, tunnel_type="cloudflare")

    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        session = server.deploy()

    assert session.tunnel_url == "https://xyz.trycloudflare.com"
    assert session.kernel_id == "kernel-456"


def test_tunnel_health_check() -> None:
    """health_check updates session.healthy based on HTTP response."""
    from engine.integrations.colab_tunnel_server import ColabTunnelServer, TunnelSession
    import time

    server = ColabTunnelServer(colab_client=None)
    session = TunnelSession(
        account_name="test",
        tunnel_url="https://test.trycloudflare.com",
        tunnel_type="cloudflare",
        runtime_url="https://rt.colab.com",
        kernel_id="k1",
        session_id="s1",
        proxy_token="token",
        hardware="T4",
        started_at=time.time(),
        last_health_check=time.time(),
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("requests.get", return_value=mock_resp):
        healthy = server.health_check(session)

    assert healthy is True
    assert session.healthy is True


def test_tunnel_infer_posts_to_correct_endpoint() -> None:
    """infer() POSTs to /infer and returns response text."""
    from engine.integrations.colab_tunnel_server import ColabTunnelServer, TunnelSession
    import time

    server = ColabTunnelServer(colab_client=None)
    session = TunnelSession(
        account_name="test",
        tunnel_url="https://test.trycloudflare.com",
        tunnel_type="cloudflare",
        runtime_url="https://rt.colab.com",
        kernel_id="k1",
        session_id="s1",
        proxy_token="token",
        hardware="T4",
        started_at=time.time(),
        last_health_check=time.time(),
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"response": "inferred text", "model": "gemini-2.5-flash-exp"}

    with patch("requests.post", return_value=mock_resp) as mock_post:
        result = server.infer(session, "test prompt")

    assert result == "inferred text"
    call_url = mock_post.call_args[0][0]
    assert call_url == "https://test.trycloudflare.com/infer"


# ──── Status ──────────────────────────────────────────────────────────────────


def test_compute_status_returns_all_backends() -> None:
    """get_status returns accounts, tunnels, and lmstudio keys."""
    router = ComputeRouter()

    mock_pool = MagicMock()
    mock_pool.list_accounts.return_value = []

    mock_server = MagicMock()
    mock_server._sessions = {}

    mock_lms_resp = MagicMock()
    mock_lms_resp.status_code = 200
    mock_lms_resp.json.return_value = {"data": [{"id": "qwen3"}]}

    with patch(
        "engine.integrations.google_account_pool.get_account_pool", return_value=mock_pool
    ):
        with patch(
            "engine.integrations.colab_tunnel_server.get_tunnel_server",
            return_value=mock_server,
        ):
            with patch(
                "engine.integrations.compute_router._resolve_lmstudio_headers",
                return_value={},
            ):
                with patch("requests.get", return_value=mock_lms_resp):
                    status = router.get_status()

    assert "accounts" in status
    assert "tunnels" in status
    assert "lmstudio" in status
    assert status["lmstudio"]["available"] is True


def test_compute_status_lmstudio_unavailable() -> None:
    """get_status marks lmstudio unavailable when connection fails."""
    router = ComputeRouter()

    mock_pool = MagicMock()
    mock_pool.list_accounts.return_value = []

    mock_server = MagicMock()
    mock_server._sessions = {}

    with patch(
        "engine.integrations.google_account_pool.get_account_pool", return_value=mock_pool
    ):
        with patch(
            "engine.integrations.colab_tunnel_server.get_tunnel_server",
            return_value=mock_server,
        ):
            with patch(
                "engine.integrations.compute_router._resolve_lmstudio_base_url",
                return_value="http://lmstudio.internal:4321",
            ):
                with patch(
                    "engine.integrations.compute_router._resolve_lmstudio_headers",
                    return_value={},
                ):
                    with patch("requests.get", side_effect=Exception("refused")):
                        status = router.get_status()

    assert status["lmstudio"]["available"] is False
    assert status["lmstudio"]["degraded"] is True
    assert status["lmstudio"]["url"] == "http://lmstudio.internal:4321"
    assert "refused" in status["lmstudio"]["error"]


def test_resolve_lmstudio_base_url_uses_config_host_and_registry_port() -> None:
    """LMStudio URL resolution uses config host and canonical registry port."""
    fake_cfg = MagicMock()

    def _cfg_get(path: str, default: Any = None) -> Any:
        values = {
            "lmstudio.base_url": "",
            "lmstudio.host": "lmstudio.internal",
            "lmstudio.port": 9999,
        }
        return values.get(path, default)

    fake_cfg.get.side_effect = _cfg_get

    with patch("engine.config.get_config", return_value=fake_cfg):
        with patch("engine.port_registry.get_port", return_value=4321):
            assert _resolve_lmstudio_base_url() == "http://lmstudio.internal:4321"


def test_resolve_lmstudio_headers_prefers_env_token() -> None:
    """LMStudio auth headers prefer environment overrides over config."""
    with patch.dict("os.environ", {"LMSTUDIO_API_TOKEN": "env-token"}, clear=False):
        assert _resolve_lmstudio_headers() == {"Authorization": "Bearer env-token"}


# ──── Reset ───────────────────────────────────────────────────────────────────


def test_reset_daily_usage_clears_counters() -> None:
    """reset_daily_usage zeroes all usage counters."""
    router = ComputeRouter()
    router.track_usage("acct1", "colab_requests_per_day", 42.0)
    router.track_usage("acct1", "nlm_queries_per_day", 10.0)
    router.reset_daily_usage()
    assert router._usage["acct1"]["colab_requests_per_day"] == 0.0
    assert router._usage["acct1"]["nlm_queries_per_day"] == 0.0


# ──── Singleton ───────────────────────────────────────────────────────────────


def test_get_compute_router_returns_singleton() -> None:
    """get_compute_router returns the same instance on repeated calls."""
    import engine.integrations.compute_router as mod
    mod._router_instance = None  # reset for test isolation
    r1 = get_compute_router()
    r2 = get_compute_router()
    assert r1 is r2
    mod._router_instance = None
