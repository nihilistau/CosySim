"""
Tests for engine.skills.builtin.security_skills — 35+ tests.

All SecretManager and RateLimiter interactions are mocked so these tests
run without any DB, Nexus, or filesystem dependencies.
"""

import json
from unittest.mock import MagicMock, patch, call
from pathlib import Path

import pytest

# Import skills module (triggers @skill decorator registration)
import engine.skills.builtin.security_skills as ss
from engine.skills.skill import skill as _skill_decorator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_sm():
    """Mock SecretManager with sensible defaults."""
    sm = MagicMock()
    sm.list_secrets.return_value = [
        {
            "name": "test_key",
            "secret_type": "api_key",
            "source": "runtime",
            "tags": ["prod"],
            "created_at": "2025-01-01T00:00:00+00:00",
            "expires_at": None,
            "rotated_at": None,
            "is_expired": False,
        }
    ]
    sm.export_safe_report.return_value = {
        "total_secrets": 1,
        "by_type": {"api_key": 1},
        "by_source": {"runtime": 1},
        "expired_count": 0,
        "secrets": sm.list_secrets.return_value,
    }
    sm.rotate.return_value = True
    sm.check_expiry.return_value = {"expired": [], "expiring_soon": []}
    sm.load_from_env.return_value = 3
    sm.get_audit_log.return_value = [
        {
            "timestamp": "2025-01-01T00:00:00+00:00",
            "event_type": "create",
            "secret_name": "test_key",
            "actor": "system",
            "details": "type=api_key",
        }
    ]
    return sm


@pytest.fixture()
def mock_rl():
    """Mock RateLimiter with sensible defaults."""
    rl = MagicMock()
    rl.get_metrics.return_value = {
        "lmstudio": {
            "service": "lmstudio",
            "tokens": 10.0,
            "capacity": 10,
            "refill_rate": 2.0,
            "queue_depth": 0,
            "backpressure_active": False,
            "calls_total": 0,
            "rejections_total": 0,
            "rejection_rate": 0.0,
            "avg_wait_ms": 0.0,
        }
    }
    rl.get_status.return_value = rl.get_metrics.return_value["lmstudio"]
    rl.backpressure_active.return_value = False
    rl._buckets = {"lmstudio": MagicMock()}
    return rl


@pytest.fixture(autouse=True)
def patch_singletons(mock_sm, mock_rl):
    """Patch get_secret_manager and get_rate_limiter for ALL tests in this module."""
    with (
        patch("engine.skills.builtin.security_skills._get_sm", return_value=mock_sm),
        patch("engine.skills.builtin.security_skills._get_rl", return_value=mock_rl),
    ):
        yield


# ---------------------------------------------------------------------------
# Secret skills
# ---------------------------------------------------------------------------


class TestGetSecretStatus:
    def test_returns_valid_json(self, mock_sm):
        result = ss.get_secret_status()
        data = json.loads(result)
        assert isinstance(data, dict)

    def test_no_value_in_output(self, mock_sm):
        result = ss.get_secret_status()
        assert "sensitive" not in result

    def test_full_report_when_no_name(self, mock_sm):
        result = ss.get_secret_status()
        data = json.loads(result)
        assert "total_secrets" in data

    def test_single_secret_by_name(self, mock_sm):
        result = ss.get_secret_status(name="test_key")
        data = json.loads(result)
        assert data["name"] == "test_key"

    def test_unknown_name_returns_error(self, mock_sm):
        mock_sm.list_secrets.return_value = []
        result = ss.get_secret_status(name="ghost")
        data = json.loads(result)
        assert "error" in data

    def test_calls_export_safe_report(self, mock_sm):
        ss.get_secret_status()
        mock_sm.export_safe_report.assert_called_once()

    def test_metadata_only_no_values(self, mock_sm):
        result = ss.get_secret_status(name="test_key")
        # value should not appear in metadata dict
        assert "value" not in json.loads(result)


