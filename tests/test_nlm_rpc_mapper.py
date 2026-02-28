"""Tests for engine.nexus.nlm_rpc_mapper.

Covers NLMRPCRegistry, get_rpc_id(), get_registry(), invalidate(),
and the _FALLBACK_RPC_IDS dictionary.

All tests that touch the filesystem redirect _REGISTRY_FILE to tmp_path —
the real data/nlm_rpc_registry.json is never read or written.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

import engine.nexus.nlm_rpc_mapper as mapper_module
from engine.nexus.nlm_rpc_mapper import (
    NLMRPCRegistry,
    _FALLBACK_RPC_IDS,
    get_rpc_id,
    get_registry,
    invalidate,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the module-level singleton before and after every test."""
    mapper_module._registry = None
    yield
    mapper_module._registry = None


@pytest.fixture()
def registry_path(tmp_path, monkeypatch):
    """Patch _REGISTRY_FILE to an isolated temp path and return it."""
    path = tmp_path / "nlm_rpc_registry.json"
    monkeypatch.setattr(mapper_module, "_REGISTRY_FILE", path)
    return path


@pytest.fixture()
def populated_registry_path(registry_path):
    """Write a realistic registry JSON and return the path."""
    data = {
        "rpc_ids": {
            "ASK_QUESTION": "CUSTOM_ASK",
            "LOAD_NOTEBOOK": "CUSTOM_LOAD",
        },
        "updated_at": datetime.now().isoformat(),
        "bl": "test_bl_12345",
    }
    registry_path.write_text(json.dumps(data), encoding="utf-8")
    return registry_path


# ──────────────────────────────────────────────────────────────────────────────
# TestFallbackRPCIDs — integrity checks on the hardcoded dict
# ──────────────────────────────────────────────────────────────────────────────

class TestFallbackRPCIDs:
    """Verify the _FALLBACK_RPC_IDS constant is correct and complete."""

    def test_all_known_rpcs_are_strings(self):
        """Every non-None fallback must be a non-empty string."""
        for op, rpc in _FALLBACK_RPC_IDS.items():
            if rpc is not None:
                assert isinstance(rpc, str), f"{op} RPC is not a string: {rpc!r}"
                assert len(rpc) > 0, f"{op} RPC is an empty string"

    def test_known_rpcs_count(self):
        """At least 21 total entries must be present in the fallback dict."""
        assert len(_FALLBACK_RPC_IDS) >= 21, (
            f"Expected ≥21 entries, found {len(_FALLBACK_RPC_IDS)}"
        )

    def test_critical_rpcs_present(self):
        """The three most-used RPC IDs must be hardcoded with exact values."""
        assert _FALLBACK_RPC_IDS["ASK_QUESTION"] == "s0tc2d"
        assert _FALLBACK_RPC_IDS["LOAD_NOTEBOOK"] == "rLM1Ne"
        assert _FALLBACK_RPC_IDS["LIST_NOTEBOOKS"] == "ub2Bae"

    def test_unknown_rpcs_are_none(self):
        """Operations that have never been captured must map to None."""
        expected_none = [
            "DELETE_NOTEBOOK",
            "RENAME_NOTEBOOK",
            "DELETE_SOURCE",
            "ADD_TEXT_SOURCE",
            "ADD_FILE_SOURCE",
            "GENERATE_AUDIO_OVERVIEW",
            "SHARE_NOTEBOOK",
        ]
        for op in expected_none:
            assert op in _FALLBACK_RPC_IDS, f"{op} missing from fallback dict"
            assert _FALLBACK_RPC_IDS[op] is None, (
                f"{op} should be None, got {_FALLBACK_RPC_IDS[op]!r}"
            )

    def test_no_duplicate_rpc_ids_for_distinct_ops(self):
        """Non-None RPC IDs shared between operations must be intentional aliases."""
        # LOAD_NOTEBOOK and POLL_SOURCES intentionally share rLM1Ne;
        # LOAD_HOMEPAGE and GET_SESSION_LIMITS intentionally share ZwVcOc.
        # All others that are non-None and appear more than once should be known aliases.
        known_shared = {"rLM1Ne", "ZwVcOc", "CCqFvf"}
        seen: dict[str, str] = {}
        for op, rpc in _FALLBACK_RPC_IDS.items():
            if rpc is None:
                continue
            if rpc in seen and rpc not in known_shared:
                pytest.fail(
                    f"Unexpected duplicate RPC '{rpc}' for '{op}' and '{seen[rpc]}'"
                )
            seen.setdefault(rpc, op)


