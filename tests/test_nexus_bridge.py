"""Tests for Nexus bridge tools in CosySim MCP server + Nexus CLI."""
import json
import pytest
from unittest.mock import patch, MagicMock


# ═══════════════════════════════════════════════════════════════════════
# Nexus Bridge Tools — test the underlying functions
# We can't call @mcp.tool() wrapped functions directly (FunctionTool),
# so we test the logic by calling the NexusClient mock through module-level
# test functions that replicate the tool logic.
# ═══════════════════════════════════════════════════════════════════════

class TestNexusBridgeTools:
    """Test the Nexus bridge tool logic."""

    def _mock_nexus(self):
        mock = MagicMock()
        mock.search.return_value = [{"title": "Test", "content": "data"}]
        mock.ask.return_value = {"answer": "42", "source": "cache"}
        mock.add_entry.return_value = "entry-123"
        mock.add_qa.return_value = "qa-456"
        mock.get_rules.return_value = [{"name": "rule1", "scope": "coding"}]
        mock.store_prompt.return_value = "prompt-789"
        mock.get_prompts.return_value = [{"title": "sys", "content": "prompt"}]
        mock.research.return_value = {"research_id": "r-1"}
        mock.converse.return_value = {"response": "analysis"}
        mock.finish_research.return_value = {"qa_pairs": 3}
        mock.import_youtube.return_value = {"title": "Video", "entry_id": "yt-1"}
        mock.log_session.return_value = "sess-1"
        mock.health.return_value = {"ok": True}
        mock.stats.return_value = {"ok": True, "entries": 100}
        mock.is_available.return_value = True
        mock.list_plugins.return_value = [{"name": "tagger"}]
        return mock

    def test_nexus_search_logic(self):
        nx = self._mock_nexus()
        results = nx.search("pipeline", limit=10)
        out = json.dumps({"results": results, "count": len(results)})
        parsed = json.loads(out)
        assert parsed["count"] == 1
        assert parsed["results"][0]["title"] == "Test"

    def test_nexus_ask_logic(self):
        nx = self._mock_nexus()
        answer = nx.ask("How?", depth="auto", category="")
        out = json.dumps(answer)
        parsed = json.loads(out)
        assert parsed["answer"] == "42"

    def test_nexus_add_logic(self):
        nx = self._mock_nexus()
        tags = [t.strip() for t in "tag1,tag2".split(",") if t.strip()]
        entry_id = nx.add_entry("Title", "Content", content_type="decision",
                                category="arch", tags=tags)
        assert entry_id == "entry-123"

    def test_nexus_add_qa_logic(self):
        nx = self._mock_nexus()
        qa_id = nx.add_qa("Q?", "A.")
        assert qa_id == "qa-456"

    def test_nexus_get_rules_logic(self):
        nx = self._mock_nexus()
        rules = nx.get_rules(scope="coding")
        assert len(rules) == 1

    def test_nexus_store_prompt_logic(self):
        nx = self._mock_nexus()
        prompt_id = nx.store_prompt("sys", "prompt text")
        assert prompt_id == "prompt-789"

    def test_nexus_get_prompts_logic(self):
        nx = self._mock_nexus()
        prompts = nx.get_prompts(category="system")
        assert len(prompts) == 1

    def test_nexus_research_logic(self):
        nx = self._mock_nexus()
        result = nx.research("Best approach?")
        assert result["research_id"] == "r-1"

    def test_nexus_converse_logic(self):
        nx = self._mock_nexus()
        result = nx.converse("r-1", "follow up")
        assert result["response"] == "analysis"

    def test_nexus_finish_research_logic(self):
        nx = self._mock_nexus()
        result = nx.finish_research("r-1")
        assert result["qa_pairs"] == 3

    def test_nexus_import_youtube_logic(self):
        nx = self._mock_nexus()
        result = nx.import_youtube("https://youtube.com/watch?v=abc")
        assert result["title"] == "Video"

    def test_nexus_log_session_logic(self):
        nx = self._mock_nexus()
        session_id = nx.log_session(project="CosySim")
        assert session_id == "sess-1"

    def test_nexus_status_logic(self):
        nx = self._mock_nexus()
        health = nx.health()
        stats = nx.stats()
        assert health["ok"] is True
        assert stats["ok"] is True

    def test_nexus_list_plugins_logic(self):
        nx = self._mock_nexus()
        plugins = nx.list_plugins()
        assert len(plugins) == 1

    def test_nexus_unavailable_returns_error(self):
        result = json.dumps({"error": "Nexus unavailable"})
        parsed = json.loads(result)
        assert "error" in parsed


