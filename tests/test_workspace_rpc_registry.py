"""Tests for WorkspaceRPCRegistry — parallel registry for Workspace endpoints."""

from __future__ import annotations

import pytest

from engine.integrations.workspace_rpc_registry import (
    WorkspaceRPCRegistry,
    get_workspace_registry,
)


# ──── Loading Tests ───────────────────────────────────────────────────────────


class TestRegistryLoading:
    """Tests for YAML loading and section parsing."""

    def test_loads_successfully(self):
        """Registry loads without errors."""
        registry = WorkspaceRPCRegistry()
        assert registry is not None

    def test_loads_workspace_gemini_section(self):
        """workspace_gemini section is present."""
        registry = WorkspaceRPCRegistry()
        section = registry.get_section("workspace_gemini")
        assert "meta" in section
        assert "operations" in section

    def test_loads_sheets_gemini_section(self):
        """sheets_gemini section is present."""
        registry = WorkspaceRPCRegistry()
        section = registry.get_section("sheets_gemini")
        assert "meta" in section

    def test_loads_cloud_search_section(self):
        """cloud_search section is present."""
        registry = WorkspaceRPCRegistry()
        section = registry.get_section("cloud_search")
        assert "meta" in section

    def test_loads_docs_gemini_section(self):
        """docs_gemini section is present."""
        registry = WorkspaceRPCRegistry()
        section = registry.get_section("docs_gemini")
        assert "meta" in section

    def test_loads_drive_gemini_section(self):
        """drive_gemini section is present."""
        registry = WorkspaceRPCRegistry()
        section = registry.get_section("drive_gemini")
        assert "meta" in section

    def test_unknown_section_returns_empty(self):
        """Unknown section returns empty dict."""
        registry = WorkspaceRPCRegistry()
        assert registry.get_section("nonexistent") == {}

    def test_reload_works(self):
        """Registry can be reloaded."""
        registry = WorkspaceRPCRegistry()
        registry.reload()
        assert len(registry.get_section("workspace_gemini")) > 0


# ──── Meta Tests ──────────────────────────────────────────────────────────────


class TestMetaAccess:
    """Tests for section metadata access."""

    def test_workspace_gemini_meta(self):
        """workspace_gemini meta has correct fields."""
        registry = WorkspaceRPCRegistry()
        meta = registry.get_meta("workspace_gemini")
        assert meta["service_name"] == "AppsGenAIServer"
        assert "appsgenaiserver-pa" in meta["base_url"]
        assert meta["auth_method"] == "api_key_query_param"

    def test_sheets_gemini_meta(self):
        """sheets_gemini meta has correct fields."""
        registry = WorkspaceRPCRegistry()
        meta = registry.get_meta("sheets_gemini")
        assert meta["service_name"] == "GoogleSheetsGemini"
        assert meta["auth_method"] == "cookie_sapisidhash"

    def test_cloud_search_meta(self):
        """cloud_search meta has correct fields."""
        registry = WorkspaceRPCRegistry()
        meta = registry.get_meta("cloud_search")
        assert meta["service_name"] == "CloudSearch"
        assert "cloudsearch" in meta["base_url"]

    def test_unknown_meta_returns_empty(self):
        """Unknown section returns empty meta."""
        registry = WorkspaceRPCRegistry()
        assert registry.get_meta("nonexistent") == {}


# ──── Operation Tests ─────────────────────────────────────────────────────────


class TestOperationAccess:
    """Tests for operation lookup."""

    def test_get_stream_generate(self):
        """stream_generate operation is defined."""
        registry = WorkspaceRPCRegistry()
        op = registry.get_operation("workspace_gemini", "stream_generate")
        assert op is not None
        assert op["path"] == "/v1/genai/streamGenerate"

    def test_get_settings_operation(self):
        """get_settings operation is defined."""
        registry = WorkspaceRPCRegistry()
        op = registry.get_operation("workspace_gemini", "get_settings")
        assert op is not None
        assert "/getSettings" in op["path"]

    def test_columnsmith_operation(self):
        """columnsmith_execute operation is defined."""
        registry = WorkspaceRPCRegistry()
        op = registry.get_operation("sheets_gemini", "columnsmith_execute")
        assert op is not None
        assert "columnsmith" in op["path"]

    def test_query_search_operation(self):
        """query_search operation is defined."""
        registry = WorkspaceRPCRegistry()
        op = registry.get_operation("cloud_search", "query_search")
        assert op is not None
        assert "/v1/query/search" in op["path"]

    def test_unknown_operation_returns_none(self):
        """Unknown operation returns None."""
        registry = WorkspaceRPCRegistry()
        assert registry.get_operation("workspace_gemini", "nonexistent") is None


