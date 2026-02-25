"""Tests for config validator — extended LMStudio schema validation."""
from __future__ import annotations

import pytest

from engine.config_validator import validate_config


def _base_config():
    """Minimal valid config."""
    return {
        "system": {"name": "CosySim", "version": "0.51"},
        "database": {"sqlite": {"path": "data/cosysim.db"}},
        "scenes": {
            "phone": {"port": 5555},
            "bedroom": {"port": 5556},
            "dashboard": {"port": 8500},
        },
        "llm": {"default": {"base_url": "http://localhost:1234"}},
        "logging": {"level": "INFO"},
    }


class TestBaseValidation:
    def test_valid_config(self):
        cfg = _base_config()
        warnings = validate_config(cfg)
        assert warnings == []

    def test_missing_required(self):
        cfg = _base_config()
        del cfg["system"]["name"]
        warnings = validate_config(cfg)
        assert any("system.name" in w for w in warnings)

    def test_type_mismatch(self):
        cfg = _base_config()
        cfg["scenes"]["phone"]["port"] = "not_a_port"
        warnings = validate_config(cfg)
        assert any("phone.port" in w and "int" in w for w in warnings)

    def test_range_violation(self):
        cfg = _base_config()
        cfg["scenes"]["phone"]["port"] = 80  # below 1024
        warnings = validate_config(cfg)
        assert any("outside range" in w for w in warnings)

    def test_port_conflict(self):
        cfg = _base_config()
        cfg["scenes"]["bedroom"]["port"] = 5555  # same as phone
        warnings = validate_config(cfg)
        assert any("conflict" in w for w in warnings)


class TestLMStudioValidation:
    def test_valid_lmstudio_config(self):
        cfg = _base_config()
        cfg["lmstudio"] = {
            "load_mode": "concurrent",
            "concurrent_slots": 4,
            "jit_ttl_seconds": 300,
            "vram_cap_mb": 11500,
            "resource_manager": {"strategy": "concurrent", "default_ttl": 300},
            "default_load_opts": {"gpu": 0.9, "context_length": 4096},
        }
        warnings = validate_config(cfg)
        assert warnings == []

    def test_invalid_load_mode(self):
        cfg = _base_config()
        cfg["lmstudio"] = {"load_mode": "invalid_mode"}
        warnings = validate_config(cfg)
        assert any("load_mode" in w and "not in allowed" in w for w in warnings)

    def test_invalid_strategy(self):
        cfg = _base_config()
        cfg["lmstudio"] = {"resource_manager": {"strategy": "bad_strategy"}}
        warnings = validate_config(cfg)
        assert any("strategy" in w and "not in allowed" in w for w in warnings)

    def test_concurrent_slots_out_of_range(self):
        cfg = _base_config()
        cfg["lmstudio"] = {"concurrent_slots": 100}
        warnings = validate_config(cfg)
        assert any("concurrent_slots" in w and "outside range" in w for w in warnings)

    def test_jit_ttl_out_of_range(self):
        cfg = _base_config()
        cfg["lmstudio"] = {"jit_ttl_seconds": 5}  # below 10
        warnings = validate_config(cfg)
        assert any("jit_ttl_seconds" in w for w in warnings)

    def test_vram_cap_valid(self):
        cfg = _base_config()
        cfg["lmstudio"] = {"vram_cap_mb": 24000}
        warnings = validate_config(cfg)
        assert not any("vram_cap_mb" in w for w in warnings)

    def test_gpu_fraction_out_of_range(self):
        cfg = _base_config()
        cfg["lmstudio"] = {"default_load_opts": {"gpu": 1.5}}
        warnings = validate_config(cfg)
        assert any("gpu" in w and "outside range" in w for w in warnings)

    def test_context_length_valid(self):
        cfg = _base_config()
        cfg["lmstudio"] = {"default_load_opts": {"context_length": 32768}}
        warnings = validate_config(cfg)
        assert not any("context_length" in w for w in warnings)

    def test_context_length_too_small(self):
        cfg = _base_config()
        cfg["lmstudio"] = {"default_load_opts": {"context_length": 100}}
        warnings = validate_config(cfg)
        assert any("context_length" in w for w in warnings)


class TestLoggingValidation:
    def test_valid_logging_level(self):
        cfg = _base_config()
        cfg["logging"]["level"] = "DEBUG"
        warnings = validate_config(cfg)
        assert not any("logging.level" in w for w in warnings)

    def test_invalid_logging_level(self):
        cfg = _base_config()
        cfg["logging"]["level"] = "VERBOSE"
        warnings = validate_config(cfg)
        assert any("logging.level" in w and "not in allowed" in w for w in warnings)


class TestMissingOptionalKeys:
    def test_no_lmstudio_section(self):
        cfg = _base_config()
        # No lmstudio section — should be fine (all optional)
        warnings = validate_config(cfg)
        assert warnings == []

    def test_empty_lmstudio_section(self):
        cfg = _base_config()
        cfg["lmstudio"] = {}
        warnings = validate_config(cfg)
        assert warnings == []
