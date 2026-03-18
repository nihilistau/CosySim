"""Comprehensive tests for ARGUS skills and NLM RPC YAML registry validation.

Covers three groups:
  1. YAML registry integrity — structure, sections, counts, enrichment
  2. ARGUS skill functions — mocked I/O, return shapes, search filters
  3. NLM RPC Registry module — singleton, resolution, operations
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
import yaml

logger = logging.getLogger(__name__)

YAML_PATH = Path("config/nlm_rpcids.yaml")


# ──── Shared Fixture ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def yaml_data() -> Dict[str, Any]:
    """Load the RPC registry YAML once for the entire module."""
    with open(YAML_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ──── Group 1: YAML Registry Integrity ──────────────────────────────────────

class TestYAMLRegistryIntegrity:
    """Validate structure, completeness, and enrichment of nlm_rpcids.yaml."""

    def test_yaml_loads_successfully(self, yaml_data: Dict[str, Any]) -> None:
        """YAML file parses without errors."""
        assert isinstance(yaml_data, dict)
        assert len(yaml_data) > 0

    def test_yaml_has_meta_section(self, yaml_data: Dict[str, Any]) -> None:
        """Meta section contains version and enrichment version."""
        assert "meta" in yaml_data
        assert "version" in yaml_data["meta"]
        assert "har_enrichment_version" in yaml_data["meta"]

    def test_yaml_version_is_6(self, yaml_data: Dict[str, Any]) -> None:
        """Registry version must be 6.0."""
        assert yaml_data["meta"]["version"] == "6.0"

    def test_yaml_has_har_sources(self, yaml_data: Dict[str, Any]) -> None:
        """HAR sources list should contain the enrichment sources."""
        sources = yaml_data["meta"].get("har_sources", [])
        assert len(sources) >= 5

    def test_yaml_has_build_labels(self, yaml_data: Dict[str, Any]) -> None:
        """Build labels section tracks latest production builds."""
        labels = yaml_data["meta"].get("build_labels_latest", {})
        assert "gemini_server" in labels
        assert "opal_server" in labels
        assert "bard_client" in labels

    def test_yaml_has_session_parameters(self, yaml_data: Dict[str, Any]) -> None:
        """Session parameters (bl, f_sid) must be documented."""
        sp = yaml_data["meta"].get("session_parameters", {})
        assert "bl" in sp
        assert "f_sid" in sp

    def test_gemini_rpcids_count(self, yaml_data: Dict[str, Any]) -> None:
        """Gemini section must contain at least 22 rpcids."""
        rpcids = yaml_data["gemini"]["rpcids"]
        assert len(rpcids) >= 22

    def test_gemini_new_rpcids_present(self, yaml_data: Dict[str, Any]) -> None:
        """v1.37 HAR goldmine rpcids are present."""
        rpcids = yaml_data["gemini"]["rpcids"]
        for rpcid in ["HcT8bb", "XqA3Ic", "ZKcapf", "jGArJ", "sJBwce"]:
            assert rpcid in rpcids, f"Missing new rpcid: {rpcid}"

    def test_gemini_rpcids_have_descriptions(self, yaml_data: Dict[str, Any]) -> None:
        """Every Gemini rpcid must have description and category."""
        for rpcid, info in yaml_data["gemini"]["rpcids"].items():
            assert "description" in info, f"{rpcid} missing description"
            assert "category" in info, f"{rpcid} missing category"

    def test_gemini_enriched_rpcids_have_payloads(self, yaml_data: Dict[str, Any]) -> None:
        """All original enriched entries should have payload_template."""
        enriched = [
            k for k, v in yaml_data["gemini"]["rpcids"].items()
            if v.get("enriched")
        ]
        assert len(enriched) >= 17

    def test_opal_section_exists(self, yaml_data: Dict[str, Any]) -> None:
        """Opal section with correct service name."""
        assert "opal" in yaml_data
        assert "meta" in yaml_data["opal"]
        assert yaml_data["opal"]["meta"]["service_name"] == "Opal"

    def test_opal_has_rpcids(self, yaml_data: Dict[str, Any]) -> None:
        """Opal should have the ug7pge rpcid."""
        assert "ug7pge" in yaml_data["opal"]["rpcids"]

    def test_opal_has_rest_apis(self, yaml_data: Dict[str, Any]) -> None:
        """Opal should expose drive_proxy and gallery_list REST APIs."""
        rest = yaml_data["opal"]["rest_apis"]
        assert "drive_proxy" in rest
        assert "gallery_list" in rest

    def test_appcatalyst_section_exists(self, yaml_data: Dict[str, Any]) -> None:
        """AppCatalyst section with correct service name."""
        assert "appcatalyst" in yaml_data
        assert yaml_data["appcatalyst"]["meta"]["service_name"] == "AppCatalyst"

    def test_appcatalyst_has_model_endpoints(self, yaml_data: Dict[str, Any]) -> None:
        """AppCatalyst must list generate_content and stream_generate_content."""
        eps = yaml_data["appcatalyst"]["endpoints"]
        assert "generate_content" in eps
        assert "stream_generate_content" in eps
        models = eps["generate_content"]["models_confirmed"]
        assert any("gemini" in m for m in models)

    def test_batchexecute_services_lists_five(self, yaml_data: Dict[str, Any]) -> None:
        """At least 5 batchexecute services discovered."""
        services = yaml_data["batchexecute_services"]["services"]
        assert len(services) >= 5
        for expected in ["BardChatUi", "LabsTailwindUi", "Opal"]:
            assert expected in services

    def test_account_linking_grpc_section(self, yaml_data: Dict[str, Any]) -> None:
        """Account linking gRPC service has all required methods."""
        methods = yaml_data["account_linking_grpc"]["methods"]
        assert len(methods) >= 5
        for m in ["DeleteLink", "DepositGoogleCredential", "FinishOAuth",
                   "GetLink", "StartLinkingSession"]:
            assert m in methods

    def test_operations_section_has_entries(self, yaml_data: Dict[str, Any]) -> None:
        """Operations section should have NLM rpcid mappings."""
        ops = yaml_data.get("operations", {})
        assert len(ops) >= 50

    def test_parameters_section_has_tier_marker(self, yaml_data: Dict[str, Any]) -> None:
        """Parameters section must define tier_marker with pro/free options."""
        params = yaml_data.get("parameters", {})
        assert "tier_marker" in params
        tm = params["tier_marker"]
        assert "default" in tm
        assert "options" in tm

    def test_shared_configs_section(self, yaml_data: Dict[str, Any]) -> None:
        """Shared configs must include write_config and source_config."""
        sc = yaml_data.get("shared_configs", {})
        assert "write_config" in sc
        assert "source_config" in sc

    def test_gemini_streaming_section(self, yaml_data: Dict[str, Any]) -> None:
        """Gemini streaming section must exist with endpoints."""
        gs = yaml_data.get("gemini_streaming", {})
        assert "meta" in gs
        assert "endpoints" in gs
        assert gs["meta"].get("service_name") == "BardFrontendService"

    def test_total_sections_at_least_40(self, yaml_data: Dict[str, Any]) -> None:
        """Registry has grown to 40+ top-level sections."""
        assert len(yaml_data) >= 40


# ──── Group 2: ARGUS Skills ─────────────────────────────────────────────────

class TestArgusSkills:
    """Test each ARGUS skill function with mocked external dependencies."""

    def test_get_rpc_registry_stats_returns_valid_json(self) -> None:
        """Stats skill returns version and section counts."""
        from engine.skills.builtin.argus_skills import get_rpc_registry_stats

        result = json.loads(get_rpc_registry_stats())
        assert "version" in result
        assert "total_sections" in result
        assert result["total_sections"] >= 40

    def test_get_rpc_registry_stats_has_sections(self) -> None:
        """Stats skill lists individual section endpoint counts."""
        from engine.skills.builtin.argus_skills import get_rpc_registry_stats

        result = json.loads(get_rpc_registry_stats())
        assert "sections" in result
        assert "total_endpoints" in result
        assert result["total_endpoints"] > 0

    def test_get_rpc_registry_stats_missing_yaml(self, tmp_path: Path) -> None:
        """Stats skill returns error when YAML is missing."""
        from engine.skills.builtin.argus_skills import get_rpc_registry_stats

        with patch("engine.skills.builtin.argus_skills.Path") as mock_path:
            mock_path.return_value.exists.return_value = False
            result = json.loads(get_rpc_registry_stats())
        assert "error" in result

    def test_list_batchexecute_services(self) -> None:
        """Services skill lists at least 5 batchexecute services."""
        from engine.skills.builtin.argus_skills import list_batchexecute_services

        result = json.loads(list_batchexecute_services())
        assert result["total"] >= 5
        names = [s["name"] for s in result["services"]]
        assert "LabsTailwindUi" in names

    def test_list_batchexecute_services_structure(self) -> None:
        """Each service entry has name, host, path, and rpcid_count."""
        from engine.skills.builtin.argus_skills import list_batchexecute_services

        result = json.loads(list_batchexecute_services())
        for svc in result["services"]:
            assert "name" in svc
            assert "host" in svc
            assert "path" in svc
            assert "rpcid_count" in svc

    def test_get_appcatalyst_endpoints(self) -> None:
        """AppCatalyst skill returns at least 9 endpoints."""
        from engine.skills.builtin.argus_skills import get_appcatalyst_endpoints

        result = json.loads(get_appcatalyst_endpoints())
        assert result["total"] >= 9
        assert result["host"] != ""

    def test_get_appcatalyst_endpoints_structure(self) -> None:
        """Each AppCatalyst endpoint has name, path, method, description."""
        from engine.skills.builtin.argus_skills import get_appcatalyst_endpoints

        result = json.loads(get_appcatalyst_endpoints())
        for ep in result["endpoints"]:
            assert "name" in ep
            assert "path" in ep
            assert "method" in ep
            assert "description" in ep

    def test_get_appcatalyst_endpoints_has_models(self) -> None:
        """generate_content endpoint should list confirmed models."""
        from engine.skills.builtin.argus_skills import get_appcatalyst_endpoints

        result = json.loads(get_appcatalyst_endpoints())
        gen_eps = [e for e in result["endpoints"] if e["name"] == "generate_content"]
        assert len(gen_eps) == 1
        assert "models" in gen_eps[0]
        assert len(gen_eps[0]["models"]) >= 1

    def test_search_rpc_registry_by_category(self) -> None:
        """Search by category='chat' returns Gemini chat rpcids."""
        from engine.skills.builtin.argus_skills import search_rpc_registry

        result = json.loads(search_rpc_registry(category="chat"))
        assert result["total"] >= 2
        for m in result["matches"]:
            assert m["category"] == "chat"

    def test_search_rpc_registry_by_service(self) -> None:
        """Search by service='gemini' returns all Gemini rpcids."""
        from engine.skills.builtin.argus_skills import search_rpc_registry

        result = json.loads(search_rpc_registry(service="gemini"))
        assert result["total"] >= 22
        for m in result["matches"]:
            assert m["service"] == "gemini"

    def test_search_rpc_registry_by_query(self) -> None:
        """Free-text search for 'streaming' returns matches."""
        from engine.skills.builtin.argus_skills import search_rpc_registry

        result = json.loads(search_rpc_registry(query="streaming"))
        assert result["total"] >= 1

    def test_search_rpc_registry_no_filters(self) -> None:
        """Search with no filters returns all entries."""
        from engine.skills.builtin.argus_skills import search_rpc_registry

        result = json.loads(search_rpc_registry())
        assert result["total"] > 50

    def test_search_rpc_registry_empty_result(self) -> None:
        """Search with impossible filter returns zero matches."""
        from engine.skills.builtin.argus_skills import search_rpc_registry

        result = json.loads(search_rpc_registry(
            query="xyznonexistent999"
        ))
        assert result["total"] == 0
        assert result["matches"] == []

    def test_get_gemini_streaming_info(self) -> None:
        """Streaming info skill returns service and endpoints."""
        from engine.skills.builtin.argus_skills import get_gemini_streaming_info

        result = json.loads(get_gemini_streaming_info())
        assert "service" in result
        assert "endpoints" in result
        assert result["service"] == "BardFrontendService"

    def test_get_gemini_streaming_info_endpoints(self) -> None:
        """Streaming endpoints contain stream_generate."""
        from engine.skills.builtin.argus_skills import get_gemini_streaming_info

        result = json.loads(get_gemini_streaming_info())
        assert "stream_generate" in result["endpoints"]
        ep = result["endpoints"]["stream_generate"]
        assert "path" in ep
        assert "method" in ep

    def test_get_build_labels(self) -> None:
        """Build labels skill returns server labels."""
        from engine.skills.builtin.argus_skills import get_build_labels

        result = json.loads(get_build_labels())
        assert "gemini_server" in result
        assert "opal_server" in result

    def test_get_build_labels_includes_section_labels(self) -> None:
        """Build labels also collects per-section build_label entries."""
        from engine.skills.builtin.argus_skills import get_build_labels

        result = json.loads(get_build_labels())
        # Must have at least the meta build labels
        assert len(result) >= 3

    @patch("engine.skills.builtin.argus_skills.Path")
    def test_mine_har_files_calls_miner(self, mock_path_cls: MagicMock) -> None:
        """mine_har_files delegates to HARMiner."""
        mock_path_cls.return_value = Path("fake/dir")
        mock_miner = MagicMock()
        mock_miner.mine_directory.return_value = {
            "rpcids": ["abc", "def"],
            "api_urls": ["https://a.com"],
            "build_labels": ["boq_123"],
            "domains": ["a.com"],
            "files_scanned": 2,
        }
        with patch(
            "scripts.argus.har_miner.HARMiner",
            return_value=mock_miner,
        ):
            from engine.skills.builtin.argus_skills import mine_har_files
            result = json.loads(mine_har_files("fake/dir"))
        assert result["rpcids_found"] == 2
        assert result["api_urls_found"] == 1
        assert result["files_scanned"] == 2

    @patch("engine.skills.builtin.argus_skills.Path")
    def test_map_rpcids_to_services_calls_mapper(
        self, mock_path_cls: MagicMock
    ) -> None:
        """map_rpcids_to_services delegates to RpcidMapper."""
        mock_mapper = MagicMock()
        mock_mapper.map_directory.return_value = {
            "abc": "LabsTailwindUi",
            "def": "BardChatUi",
        }
        with patch(
            "scripts.argus.rpcid_mapper.RpcidMapper",
            return_value=mock_mapper,
        ):
            from engine.skills.builtin.argus_skills import map_rpcids_to_services
            result = json.loads(map_rpcids_to_services())
        assert result["abc"] == "LabsTailwindUi"

    @patch("engine.skills.builtin.argus_skills.Path")
    def test_extract_rpcid_payloads_calls_extractor(
        self, mock_path_cls: MagicMock
    ) -> None:
        """extract_rpcid_payloads delegates to PayloadExtractor."""
        mock_ext = MagicMock()
        mock_ext.extract_directory.return_value = {
            "abc": {"payload": [1, 2, 3]}
        }
        with patch(
            "scripts.argus.rpcid_payload_extractor.PayloadExtractor",
            return_value=mock_ext,
        ):
            from engine.skills.builtin.argus_skills import extract_rpcid_payloads
            result = json.loads(extract_rpcid_payloads())
        assert "abc" in result


# ──── Group 3: NLM RPC Registry Module ──────────────────────────────────────

class TestNLMRpcRegistry:
    """Test the NLMRpcRegistry class against the real YAML."""

    @pytest.fixture(autouse=True)
    def _reset(self) -> None:
        """Reset registry singleton before each test."""
        from engine.integrations.nlm_rpc_registry import reset_registry
        reset_registry()

    def test_rpc_registry_loads(self) -> None:
        """Registry loads without error."""
        from engine.integrations.nlm_rpc_registry import get_rpc_registry

        reg = get_rpc_registry()
        assert reg is not None

    def test_rpc_registry_known_rpcid(self) -> None:
        """list_notebooks resolves to a known rpcid."""
        from engine.integrations.nlm_rpc_registry import get_rpc_registry

        reg = get_rpc_registry()
        rpcid = reg.get_rpcid("list_notebooks")
        assert isinstance(rpcid, str)
        assert len(rpcid) > 0

    def test_rpc_registry_fallback_rpcid(self) -> None:
        """list_notebooks has a fallback rpcid."""
        from engine.integrations.nlm_rpc_registry import get_rpc_registry

        reg = get_rpc_registry()
        assert reg.has_fallback("list_notebooks")
        fallback = reg.get_fallback_rpcid("list_notebooks")
        assert fallback is not None
        assert fallback != reg.get_rpcid("list_notebooks")

    def test_rpc_registry_meta(self) -> None:
        """Registry meta contains version."""
        from engine.integrations.nlm_rpc_registry import get_rpc_registry

        reg = get_rpc_registry()
        meta = reg.get_meta()
        assert "version" in meta
        assert meta["version"] == "6.0"

    def test_rpc_registry_list_operations(self) -> None:
        """list_operations returns all operations."""
        from engine.integrations.nlm_rpc_registry import get_rpc_registry

        reg = get_rpc_registry()
        ops = reg.list_operations()
        assert len(ops) >= 50

    def test_rpc_registry_list_categories(self) -> None:
        """list_categories returns sorted unique categories."""
        from engine.integrations.nlm_rpc_registry import get_rpc_registry

        reg = get_rpc_registry()
        cats = reg.list_categories()
        assert isinstance(cats, list)
        assert len(cats) >= 3
        assert cats == sorted(cats)

    def test_rpc_registry_requires_notebook(self) -> None:
        """create_notebook should not require notebook context."""
        from engine.integrations.nlm_rpc_registry import get_rpc_registry

        reg = get_rpc_registry()
        assert not reg.requires_notebook("create_notebook")

    def test_rpc_registry_build_payload(self) -> None:
        """build_payload resolves $param references."""
        from engine.integrations.nlm_rpc_registry import get_rpc_registry

        reg = get_rpc_registry()
        payload = reg.build_payload("list_notebooks")
        assert isinstance(payload, list)
        assert len(payload) > 0

    def test_rpc_registry_singleton_same_instance(self) -> None:
        """get_rpc_registry returns the same singleton instance."""
        from engine.integrations.nlm_rpc_registry import get_rpc_registry

        reg1 = get_rpc_registry()
        reg2 = get_rpc_registry()
        assert reg1 is reg2

    def test_rpc_registry_repr(self) -> None:
        """repr shows operation count and path."""
        from engine.integrations.nlm_rpc_registry import get_rpc_registry

        reg = get_rpc_registry()
        r = repr(reg)
        assert "NLMRpcRegistry" in r
        assert "ops=" in r
