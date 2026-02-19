"""Tests for ConfigManager — dot-notation, env overrides, deep merge."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.config import ConfigManager


class TestDotNotation:
    """Config.get() with dot-separated keys."""

    def test_nested_key(self):
        config = ConfigManager()
        # default.yaml should have scenes.phone.port
        port = config.get("scenes.phone.port")
        assert port is not None

    def test_missing_key_returns_default(self):
        config = ConfigManager()
        val = config.get("totally.nonexistent.path", "fallback")
        assert val == "fallback"

    def test_set_and_get(self):
        config = ConfigManager()
        config.set("test.nested.key", 42)
        assert config.get("test.nested.key") == 42


class TestEnvOverride:
    """Environment variables override YAML values."""

    def test_env_var_overrides_config(self, monkeypatch):
        monkeypatch.setenv("COSYSIM_DB_PATH", "/tmp/override.db")
        config = ConfigManager()
        assert config.get("database.sqlite.path") == "/tmp/override.db"

    def test_legacy_env_var(self, monkeypatch):
        monkeypatch.setenv("COSYVOICE_LLM_URL", "http://custom:9999")
        config = ConfigManager()
        assert config.get("llm.base_url") == "http://custom:9999"
