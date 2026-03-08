"""Tests for NLM RPC Registry — YAML loading, lookups, payload building."""
from __future__ import annotations

import copy
import textwrap
from pathlib import Path

import pytest
import yaml

from engine.integrations.nlm_rpc_registry import (
    NLMRpcRegistry,
    get_rpc_registry,
    reset_registry,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────

MINIMAL_YAML = {
    "meta": {"version": "1.0", "updated": "2026-01-01"},
    "parameters": {
        "tier_marker": {
            "description": "Tier hint",
            "type": "array",
            "default": [2],
            "options": {"free": [1], "pro": [2], "ultra": [3]},
        },
        "doc_type": {
            "description": "Doc type",
            "type": "integer",
            "default": 2,
            "options": {"brief": 2, "deep": 9},
        },
        "page_size": {
            "description": "Page size",
            "type": "integer",
            "default": 20,
        },
    },
    "shared_configs": {
        "write_config": {
            "description": "Write config",
            "value": [2, None, None, [1, None, None, None, None, None, None, None, None, None, [1]], [[2, 1]]],
            "configurable_slots": {"0": "doc_type", "4": "model_quality"},
        },
        "source_config": {
            "description": "Source config",
            "value": [1, None, None, None, None, None, None, None, None, None, [1]],
            "configurable_slots": {},
        },
    },
    "operations": {
        "list_notebooks": {
            "rpcid": "wXbhsf",
            "fallback_rpcid": "ub2Bae",
            "payload": [None, 1, None, "$tier_marker"],
            "fallback_payload": ["$tier_marker"],
            "requires_notebook": False,
            "timeout": 30,
            "confirmed": "2026-06-10",
            "category": "notebook",
            "description": "List notebooks",
            "configurable": ["tier_marker"],
        },
        "create_notebook": {
            "rpcid": "CCqFvf",
            "fallback_rpcid": "VqhFhd",
            "payload": ["$title", None, None, "$tier_marker", "$source_config"],
            "fallback_payload": ["$title", None, None],
            "requires_notebook": False,
            "timeout": 30,
            "confirmed": "2026-06-10",
            "category": "notebook",
            "description": "Create notebook",
            "configurable": ["tier_marker", "source_config"],
        },
        "delete_notebook": {
            "rpcid": "WWINqb",
            "fallback_rpcid": "kVoZqc",
            "payload": [["$notebook_id"], "$tier_marker"],
            "fallback_payload": [["$notebook_id"]],
            "requires_notebook": False,
            "timeout": 30,
            "confirmed": "2026-06-10",
            "category": "notebook",
            "description": "Delete notebook",
            "configurable": ["tier_marker"],
        },
        "create_note": {
            "rpcid": "CYK0Xb",
            "fallback_rpcid": None,
            "payload": ["$notebook_id", "$question_text"],
            "requires_notebook": True,
            "timeout": 180,
            "confirmed": "2026-02-22",
            "category": "chat",
            "description": "Citation-grounded Q&A",
            "aliases": ["ask_with_citations"],
        },
        "session_init": {
            "rpcid": "ZwVcOc",
            "fallback_rpcid": None,
            "payload": [],
            "requires_notebook": False,
            "timeout": 15,
            "confirmed": "2026-02-20",
            "category": "session",
            "description": "Init session",
        },
        "add_source": {
            "rpcid": "izAoDd",
            "fallback_rpcid": None,
            "payload": [["$source_obj"], "$notebook_id", "$tier_marker", "$source_config"],
            "requires_notebook": True,
            "timeout": 60,
            "confirmed": "2026-02-28",
            "category": "source",
            "description": "Add source",
            "configurable": ["tier_marker", "source_config"],
        },
        "get_notebook_analysis": {
            "rpcid": "VfAZjd",
            "fallback_rpcid": None,
            "payload": ["$notebook_id", ["$analysis_depth"]],
            "requires_notebook": True,
            "timeout": 60,
            "confirmed": "2026-02-20",
            "category": "notebook",
            "description": "Structural analysis",
        },
    },
    "mime_types": {
        "images": {".jpg": "image/jpeg", ".png": "image/png"},
        "audio": {".mp3": "audio/mpeg"},
        "documents": {".pdf": "application/pdf"},
    },
}


@pytest.fixture
def yaml_path(tmp_path: Path) -> Path:
    """Write a minimal YAML registry and return the path."""
    path = tmp_path / "nlm_rpcids.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(MINIMAL_YAML, f, default_flow_style=False)
    return path


@pytest.fixture
def registry(yaml_path: Path) -> NLMRpcRegistry:
    """Create a fresh registry from the minimal YAML."""
    return NLMRpcRegistry(yaml_path)


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the global singleton between tests."""
    reset_registry()
    yield
    reset_registry()


# ─── Loading ─────────────────────────────────────────────────────────────────

class TestLoading:
    def test_load_from_yaml(self, registry: NLMRpcRegistry) -> None:
        assert repr(registry).startswith("<NLMRpcRegistry")

    def test_load_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            NLMRpcRegistry(tmp_path / "nonexistent.yaml")

    def test_reload(self, registry: NLMRpcRegistry, yaml_path: Path) -> None:
        # Modify the YAML on disk
        data = copy.deepcopy(MINIMAL_YAML)
        data["meta"]["version"] = "2.0"
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f)
        registry.reload()
        assert registry.get_meta()["version"] == "2.0"

    def test_get_meta(self, registry: NLMRpcRegistry) -> None:
        meta = registry.get_meta()
        assert meta["version"] == "1.0"
        assert meta["updated"] == "2026-01-01"


# ─── rpcid Lookups ───────────────────────────────────────────────────────────

class TestRpcidLookup:
    def test_get_primary_rpcid(self, registry: NLMRpcRegistry) -> None:
        assert registry.get_rpcid("list_notebooks") == "wXbhsf"
        assert registry.get_rpcid("create_notebook") == "CCqFvf"
        assert registry.get_rpcid("delete_notebook") == "WWINqb"

    def test_get_fallback_rpcid(self, registry: NLMRpcRegistry) -> None:
        assert registry.get_rpcid("list_notebooks", "fallback") == "ub2Bae"
        assert registry.get_rpcid("create_notebook", "fallback") == "VqhFhd"
        assert registry.get_rpcid("delete_notebook", "fallback") == "kVoZqc"

    def test_get_fallback_none_raises(self, registry: NLMRpcRegistry) -> None:
        with pytest.raises(ValueError, match="no fallback"):
            registry.get_rpcid("create_note", "fallback")

    def test_get_fallback_rpcid_helper(self, registry: NLMRpcRegistry) -> None:
        assert registry.get_fallback_rpcid("list_notebooks") == "ub2Bae"
        assert registry.get_fallback_rpcid("create_note") is None

    def test_has_fallback(self, registry: NLMRpcRegistry) -> None:
        assert registry.has_fallback("list_notebooks") is True
        assert registry.has_fallback("create_note") is False

    def test_unknown_operation_raises(self, registry: NLMRpcRegistry) -> None:
        with pytest.raises(KeyError, match="Unknown NLM operation"):
            registry.get_rpcid("nonexistent_op")

    def test_unknown_tier_raises(self, registry: NLMRpcRegistry) -> None:
        with pytest.raises(ValueError, match="Unknown tier"):
            registry.get_rpcid("list_notebooks", "ultra")

    def test_alias_lookup(self, registry: NLMRpcRegistry) -> None:
        # create_note has alias "ask_with_citations"
        assert registry.get_rpcid("ask_with_citations") == "CYK0Xb"


# ─── Operation Metadata ─────────────────────────────────────────────────────

class TestOperationMetadata:
    def test_get_operation(self, registry: NLMRpcRegistry) -> None:
        op = registry.get_operation("list_notebooks")
        assert op["rpcid"] == "wXbhsf"
        assert op["category"] == "notebook"

    def test_get_timeout(self, registry: NLMRpcRegistry) -> None:
        assert registry.get_timeout("list_notebooks") == 30
        assert registry.get_timeout("create_note") == 180

    def test_requires_notebook(self, registry: NLMRpcRegistry) -> None:
        assert registry.requires_notebook("create_note") is True
        assert registry.requires_notebook("list_notebooks") is False

    def test_find_by_rpcid(self, registry: NLMRpcRegistry) -> None:
        assert registry.find_operation_by_rpcid("wXbhsf") == "list_notebooks"
        assert registry.find_operation_by_rpcid("ub2Bae") == "list_notebooks"
        assert registry.find_operation_by_rpcid("UNKNOWN") is None


# ─── Parameters ──────────────────────────────────────────────────────────────

class TestParameters:
    def test_get_default(self, registry: NLMRpcRegistry) -> None:
        assert registry.get_parameter("tier_marker") == [2]
        assert registry.get_parameter("doc_type") == 2
        assert registry.get_parameter("page_size") == 20

    def test_get_named_option(self, registry: NLMRpcRegistry) -> None:
        assert registry.get_parameter("tier_marker", "free") == [1]
        assert registry.get_parameter("tier_marker", "pro") == [2]
        assert registry.get_parameter("tier_marker", "ultra") == [3]
        assert registry.get_parameter("doc_type", "deep") == 9

    def test_unknown_option_raises(self, registry: NLMRpcRegistry) -> None:
        with pytest.raises(KeyError, match="Unknown option"):
            registry.get_parameter("tier_marker", "nonexistent")

    def test_unknown_parameter_raises(self, registry: NLMRpcRegistry) -> None:
        with pytest.raises(KeyError, match="Unknown NLM parameter"):
            registry.get_parameter("nonexistent")

    def test_set_override(self, registry: NLMRpcRegistry) -> None:
        registry.set_parameter("tier_marker", [3])
        assert registry.get_parameter("tier_marker") == [3]
        # Named option still works (override ignored when option specified)
        assert registry.get_parameter("tier_marker", "free") == [1]

    def test_clear_overrides(self, registry: NLMRpcRegistry) -> None:
        registry.set_parameter("tier_marker", [3])
        registry.clear_overrides()
        assert registry.get_parameter("tier_marker") == [2]

    def test_list_parameters(self, registry: NLMRpcRegistry) -> None:
        params = registry.list_parameters()
        assert "tier_marker" in params
        assert params["tier_marker"]["current"] == [2]
        assert params["tier_marker"]["overridden"] is False

    def test_list_parameters_with_override(self, registry: NLMRpcRegistry) -> None:
        registry.set_parameter("tier_marker", [3])
        params = registry.list_parameters()
        assert params["tier_marker"]["current"] == [3]
        assert params["tier_marker"]["overridden"] is True

    def test_override_returns_deepcopy(self, registry: NLMRpcRegistry) -> None:
        """Ensure mutations to returned values don't corrupt the registry."""
        val = registry.get_parameter("tier_marker")
        val.append(999)
        assert registry.get_parameter("tier_marker") == [2]


# ─── Shared Configs ──────────────────────────────────────────────────────────

class TestSharedConfigs:
    def test_get_write_config(self, registry: NLMRpcRegistry) -> None:
        wc = registry.get_shared_config("write_config")
        assert wc[0] == 2  # doc_type default
        assert wc[4] == [[2, 1]]  # model_quality default

    def test_get_source_config(self, registry: NLMRpcRegistry) -> None:
        sc = registry.get_shared_config("source_config")
        assert sc[0] == 1
        assert sc[10] == [1]
        assert len(sc) == 11

    def test_write_config_override_doc_type(self, registry: NLMRpcRegistry) -> None:
        wc = registry.get_shared_config("write_config", doc_type=9)
        assert wc[0] == 9  # overridden

    def test_write_config_override_model_quality(self, registry: NLMRpcRegistry) -> None:
        wc = registry.get_shared_config("write_config", model_quality=[3, 1])
        assert wc[4] == [3, 1]

    def test_unknown_config_raises(self, registry: NLMRpcRegistry) -> None:
        with pytest.raises(KeyError, match="Unknown shared config"):
            registry.get_shared_config("nonexistent")

    def test_config_deepcopy(self, registry: NLMRpcRegistry) -> None:
        wc1 = registry.get_shared_config("write_config")
        wc1[0] = 999
        wc2 = registry.get_shared_config("write_config")
        assert wc2[0] == 2  # not corrupted


# ─── Payload Building ───────────────────────────────────────────────────────

class TestPayloadBuilding:
    def test_build_list_notebooks_primary(self, registry: NLMRpcRegistry) -> None:
        payload = registry.build_payload("list_notebooks")
        assert payload == [None, 1, None, [2]]

    def test_build_list_notebooks_fallback(self, registry: NLMRpcRegistry) -> None:
        payload = registry.build_payload("list_notebooks", tier="fallback")
        assert payload == [[2]]

    def test_build_with_kwarg_override(self, registry: NLMRpcRegistry) -> None:
        payload = registry.build_payload("list_notebooks", tier_marker=[1])
        assert payload == [None, 1, None, [1]]

    def test_build_create_notebook(self, registry: NLMRpcRegistry) -> None:
        payload = registry.build_payload("create_notebook", title="My NB")
        assert payload[0] == "My NB"
        assert payload[3] == [2]  # tier_marker default
        # source_config resolved from shared_configs
        assert payload[4][0] == 1
        assert len(payload[4]) == 11

    def test_build_create_notebook_fallback(self, registry: NLMRpcRegistry) -> None:
        payload = registry.build_payload("create_notebook", tier="fallback", title="Test")
        assert payload == ["Test", None, None]

    def test_build_delete_notebook(self, registry: NLMRpcRegistry) -> None:
        payload = registry.build_payload("delete_notebook", notebook_id="abc-123")
        assert payload == [["abc-123"], [2]]

    def test_build_delete_notebook_fallback(self, registry: NLMRpcRegistry) -> None:
        payload = registry.build_payload("delete_notebook", tier="fallback", notebook_id="abc-123")
        assert payload == [["abc-123"]]

    def test_build_create_note(self, registry: NLMRpcRegistry) -> None:
        payload = registry.build_payload(
            "create_note", notebook_id="nb-1", question_text="What is MCP?"
        )
        assert payload == ["nb-1", "What is MCP?"]

    def test_build_add_source(self, registry: NLMRpcRegistry) -> None:
        payload = registry.build_payload(
            "add_source",
            source_obj=[None, None, "https://example.com"],
            notebook_id="nb-1",
        )
        assert payload[0] == [[None, None, "https://example.com"]]
        assert payload[1] == "nb-1"
        assert payload[2] == [2]  # tier_marker
        assert payload[3][0] == 1  # source_config

    def test_build_no_fallback_payload_raises(self, registry: NLMRpcRegistry) -> None:
        with pytest.raises(ValueError, match="no fallback_payload"):
            registry.build_payload("create_note", tier="fallback")

    def test_build_with_runtime_override(self, registry: NLMRpcRegistry) -> None:
        registry.set_parameter("tier_marker", [3])
        payload = registry.build_payload("list_notebooks")
        assert payload == [None, 1, None, [3]]

    def test_kwarg_overrides_runtime_override(self, registry: NLMRpcRegistry) -> None:
        registry.set_parameter("tier_marker", [3])
        payload = registry.build_payload("list_notebooks", tier_marker=[1])
        assert payload == [None, 1, None, [1]]

    def test_build_session_init_empty(self, registry: NLMRpcRegistry) -> None:
        payload = registry.build_payload("session_init")
        assert payload == []

    def test_build_analysis_with_depth(self, registry: NLMRpcRegistry) -> None:
        """analysis_depth is not in shared configs but is a parameter."""
        payload = registry.build_payload(
            "get_notebook_analysis",
            notebook_id="nb-1",
            analysis_depth=1,
        )
        assert payload[0] == "nb-1"
        assert payload[1] == [1]


# ─── Listing / Discovery ────────────────────────────────────────────────────

class TestDiscovery:
    def test_list_operations(self, registry: NLMRpcRegistry) -> None:
        ops = registry.list_operations()
        assert "list_notebooks" in ops
        assert "create_notebook" in ops

    def test_list_operations_by_category(self, registry: NLMRpcRegistry) -> None:
        notebook_ops = registry.list_operations(category="notebook")
        assert "list_notebooks" in notebook_ops
        assert "create_notebook" in notebook_ops
        assert "create_note" not in notebook_ops

    def test_list_categories(self, registry: NLMRpcRegistry) -> None:
        cats = registry.list_categories()
        assert "notebook" in cats
        assert "chat" in cats
        assert "session" in cats
        assert "source" in cats

    def test_get_mime_types(self, registry: NLMRpcRegistry) -> None:
        mimes = registry.get_mime_types()
        assert mimes[".jpg"] == "image/jpeg"
        assert mimes[".mp3"] == "audio/mpeg"
        assert mimes[".pdf"] == "application/pdf"

    def test_to_summary(self, registry: NLMRpcRegistry) -> None:
        summary = registry.to_summary()
        assert "NLM RPC Registry" in summary
        assert "wXbhsf" in summary
        assert "ub2Bae" in summary


# ─── Singleton ───────────────────────────────────────────────────────────────

class TestSingleton:
    def test_get_rpc_registry(self, yaml_path: Path) -> None:
        reg1 = get_rpc_registry(yaml_path)
        reg2 = get_rpc_registry()
        assert reg1 is reg2

    def test_reset_registry(self, yaml_path: Path) -> None:
        reg1 = get_rpc_registry(yaml_path)
        reset_registry()
        reg2 = get_rpc_registry(yaml_path)
        assert reg1 is not reg2


# ─── Real YAML Loading ──────────────────────────────────────────────────────

class TestRealYaml:
    """Tests that load from the actual config/nlm_rpcids.yaml on disk."""

    @pytest.fixture
    def real_registry(self) -> NLMRpcRegistry:
        real_path = Path(__file__).resolve().parents[1] / "config" / "nlm_rpcids.yaml"
        if not real_path.exists():
            pytest.skip("config/nlm_rpcids.yaml not found")
        return NLMRpcRegistry(real_path)

    def test_real_yaml_loads(self, real_registry: NLMRpcRegistry) -> None:
        ops = real_registry.list_operations()
        assert len(ops) >= 30  # we defined 38+ operations

    def test_real_list_notebooks(self, real_registry: NLMRpcRegistry) -> None:
        assert real_registry.get_rpcid("list_notebooks") == "wXbhsf"
        assert real_registry.get_rpcid("list_notebooks", "fallback") == "ub2Bae"

    def test_real_create_notebook(self, real_registry: NLMRpcRegistry) -> None:
        assert real_registry.get_rpcid("create_notebook") == "CCqFvf"
        assert real_registry.get_rpcid("create_notebook", "fallback") == "VqhFhd"

    def test_real_delete_notebook(self, real_registry: NLMRpcRegistry) -> None:
        assert real_registry.get_rpcid("delete_notebook") == "WWINqb"
        assert real_registry.get_rpcid("delete_notebook", "fallback") == "kVoZqc"

    def test_real_build_list_notebooks(self, real_registry: NLMRpcRegistry) -> None:
        payload = real_registry.build_payload("list_notebooks")
        assert payload == [None, 1, None, [2]]

    def test_real_build_create_notebook(self, real_registry: NLMRpcRegistry) -> None:
        payload = real_registry.build_payload("create_notebook", title="Test")
        assert payload[0] == "Test"
        assert payload[3] == [2]

    def test_real_all_operations_have_rpcid(self, real_registry: NLMRpcRegistry) -> None:
        for name, op in real_registry.list_operations().items():
            if isinstance(op, list):
                # har_markers is a list of marker dicts, not an operation
                continue
            assert "rpcid" in op, f"Operation {name} missing rpcid"
            # Heap-discovered operations may have null rpcid (not yet captured live)
            if op.get("source") == "argus_heap":
                continue
            assert isinstance(op["rpcid"], str), f"Operation {name} rpcid not string"

    def test_real_all_categories_valid(self, real_registry: NLMRpcRegistry) -> None:
        valid = {"session", "account", "notebook", "source", "chat", "artifact", "research", "media", "webrtc"}
        for name, op in real_registry.list_operations().items():
            if isinstance(op, list):
                continue
            cat = op.get("category")
            assert cat in valid, f"Operation {name} has invalid category: {cat}"

    def test_real_tier_marker_options(self, real_registry: NLMRpcRegistry) -> None:
        assert real_registry.get_parameter("tier_marker", "free") == [1]
        assert real_registry.get_parameter("tier_marker", "pro") == [2]
        assert real_registry.get_parameter("tier_marker", "ultra") == [3]

    def test_real_write_config(self, real_registry: NLMRpcRegistry) -> None:
        wc = real_registry.get_shared_config("write_config")
        assert wc[0] == 2
        assert wc[4] == [[2, 1]]

    def test_real_source_config(self, real_registry: NLMRpcRegistry) -> None:
        sc = real_registry.get_shared_config("source_config")
        assert sc[0] == 1
        assert sc[10] == [1]


class TestMultiServiceSections:
    """Tests for the Gemini, AI Studio, Colab, and quota sections."""

    @pytest.fixture()
    def registry_data(self) -> Dict[str, Any]:
        reg = get_rpc_registry()
        return reg._data

    def test_gemini_rpcids_present(self, registry_data: Dict[str, Any]) -> None:
        gemini = registry_data.get("gemini", {}).get("rpcids", {})
        assert len(gemini) >= 17
        assert "otAQ7b" in gemini
        assert "K4WWud" in gemini
        assert "ozz5Z" in gemini
        assert "NXpLKc" in gemini

    def test_gemini_meta(self, registry_data: Dict[str, Any]) -> None:
        meta = registry_data.get("gemini", {}).get("meta", {})
        assert meta["service_name"] == "BardChatUi"
        assert "batchexecute" in meta["rpc_path"]

    def test_gemini_rpcid_descriptions(self, registry_data: Dict[str, Any]) -> None:
        gemini = registry_data["gemini"]["rpcids"]
        for name, info in gemini.items():
            assert "description" in info, f"Gemini rpcid {name} missing description"
            assert "category" in info, f"Gemini rpcid {name} missing category"

    def test_aistudio_methods_present(self, registry_data: Dict[str, Any]) -> None:
        methods = registry_data.get("aistudio", {}).get("methods", {})
        assert len(methods) >= 27
        assert "GenerateContent" in methods
        assert "StreamGenerateContent" in methods
        assert "BidiGenerateContent" in methods
        assert "ListModels" in methods
        assert "ProxyUnaryCall" in methods

    def test_aistudio_meta(self, registry_data: Dict[str, Any]) -> None:
        meta = registry_data.get("aistudio", {}).get("meta", {})
        assert meta["service_name"] == "MakerSuiteService"
        assert meta["protocol"] == "grpc-web"
        assert "clients6.google.com" in meta["grpc_host"]

    def test_aistudio_streaming_flags(self, registry_data: Dict[str, Any]) -> None:
        methods = registry_data["aistudio"]["methods"]
        assert methods["StreamGenerateContent"]["streaming"] is True
        assert methods["GenerateContent"]["streaming"] is False
        assert methods["BidiGenerateContent"]["streaming"] is True

    def test_colab_methods_present(self, registry_data: Dict[str, Any]) -> None:
        methods = registry_data.get("colab", {}).get("methods", {})
        assert len(methods) >= 10
        assert "AgentCreateTask" in methods
        assert "CompleteCode" in methods
        assert "SmartPaste" in methods
        assert "ExecuteCell" in methods

    def test_colab_meta(self, registry_data: Dict[str, Any]) -> None:
        meta = registry_data.get("colab", {}).get("meta", {})
        assert meta["service_name"] == "ColabService"
        assert meta["protocol"] == "grpc-web"

    def test_quota_events_present(self, registry_data: Dict[str, Any]) -> None:
        events = registry_data.get("quota_events", {})
        assert len(events) >= 4
        assert "audio_overview" in events
        assert "deep_research" in events
        assert "notebook_limit" in events
        assert "source_limit" in events

    def test_quota_event_observables(self, registry_data: Dict[str, Any]) -> None:
        events = registry_data["quota_events"]
        for name, info in events.items():
            assert "observable" in info, f"Quota event {name} missing observable"
            assert info["observable"].endswith("$"), f"{name} observable should end with $"

    def test_nlm_identity(self, registry_data: Dict[str, Any]) -> None:
        identity = registry_data.get("nlm_identity", {})
        assert identity["service_name"] == "LabsTailwindUi"
        assert identity["product_id"] == 269
        assert identity["service_pid"] == 666
        assert "batchexecute" in identity["rpc_path"]

    def test_service_method_mappings(self, registry_data: Dict[str, Any]) -> None:
        """Test that service_method fields are properly populated."""
        ops = registry_data.get("operations", {})
        mapped = 0
        for name, op in ops.items():
            if not isinstance(op, dict):
                continue
            sm = op.get("service_method")
            if sm:
                assert sm.startswith("LabsTailwindOrchestrationService."), (
                    f"{name}: service_method should start with LabsTailwindOrchestrationService"
                )
                mapped += 1
        assert mapped >= 30, f"Expected 30+ operations with service_method, got {mapped}"

    def test_heap_discovered_operations(self, registry_data: Dict[str, Any]) -> None:
        """Test that heap-discovered operations are properly tagged."""
        ops = registry_data.get("operations", {})
        heap_ops = {k: v for k, v in ops.items() if isinstance(v, dict) and v.get("source") == "argus_heap"}
        assert len(heap_ops) >= 10, f"Expected 10+ heap-discovered operations, got {len(heap_ops)}"
        for name, op in heap_ops.items():
            assert op.get("service_method"), f"Heap operation {name} missing service_method"

    def test_total_api_surface(self, registry_data: Dict[str, Any]) -> None:
        """Verify the total API surface count matches expectations."""
        nlm = len([v for v in registry_data.get("operations", {}).values() if isinstance(v, dict)])
        gemini = len(registry_data.get("gemini", {}).get("rpcids", {}))
        aistudio = len(registry_data.get("aistudio", {}).get("methods", {}))
        colab = len(registry_data.get("colab", {}).get("methods", {}))
        quota = len(registry_data.get("quota_events", {}))
        total = nlm + gemini + aistudio + colab + quota
        assert total >= 100, f"Expected 100+ total API surface entries, got {total}"
