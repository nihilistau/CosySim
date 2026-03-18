"""
Tests for engine.security.secret_manager — 55+ tests covering:
- SecretEntry creation and validation
- set / get / delete lifecycle
- Fernet encryption round-trip
- TTL / expiry logic
- load_from_env and load_from_config
- Audit log recording
- list_secrets (never exposes values)
- rotate (updates rotated_at, logs to Nexus)
- export_safe_report (metadata only)
- Persistence across instances
- Helper functions
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.security.secret_manager import (
    SecretEntry,
    SecretManager,
    SecretSource,
    SecretType,
    _count_by,
    _infer_secret_type,
    _is_secret_key,
    get_secret_manager,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sm(tmp_path: Path) -> SecretManager:
    """Fresh SecretManager backed by a temp SQLite DB and key file."""
    return SecretManager(
        db_path=str(tmp_path / "secrets.db"),
        key_file=str(tmp_path / ".secret_key"),
    )


@pytest.fixture()
def sm2(tmp_path: Path) -> SecretManager:
    """Second instance sharing the same DB/key — tests persistence."""
    return SecretManager(
        db_path=str(tmp_path / "secrets.db"),
        key_file=str(tmp_path / ".secret_key"),
    )


# ---------------------------------------------------------------------------
# SecretEntry tests
# ---------------------------------------------------------------------------


class TestSecretEntry:
    def test_creation_minimal(self):
        entry = SecretEntry(name="k", value="v")
        assert entry.name == "k"
        assert entry.value == "v"
        assert entry.secret_type == SecretType.OTHER

    def test_creation_full(self):
        now = datetime.now(timezone.utc)
        entry = SecretEntry(
            name="tok",
            value="secret",
            secret_type=SecretType.API_KEY,
            created_at=now,
            source=SecretSource.ENV_VAR,
            tags=["prod"],
        )
        assert entry.secret_type == SecretType.API_KEY
        assert entry.source == SecretSource.ENV_VAR
        assert "prod" in entry.tags

    def test_not_expired_no_expiry(self):
        entry = SecretEntry(name="k", value="v")
        assert entry.is_expired() is False

    def test_not_expired_future(self):
        entry = SecretEntry(
            name="k",
            value="v",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        assert entry.is_expired() is False

    def test_expired_past(self):
        entry = SecretEntry(
            name="k",
            value="v",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        assert entry.is_expired() is True

    def test_expires_soon_true(self):
        entry = SecretEntry(
            name="k",
            value="v",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=100),
        )
        assert entry.expires_soon(threshold_seconds=200) is True

    def test_expires_soon_false_far_future(self):
        entry = SecretEntry(
            name="k",
            value="v",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        assert entry.expires_soon(threshold_seconds=3600) is False

    def test_expires_soon_no_expiry(self):
        entry = SecretEntry(name="k", value="v")
        assert entry.expires_soon() is False

    def test_expires_soon_already_expired(self):
        entry = SecretEntry(
            name="k",
            value="v",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        )
        # Already expired — not "soon"
        assert entry.expires_soon() is False

    def test_tags_default_empty(self):
        entry = SecretEntry(name="k", value="v")
        assert entry.tags == []

    def test_rotated_at_default_none(self):
        entry = SecretEntry(name="k", value="v")
        assert entry.rotated_at is None


# ---------------------------------------------------------------------------
# SecretType & SecretSource enums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_secret_type_values(self):
        assert SecretType.API_KEY == "api_key"
        assert SecretType.BEARER_TOKEN == "bearer_token"
        assert SecretType.DB_PATH == "db_path"
        assert SecretType.PASSWORD == "password"
        assert SecretType.CERT == "cert"
        assert SecretType.WEBHOOK == "webhook"
        assert SecretType.OTHER == "other"

    def test_secret_source_values(self):
        assert SecretSource.ENV_VAR == "env_var"
        assert SecretSource.CONFIG_FILE == "config_file"
        assert SecretSource.VAULT_FILE == "vault_file"
        assert SecretSource.RUNTIME == "runtime"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_is_secret_key_token(self):
        assert _is_secret_key("api_token") is True

    def test_is_secret_key_password(self):
        assert _is_secret_key("db_password") is True

    def test_is_secret_key_secret(self):
        assert _is_secret_key("client_secret") is True

    def test_is_secret_key_key(self):
        assert _is_secret_key("api_key") is True

    def test_is_secret_key_bearer(self):
        assert _is_secret_key("bearer_header") is True

    def test_is_secret_key_negative(self):
        assert _is_secret_key("database_host") is False
        assert _is_secret_key("port") is False

    def test_infer_type_bearer(self):
        assert _infer_secret_type("bearer_token") == SecretType.BEARER_TOKEN

    def test_infer_type_token(self):
        assert _infer_secret_type("access_token") == SecretType.BEARER_TOKEN

    def test_infer_type_api_key(self):
        assert _infer_secret_type("api_key") == SecretType.API_KEY

    def test_infer_type_apikey(self):
        assert _infer_secret_type("apikey") == SecretType.API_KEY

    def test_infer_type_password(self):
        assert _infer_secret_type("db_password") == SecretType.PASSWORD

    def test_infer_type_passwd(self):
        assert _infer_secret_type("passwd") == SecretType.PASSWORD

    def test_infer_type_cert(self):
        assert _infer_secret_type("ssl_cert") == SecretType.CERT

    def test_infer_type_webhook(self):
        assert _infer_secret_type("webhook_url") == SecretType.WEBHOOK

    def test_infer_type_db_path(self):
        assert _infer_secret_type("database_path") == SecretType.DB_PATH

    def test_infer_type_other(self):
        assert _infer_secret_type("some_random_thing") == SecretType.OTHER

    def test_count_by(self):
        secrets = [
            {"secret_type": "api_key"},
            {"secret_type": "api_key"},
            {"secret_type": "password"},
        ]
        result = _count_by(secrets, "secret_type")
        assert result["api_key"] == 2
        assert result["password"] == 1


# ---------------------------------------------------------------------------
# Set / Get / Delete lifecycle
# ---------------------------------------------------------------------------


class TestSetGetDelete:
    def test_set_and_get(self, sm):
        sm.set("my_key", "my_value", SecretType.API_KEY)
        assert sm.get("my_key") == "my_value"

    def test_get_unknown_returns_default(self, sm):
        assert sm.get("nonexistent") is None
        assert sm.get("nonexistent", "fallback") == "fallback"

    def test_set_updates_existing(self, sm):
        sm.set("k", "v1")
        sm.set("k", "v2")
        assert sm.get("k") == "v2"

    def test_set_preserves_created_at_on_update(self, sm):
        sm.set("k", "v1")
        first_created = sm._cache["k"].created_at
        time.sleep(0.01)
        sm.set("k", "v2")
        assert sm._cache["k"].created_at == first_created

    def test_set_with_ttl(self, sm):
        sm.set("expiring", "val", ttl_seconds=60)
        assert sm._cache["expiring"].expires_at is not None

    def test_set_expired_ttl_returns_default(self, sm):
        sm.set("expired_key", "val", ttl_seconds=0)
        # TTL of 0 → immediate expiry
        time.sleep(0.01)
        assert sm.get("expired_key") is None

    def test_set_with_tags(self, sm):
        sm.set("k", "v", tags=["prod", "lmstudio"])
        assert sm._cache["k"].tags == ["prod", "lmstudio"]

    def test_set_source(self, sm):
        sm.set("k", "v", source=SecretSource.ENV_VAR)
        assert sm._cache["k"].source == SecretSource.ENV_VAR

    def test_delete_existing(self, sm):
        sm.set("k", "v")
        result = sm.delete("k")
        assert result is True
        assert sm.get("k") is None

    def test_delete_nonexistent(self, sm):
        assert sm.delete("ghost") is False

    def test_delete_clears_cache(self, sm):
        sm.set("k", "v")
        sm.delete("k")
        assert "k" not in sm._cache


# ---------------------------------------------------------------------------
# Fernet encryption
# ---------------------------------------------------------------------------


class TestEncryption:
    def test_fernet_round_trip(self, sm):
        """Encrypted value is correctly decrypted on read."""
        sm.set("secret", "my_plaintext", SecretType.API_KEY)
        assert sm.get("secret") == "my_plaintext"

    def test_fernet_key_generated(self, tmp_path):
        key_file = tmp_path / ".key"
        assert not key_file.exists()
        SecretManager(
            db_path=str(tmp_path / "s.db"), key_file=str(key_file)
        )
        assert key_file.exists()

    def test_fernet_key_persists(self, tmp_path):
        """Two instances sharing the same key file can decrypt each other's data."""
        db = str(tmp_path / "s.db")
        key = str(tmp_path / ".key")
        sm_a = SecretManager(db_path=db, key_file=key)
        sm_a.set("cross", "instance_value")
        sm_b = SecretManager(db_path=db, key_file=key)
        assert sm_b.get("cross") == "instance_value"

    def test_plaintext_fallback(self, tmp_path):
        """When _FERNET_AVAILABLE is patched to False, values are stored plaintext."""
        with patch("engine.security.secret_manager._FERNET_AVAILABLE", False):
            sm_plain = SecretManager(
                db_path=str(tmp_path / "plain.db"),
                key_file=str(tmp_path / ".key"),
            )
            sm_plain.set("k", "plainval")
            assert sm_plain.get("k") == "plainval"


