"""Tests for prompts.chat integration skills."""
import json
from unittest.mock import patch, MagicMock

import pytest


# ── search_prompts ─────────────────────────────────────────────


class TestSearchPrompts:
    """Tests for the search_prompts skill."""

    @patch("engine.skills.builtin.prompts_chat_skills._mcp_call")
    def test_search_returns_results(self, mock_call):
        from engine.skills.builtin.prompts_chat_skills import search_prompts

        mock_call.return_value = {
            "result": {
                "content": [{"text": json.dumps({
                    "query": "code review",
                    "count": 1,
                    "prompts": [{"id": "abc", "title": "Code Reviewer"}],
                })}]
            }
        }
        result = json.loads(search_prompts("code review", limit=5))
        assert "result" in result
        mock_call.assert_called_once_with(
            "search_prompts", {"query": "code review", "limit": 5}
        )

    @patch("engine.skills.builtin.prompts_chat_skills._mcp_call")
    def test_search_clamps_limit(self, mock_call):
        from engine.skills.builtin.prompts_chat_skills import search_prompts

        mock_call.return_value = {"result": {}}
        search_prompts("test", limit=100)
        args = mock_call.call_args[0][1]
        assert args["limit"] == 50

    @patch("engine.skills.builtin.prompts_chat_skills._mcp_call")
    def test_search_with_type_filter(self, mock_call):
        from engine.skills.builtin.prompts_chat_skills import search_prompts

        mock_call.return_value = {"result": {}}
        search_prompts("test", prompt_type="IMAGE")
        args = mock_call.call_args[0][1]
        assert args["type"] == "IMAGE"

    @patch("engine.skills.builtin.prompts_chat_skills._mcp_call")
    def test_search_with_category_filter(self, mock_call):
        from engine.skills.builtin.prompts_chat_skills import search_prompts

        mock_call.return_value = {"result": {}}
        search_prompts("test", category="coding")
        args = mock_call.call_args[0][1]
        assert args["category"] == "coding"

    @patch("engine.skills.builtin.prompts_chat_skills._mcp_call")
    def test_search_omits_empty_filters(self, mock_call):
        from engine.skills.builtin.prompts_chat_skills import search_prompts

        mock_call.return_value = {"result": {}}
        search_prompts("test")
        args = mock_call.call_args[0][1]
        assert "type" not in args
        assert "category" not in args


# ── get_prompt ─────────────────────────────────────────────────


class TestGetPrompt:
    """Tests for the get_prompt skill."""

    @patch("engine.skills.builtin.prompts_chat_skills._mcp_call")
    def test_get_prompt_by_id(self, mock_call):
        from engine.skills.builtin.prompts_chat_skills import get_prompt

        mock_call.return_value = {"result": {"id": "abc123", "title": "Test"}}
        result = json.loads(get_prompt("abc123"))
        assert result["result"]["id"] == "abc123"
        mock_call.assert_called_once_with("get_prompt", {"id": "abc123"})


# ── get_skill_from_prompts ─────────────────────────────────────


class TestGetSkill:
    """Tests for the get_skill_from_prompts skill."""

    @patch("engine.skills.builtin.prompts_chat_skills._mcp_call")
    def test_get_skill_by_id(self, mock_call):
        from engine.skills.builtin.prompts_chat_skills import get_skill_from_prompts

        mock_call.return_value = {"result": {"id": "s1", "files": []}}
        result = json.loads(get_skill_from_prompts("s1"))
        assert result["result"]["id"] == "s1"


# ── improve_prompt ─────────────────────────────────────────────


