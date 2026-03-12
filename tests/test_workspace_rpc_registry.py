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
        assert meta["auth_method"] == "api_key_query_param_plus_sapisidhash"

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
        """workspace_gemini uses api_key + SAPISIDHASH auth."""
        registry = WorkspaceRPCRegistry()
        assert registry.get_auth_method("workspace_gemini") == "api_key_query_param_plus_sapisidhash"

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
        """get_parameters returns HAR-verified operation parameters."""
        registry = WorkspaceRPCRegistry()
        params = registry.get_parameters("workspace_gemini", "stream_generate")
        assert "op_code" in params
        assert "context_code" in params

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
        assert s["sections_loaded"] == 16
        assert s["total_operations"] >= 50  # 16 sections, 50 operations from HAR mining

    def test_summary_section_names(self):
        """summary includes all section names."""
        registry = WorkspaceRPCRegistry()
        s = registry.summary()
        expected = [
            "workspace_gemini", "sheets_gemini", "cloud_search",
            "docs_gemini", "drive_gemini", "workspace_support",
            "drive_v2internal", "sheets_extended", "people_stack",
            "experiments", "feedback", "workspace_analytics",
            "addons", "ogads", "consent", "growth_promos",
        ]
        for name in expected:
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


# ──── New Section Tests (v1.19 HAR Expansion) ─────────────────────────────────


class TestDriveV2InternalSection:
    """Tests for the drive_v2internal section."""

    def test_section_loaded(self):
        """drive_v2internal section is present."""
        registry = WorkspaceRPCRegistry()
        section = registry.get_section("drive_v2internal")
        assert "meta" in section
        assert "operations" in section

    def test_meta_fields(self):
        """drive_v2internal meta has correct values."""
        registry = WorkspaceRPCRegistry()
        meta = registry.get_meta("drive_v2internal")
        assert meta["service_name"] == "DriveV2Internal"
        assert "clients6.google.com" in meta["base_url"]
        assert meta["auth_method"] == "api_key_query_param_plus_sapisidhash"

    def test_has_9_operations(self):
        """drive_v2internal has 9 operations."""
        registry = WorkspaceRPCRegistry()
        ops = registry.get_operations("drive_v2internal")
        assert len(ops) == 9

    def test_upload_file_operation(self):
        """upload_file operation is defined with correct path."""
        registry = WorkspaceRPCRegistry()
        op = registry.get_operation("drive_v2internal", "upload_file")
        assert op is not None
        assert "/upload/drive/v2internal/files" in op["path"]

    def test_get_permissions_operation(self):
        """get_permissions operation is defined."""
        registry = WorkspaceRPCRegistry()
        op = registry.get_operation("drive_v2internal", "get_permissions")
        assert op is not None
        assert "permissions" in op["path"]

    def test_api_keys_in_meta(self):
        """drive_v2internal meta contains API key catalog."""
        registry = WorkspaceRPCRegistry()
        meta = registry.get_meta("drive_v2internal")
        assert "api_keys" in meta
        assert "files_upload" in meta["api_keys"]
        assert "permissions" in meta["api_keys"]


class TestSheetsExtendedSection:
    """Tests for the sheets_extended section."""

    def test_section_loaded(self):
        """sheets_extended section is present."""
        registry = WorkspaceRPCRegistry()
        section = registry.get_section("sheets_extended")
        assert "meta" in section

    def test_has_4_operations(self):
        """sheets_extended has 4 operations."""
        registry = WorkspaceRPCRegistry()
        ops = registry.get_operations("sheets_extended")
        assert len(ops) == 4

    def test_save_operation(self):
        """save operation is defined."""
        registry = WorkspaceRPCRegistry()
        op = registry.get_operation("sheets_extended", "save")
        assert op is not None
        assert "save" in op["path"]


class TestPeopleStackSection:
    """Tests for the people_stack section."""

    def test_section_loaded(self):
        """people_stack section is present."""
        registry = WorkspaceRPCRegistry()
        section = registry.get_section("people_stack")
        assert "meta" in section

    def test_meta_fields(self):
        """people_stack meta has correct values."""
        registry = WorkspaceRPCRegistry()
        meta = registry.get_meta("people_stack")
        assert meta["service_name"] == "PeopleStack"
        assert meta["protocol"] == "grpc_web_json"

    def test_has_3_operations(self):
        """people_stack has 3 operations."""
        registry = WorkspaceRPCRegistry()
        ops = registry.get_operations("people_stack")
        assert len(ops) == 3

    def test_autocomplete_operation(self):
        """autocomplete operation is defined with gRPC path."""
        registry = WorkspaceRPCRegistry()
        op = registry.get_operation("people_stack", "autocomplete")
        assert op is not None
        assert "Autocomplete" in op["path"]


class TestExperimentsSection:
    """Tests for the experiments section."""

    def test_section_loaded(self):
        """experiments section is present."""
        registry = WorkspaceRPCRegistry()
        section = registry.get_section("experiments")
        assert "meta" in section

    def test_get_experiment_flags(self):
        """get_experiment_flags operation is defined."""
        registry = WorkspaceRPCRegistry()
        op = registry.get_operation("experiments", "get_experiment_flags")
        assert op is not None
        assert "GetExperimentFlags" in op["path"]


class TestFeedbackSection:
    """Tests for the feedback section."""

    def test_section_loaded(self):
        """feedback section is present."""
        registry = WorkspaceRPCRegistry()
        section = registry.get_section("feedback")
        assert "meta" in section

    def test_has_3_operations(self):
        """feedback has 3 operations."""
        registry = WorkspaceRPCRegistry()
        ops = registry.get_operations("feedback")
        assert len(ops) == 3


class TestAnalyticsSection:
    """Tests for the workspace_analytics section."""

    def test_section_loaded(self):
        """workspace_analytics section is present."""
        registry = WorkspaceRPCRegistry()
        section = registry.get_section("workspace_analytics")
        assert "meta" in section

    def test_has_2_operations(self):
        """workspace_analytics has 2 operations."""
        registry = WorkspaceRPCRegistry()
        ops = registry.get_operations("workspace_analytics")
        assert len(ops) == 2


class TestAddonsSection:
    """Tests for the addons section."""

    def test_section_loaded(self):
        """addons section is present."""
        registry = WorkspaceRPCRegistry()
        section = registry.get_section("addons")
        assert "meta" in section

    def test_list_installations_operation(self):
        """list_installations operation is defined."""
        registry = WorkspaceRPCRegistry()
        op = registry.get_operation("addons", "list_installations")
        assert op is not None
        assert "ListInstallations" in op["path"]


class TestConsentSection:
    """Tests for the consent section."""

    def test_section_loaded(self):
        """consent section is present."""
        registry = WorkspaceRPCRegistry()
        section = registry.get_section("consent")
        assert "meta" in section

    def test_fetch_compiled_operation(self):
        """fetch_compiled operation is defined."""
        registry = WorkspaceRPCRegistry()
        op = registry.get_operation("consent", "fetch_compiled")
        assert op is not None


class TestGrowthPromosSection:
    """Tests for the growth_promos section."""

    def test_section_loaded(self):
        """growth_promos section is present."""
        registry = WorkspaceRPCRegistry()
        section = registry.get_section("growth_promos")
        assert "meta" in section

    def test_has_2_operations(self):
        """growth_promos has 2 operations."""
        registry = WorkspaceRPCRegistry()
        ops = registry.get_operations("growth_promos")
        assert len(ops) == 2