# ---------------------------------------------------------------------------
# list_secrets — never exposes values
# ---------------------------------------------------------------------------


class TestListSecrets:
    def test_list_secrets_empty(self, sm):
        assert sm.list_secrets() == []

    def test_list_secrets_no_value_field(self, sm):
        sm.set("k", "sensitive_value", SecretType.API_KEY)
        for item in sm.list_secrets():
            assert "value" not in item
            assert "sensitive_value" not in str(item)

    def test_list_secrets_by_type(self, sm):
        sm.set("k1", "v1", SecretType.API_KEY)
        sm.set("k2", "v2", SecretType.PASSWORD)
        results = sm.list_secrets(secret_type=SecretType.API_KEY)
        assert len(results) == 1
        assert results[0]["name"] == "k1"

    def test_list_secrets_by_tags(self, sm):
        sm.set("k1", "v1", tags=["prod"])
        sm.set("k2", "v2", tags=["dev"])
        results = sm.list_secrets(tags=["prod"])
        assert len(results) == 1
        assert results[0]["name"] == "k1"

    def test_list_secrets_multiple(self, sm):
        sm.set("a", "va", SecretType.API_KEY)
        sm.set("b", "vb", SecretType.PASSWORD)
        assert len(sm.list_secrets()) == 2

    def test_list_secrets_metadata_fields(self, sm):
        sm.set("k", "v", SecretType.API_KEY, tags=["test"])
        item = sm.list_secrets()[0]
        assert "name" in item
        assert "secret_type" in item
        assert "source" in item
        assert "tags" in item
        assert "created_at" in item
        assert "is_expired" in item


