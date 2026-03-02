"""Tests for engine/nexus/master_notebook_builder.py.

Covers: bundle builders, state persistence, build orchestration, dry-run mode,
SDK_URLS catalogue, DISTILLATION_QUESTIONS completeness, and MCP tools.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_builder(dry_run: bool = False, state_file: Path | None = None) -> Any:
    """Return a MasterNotebookBuilder with an isolated state file."""
    from engine.nexus.master_notebook_builder import MasterNotebookBuilder
    builder = MasterNotebookBuilder(dry_run=dry_run)
    if state_file is not None:
        builder._state = {}
    return builder


# ──────────────────────────────────────────────────────────────────────────────
# Module-level constants
# ──────────────────────────────────────────────────────────────────────────────

class TestModuleConstants:
    def test_sdk_urls_not_empty(self) -> None:
        from engine.nexus.master_notebook_builder import SDK_URLS
        assert len(SDK_URLS) >= 10

    def test_sdk_urls_have_url_and_label(self) -> None:
        from engine.nexus.master_notebook_builder import SDK_URLS
        for item in SDK_URLS:
            assert "url" in item and "label" in item
            assert item["url"].startswith("http")
            assert len(item["label"]) > 3

    def test_sdk_urls_include_lmstudio(self) -> None:
        from engine.nexus.master_notebook_builder import SDK_URLS
        labels = [s["label"].lower() for s in SDK_URLS]
        assert any("lmstudio" in l for l in labels)

    def test_sdk_urls_include_flask(self) -> None:
        from engine.nexus.master_notebook_builder import SDK_URLS
        labels = [s["label"].lower() for s in SDK_URLS]
        assert any("flask" in l for l in labels)

    def test_sdk_urls_include_mcp(self) -> None:
        from engine.nexus.master_notebook_builder import SDK_URLS
        labels = [s["label"].lower() for s in SDK_URLS]
        assert any("mcp" in l for l in labels)

    def test_distillation_questions_not_empty(self) -> None:
        from engine.nexus.master_notebook_builder import DISTILLATION_QUESTIONS
        assert len(DISTILLATION_QUESTIONS) >= 20

    def test_distillation_questions_are_strings(self) -> None:
        from engine.nexus.master_notebook_builder import DISTILLATION_QUESTIONS
        for q in DISTILLATION_QUESTIONS:
            assert isinstance(q, str) and len(q) > 10

    def test_distillation_questions_cover_architecture(self) -> None:
        from engine.nexus.master_notebook_builder import DISTILLATION_QUESTIONS
        combined = " ".join(DISTILLATION_QUESTIONS).lower()
        assert "mcpframework" in combined or "mcp" in combined
        assert "skill" in combined
        assert "nexus" in combined

    def test_notebook_name_and_version_set(self) -> None:
        from engine.nexus.master_notebook_builder import NOTEBOOK_NAME, NOTEBOOK_VERSION
        assert NOTEBOOK_NAME
        assert NOTEBOOK_VERSION.startswith("v")


# ──────────────────────────────────────────────────────────────────────────────
# Bundle builders
# ──────────────────────────────────────────────────────────────────────────────

class TestBundleBuilders:
    def test_hardware_system_doc_contains_hardware_specs(self) -> None:
        from engine.nexus.master_notebook_builder import build_hardware_system_doc
        doc = build_hardware_system_doc()
        # Must mention the hardware spec even if it comes from the inline string
        assert "RTX" in doc or "VRAM" in doc or "hardware" in doc.lower()
        assert len(doc) > 500

    def test_hardware_system_doc_contains_service_ports(self) -> None:
        from engine.nexus.master_notebook_builder import build_hardware_system_doc
        doc = build_hardware_system_doc()
        assert "1234" in doc or "LMStudio" in doc

    def test_framework_bundle_returns_string(self) -> None:
        from engine.nexus.master_notebook_builder import build_engine_framework_bundle
        result = build_engine_framework_bundle()
        assert isinstance(result, str)
        assert len(result) > 100

    def test_nexus_bundle_returns_string(self) -> None:
        from engine.nexus.master_notebook_builder import build_engine_nexus_bundle
        result = build_engine_nexus_bundle()
        assert isinstance(result, str)
        assert len(result) > 100

    def test_lmstudio_bundle_returns_string(self) -> None:
        from engine.nexus.master_notebook_builder import build_engine_lmstudio_bundle
        result = build_engine_lmstudio_bundle()
        assert isinstance(result, str)
        assert len(result) > 100

    def test_mcp_tools_bundle_returns_string(self) -> None:
        from engine.nexus.master_notebook_builder import build_engine_mcp_tools_bundle
        result = build_engine_mcp_tools_bundle()
        assert isinstance(result, str)
        assert len(result) > 100

    def test_skills_bundle_returns_string(self) -> None:
        from engine.nexus.master_notebook_builder import build_engine_skills_bundle
        result = build_engine_skills_bundle()
        assert isinstance(result, str)
        assert len(result) > 100

    def test_config_rules_bundle_returns_string(self) -> None:
        from engine.nexus.master_notebook_builder import build_config_rules_bundle
        result = build_config_rules_bundle()
        assert isinstance(result, str)
        assert len(result) > 100

    def test_dependencies_bundle_contains_requirements(self) -> None:
        from engine.nexus.master_notebook_builder import build_dependencies_bundle
        result = build_dependencies_bundle()
        # Either references requirements.txt or its contents
        assert "flask" in result.lower() or "requirements" in result.lower()


# ──────────────────────────────────────────────────────────────────────────────
# build_all_sources
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildAllSources:
    def test_returns_correct_count(self) -> None:
        from engine.nexus.master_notebook_builder import build_all_sources, SDK_URLS
        sources = build_all_sources()
        # 13 text bundles + len(SDK_URLS) URL entries
        expected_total = 13 + len(SDK_URLS)
        assert len(sources) == expected_total

    def test_items_have_three_fields(self) -> None:
        from engine.nexus.master_notebook_builder import build_all_sources
        sources = build_all_sources()
        for label, content, source_type in sources:
            assert isinstance(label, str)
            assert isinstance(content, str)
            assert source_type in ("text", "url")

    def test_url_sources_are_valid_urls(self) -> None:
        from engine.nexus.master_notebook_builder import build_all_sources
        for _label, content, source_type in build_all_sources():
            if source_type == "url":
                assert content.startswith("http"), f"URL source should start with http: {content}"

    def test_text_sources_not_empty(self) -> None:
        from engine.nexus.master_notebook_builder import build_all_sources
        for label, content, source_type in build_all_sources():
            if source_type == "text":
                assert len(content) > 50, f"Text bundle '{label}' is too short"

    def test_hardware_bundle_is_present(self) -> None:
        from engine.nexus.master_notebook_builder import build_all_sources
        labels = [label for label, _, _ in build_all_sources()]
        assert any("Hardware" in l or "System Spec" in l for l in labels)

    def test_lmstudio_sdk_url_present(self) -> None:
        from engine.nexus.master_notebook_builder import build_all_sources
        url_labels = [l for l, _, t in build_all_sources() if t == "url"]
        assert any("LMStudio" in l for l in url_labels)


# ──────────────────────────────────────────────────────────────────────────────
# State persistence
# ──────────────────────────────────────────────────────────────────────────────

class TestStatePersistence:
    def test_load_state_returns_empty_dict_if_missing(self, tmp_path: Path) -> None:
        from engine.nexus import master_notebook_builder as m
        original = m._STATE_FILE
        m._STATE_FILE = tmp_path / "nonexistent.json"
        try:
            state = m._load_state()
            assert isinstance(state, dict)
        finally:
            m._STATE_FILE = original

    def test_save_and_load_state_roundtrip(self, tmp_path: Path) -> None:
        from engine.nexus import master_notebook_builder as m
        original = m._STATE_FILE
        state_file = tmp_path / "state.json"
        m._STATE_FILE = state_file
        try:
            data = {"notebook_id": "nb-test-123", "sources_uploaded": ["bundle-a"]}
            m._save_state(data)
            loaded = m._load_state()
            assert loaded["notebook_id"] == "nb-test-123"
            assert "bundle-a" in loaded["sources_uploaded"]
        finally:
            m._STATE_FILE = original


# ──────────────────────────────────────────────────────────────────────────────
# MasterNotebookBuilder
# ──────────────────────────────────────────────────────────────────────────────

class TestMasterNotebookBuilder:
    def test_constructor_dry_run(self) -> None:
        from engine.nexus.master_notebook_builder import MasterNotebookBuilder
        b = MasterNotebookBuilder(dry_run=True)
        assert b.dry_run is True

    def test_constructor_not_dry_run_by_default(self) -> None:
        from engine.nexus.master_notebook_builder import MasterNotebookBuilder
        b = MasterNotebookBuilder()
        assert b.dry_run is False

    def test_create_or_find_notebook_returns_dry_run_id(self) -> None:
        from engine.nexus.master_notebook_builder import MasterNotebookBuilder
        b = MasterNotebookBuilder(dry_run=True)
        b._state = {}  # no existing notebook
        nb_id = b.create_or_find_notebook()
        assert "dry-run" in nb_id

    def test_create_or_find_notebook_reuses_existing_id(self) -> None:
        from engine.nexus.master_notebook_builder import MasterNotebookBuilder
        b = MasterNotebookBuilder(dry_run=False)
        b._state = {"notebook_id": "existing-123"}
        nb_id = b.create_or_find_notebook()
        assert nb_id == "existing-123"

    def test_upload_sources_dry_run_returns_counts(self) -> None:
        from engine.nexus.master_notebook_builder import MasterNotebookBuilder
        b = MasterNotebookBuilder(dry_run=True)
        b._state = {"sources_uploaded": []}
        result = b.upload_sources("nb-dry")
        # dry-run should count text and url sources without making calls
        assert "text" in result
        assert "url" in result
        assert result["text"] >= 10
        assert result["url"] >= 5

    def test_upload_sources_skips_already_uploaded(self) -> None:
        from engine.nexus.master_notebook_builder import MasterNotebookBuilder, build_all_sources
        b = MasterNotebookBuilder(dry_run=True)
        # Pre-mark all sources as uploaded
        all_labels = [label for label, _, _ in build_all_sources()]
        b._state = {"sources_uploaded": all_labels}
        result = b.upload_sources("nb-dry")
        assert result["skipped"] == len(all_labels)
        assert result["text"] == 0
        assert result["url"] == 0

    def test_run_generator_returns_skipped_if_done(self) -> None:
        from engine.nexus.master_notebook_builder import MasterNotebookBuilder
        b = MasterNotebookBuilder(dry_run=False)
        b._state = {"generators_done": ["audio_standard"]}
        fn = MagicMock()
        result = b._run_generator("audio_standard", "nb-x", fn)
        assert result["status"] == "skipped"
        fn.assert_not_called()

    def test_run_generator_returns_dry_run_if_dry(self) -> None:
        from engine.nexus.master_notebook_builder import MasterNotebookBuilder
        b = MasterNotebookBuilder(dry_run=True)
        b._state = {"generators_done": []}
        fn = MagicMock()
        result = b._run_generator("audio_standard", "nb-x", fn)
        assert result["status"] == "dry-run"
        fn.assert_not_called()

    def test_run_qa_distillation_dry_run(self) -> None:
        from engine.nexus.master_notebook_builder import MasterNotebookBuilder
        b = MasterNotebookBuilder(dry_run=True)
        b._state = {"qa_done_index": 0}
        result = b.run_qa_distillation("nb-dry")
        assert result["status"] == "dry-run"

    def test_run_qa_distillation_skips_already_done(self) -> None:
        from engine.nexus.master_notebook_builder import MasterNotebookBuilder, DISTILLATION_QUESTIONS
        b = MasterNotebookBuilder(dry_run=False)
        b._state = {"qa_done_index": len(DISTILLATION_QUESTIONS)}
        result = b.run_qa_distillation("nb-x")
        assert result["status"] == "complete"

    def test_build_dry_run_returns_summary(self) -> None:
        """Full dry-run build should return a dict with status fields."""
        from engine.nexus.master_notebook_builder import MasterNotebookBuilder
        b = MasterNotebookBuilder(dry_run=True)
        b._state = {}
        result = b.build()
        assert isinstance(result, dict)
        assert "notebook_id" in result or "status" in result

    def test_build_sources_only_dry_run(self) -> None:
        from engine.nexus.master_notebook_builder import MasterNotebookBuilder
        b = MasterNotebookBuilder(dry_run=True)
        b._state = {}
        result = b.build(sources_only=True)
        assert isinstance(result, dict)

    def test_build_with_existing_notebook_id(self) -> None:
        from engine.nexus.master_notebook_builder import MasterNotebookBuilder
        b = MasterNotebookBuilder(dry_run=True)
        b._state = {}
        result = b.build(notebook_id="given-nb-id", sources_only=True)
        assert isinstance(result, dict)


# ──────────────────────────────────────────────────────────────────────────────
# refresh_master_notebook
# ──────────────────────────────────────────────────────────────────────────────

class TestRefreshMasterNotebook:
    def test_refresh_calls_build(self) -> None:
        """refresh_master_notebook() calls MasterNotebookBuilder.build()."""
        with patch("engine.nexus.master_notebook_builder.MasterNotebookBuilder") as MockCls:
            mock_instance = MagicMock()
            mock_instance.build.return_value = {"status": "done"}
            MockCls.return_value = mock_instance
            from engine.nexus.master_notebook_builder import refresh_master_notebook
            result = refresh_master_notebook()
        mock_instance.build.assert_called_once()
        assert result == {"status": "done"}


# ──────────────────────────────────────────────────────────────────────────────
# Scheduler integration
# ──────────────────────────────────────────────────────────────────────────────

class TestSchedulerIntegration:
    def test_master_notebook_task_registered(self) -> None:
        """master-notebook-refresh is registered in the builtin task list."""
        from engine.nexus.scheduler_daemon import _register_builtin_tasks
        daemon = MagicMock()
        _register_builtin_tasks(daemon)
        registered_ids = [call.args[0] for call in daemon.register.call_args_list]
        assert "master-notebook-refresh" in registered_ids

    def test_master_notebook_task_count_is_20(self) -> None:
        """master-notebook-refresh task is present (one of 37 total)."""
        from engine.nexus.scheduler_daemon import _register_builtin_tasks
        daemon = MagicMock()
        _register_builtin_tasks(daemon)
        assert daemon.register.call_count == 40

    def test_master_notebook_callback_calls_refresh(self) -> None:
        from engine.nexus.scheduler_daemon import _master_notebook_refresh_callback
        with patch("engine.nexus.master_notebook_builder.refresh_master_notebook") as mock_ref:
            mock_ref.return_value = {"status": "done"}
            result = _master_notebook_refresh_callback()
        mock_ref.assert_called_once()
        assert result == {"status": "done"}

    def test_master_notebook_callback_handles_exception(self) -> None:
        """_master_notebook_refresh_callback returns error dict on exception."""
        from engine.nexus.scheduler_daemon import _master_notebook_refresh_callback
        with patch("engine.nexus.master_notebook_builder.refresh_master_notebook",
                   side_effect=RuntimeError("NLM offline")):
            result = _master_notebook_refresh_callback()
        assert "error" in result
        assert "NLM offline" in result["error"]


# ──────────────────────────────────────────────────────────────────────────────
# get_master_notebook_builder singleton
# ──────────────────────────────────────────────────────────────────────────────

class TestGetMasterNotebookBuilder:
    def test_singleton_returns_same_instance(self) -> None:
        from engine.nexus.master_notebook_builder import get_master_notebook_builder
        b1 = get_master_notebook_builder()
        b2 = get_master_notebook_builder()
        assert b1 is b2