# ──────────────────────────────────────────────────────────────────────────────
# TestNLMRPCRegistry — class-level behaviour
# ──────────────────────────────────────────────────────────────────────────────

class TestNLMRPCRegistry:
    """Tests for the NLMRPCRegistry class."""

    # ── Construction ──────────────────────────────────────────────────────────

    def test_init_without_registry_file(self, registry_path):
        """Registry initialises successfully when the JSON file does not exist."""
        assert not registry_path.exists()
        reg = NLMRPCRegistry()
        assert reg is not None
        assert reg._data == {"rpc_ids": {}, "updated_at": None}

    # ── get_rpc_id ────────────────────────────────────────────────────────────

    def test_get_rpc_id_returns_fallback(self, registry_path):
        """Falls back to _FALLBACK_RPC_IDS when no registry file exists."""
        reg = NLMRPCRegistry()
        assert reg.get_rpc_id("ASK_QUESTION") == "s0tc2d"
        assert reg.get_rpc_id("LIST_NOTEBOOKS") == "ub2Bae"

    def test_get_rpc_id_returns_none_for_unknown(self, registry_path):
        """Returns None for an operation not in fallbacks or registry."""
        reg = NLMRPCRegistry()
        assert reg.get_rpc_id("TOTALLY_MADE_UP_OP") is None

    def test_get_rpc_id_prefers_registry_over_fallback(self, populated_registry_path):
        """Registry file value overrides the hardcoded fallback."""
        reg = NLMRPCRegistry()
        # populated_registry_path sets ASK_QUESTION → CUSTOM_ASK
        assert reg.get_rpc_id("ASK_QUESTION") == "CUSTOM_ASK"

    def test_get_rpc_id_uses_registry_first(self, registry_path):
        """For an operation absent from fallbacks, registry file is used."""
        data = {"rpc_ids": {"NEW_OP": "newrpc1"}, "updated_at": datetime.now().isoformat()}
        registry_path.write_text(json.dumps(data), encoding="utf-8")
        reg = NLMRPCRegistry()
        assert reg.get_rpc_id("NEW_OP") == "newrpc1"

    def test_get_rpc_id_falls_through_empty_registry_entry(self, registry_path):
        """An empty string in the registry falls through to the fallback."""
        data = {"rpc_ids": {"ASK_QUESTION": ""}, "updated_at": datetime.now().isoformat()}
        registry_path.write_text(json.dumps(data), encoding="utf-8")
        reg = NLMRPCRegistry()
        # Empty string → falsy → falls back to hardcoded "s0tc2d"
        assert reg.get_rpc_id("ASK_QUESTION") == "s0tc2d"

    # ── is_stale ──────────────────────────────────────────────────────────────

    def test_is_stale_when_no_file(self, registry_path):
        """Registry is stale when no file exists (updated_at is None)."""
        reg = NLMRPCRegistry()
        assert reg.is_stale() is True

    def test_is_stale_when_recently_updated(self, registry_path):
        """Registry is NOT stale when updated_at is recent (< 10 days ago)."""
        data = {"rpc_ids": {}, "updated_at": datetime.now().isoformat()}
        registry_path.write_text(json.dumps(data), encoding="utf-8")
        reg = NLMRPCRegistry()
        assert reg.is_stale() is False

    def test_is_stale_when_old(self, registry_path):
        """Registry is stale when updated_at is 11+ days in the past."""
        old_ts = (datetime.now() - timedelta(days=11)).isoformat()
        data = {"rpc_ids": {}, "updated_at": old_ts}
        registry_path.write_text(json.dumps(data), encoding="utf-8")
        reg = NLMRPCRegistry()
        assert reg.is_stale() is True

    def test_is_stale_with_malformed_date(self, registry_path):
        """Malformed updated_at is treated as stale (exception → True)."""
        data = {"rpc_ids": {}, "updated_at": "not-a-date"}
        registry_path.write_text(json.dumps(data), encoding="utf-8")
        reg = NLMRPCRegistry()
        assert reg.is_stale() is True

    # ── get_all ───────────────────────────────────────────────────────────────

    def test_get_all_returns_merged(self, registry_path):
        """get_all() contains both hardcoded fallbacks and registry entries."""
        data = {"rpc_ids": {"CUSTOM_OP": "customrpc"}, "updated_at": datetime.now().isoformat()}
        registry_path.write_text(json.dumps(data), encoding="utf-8")
        reg = NLMRPCRegistry()
        result = reg.get_all()
        # Fallback entries are present
        assert result.get("ASK_QUESTION") == "s0tc2d"
        # Registry entries are present
        assert result.get("CUSTOM_OP") == "customrpc"

    def test_get_all_registry_overrides_fallback(self, populated_registry_path):
        """Registry value wins when the same key exists in both."""
        reg = NLMRPCRegistry()
        result = reg.get_all()
        assert result["ASK_QUESTION"] == "CUSTOM_ASK"

    def test_get_all_without_file(self, registry_path):
        """get_all() returns only fallbacks when no registry file exists."""
        reg = NLMRPCRegistry()
        result = reg.get_all()
        # All fallback ops should be present
        for op in ("ASK_QUESTION", "LOAD_NOTEBOOK", "LIST_NOTEBOOKS"):
            assert op in result

    # ── get_unknown_operations ────────────────────────────────────────────────

    def test_get_unknown_operations(self, registry_path):
        """Returns the list of operations with a None fallback RPC ID."""
        reg = NLMRPCRegistry()
        unknowns = reg.get_unknown_operations()
        assert isinstance(unknowns, list)
        assert "DELETE_NOTEBOOK" in unknowns
        assert "RENAME_NOTEBOOK" in unknowns
        # Known operations must NOT be in the list
        assert "ASK_QUESTION" not in unknowns

    # ── get_operation (reverse lookup) ────────────────────────────────────────

    def test_get_operation_reverse_lookup(self, registry_path):
        """get_operation('s0tc2d') resolves to 'ASK_QUESTION' via fallback map."""
        reg = NLMRPCRegistry()
        op = reg.get_operation("s0tc2d")
        assert op == "ASK_QUESTION"

    def test_get_operation_registry_reverse_lookup(self, registry_path):
        """get_operation() checks registry entries before fallback map."""
        data = {"rpc_ids": {"CUSTOM_OP": "myrpc42"}, "updated_at": datetime.now().isoformat()}
        registry_path.write_text(json.dumps(data), encoding="utf-8")
        reg = NLMRPCRegistry()
        op = reg.get_operation("myrpc42")
        assert op == "CUSTOM_OP"

    def test_get_operation_unknown_rpc(self, registry_path):
        """get_operation() returns UNKNOWN(rpc_id) for completely unknown IDs."""
        reg = NLMRPCRegistry()
        result = reg.get_operation("zzz999neverexists")
        assert "UNKNOWN" in result
        assert "zzz999neverexists" in result

    # ── get_bl ────────────────────────────────────────────────────────────────

    def test_get_bl_returns_none_without_file(self, registry_path):
        """get_bl() returns None when no registry file is present."""
        reg = NLMRPCRegistry()
        assert reg.get_bl() is None

    def test_get_bl_returns_value_from_file(self, populated_registry_path):
        """get_bl() reads the 'bl' key from the registry JSON file."""
        reg = NLMRPCRegistry()
        assert reg.get_bl() == "test_bl_12345"

    # ── update_from_automation ────────────────────────────────────────────────

    def test_update_from_automation_writes_file(self, registry_path):
        """update_from_automation() creates the registry JSON file."""
        reg = NLMRPCRegistry()
        assert not registry_path.exists()
        reg.update_from_automation({"ASK_QUESTION": ["newrpc1"]})
        assert registry_path.exists()
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        assert data["rpc_ids"]["ASK_QUESTION"] == "newrpc1"

    def test_update_from_automation_merges_ops(self, registry_path):
        """New operations are added; existing entries are updated, not wiped."""
        # Pre-seed with one entry
        existing = {"rpc_ids": {"LOAD_NOTEBOOK": "rLM1Ne"}, "updated_at": datetime.now().isoformat()}
        registry_path.write_text(json.dumps(existing), encoding="utf-8")
        reg = NLMRPCRegistry()

        reg.update_from_automation({"ASK_QUESTION": ["s0tc2d"]})

        data = json.loads(registry_path.read_text(encoding="utf-8"))
        assert data["rpc_ids"]["LOAD_NOTEBOOK"] == "rLM1Ne"   # preserved
        assert data["rpc_ids"]["ASK_QUESTION"] == "s0tc2d"    # added

    def test_update_from_automation_stores_bl(self, registry_path):
        """update_from_automation() persists the build label to the file."""
        reg = NLMRPCRegistry()
        reg.update_from_automation({"ASK_QUESTION": ["s0tc2d"]}, bl="bl_20260226")
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        assert data["bl"] == "bl_20260226"

    def test_update_from_automation_uses_first_rpc_when_multiple(self, registry_path):
        """When multiple RPCs are provided for an op, the first is stored."""
        reg = NLMRPCRegistry()
        reg.update_from_automation({"ASK_QUESTION": ["primary", "secondary"]})
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        assert data["rpc_ids"]["ASK_QUESTION"] == "primary"

    def test_update_from_automation_sets_updated_at(self, registry_path):
        """updated_at is written as a valid ISO timestamp."""
        reg = NLMRPCRegistry()
        reg.update_from_automation({"ASK_QUESTION": ["s0tc2d"]})
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        ts = data.get("updated_at")
        assert ts is not None
        # Should be parseable by fromisoformat
        dt = datetime.fromisoformat(ts)
        # Should be recent (within last 10 seconds)
        assert (datetime.now() - dt).total_seconds() < 10

    # ── report ────────────────────────────────────────────────────────────────

    def test_report_is_string(self, registry_path):
        """report() returns a non-empty human-readable string."""
        reg = NLMRPCRegistry()
        result = reg.report()
        assert isinstance(result, str)
        assert len(result) > 0
        assert "NLM RPC Registry" in result

    def test_report_contains_captured_and_missing_sections(self, populated_registry_path):
        """report() lists both captured operations and missing ones."""
        reg = NLMRPCRegistry()
        result = reg.report()
        assert "Captured" in result
        assert "Missing" in result

    # ── _reload_if_stale ──────────────────────────────────────────────────────

    def test_reload_if_stale_on_file_change(self, registry_path):
        """Registry reloads from disk when file mtime advances past _loaded_at."""
        # Start with a file that has no custom ASK_QUESTION
        initial = {"rpc_ids": {}, "updated_at": None}
        registry_path.write_text(json.dumps(initial), encoding="utf-8")
        reg = NLMRPCRegistry()

        # Update the file with a custom value
        updated = {"rpc_ids": {"ASK_QUESTION": "RELOADED"}, "updated_at": datetime.now().isoformat()}
        registry_path.write_text(json.dumps(updated), encoding="utf-8")

        # Force _loaded_at to the past so the new mtime is detected as newer
        reg._loaded_at = 0.0

        # Calling get_rpc_id triggers _reload_if_stale internally
        result = reg.get_rpc_id("ASK_QUESTION")
        assert result == "RELOADED"

    def test_reload_skipped_when_no_file(self, registry_path):
        """_reload_if_stale is a no-op when the file does not exist."""
        reg = NLMRPCRegistry()
        original_loaded_at = reg._loaded_at
        reg._loaded_if_stale = lambda: None  # not called at all
        # Invoking through get_rpc_id should not crash
        result = reg.get_rpc_id("ASK_QUESTION")
        assert result == "s0tc2d"