# ---------------------------------------------------------------------------
# rotate
# ---------------------------------------------------------------------------


class TestRotate:
    def test_rotate_updates_value(self, sm):
        sm.set("tok", "old_value")
        sm.rotate("tok", "new_value")
        assert sm.get("tok") == "new_value"

    def test_rotate_updates_rotated_at(self, sm):
        sm.set("tok", "v1")
        assert sm._cache["tok"].rotated_at is None
        sm.rotate("tok", "v2")
        assert sm._cache["tok"].rotated_at is not None

    def test_rotate_nonexistent_returns_false(self, sm):
        assert sm.rotate("ghost", "new_val") is False

    def test_rotate_logs_to_nexus(self, sm):
        sm.set("tok", "v1")
        mock_client = MagicMock()
        with patch(
            "engine.nexus.client.get_nexus_client", return_value=mock_client
        ):
            sm.rotate("tok", "v2")
        mock_client.add_entry.assert_called_once()

    def test_rotate_nexus_failure_nonfatal(self, sm):
        sm.set("tok", "v1")
        with patch(
            "engine.nexus.client.get_nexus_client",
            side_effect=Exception("network down"),
        ):
            # Should not raise
            result = sm.rotate("tok", "v2")
        assert result is True
        assert sm.get("tok") == "v2"


# ---------------------------------------------------------------------------
# load_from_env
# ---------------------------------------------------------------------------