class TestImprovePrompt:
    """Tests for the improve_prompt skill."""

    @patch("engine.skills.builtin.prompts_chat_skills._request")
    def test_improve_prompt_basic(self, mock_req):
        from engine.skills.builtin.prompts_chat_skills import improve_prompt

        mock_req.return_value = {
            "original": "write about AI",
            "improved": "You are an expert...",
        }
        result = json.loads(improve_prompt("write about AI"))
        assert result["original"] == "write about AI"
        assert "improved" in result

    @patch("engine.skills.builtin.prompts_chat_skills._request")
    def test_improve_prompt_truncates(self, mock_req):
        from engine.skills.builtin.prompts_chat_skills import improve_prompt

        mock_req.return_value = {"improved": "ok"}
        improve_prompt("x" * 20000)
        call_data = mock_req.call_args[1]["data"] if "data" in (mock_req.call_args[1] or {}) else mock_req.call_args[0][2]
        assert len(call_data["prompt"]) <= 10000

    @patch("engine.skills.builtin.prompts_chat_skills._request")
    def test_improve_prompt_custom_types(self, mock_req):
        from engine.skills.builtin.prompts_chat_skills import improve_prompt

        mock_req.return_value = {"improved": "ok"}
        improve_prompt("test", output_type="image", output_format="structured_json")
        call_data = mock_req.call_args[1].get("data") if mock_req.call_args[1] else mock_req.call_args[0][2]
        assert call_data["outputType"] == "image"
        assert call_data["outputFormat"] == "structured_json"


# ── ingest_prompts_to_nexus ────────────────────────────────────


class TestIngestToNexus:
    """Tests for the ingest_prompts_to_nexus skill."""

    @patch("engine.nexus.client.get_nexus_client")
    @patch("engine.skills.builtin.prompts_chat_skills._mcp_call")
    def test_ingest_stores_in_nexus(self, mock_call, mock_nexus):
        from engine.skills.builtin.prompts_chat_skills import ingest_prompts_to_nexus

        mock_call.return_value = {
            "result": {
                "content": [{"text": json.dumps({
                    "prompts": [
                        {"title": "Prompt A", "content": "Do X", "description": "Desc", "tags": ["a"]},
                        {"title": "Prompt B", "content": "Do Y", "description": "Desc", "tags": ["b"]},
                    ]
                })}]
            }
        }
        client = MagicMock()
        client.add_entry.return_value = "entry-1"
        mock_nexus.return_value = client

        result = json.loads(ingest_prompts_to_nexus("test", limit=2))
        assert result["stored_in_nexus"] == 2
        assert client.add_entry.call_count == 2

    @patch("engine.skills.builtin.prompts_chat_skills._mcp_call")
    def test_ingest_handles_empty_results(self, mock_call):
        from engine.skills.builtin.prompts_chat_skills import ingest_prompts_to_nexus

        mock_call.return_value = {"result": {"content": []}}
        result = json.loads(ingest_prompts_to_nexus("nothing"))
        assert result["stored_in_nexus"] == 0


# ── _request ───────────────────────────────────────────────────


class TestRequest:
    """Tests for the internal _request helper."""

    @patch("engine.skills.builtin.prompts_chat_skills.urllib.request.urlopen")
    def test_request_get(self, mock_urlopen):
        from engine.skills.builtin.prompts_chat_skills import _request

        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _request("GET", "/test")
        assert result["ok"] is True

    @patch("engine.skills.builtin.prompts_chat_skills._get_api_key")
    @patch("engine.skills.builtin.prompts_chat_skills.urllib.request.urlopen")
    def test_request_includes_api_key(self, mock_urlopen, mock_key):
        from engine.skills.builtin.prompts_chat_skills import _request

        mock_key.return_value = "pchat_test123"
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        _request("GET", "/test")
        req_obj = mock_urlopen.call_args[0][0]
        assert req_obj.get_header("Prompts_api_key") == "pchat_test123"

    @patch("engine.skills.builtin.prompts_chat_skills.urllib.request.urlopen")
    def test_request_handles_http_error(self, mock_urlopen):
        from engine.skills.builtin.prompts_chat_skills import _request

        error = MagicMock()
        error.code = 429
        error.read.return_value = b"rate limited"
        mock_urlopen.side_effect = type(
            "HTTPError", (Exception,), {"code": 429, "read": lambda s: b"rate limited"}
        )()

        # Should not raise
        result = _request("GET", "/test")
        assert "error" in result