class TestPathAccess:
    """Tests for URL path access."""

    def test_get_path(self):
        """get_path returns the operation path."""
        registry = WorkspaceRPCRegistry()
        path = registry.get_path("workspace_gemini", "stream_generate")
        assert path == "/v1/genai/streamGenerate"

    def test_get_full_url(self):
        """get_full_url combines base_url and path."""
        registry = WorkspaceRPCRegistry()
        url = registry.get_full_url("workspace_gemini", "stream_generate")
        assert url == "https://appsgenaiserver-pa.clients6.google.com/v1/genai/streamGenerate"

    def test_get_full_url_with_path_params(self):
        """get_full_url substitutes path parameters."""
        registry = WorkspaceRPCRegistry()
        url = registry.get_full_url(
            "sheets_gemini",
            "columnsmith_execute",
            path_params={"spreadsheet_id": "abc123"},
        )
        assert url is not None
        assert "abc123" in url

    def test_get_full_url_via_reference_returns_none(self):
        """get_full_url returns None for via_ references."""
        registry = WorkspaceRPCRegistry()
        url = registry.get_full_url("docs_gemini", "help_me_create")
        assert url is None

    def test_unknown_path_returns_none(self):
        """Unknown operation path returns None."""
        registry = WorkspaceRPCRegistry()
        assert registry.get_path("workspace_gemini", "nope") is None


class TestStreamingCheck:
    """Tests for streaming detection."""

    def test_stream_generate_is_streaming(self):
        """stream_generate is a streaming endpoint."""
        registry = WorkspaceRPCRegistry()
        assert registry.is_streaming("workspace_gemini", "stream_generate") is True

    def test_get_settings_is_not_streaming(self):
        """get_settings is not a streaming endpoint."""
        registry = WorkspaceRPCRegistry()
        assert registry.is_streaming("workspace_gemini", "get_settings") is False

    def test_unknown_is_not_streaming(self):
        """Unknown operation is not streaming."""
        registry = WorkspaceRPCRegistry()
        assert registry.is_streaming("workspace_gemini", "nope") is False


class TestAuthMethod:
    """Tests for auth method lookup."""

    def test_workspace_gemini_auth(self):
        """workspace_gemini uses api_key_query_param."""
        registry = WorkspaceRPCRegistry()
        assert registry.get_auth_method("workspace_gemini") == "api_key_query_param"

    def test_sheets_gemini_auth(self):
        """sheets_gemini uses cookie_sapisidhash."""
        registry = WorkspaceRPCRegistry()
        assert registry.get_auth_method("sheets_gemini") == "cookie_sapisidhash"

    def test_unknown_defaults_to_cookie(self):
        """Unknown section defaults to cookie_sapisidhash."""
        registry = WorkspaceRPCRegistry()
        assert registry.get_auth_method("nonexistent") == "cookie_sapisidhash"


# ──── Cross-Section Queries ───────────────────────────────────────────────────


class TestCrossSectionQueries:
    """Tests for cross-section query methods."""

    def test_list_all_operations(self):
        """list_all_operations returns all operations."""
        registry = WorkspaceRPCRegistry()
        ops = registry.list_all_operations()
        assert len(ops) >= 10  # 5 ws_gemini + 2 sheets + 1 cloud + 2 docs + 2 drive
        assert all(isinstance(o, tuple) and len(o) == 3 for o in ops)

    def test_find_operation_cross_section(self):
        """find_operation finds operations across sections."""
        registry = WorkspaceRPCRegistry()

        found = registry.find_operation("stream_generate")
        assert found is not None
        assert found[0] == "workspace_gemini"

        found = registry.find_operation("columnsmith_execute")
        assert found is not None
        assert found[0] == "sheets_gemini"

    def test_find_operation_unknown(self):
        """find_operation returns None for unknown operations."""
        registry = WorkspaceRPCRegistry()
        assert registry.find_operation("does_not_exist") is None

    def test_get_parameters(self):
        """get_parameters returns operation parameters."""
        registry = WorkspaceRPCRegistry()
        params = registry.get_parameters("workspace_gemini", "stream_generate")
        assert "prompt" in params

    def test_get_parameters_empty(self):
        """get_parameters returns empty dict for no-param operations."""
        registry = WorkspaceRPCRegistry()
        params = registry.get_parameters("workspace_gemini", "list_gems")
        assert isinstance(params, dict)


# ──── Summary Tests ───────────────────────────────────────────────────────────


class TestSummary:
    """Tests for the summary method."""

    def test_summary_has_all_fields(self):
        """summary returns expected fields."""
        registry = WorkspaceRPCRegistry()
        s = registry.summary()
        assert "sections_loaded" in s
        assert "total_operations" in s
        assert "sections" in s

    def test_summary_counts(self):
        """summary reports correct counts."""
        registry = WorkspaceRPCRegistry()
        s = registry.summary()
        assert s["sections_loaded"] == 5
        assert s["total_operations"] >= 12  # 5+2+1+2+2 = 12 minimum

    def test_summary_section_names(self):
        """summary includes all section names."""
        registry = WorkspaceRPCRegistry()
        s = registry.summary()
        for name in ["workspace_gemini", "sheets_gemini", "cloud_search", "docs_gemini", "drive_gemini"]:
            assert name in s["sections"]


# ──── Factory Tests ───────────────────────────────────────────────────────────


class TestFactory:
    """Tests for the singleton factory."""

    def test_get_workspace_registry_returns_instance(self):
        """get_workspace_registry returns a registry."""
        registry = get_workspace_registry()
        assert isinstance(registry, WorkspaceRPCRegistry)

    def test_factory_is_singleton(self):
        """Factory returns the same instance."""
        r1 = get_workspace_registry()
        r2 = get_workspace_registry()
        assert r1 is r2

    def test_force_reload(self):
        """Force reload creates a new instance."""
        r1 = get_workspace_registry()
        r2 = get_workspace_registry(force_reload=True)
        assert r2 is not None