class TestLoadFromEnv:
    def test_load_from_env_basic(self, sm, monkeypatch):
        monkeypatch.setenv("COSYSIM_MY_TOKEN", "tok123")
        count = sm.load_from_env()
        assert count >= 1
        assert sm.get("my_token") == "tok123"

    def test_load_from_env_empty_prefix(self, sm, monkeypatch):
        # No matching vars
        count = sm.load_from_env(prefix="NONEXISTENT_PREFIX_XYZ_")
        assert count == 0

    def test_load_from_env_strips_prefix(self, sm, monkeypatch):
        monkeypatch.setenv("COSYSIM_SOME_KEY", "value")
        sm.load_from_env()
        assert sm.get("some_key") == "value"

    def test_load_from_env_infers_type(self, sm, monkeypatch):
        monkeypatch.setenv("COSYSIM_API_TOKEN", "tok")
        sm.load_from_env()
        entry = sm._cache.get("api_token")
        assert entry is not None
        assert entry.source == SecretSource.ENV_VAR

    def test_load_from_env_returns_count(self, sm, monkeypatch):
        monkeypatch.setenv("COSYSIM_ALPHA", "a")
        monkeypatch.setenv("COSYSIM_BETA", "b")
        count = sm.load_from_env()
        assert count >= 2


# ---------------------------------------------------------------------------
# load_from_config
# ---------------------------------------------------------------------------


class TestLoadFromConfig:
    def _mock_cfg(self, top_level_data: dict, full_data: dict = None) -> MagicMock:
        cfg = MagicMock()
        cfg.get.side_effect = lambda path, default=None: top_level_data.get(path, default)
        cfg.get_all.return_value = full_data if full_data is not None else top_level_data
        return cfg

    def test_load_lmstudio_api_token(self, sm):
        cfg = self._mock_cfg({"lmstudio.api_token": "lm_tok_123"}, {})
        with patch("engine.config.get_config", return_value=cfg):
            count = sm.load_from_config()
        assert count >= 1
        assert sm.get("lmstudio_api_token") == "lm_tok_123"

    def test_load_nexus_api_key(self, sm):
        cfg = self._mock_cfg({"nexus.api_key": "nex_key_456"}, {})
        with patch("engine.config.get_config", return_value=cfg):
            count = sm.load_from_config()
        assert count >= 1

    def test_load_scans_all_keys(self, sm):
        full_data = {"section": {"api_token": "tok", "host": "localhost"}}
        cfg = self._mock_cfg({}, full_data)
        with patch("engine.config.get_config", return_value=cfg):
            sm.load_from_config()
        # api_token should have been found; host should not
        assert sm.get("section_api_token") == "tok"

    def test_load_from_config_does_not_override_existing(self, sm):
        sm.set("lmstudio_api_token", "manual_value")
        cfg = self._mock_cfg({"lmstudio.api_token": "config_value"}, {})
        with patch("engine.config.get_config", return_value=cfg):
            sm.load_from_config()
        # Manual value should NOT be overridden since key already in cache
        assert sm.get("lmstudio_api_token") == "manual_value"


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


class TestAuditLog:
    def test_audit_records_create(self, sm):
        sm.set("k", "v")
        log = sm.get_audit_log()
        events = [e["event_type"] for e in log]
        assert "create" in events

    def test_audit_records_access(self, sm):
        sm.set("k", "v")
        sm.get("k")
        log = sm.get_audit_log()
        events = [e["event_type"] for e in log]
        assert "access" in events

    def test_audit_records_delete(self, sm):
        sm.set("k", "v")
        sm.delete("k")
        log = sm.get_audit_log()
        events = [e["event_type"] for e in log]
        assert "delete" in events

    def test_audit_records_rotate(self, sm):
        sm.set("k", "v")
        with patch("engine.nexus.client.get_nexus_client"):
            sm.rotate("k", "v2")
        log = sm.get_audit_log()
        events = [e["event_type"] for e in log]
        assert "rotate" in events

    def test_audit_records_expired_access(self, sm):
        sm.set("k", "v", ttl_seconds=0)
        time.sleep(0.02)
        sm.get("k")
        log = sm.get_audit_log()
        events = [e["event_type"] for e in log]
        assert "access_expired" in events

    def test_audit_log_limit(self, sm):
        for i in range(10):
            sm.set(f"key_{i}", "v")
        log = sm.get_audit_log(limit=3)
        assert len(log) <= 3

    def test_audit_log_fields(self, sm):
        sm.set("k", "v")
        entry = sm.get_audit_log()[0]
        assert "timestamp" in entry
        assert "event_type" in entry
        assert "secret_name" in entry
        assert "actor" in entry