class TestRotateSecret:
    def test_success_returns_ok(self, mock_sm):
        result = ss.rotate_secret("test_key", "new_val")
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["rotated"] == "test_key"

    def test_not_found_returns_error(self, mock_sm):
        mock_sm.rotate.return_value = False
        result = ss.rotate_secret("ghost", "v")
        data = json.loads(result)
        assert data["status"] == "error"

    def test_calls_rotate(self, mock_sm):
        ss.rotate_secret("k", "new")
        mock_sm.rotate.assert_called_once_with("k", "new")

    def test_returns_valid_json(self, mock_sm):
        result = ss.rotate_secret("k", "v")
        json.loads(result)  # must not raise

    def test_rotated_name_in_response(self, mock_sm):
        result = ss.rotate_secret("my_secret", "new_value")
        data = json.loads(result)
        assert "my_secret" in str(data)


class TestCheckSecretExpiry:
    def test_returns_valid_json(self):
        result = ss.check_secret_expiry()
        json.loads(result)

    def test_has_expired_field(self):
        result = ss.check_secret_expiry()
        data = json.loads(result)
        assert "expired" in data

    def test_has_expiring_soon_field(self):
        result = ss.check_secret_expiry()
        data = json.loads(result)
        assert "expiring_soon" in data

    def test_calls_check_expiry(self, mock_sm):
        ss.check_secret_expiry()
        mock_sm.check_expiry.assert_called_once()


class TestLoadSecretsFromEnv:
    def test_returns_valid_json(self):
        result = ss.load_secrets_from_env()
        json.loads(result)

    def test_loaded_count_in_response(self, mock_sm):
        result = ss.load_secrets_from_env()
        data = json.loads(result)
        assert "loaded" in data
        assert data["loaded"] == 3

    def test_status_ok(self):
        result = ss.load_secrets_from_env()
        assert json.loads(result)["status"] == "ok"

    def test_calls_load_from_env(self, mock_sm):
        ss.load_secrets_from_env()
        mock_sm.load_from_env.assert_called_once()


class TestGetSecretAuditLog:
    def test_returns_valid_json(self):
        result = ss.get_secret_audit_log()
        data = json.loads(result)
        assert isinstance(data, list)

    def test_respects_limit(self, mock_sm):
        ss.get_secret_audit_log(limit=5)
        mock_sm.get_audit_log.assert_called_once_with(limit=5)

    def test_default_limit(self, mock_sm):
        ss.get_secret_audit_log()
        mock_sm.get_audit_log.assert_called_once_with(limit=20)

    def test_entries_have_event_type(self):
        result = ss.get_secret_audit_log()
        data = json.loads(result)
        if data:
            assert "event_type" in data[0]


# ---------------------------------------------------------------------------
# Rate limit skills
# ---------------------------------------------------------------------------


class TestGetRateLimitStatus:
    def test_returns_valid_json(self):
        result = ss.get_rate_limit_status()
        json.loads(result)

    def test_all_services_when_no_arg(self, mock_rl):
        result = ss.get_rate_limit_status()
        data = json.loads(result)
        assert isinstance(data, dict)
        mock_rl.get_metrics.assert_called_once()

    def test_single_service(self, mock_rl):
        result = ss.get_rate_limit_status(service="lmstudio")
        data = json.loads(result)
        assert "service" in data
        mock_rl.get_status.assert_called_once_with("lmstudio")

    def test_status_has_tokens_field(self, mock_rl):
        result = ss.get_rate_limit_status(service="lmstudio")
        data = json.loads(result)
        assert "tokens" in data


class TestConfigureRateLimit:
    def test_returns_valid_json(self):
        result = ss.configure_rate_limit("lmstudio", 20, 5.0)
        json.loads(result)

    def test_status_ok(self):
        result = ss.configure_rate_limit("lmstudio", 20, 5.0)
        assert json.loads(result)["status"] == "ok"

    def test_response_has_fields(self):
        result = ss.configure_rate_limit("svc", 30, 3.0)
        data = json.loads(result)
        assert data["service"] == "svc"
        assert data["capacity"] == 30
        assert data["refill_rate"] == 3.0

    def test_calls_configure_service(self, mock_rl):
        ss.configure_rate_limit("custom", 100, 10.0)
        mock_rl.configure_service.assert_called_once()


class TestResetRateLimit:
    def test_returns_valid_json(self):
        result = ss.reset_rate_limit("lmstudio")
        json.loads(result)

    def test_status_ok(self):
        result = ss.reset_rate_limit("lmstudio")
        assert json.loads(result)["status"] == "ok"

    def test_calls_release_all(self, mock_rl):
        ss.reset_rate_limit("lmstudio")
        mock_rl.release_all.assert_called_once_with("lmstudio")

    def test_service_in_response(self):
        result = ss.reset_rate_limit("tts")
        assert json.loads(result)["service"] == "tts"