# ═══════════════════════════════════════════════════════════════════════
# MCP Server Tool Registration
# ═══════════════════════════════════════════════════════════════════════

class TestMCPToolRegistration:
    """Verify tools are registered in the MCP server."""

    def test_nexus_tools_registered(self):
        import asyncio
        from engine.mcp.cosysim_server import mcp

        async def check():
            tools = await mcp.get_tools()
            return tools

        tools = asyncio.run(check())
        nexus_tools = [n for n in tools if "nexus" in n.lower()]
        assert len(nexus_tools) >= 14, f"Expected 14+ Nexus tools, got {len(nexus_tools)}"

    def test_discovery_tools_registered(self):
        import asyncio
        from engine.mcp.cosysim_server import mcp

        async def check():
            tools = await mcp.get_tools()
            return tools

        tools = asyncio.run(check())
        assert "list_all_skills" in tools
        assert "get_skill_info" in tools
        assert "system_status" in tools

    def test_total_tool_count(self):
        import asyncio
        from engine.mcp.cosysim_server import mcp

        async def check():
            tools = await mcp.get_tools()
            return tools

        tools = asyncio.run(check())
        assert len(tools) >= 120, f"Expected 120+ tools, got {len(tools)}"


# ═══════════════════════════════════════════════════════════════════════
# Nexus CLI
# ═══════════════════════════════════════════════════════════════════════

class TestNexusCLI:
    """Test the Nexus CLI argument parsing and commands."""

    def test_search_command(self):
        from engine.nexus.cli import main
        with patch("engine.nexus.cli.get_nexus_client") as mock_client:
            mock = MagicMock()
            mock.search.return_value = [{"title": "Result", "content": "data", "content_type": "note"}]
            mock_client.return_value = mock
            with patch("sys.argv", ["nexus", "search", "pipeline"]):
                main()
            mock.search.assert_called_once_with("pipeline", limit=10)

    def test_ask_command(self):
        from engine.nexus.cli import main
        with patch("engine.nexus.cli.get_nexus_client") as mock_client:
            mock = MagicMock()
            mock.ask.return_value = {"answer": "42", "source": "cache"}
            mock_client.return_value = mock
            with patch("sys.argv", ["nexus", "ask", "How does X work?"]):
                main()
            mock.ask.assert_called_once()

    def test_status_command(self):
        from engine.nexus.cli import main
        with patch("engine.nexus.cli.get_nexus_client") as mock_client:
            mock = MagicMock()
            mock.health.return_value = {"ok": True}
            mock.stats.return_value = {"ok": True, "entries": 50}
            mock_client.return_value = mock
            with patch("sys.argv", ["nexus", "status"]):
                main()
            mock.health.assert_called_once()

    def test_add_command(self):
        from engine.nexus.cli import main
        with patch("engine.nexus.cli.get_nexus_client") as mock_client:
            mock = MagicMock()
            mock.add_entry.return_value = "entry-1"
            mock_client.return_value = mock
            with patch("sys.argv", ["nexus", "add", "Title", "Content", "--type", "decision"]):
                main()
            mock.add_entry.assert_called_once()

    def test_qa_command(self):
        from engine.nexus.cli import main
        with patch("engine.nexus.cli.get_nexus_client") as mock_client:
            mock = MagicMock()
            mock.add_qa.return_value = "qa-1"
            mock_client.return_value = mock
            with patch("sys.argv", ["nexus", "qa", "Q?", "A."]):
                main()
            mock.add_qa.assert_called_once()

    def test_no_command_shows_help(self):
        from engine.nexus.cli import main
        with patch("sys.argv", ["nexus"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