# ──────────────────────────────────────────────────────────────────────────────
# TestGetRpcIdConvenience — module-level convenience wrapper
# ──────────────────────────────────────────────────────────────────────────────

class TestGetRpcIdConvenience:
    """Tests for the get_rpc_id() module-level function."""

    def test_returns_known_rpc(self, registry_path):
        """get_rpc_id('ASK_QUESTION') returns the known hardcoded value."""
        result = get_rpc_id("ASK_QUESTION")
        assert result == "s0tc2d"

    def test_returns_none_for_missing(self, registry_path):
        """get_rpc_id('NONEXISTENT') returns None."""
        result = get_rpc_id("NONEXISTENT")
        assert result is None

    def test_returns_fallback_for_unregistered_known_op(self, registry_path):
        """get_rpc_id uses fallback for ops not in the file."""
        result = get_rpc_id("LOAD_NOTEBOOK")
        assert result == "rLM1Ne"


# ──────────────────────────────────────────────────────────────────────────────
# TestInvalidate — singleton lifecycle
# ──────────────────────────────────────────────────────────────────────────────

class TestInvalidate:
    """Tests for the invalidate() function."""

    def test_invalidate_clears_singleton(self, registry_path):
        """invalidate() sets _registry back to None."""
        _ = get_registry()
        assert mapper_module._registry is not None
        invalidate()
        assert mapper_module._registry is None

    def test_invalidate_forces_new_registry(self, registry_path):
        """After invalidate(), the next get_registry() call returns a fresh object."""
        reg1 = get_registry()
        invalidate()
        reg2 = get_registry()
        assert reg2 is not reg1
        assert mapper_module._registry is reg2

    def test_get_registry_returns_same_singleton(self, registry_path):
        """Repeated get_registry() calls return the same object (singleton)."""
        reg1 = get_registry()
        reg2 = get_registry()
        assert reg1 is reg2

    def test_invalidate_idempotent(self, registry_path):
        """Calling invalidate() twice in a row does not raise."""
        invalidate()
        invalidate()  # second call must not raise
        assert mapper_module._registry is None


# ──────────────────────────────────────────────────────────────────────────────
# TestModuleCLI — __main__ entry point
# ──────────────────────────────────────────────────────────────────────────────

class TestModuleCLI:
    """Tests for the module's __main__ entry point."""

    def test_module_runs_without_error(self, tmp_path):
        """python -m engine.nexus.nlm_rpc_mapper exits 0 and prints report text."""
        import os
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [sys.executable, "-m", "engine.nexus.nlm_rpc_mapper"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            cwd=str(Path(__file__).parent.parent),  # project root
        )
        assert result.returncode == 0, (
            f"Module exited with {result.returncode}.\nSTDERR: {result.stderr}"
        )
        # Should contain the report header
        assert "NLM RPC Registry" in result.stdout

    def test_module_output_contains_operations(self, tmp_path):
        """CLI output lists at least one known operation name."""
        import os
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [sys.executable, "-m", "engine.nexus.nlm_rpc_mapper"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            cwd=str(Path(__file__).parent.parent),
        )
        combined = result.stdout + result.stderr
        assert "ASK_QUESTION" in combined or "LOAD_NOTEBOOK" in combined