class TestGetRateMetrics:
    def test_returns_valid_json(self):
        result = ss.get_rate_metrics()
        json.loads(result)

    def test_calls_get_metrics(self, mock_rl):
        ss.get_rate_metrics()
        mock_rl.get_metrics.assert_called_once()

    def test_returns_dict(self):
        result = ss.get_rate_metrics()
        assert isinstance(json.loads(result), dict)


class TestCheckBackpressure:
    def test_returns_valid_json(self):
        result = ss.check_backpressure()
        json.loads(result)

    def test_has_backpressure_count(self):
        result = ss.check_backpressure()
        data = json.loads(result)
        assert "backpressure_count" in data

    def test_has_services_list(self):
        result = ss.check_backpressure()
        data = json.loads(result)
        assert "services" in data
        assert isinstance(data["services"], list)

    def test_empty_when_no_pressure(self, mock_rl):
        mock_rl.backpressure_active.return_value = False
        result = ss.check_backpressure()
        data = json.loads(result)
        assert data["backpressure_count"] == 0

    def test_includes_services_under_pressure(self, mock_rl):
        mock_rl._buckets = {"svc_a": MagicMock(), "svc_b": MagicMock()}
        mock_rl.backpressure_active.side_effect = lambda s: s == "svc_a"
        mock_rl.get_status.return_value = {"service": "svc_a", "tokens": 0.1}
        result = ss.check_backpressure()
        data = json.loads(result)
        assert data["backpressure_count"] == 1


# ---------------------------------------------------------------------------
# Skill registration assertions
# ---------------------------------------------------------------------------


class TestSkillRegistration:
    def test_all_skills_registered(self):
        from engine.skills.registry import SKILL_REGISTRY

        security_skills = [
            "get_secret_status",
            "rotate_secret",
            "check_secret_expiry",
            "load_secrets_from_env",
            "get_secret_audit_log",
            "get_rate_limit_status",
            "configure_rate_limit",
            "reset_rate_limit",
            "get_rate_metrics",
            "check_backpressure",
        ]
        for skill_name in security_skills:
            assert SKILL_REGISTRY.get_skill(skill_name) is not None, (
                f"Skill '{skill_name}' is not registered"
            )

    def test_security_pack_exists(self):
        from engine.skills.registry import SKILL_REGISTRY

        packs = SKILL_REGISTRY.all_packs()
        assert "security" in packs

    def test_security_pack_has_10_skills(self):
        from engine.skills.registry import SKILL_REGISTRY

        metas = SKILL_REGISTRY.get_pack_metas("security")
        assert len(metas) == 10

    def test_all_skills_category_system(self):
        from engine.skills.registry import SKILL_REGISTRY

        metas = SKILL_REGISTRY.get_pack_metas("security")
        for meta in metas:
            assert meta.category == "system", (
                f"Skill '{meta.name}' has category '{meta.category}', expected 'system'"
            )

    def test_all_skills_have_descriptions(self):
        from engine.skills.registry import SKILL_REGISTRY

        metas = SKILL_REGISTRY.get_pack_metas("security")
        for meta in metas:
            assert meta.description, f"Skill '{meta.name}' is missing a description"

    def test_all_skills_return_valid_json(self, mock_sm, mock_rl):
        """End-to-end: every skill function returns parseable JSON."""
        skill_calls = [
            (ss.get_secret_status, []),
            (ss.get_secret_status, ["test_key"]),
            (ss.rotate_secret, ["k", "v"]),
            (ss.check_secret_expiry, []),
            (ss.load_secrets_from_env, []),
            (ss.get_secret_audit_log, []),
            (ss.get_rate_limit_status, []),
            (ss.get_rate_limit_status, ["lmstudio"]),
            (ss.configure_rate_limit, ["svc", 10, 1.0]),
            (ss.reset_rate_limit, ["lmstudio"]),
            (ss.get_rate_metrics, []),
            (ss.check_backpressure, []),
        ]
        for func, args in skill_calls:
            result = func(*args)
            try:
                json.loads(result)
            except json.JSONDecodeError as exc:
                pytest.fail(f"{func.__name__}{args} returned invalid JSON: {exc}")
