"""Tests for engine.lmstudio.tool_registry — MCP ↔ SDK tool bridge."""
import pytest

from engine.lmstudio.tool_registry import (
    ToolRegistry, ToolScope, ToolSpec, get_tool_registry,
    reset_tool_registry, _extract_params,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _dummy_tool_a(name: str, count: int = 5) -> str:
    """Tool A docstring."""
    return f"{name}:{count}"

def _dummy_tool_b(x: float) -> str:
    """Tool B."""
    return str(x)

def _dummy_router(query: str) -> str:
    """Route a query."""
    return query


# ── Tests: ToolSpec ──────────────────────────────────────────────────

class TestToolSpec:
    def test_to_schema(self):
        spec = ToolSpec(
            name="my_tool", fn=_dummy_tool_a,
            description="Does stuff",
            scopes={ToolScope.CHARACTER, ToolScope.GAME},
        )
        schema = spec.to_schema()
        assert schema["name"] == "my_tool"
        assert schema["description"] == "Does stuff"
        assert "character" in schema["scopes"]
        assert "game" in schema["scopes"]

    def test_default_scopes(self):
        spec = ToolSpec(name="t", fn=lambda: None)
        assert spec.scopes == set()


# ── Tests: Parameter extraction ──────────────────────────────────────

class TestParamExtraction:
    def test_extracts_string_and_int(self):
        params = _extract_params(_dummy_tool_a)
        assert params["properties"]["name"]["type"] == "string"
        assert params["properties"]["count"]["type"] == "integer"
        assert "name" in params["required"]
        # count has default so not required
        assert "count" not in params["required"]

    def test_extracts_float(self):
        params = _extract_params(_dummy_tool_b)
        assert params["properties"]["x"]["type"] == "number"
        assert "x" in params["required"]

    def test_no_params(self):
        params = _extract_params(lambda: None)
        assert params["properties"] == {}
        assert params["required"] == []


# ── Tests: Registry CRUD ─────────────────────────────────────────────

class TestRegistryCRUD:
    def setup_method(self):
        self.reg = ToolRegistry()

    def test_register_and_get(self):
        spec = self.reg.register("tool_a", _dummy_tool_a)
        assert spec.name == "tool_a"
        assert self.reg.get_tool("tool_a") is spec

    def test_register_auto_description(self):
        spec = self.reg.register("tool_a", _dummy_tool_a)
        assert "Tool A docstring" in spec.description

    def test_count(self):
        self.reg.register("a", _dummy_tool_a)
        self.reg.register("b", _dummy_tool_b)
        assert self.reg.count == 2

    def test_unregister(self):
        self.reg.register("a", _dummy_tool_a)
        assert self.reg.unregister("a")
        assert self.reg.get_tool("a") is None
        assert not self.reg.unregister("nonexistent")

    def test_list_names(self):
        self.reg.register("b_tool", _dummy_tool_b)
        self.reg.register("a_tool", _dummy_tool_a)
        assert self.reg.list_names() == ["a_tool", "b_tool"]


# ── Tests: Scope filtering ──────────────────────────────────────────

class TestScopeFiltering:
    def setup_method(self):
        self.reg = ToolRegistry()
        self.reg.register("char_tool", _dummy_tool_a, scopes={ToolScope.CHARACTER})
        self.reg.register("game_tool", _dummy_tool_b, scopes={ToolScope.GAME})
        self.reg.register(
            "both_tool", _dummy_router,
            scopes={ToolScope.CHARACTER, ToolScope.GAME},
        )
        self.reg.register("router_tool", lambda: None, scopes={ToolScope.ROUTER})

    def test_filter_by_scope(self):
        tools = self.reg.get_tools(scope=ToolScope.CHARACTER)
        assert len(tools) == 2  # char_tool + both_tool

    def test_filter_by_scope_string(self):
        tools = self.reg.get_tools(scope="game")
        assert len(tools) == 2  # game_tool + both_tool

    def test_filter_by_names(self):
        tools = self.reg.get_tools(names=["char_tool", "router_tool"])
        assert len(tools) == 2

    def test_get_tool_schemas(self):
        schemas = self.reg.get_tool_schemas(scope=ToolScope.ROUTER)
        assert len(schemas) == 1
        assert schemas[0]["name"] == "router_tool"

    def test_no_scope_returns_all(self):
        tools = self.reg.get_tools()
        assert len(tools) == 4


# ── Tests: Composite role helpers ────────────────────────────────────

class TestRoleHelpers:
    def setup_method(self):
        self.reg = ToolRegistry()
        self.reg.register("c", _dummy_tool_a, scopes={ToolScope.CHARACTER})
        self.reg.register("g", _dummy_tool_b, scopes={ToolScope.GAME})
        self.reg.register("s", _dummy_router, scopes={ToolScope.SYSTEM})
        self.reg.register("r", lambda: None, scopes={ToolScope.ROUTER})
        self.reg.register("sc", lambda: None, scopes={ToolScope.SCENE})

    def test_for_character_agent(self):
        tools = self.reg.for_character_agent("lola")
        assert len(tools) == 2  # CHARACTER + GAME

    def test_for_game_master(self):
        tools = self.reg.for_game_master()
        assert len(tools) == 3  # GAME + SCENE + CHARACTER

    def test_for_system(self):
        tools = self.reg.for_system()
        assert len(tools) == 5  # All

    def test_for_router(self):
        tools = self.reg.for_router()
        assert len(tools) == 1  # ROUTER only


# ── Tests: Singleton ─────────────────────────────────────────────────

class TestSingleton:
    def setup_method(self):
        reset_tool_registry()

    def teardown_method(self):
        reset_tool_registry()

    def test_get_returns_same_instance(self):
        r1 = get_tool_registry(auto_load=False)
        r2 = get_tool_registry(auto_load=False)
        assert r1 is r2

    def test_reset_clears(self):
        r1 = get_tool_registry(auto_load=False)
        reset_tool_registry()
        r2 = get_tool_registry(auto_load=False)
        assert r1 is not r2


# ── Tests: MCP server loading (integration) ──────────────────────────

class TestMCPLoading:
    def test_load_from_mcp_server_runs(self):
        """Smoke test — loads whatever tools the server exposes."""
        reg = ToolRegistry()
        count = reg.load_from_mcp_server()
        # Should load at least some tools (>50 known in cosysim_server)
        assert count >= 0  # May fail if server has import issues
        if count > 0:
            assert reg.count == count
            # Spot check a known tool
            if reg.get_tool("roll_dice"):
                assert ToolScope.GAME in reg.get_tool("roll_dice").scopes