# ---------------------------------------------------------------------------
# check_expiry
# ---------------------------------------------------------------------------


class TestCheckExpiry:
    def test_no_expired(self, sm):
        sm.set("k", "v")
        result = sm.check_expiry()
        assert result["expired"] == []
        assert result["expiring_soon"] == []

    def test_detects_expired(self, sm):
        sm.set("dead", "v", ttl_seconds=0)
        time.sleep(0.02)
        result = sm.check_expiry()
        assert "dead" in result["expired"]

    def test_detects_expiring_soon(self, sm):
        sm.set("soon", "v", ttl_seconds=100)
        result = sm.check_expiry()
        # 100 s < 24 h threshold
        assert "soon" in result["expiring_soon"]

    def test_nexus_alert_on_expired(self, sm):
        sm.set("dead", "v", ttl_seconds=0)
        time.sleep(0.02)
        mock_client = MagicMock()
        with patch(
            "engine.nexus.client.get_nexus_client", return_value=mock_client
        ):
            sm.check_expiry()
        mock_client.add_entry.assert_called_once()

    def test_nexus_failure_nonfatal(self, sm):
        sm.set("dead", "v", ttl_seconds=0)
        time.sleep(0.02)
        with patch(
            "engine.nexus.client.get_nexus_client",
            side_effect=RuntimeError("down"),
        ):
            result = sm.check_expiry()  # Must not raise
        assert "dead" in result["expired"]


# ---------------------------------------------------------------------------
# export_safe_report
# ---------------------------------------------------------------------------


class TestExportSafeReport:
    def test_no_values_in_report(self, sm):
        sm.set("k", "super_secret_value", SecretType.API_KEY)
        report = sm.export_safe_report()
        assert "super_secret_value" not in json.dumps(report)

    def test_report_counts(self, sm):
        sm.set("k1", "v1", SecretType.API_KEY)
        sm.set("k2", "v2", SecretType.PASSWORD)
        report = sm.export_safe_report()
        assert report["total_secrets"] == 2
        assert report["by_type"]["api_key"] == 1
        assert report["by_type"]["password"] == 1

    def test_report_empty(self, sm):
        report = sm.export_safe_report()
        assert report["total_secrets"] == 0
        assert report["secrets"] == []

    def test_report_expired_count(self, sm):
        sm.set("live", "v1")
        sm.set("dead", "v2", ttl_seconds=0)
        time.sleep(0.02)
        report = sm.export_safe_report()
        assert report["expired_count"] >= 1

    def test_report_has_required_fields(self, sm):
        report = sm.export_safe_report()
        assert "total_secrets" in report
        assert "by_type" in report
        assert "by_source" in report
        assert "expired_count" in report
        assert "secrets" in report


# ---------------------------------------------------------------------------
# Persistence across instances
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_survives_restart(self, tmp_path):
        db = str(tmp_path / "s.db")
        key = str(tmp_path / ".key")
        sm_a = SecretManager(db_path=db, key_file=key)
        sm_a.set("persistent_key", "persistent_value", SecretType.API_KEY)
        del sm_a
        sm_b = SecretManager(db_path=db, key_file=key)
        assert sm_b.get("persistent_key") == "persistent_value"

    def test_delete_persists(self, tmp_path):
        db = str(tmp_path / "s.db")
        key = str(tmp_path / ".key")
        sm_a = SecretManager(db_path=db, key_file=key)
        sm_a.set("k", "v")
        sm_a.delete("k")
        del sm_a
        sm_b = SecretManager(db_path=db, key_file=key)
        assert sm_b.get("k") is None


# ---------------------------------------------------------------------------
# Thread safety smoke test
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_set_get(self, sm):
        import threading

        errors = []

        def worker(i: int) -> None:
            try:
                sm.set(f"key_{i}", f"val_{i}")
                val = sm.get(f"key_{i}")
                assert val == f"val_{i}"
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread safety errors: {errors}"
