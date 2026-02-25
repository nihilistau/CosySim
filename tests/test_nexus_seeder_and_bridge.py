"""Tests for Nexus seeder (nexus_seeder.py) and bridge (bridge.py) modules.

Covers:
- Seeder functions: seed_docs, seed_qa, seed_rules, seed_prompts, seed_conventions
- Seeder idempotency via _entry_exists / _qa_exists
- Seeder error handling (Nexus down, bad responses)
- Seeder CLI dispatch (main)
- Bridge CLI commands: search, ask, store, qa, rules, health, seed, maintain
- Bridge dedup and cleanup logic
- MCP tool wrappers: seed_nexus, nexus_maintain
"""
import json
import sys
from argparse import Namespace
from io import StringIO
from unittest.mock import MagicMock, patch, call

import pytest


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _mock_urlopen_response(data: dict):
    """Create a mock urllib response that returns JSON data."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(data).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ═══════════════════════════════════════════════════════════════════════
# NEXUS SEEDER — Module-level functions
# ═══════════════════════════════════════════════════════════════════════

class TestSeederHelpers:
    """Tests for the low-level helpers _post, _get, _search, _entry_exists, _qa_exists."""

    @patch("engine.nexus.nexus_seeder.urllib.request.urlopen")
    def test_post_sends_json_body(self, mock_urlopen):
        """_post sends a JSON POST to the Nexus API and returns parsed response."""
        from engine.nexus.nexus_seeder import _post

        mock_urlopen.return_value = _mock_urlopen_response({"ok": True, "id": "e-1"})

        result = _post("/api/entries", {"title": "Test"})

        assert result == {"ok": True, "id": "e-1"}
        mock_urlopen.assert_called_once()

    @patch("engine.nexus.nexus_seeder.urllib.request.urlopen")
    def test_post_returns_none_on_failure(self, mock_urlopen):
        """_post returns None when the request fails."""
        from engine.nexus.nexus_seeder import _post

        mock_urlopen.side_effect = Exception("Connection refused")

        result = _post("/api/entries", {"title": "Test"})

        assert result is None

    @patch("engine.nexus.nexus_seeder.urllib.request.urlopen")
    def test_get_returns_parsed_json(self, mock_urlopen):
        """_get returns parsed JSON from a GET request."""
        from engine.nexus.nexus_seeder import _get

        mock_urlopen.return_value = _mock_urlopen_response({"ok": True, "data": []})

        result = _get("/api/qa")

        assert result == {"ok": True, "data": []}

    @patch("engine.nexus.nexus_seeder.urllib.request.urlopen")
    def test_get_returns_none_on_failure(self, mock_urlopen):
        """_get returns None when the request fails."""
        from engine.nexus.nexus_seeder import _get

        mock_urlopen.side_effect = Exception("Timeout")

        result = _get("/api/qa")

        assert result is None

    @patch("engine.nexus.nexus_seeder._get")
    def test_search_returns_matching_entries(self, mock_get):
        """_search extracts data list from search results."""
        from engine.nexus.nexus_seeder import _search

        mock_get.return_value = {
            "ok": True,
            "data": [{"title": "Architecture", "id": "1"}],
        }

        results = _search("Architecture")

        assert len(results) == 1
        assert results[0]["title"] == "Architecture"

    @patch("engine.nexus.nexus_seeder._get")
    def test_search_returns_empty_on_api_error(self, mock_get):
        """_search returns empty list when API returns non-ok."""
        from engine.nexus.nexus_seeder import _search

        mock_get.return_value = None

        assert _search("anything") == []

    @patch("engine.nexus.nexus_seeder._search")
    def test_entry_exists_true_when_title_matches(self, mock_search):
        """_entry_exists returns True when a search result title matches exactly."""
        from engine.nexus.nexus_seeder import _entry_exists

        mock_search.return_value = [{"title": "CosySim Architecture Overview"}]

        assert _entry_exists("CosySim Architecture Overview") is True

    @patch("engine.nexus.nexus_seeder._search")
    def test_entry_exists_case_insensitive(self, mock_search):
        """_entry_exists performs case-insensitive comparison."""
        from engine.nexus.nexus_seeder import _entry_exists

        mock_search.return_value = [{"title": "cosysim architecture overview"}]

        assert _entry_exists("CosySim Architecture Overview") is True

    @patch("engine.nexus.nexus_seeder._search")
    def test_entry_exists_false_when_no_match(self, mock_search):
        """_entry_exists returns False when no title matches."""
        from engine.nexus.nexus_seeder import _entry_exists

        mock_search.return_value = [{"title": "Something Else"}]

        assert _entry_exists("Nonexistent Entry") is False

    @patch("engine.nexus.nexus_seeder._get")
    def test_qa_exists_true_when_question_matches(self, mock_get):
        """_qa_exists returns True when a Q&A question matches exactly."""
        from engine.nexus.nexus_seeder import _qa_exists

        mock_get.return_value = {
            "ok": True,
            "data": [{"question": "What is CosySim?"}],
        }

        assert _qa_exists("What is CosySim?") is True

    @patch("engine.nexus.nexus_seeder._get")
    def test_qa_exists_false_when_no_match(self, mock_get):
        """_qa_exists returns False when no Q&A question matches."""
        from engine.nexus.nexus_seeder import _qa_exists

        mock_get.return_value = {
            "ok": True,
            "data": [{"question": "How does X work?"}],
        }

        assert _qa_exists("What is CosySim?") is False

    @patch("engine.nexus.nexus_seeder._get")
    def test_qa_exists_false_when_api_down(self, mock_get):
        """_qa_exists returns False when API returns None."""
        from engine.nexus.nexus_seeder import _qa_exists

        mock_get.return_value = None

        assert _qa_exists("Any question") is False


class TestAddEntry:
    """Tests for the add_entry function."""

    @patch("engine.nexus.nexus_seeder._post")
    @patch("engine.nexus.nexus_seeder._entry_exists", return_value=False)
    def test_add_entry_creates_new_entry(self, mock_exists, mock_post):
        """add_entry posts to /api/entries when entry doesn't exist."""
        from engine.nexus.nexus_seeder import add_entry

        mock_post.return_value = {"ok": True}

        result = add_entry("Test Title", "Test Content", "note", "dev", ["tag1"])

        assert result is True
        mock_post.assert_called_once()
        payload = mock_post.call_args[0][1]
        assert payload["title"] == "Test Title"
        assert payload["tags"] == ["tag1"]

    @patch("engine.nexus.nexus_seeder._post")
    @patch("engine.nexus.nexus_seeder._entry_exists", return_value=True)
    def test_add_entry_skips_existing(self, mock_exists, mock_post):
        """add_entry returns False and skips POST when entry already exists."""
        from engine.nexus.nexus_seeder import add_entry

        result = add_entry("Existing Title", "Content")

        assert result is False
        mock_post.assert_not_called()

    @patch("engine.nexus.nexus_seeder._post")
    @patch("engine.nexus.nexus_seeder._entry_exists", return_value=False)
    def test_add_entry_returns_false_on_api_failure(self, mock_exists, mock_post):
        """add_entry returns False when POST fails."""
        from engine.nexus.nexus_seeder import add_entry

        mock_post.return_value = None

        result = add_entry("Title", "Content")

        assert result is False


class TestAddQA:
    """Tests for the add_qa function."""

    @patch("engine.nexus.nexus_seeder._post")
    @patch("engine.nexus.nexus_seeder._qa_exists", return_value=False)
    def test_add_qa_creates_new_pair(self, mock_exists, mock_post):
        """add_qa posts to /api/qa when the question doesn't exist."""
        from engine.nexus.nexus_seeder import add_qa

        mock_post.return_value = {"ok": True}

        result = add_qa("How?", "Like this.", "dev", ["tag"])

        assert result is True
        mock_post.assert_called_once()
        payload = mock_post.call_args[0][1]
        assert payload["question"] == "How?"
        assert payload["answer"] == "Like this."

    @patch("engine.nexus.nexus_seeder._post")
    @patch("engine.nexus.nexus_seeder._qa_exists", return_value=True)
    def test_add_qa_skips_existing(self, mock_exists, mock_post):
        """add_qa returns False and skips POST when question already exists."""
        from engine.nexus.nexus_seeder import add_qa

        result = add_qa("Existing Q?", "Answer")

        assert result is False
        mock_post.assert_not_called()


class TestAddRule:
    """Tests for the add_rule function."""

    @patch("engine.nexus.nexus_seeder._post")
    def test_add_rule_creates_rule(self, mock_post):
        """add_rule posts to /api/rules with correct payload."""
        from engine.nexus.nexus_seeder import add_rule

        mock_post.return_value = {"ok": True}

        result = add_rule("global", "convention", "All Python files", "Use type hints", 10)

        assert result is True
        payload = mock_post.call_args[0][1]
        assert payload["scope"] == "global"
        assert payload["priority"] == 10

    @patch("engine.nexus.nexus_seeder._post")
    def test_add_rule_returns_false_on_failure(self, mock_post):
        """add_rule returns False when POST fails."""
        from engine.nexus.nexus_seeder import add_rule

        mock_post.return_value = None

        result = add_rule("global", "convention", "Test", "Test", 10)

        assert result is False


class TestSeedFunctions:
    """Tests for seed_docs, seed_qa, seed_rules, seed_prompts, seed_conventions."""

    @patch("engine.nexus.nexus_seeder.add_entry")
    def test_seed_docs_creates_entries(self, mock_add):
        """seed_docs calls add_entry for each doc entry."""
        from engine.nexus.nexus_seeder import seed_docs

        mock_add.return_value = True

        count = seed_docs()

        assert count > 0
        assert mock_add.call_count > 0
        # Every doc should be attempted
        assert count == mock_add.call_count

    @patch("engine.nexus.nexus_seeder.add_entry")
    def test_seed_docs_counts_only_created(self, mock_add):
        """seed_docs only counts entries that were actually created."""
        from engine.nexus.nexus_seeder import seed_docs

        # Alternate True/False to simulate some existing entries
        side_effects = [True, False, True, False] + [True] * 50
        mock_add.side_effect = side_effects

        count = seed_docs()

        # Count should only include True returns
        expected = sum(1 for r in side_effects[:mock_add.call_count] if r)
        assert count == expected

    @patch("engine.nexus.nexus_seeder.add_qa")
    def test_seed_qa_creates_pairs(self, mock_add):
        """seed_qa calls add_qa for each Q&A pair."""
        from engine.nexus.nexus_seeder import seed_qa

        mock_add.return_value = True

        count = seed_qa()

        assert count > 0
        assert mock_add.call_count > 0

    @patch("engine.nexus.nexus_seeder.add_qa")
    def test_seed_qa_skips_existing_pairs(self, mock_add):
        """seed_qa counts zero when all pairs already exist."""
        from engine.nexus.nexus_seeder import seed_qa

        mock_add.return_value = False

        count = seed_qa()

        assert count == 0

    @patch("engine.nexus.nexus_seeder.add_rule")
    def test_seed_rules_creates_rules(self, mock_add):
        """seed_rules calls add_rule for each governance rule."""
        from engine.nexus.nexus_seeder import seed_rules

        mock_add.return_value = True

        count = seed_rules()

        assert count > 0
        assert mock_add.call_count >= 10  # We know there are 16 rules

    @patch("engine.nexus.nexus_seeder.add_entry")
    def test_seed_prompts_creates_entries(self, mock_add):
        """seed_prompts calls add_entry for each prompt entry."""
        from engine.nexus.nexus_seeder import seed_prompts

        mock_add.return_value = True

        count = seed_prompts()

        assert count > 0

    @patch("engine.nexus.nexus_seeder.add_entry")
    def test_seed_conventions_creates_entries(self, mock_add):
        """seed_conventions calls add_entry for each convention entry."""
        from engine.nexus.nexus_seeder import seed_conventions

        mock_add.return_value = True

        count = seed_conventions()

        assert count > 0

    @patch("engine.nexus.nexus_seeder.seed_conventions")
    @patch("engine.nexus.nexus_seeder.seed_prompts")
    @patch("engine.nexus.nexus_seeder.seed_rules")
    @patch("engine.nexus.nexus_seeder.seed_qa")
    @patch("engine.nexus.nexus_seeder.seed_docs")
    def test_seed_all_calls_all_seeders(self, m_docs, m_qa, m_rules, m_prompts, m_conv):
        """seed_all invokes every individual seeder and aggregates counts."""
        from engine.nexus.nexus_seeder import seed_all

        m_docs.return_value = 5
        m_qa.return_value = 3
        m_rules.return_value = 2
        m_prompts.return_value = 4
        m_conv.return_value = 1

        result = seed_all()

        assert result == {"docs": 5, "qa": 3, "rules": 2, "prompts": 4, "conventions": 1}
        m_docs.assert_called_once()
        m_qa.assert_called_once()
        m_rules.assert_called_once()
        m_prompts.assert_called_once()
        m_conv.assert_called_once()


class TestSeederCLI:
    """Tests for the seeder main() CLI entry point."""

    @patch("engine.nexus.nexus_seeder.seed_docs")
    def test_main_dispatches_docs(self, mock_seed):
        """main('docs') dispatches to seed_docs."""
        from engine.nexus.nexus_seeder import main

        mock_seed.return_value = 5

        with patch("sys.argv", ["nexus_seeder", "docs"]):
            main()

        mock_seed.assert_called_once()

    @patch("engine.nexus.nexus_seeder.seed_qa")
    def test_main_dispatches_qa(self, mock_seed):
        """main('qa') dispatches to seed_qa."""
        from engine.nexus.nexus_seeder import main

        mock_seed.return_value = 3

        with patch("sys.argv", ["nexus_seeder", "qa"]):
            main()

        mock_seed.assert_called_once()

    @patch("engine.nexus.nexus_seeder.seed_all")
    def test_main_defaults_to_all(self, mock_seed):
        """main() with no args defaults to seed_all."""
        from engine.nexus.nexus_seeder import main

        mock_seed.return_value = {"docs": 1, "qa": 1, "rules": 1, "prompts": 1, "conventions": 1}

        with patch("sys.argv", ["nexus_seeder"]):
            main()

        mock_seed.assert_called_once()

    def test_main_exits_on_unknown_target(self):
        """main() with unknown target prints error and exits."""
        from engine.nexus.nexus_seeder import main

        with patch("sys.argv", ["nexus_seeder", "unknown"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    @patch("engine.nexus.nexus_seeder.seed_rules")
    def test_main_dispatches_rules(self, mock_seed):
        """main('rules') dispatches to seed_rules."""
        from engine.nexus.nexus_seeder import main

        mock_seed.return_value = 2

        with patch("sys.argv", ["nexus_seeder", "rules"]):
            main()

        mock_seed.assert_called_once()

    @patch("engine.nexus.nexus_seeder.seed_prompts")
    def test_main_dispatches_prompts(self, mock_seed):
        """main('prompts') dispatches to seed_prompts."""
        from engine.nexus.nexus_seeder import main

        mock_seed.return_value = 4

        with patch("sys.argv", ["nexus_seeder", "prompts"]):
            main()

        mock_seed.assert_called_once()

    @patch("engine.nexus.nexus_seeder.seed_conventions")
    def test_main_dispatches_conventions(self, mock_seed):
        """main('conventions') dispatches to seed_conventions."""
        from engine.nexus.nexus_seeder import main

        mock_seed.return_value = 1

        with patch("sys.argv", ["nexus_seeder", "conventions"]):
            main()

        mock_seed.assert_called_once()


class TestSeederDataIntegrity:
    """Verify the static seed data arrays contain expected structure."""

    def test_doc_entries_are_well_formed(self):
        """Each doc entry should have 5 elements: title, content, type, category, tags."""
        from engine.nexus.nexus_seeder import _get_doc_entries

        entries = _get_doc_entries()

        assert len(entries) > 0
        for entry in entries:
            assert len(entry) == 5, f"Entry should be 5-tuple: {entry[0]}"
            title, content, ct, cat, tags = entry
            assert isinstance(title, str) and len(title) > 0
            assert isinstance(content, str) and len(content) > 10
            assert isinstance(tags, list)

    def test_qa_pairs_are_well_formed(self):
        """Each Q&A pair should have 4 elements: question, answer, category, tags."""
        from engine.nexus.nexus_seeder import _get_qa_pairs

        pairs = _get_qa_pairs()

        assert len(pairs) > 0
        for pair in pairs:
            assert len(pair) == 4, f"Pair should be 4-tuple: {pair[0]}"
            question, answer, category, tags = pair
            assert question.endswith("?"), f"Question should end with '?': {question}"
            assert isinstance(answer, str) and len(answer) > 10


# ═══════════════════════════════════════════════════════════════════════
# BRIDGE — CLI commands
# ═══════════════════════════════════════════════════════════════════════

class TestBridgeSearch:
    """Tests for cmd_search."""

    @patch("engine.nexus.bridge.get_nexus_client")
    def test_search_calls_client_with_query(self, mock_get_client, capsys):
        """cmd_search searches via NexusClient and outputs JSON."""
        from engine.nexus.bridge import cmd_search

        mock_client = MagicMock()
        mock_client.search.return_value = [{"title": "Result A", "content": "data"}]
        mock_get_client.return_value = mock_client

        args = Namespace(query="interceptor", limit=10)
        cmd_search(args)

        mock_client.search.assert_called_once_with("interceptor", limit=10)
        output = json.loads(capsys.readouterr().out)
        assert output["count"] == 1
        assert output["query"] == "interceptor"

    @patch("engine.nexus.bridge.get_nexus_client")
    def test_search_with_custom_limit(self, mock_get_client, capsys):
        """cmd_search respects custom limit parameter."""
        from engine.nexus.bridge import cmd_search

        mock_client = MagicMock()
        mock_client.search.return_value = []
        mock_get_client.return_value = mock_client

        args = Namespace(query="test", limit=5)
        cmd_search(args)

        mock_client.search.assert_called_once_with("test", limit=5)
        output = json.loads(capsys.readouterr().out)
        assert output["count"] == 0


class TestBridgeAsk:
    """Tests for cmd_ask."""

    @patch("engine.nexus.bridge.get_nexus_client")
    def test_ask_calls_client_with_question(self, mock_get_client, capsys):
        """cmd_ask queries NexusClient and outputs JSON answer."""
        from engine.nexus.bridge import cmd_ask

        mock_client = MagicMock()
        mock_client.ask.return_value = {"answer": "42", "source": "cache"}
        mock_get_client.return_value = mock_client

        args = Namespace(question="How does X work?", depth="auto")
        cmd_ask(args)

        mock_client.ask.assert_called_once_with("How does X work?", depth="auto")
        output = json.loads(capsys.readouterr().out)
        assert output["answer"] == "42"


class TestBridgeStore:
    """Tests for cmd_store."""

    @patch("engine.nexus.bridge.get_nexus_client")
    def test_store_calls_add_entry(self, mock_get_client, capsys):
        """cmd_store stores an entry via NexusClient."""
        from engine.nexus.bridge import cmd_store

        mock_client = MagicMock()
        mock_client.add_entry.return_value = "entry-123"
        mock_get_client.return_value = mock_client

        args = Namespace(
            title="My Note", content="Some content",
            type="note", category="dev", tags="a,b",
        )
        cmd_store(args)

        mock_client.add_entry.assert_called_once_with(
            title="My Note", content="Some content",
            content_type="note", category="dev", tags=["a", "b"],
        )
        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "stored"

    @patch("engine.nexus.bridge.get_nexus_client")
    def test_store_with_empty_tags(self, mock_get_client, capsys):
        """cmd_store passes empty list when tags is empty string."""
        from engine.nexus.bridge import cmd_store

        mock_client = MagicMock()
        mock_client.add_entry.return_value = "entry-456"
        mock_get_client.return_value = mock_client

        args = Namespace(
            title="Title", content="Content",
            type="note", category="dev", tags="",
        )
        cmd_store(args)

        mock_client.add_entry.assert_called_once_with(
            title="Title", content="Content",
            content_type="note", category="dev", tags=[],
        )


class TestBridgeQA:
    """Tests for cmd_qa."""

    @patch("engine.nexus.bridge.get_nexus_client")
    def test_qa_stores_pair(self, mock_get_client, capsys):
        """cmd_qa stores a Q&A pair via NexusClient."""
        from engine.nexus.bridge import cmd_qa

        mock_client = MagicMock()
        mock_client.add_qa.return_value = "qa-789"
        mock_get_client.return_value = mock_client

        args = Namespace(question="Why?", answer="Because.", category="dev")
        cmd_qa(args)

        mock_client.add_qa.assert_called_once_with(
            question="Why?", answer="Because.", category="dev",
        )
        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "stored"


class TestBridgeRules:
    """Tests for cmd_rules."""

    @patch("engine.nexus.bridge.get_nexus_client")
    def test_rules_fetches_by_scope(self, mock_get_client, capsys):
        """cmd_rules queries governance rules by scope."""
        from engine.nexus.bridge import cmd_rules

        mock_client = MagicMock()
        mock_client.get_rules.return_value = [
            {"name": "r1", "scope": "coding"},
            {"name": "r2", "scope": "coding"},
        ]
        mock_get_client.return_value = mock_client

        args = Namespace(scope="coding")
        cmd_rules(args)

        mock_client.get_rules.assert_called_once_with(scope="coding")
        output = json.loads(capsys.readouterr().out)
        assert output["count"] == 2

    @patch("engine.nexus.bridge.get_nexus_client")
    def test_rules_with_no_scope(self, mock_get_client, capsys):
        """cmd_rules passes empty string when scope is None."""
        from engine.nexus.bridge import cmd_rules

        mock_client = MagicMock()
        mock_client.get_rules.return_value = []
        mock_get_client.return_value = mock_client

        args = Namespace(scope=None)
        cmd_rules(args)

        mock_client.get_rules.assert_called_once_with(scope="")


class TestBridgeHealth:
    """Tests for cmd_health."""

    @patch("requests.get")
    def test_health_aggregates_stats(self, mock_get, capsys):
        """cmd_health fetches entries, qa, rules and aggregates counts."""
        from engine.nexus.bridge import cmd_health

        # Mock entries response
        entries_resp = MagicMock()
        entries_resp.ok = True
        entries_resp.json.return_value = {
            "data": [
                {"content_type": "note", "category": "dev"},
                {"content_type": "note", "category": "arch"},
                {"content_type": "code", "category": "dev"},
            ]
        }

        # Mock qa response
        qa_resp = MagicMock()
        qa_resp.ok = True
        qa_resp.json.return_value = {"data": [{"question": "Q1"}, {"question": "Q2"}]}

        # Mock rules response
        rules_resp = MagicMock()
        rules_resp.ok = True
        rules_resp.json.return_value = {"data": [{"name": "rule1"}]}

        mock_get.side_effect = [entries_resp, qa_resp, rules_resp]

        args = Namespace()
        cmd_health(args)

        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "healthy"
        assert output["entries"] == 3
        assert output["qa_pairs"] == 2
        assert output["rules"] == 1
        assert output["by_type"]["note"] == 2
        assert output["by_type"]["code"] == 1

    @patch("requests.get")
    def test_health_reports_error_when_nexus_down(self, mock_get, capsys):
        """cmd_health outputs error status when Nexus is unreachable."""
        from engine.nexus.bridge import cmd_health

        mock_get.side_effect = Exception("Connection refused")

        args = Namespace()
        cmd_health(args)

        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "error"
        assert "Connection refused" in output["error"]


class TestBridgeSeed:
    """Tests for cmd_seed."""

    def test_seed_dispatches_to_seeder(self, capsys):
        """cmd_seed imports NexusSeeder and calls seed()."""
        from engine.nexus.bridge import cmd_seed

        # NexusSeeder is imported inside cmd_seed — mock the import target
        mock_seeder_cls = MagicMock()
        mock_seeder_instance = MagicMock()
        mock_seeder_instance.seed.return_value = {"docs": 5, "qa": 3}
        mock_seeder_cls.return_value = mock_seeder_instance

        with patch.dict("sys.modules", {
            "engine.nexus.nexus_seeder": MagicMock(NexusSeeder=mock_seeder_cls)
        }):
            args = Namespace(source="all")
            cmd_seed(args)

        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "ok"
        assert output["source"] == "all"


class TestBridgeMaintainDedup:
    """Tests for cmd_maintain dedup action."""

    @patch("requests.delete")
    @patch("requests.get")
    def test_dedup_finds_and_removes_duplicates(self, mock_get, mock_delete, capsys):
        """cmd_maintain('dedup') identifies duplicate titles and deletes them."""
        from engine.nexus.bridge import cmd_maintain

        # Mock GET entries — two entries with same title
        entries_resp = MagicMock()
        entries_resp.ok = True
        entries_resp.json.return_value = {
            "data": [
                {"id": "e-1", "title": "Architecture Overview"},
                {"id": "e-2", "title": "Architecture Overview"},  # duplicate
                {"id": "e-3", "title": "Something Else"},
            ]
        }

        mock_get.return_value = entries_resp
        mock_delete.return_value = MagicMock(ok=True)

        args = Namespace(action="dedup")
        cmd_maintain(args)

        output = json.loads(capsys.readouterr().out)
        assert output["found"] == 1
        assert output["removed"] == 1
        assert output["duplicates"][0]["id"] == "e-2"

    @patch("requests.delete")
    @patch("requests.get")
    def test_dedup_case_insensitive_matching(self, mock_get, mock_delete, capsys):
        """Dedup normalizes titles to lowercase for comparison."""
        from engine.nexus.bridge import cmd_maintain

        entries_resp = MagicMock()
        entries_resp.ok = True
        entries_resp.json.return_value = {
            "data": [
                {"id": "e-1", "title": "My Title"},
                {"id": "e-2", "title": "  my title  "},  # same after strip+lower
            ]
        }

        mock_get.return_value = entries_resp
        mock_delete.return_value = MagicMock(ok=True)

        args = Namespace(action="dedup")
        cmd_maintain(args)

        output = json.loads(capsys.readouterr().out)
        assert output["found"] == 1

    @patch("requests.get")
    def test_dedup_no_duplicates(self, mock_get, capsys):
        """Dedup with no duplicates reports zero found/removed."""
        from engine.nexus.bridge import cmd_maintain

        entries_resp = MagicMock()
        entries_resp.ok = True
        entries_resp.json.return_value = {
            "data": [
                {"id": "e-1", "title": "Unique A"},
                {"id": "e-2", "title": "Unique B"},
            ]
        }

        mock_get.return_value = entries_resp

        args = Namespace(action="dedup")
        cmd_maintain(args)

        output = json.loads(capsys.readouterr().out)
        assert output["found"] == 0
        assert output["removed"] == 0

    @patch("requests.delete")
    @patch("requests.get")
    def test_dedup_handles_delete_failure(self, mock_get, mock_delete, capsys):
        """Dedup counts only successfully deleted entries."""
        from engine.nexus.bridge import cmd_maintain

        entries_resp = MagicMock()
        entries_resp.ok = True
        entries_resp.json.return_value = {
            "data": [
                {"id": "e-1", "title": "Dup"},
                {"id": "e-2", "title": "Dup"},
            ]
        }

        mock_get.return_value = entries_resp
        mock_delete.return_value = MagicMock(ok=False)  # delete fails

        args = Namespace(action="dedup")
        cmd_maintain(args)

        output = json.loads(capsys.readouterr().out)
        assert output["found"] == 1
        assert output["removed"] == 0


class TestBridgeMaintainCleanup:
    """Tests for cmd_maintain cleanup action."""

    @patch("requests.delete")
    @patch("requests.get")
    def test_cleanup_removes_low_quality_entries(self, mock_get, mock_delete, capsys):
        """cmd_maintain('cleanup') removes entries with content < 10 chars."""
        from engine.nexus.bridge import cmd_maintain

        entries_resp = MagicMock()
        entries_resp.ok = True
        entries_resp.json.return_value = {
            "data": [
                {"id": "e-1", "content": "short"},      # < 10 chars → low quality
                {"id": "e-2", "content": "A" * 100},     # >= 10 chars → ok
                {"id": "e-3", "content": "tiny"},         # < 10 chars → low quality
            ]
        }

        mock_get.return_value = entries_resp
        mock_delete.return_value = MagicMock(ok=True)

        args = Namespace(action="cleanup")
        cmd_maintain(args)

        output = json.loads(capsys.readouterr().out)
        assert output["low_quality"] == 2
        assert output["removed"] == 2
        assert mock_delete.call_count == 2

    @patch("requests.get")
    def test_cleanup_no_low_quality(self, mock_get, capsys):
        """Cleanup with all good entries reports zero."""
        from engine.nexus.bridge import cmd_maintain

        entries_resp = MagicMock()
        entries_resp.ok = True
        entries_resp.json.return_value = {
            "data": [{"id": "e-1", "content": "A" * 50}]
        }

        mock_get.return_value = entries_resp

        args = Namespace(action="cleanup")
        cmd_maintain(args)

        output = json.loads(capsys.readouterr().out)
        assert output["low_quality"] == 0
        assert output["removed"] == 0


class TestBridgeMaintainHealth:
    """Tests for cmd_maintain('health') which delegates to cmd_health."""

    @patch("engine.nexus.bridge.cmd_health")
    def test_maintain_health_delegates(self, mock_health):
        """cmd_maintain('health') delegates to cmd_health."""
        from engine.nexus.bridge import cmd_maintain

        args = Namespace(action="health")
        cmd_maintain(args)

        mock_health.assert_called_once_with(args)


class TestBridgeMaintainUnknown:
    """Tests for cmd_maintain with unknown action."""

    def test_maintain_unknown_action_outputs_error(self, capsys):
        """cmd_maintain with unknown action outputs error JSON."""
        from engine.nexus.bridge import cmd_maintain

        args = Namespace(action="foobar")
        cmd_maintain(args)

        output = json.loads(capsys.readouterr().out)
        assert "error" in output
        assert "foobar" in output["error"]


class TestBridgeCLI:
    """Tests for the bridge main() argparse entry point."""

    @patch("engine.nexus.bridge.cmd_search")
    def test_cli_search_command(self, mock_cmd):
        """main() routes 'search' to cmd_search."""
        from engine.nexus.bridge import main

        with patch("sys.argv", ["bridge", "search", "pipeline"]):
            main()

        mock_cmd.assert_called_once()
        args = mock_cmd.call_args[0][0]
        assert args.query == "pipeline"
        assert args.limit == 10  # default

    @patch("engine.nexus.bridge.cmd_ask")
    def test_cli_ask_command(self, mock_cmd):
        """main() routes 'ask' to cmd_ask."""
        from engine.nexus.bridge import main

        with patch("sys.argv", ["bridge", "ask", "How does it work?"]):
            main()

        mock_cmd.assert_called_once()
        args = mock_cmd.call_args[0][0]
        assert args.question == "How does it work?"
        assert args.depth == "auto"  # default

    @patch("engine.nexus.bridge.cmd_store")
    def test_cli_store_command(self, mock_cmd):
        """main() routes 'store' to cmd_store."""
        from engine.nexus.bridge import main

        with patch("sys.argv", ["bridge", "store", "Title", "Content", "--type", "decision"]):
            main()

        mock_cmd.assert_called_once()
        args = mock_cmd.call_args[0][0]
        assert args.title == "Title"
        assert args.content == "Content"
        assert args.type == "decision"

    @patch("engine.nexus.bridge.cmd_qa")
    def test_cli_qa_command(self, mock_cmd):
        """main() routes 'qa' to cmd_qa."""
        from engine.nexus.bridge import main

        with patch("sys.argv", ["bridge", "qa", "Q?", "A."]):
            main()

        mock_cmd.assert_called_once()
        args = mock_cmd.call_args[0][0]
        assert args.question == "Q?"
        assert args.answer == "A."

    @patch("engine.nexus.bridge.cmd_rules")
    def test_cli_rules_command(self, mock_cmd):
        """main() routes 'rules' to cmd_rules."""
        from engine.nexus.bridge import main

        with patch("sys.argv", ["bridge", "rules", "coding"]):
            main()

        mock_cmd.assert_called_once()

    @patch("engine.nexus.bridge.cmd_health")
    def test_cli_health_command(self, mock_cmd):
        """main() routes 'health' to cmd_health."""
        from engine.nexus.bridge import main

        with patch("sys.argv", ["bridge", "health"]):
            main()

        mock_cmd.assert_called_once()

    @patch("engine.nexus.bridge.cmd_seed")
    def test_cli_seed_command_defaults_all(self, mock_cmd):
        """main() routes 'seed' to cmd_seed with default 'all'."""
        from engine.nexus.bridge import main

        with patch("sys.argv", ["bridge", "seed"]):
            main()

        mock_cmd.assert_called_once()
        args = mock_cmd.call_args[0][0]
        assert args.source == "all"

    @patch("engine.nexus.bridge.cmd_maintain")
    def test_cli_maintain_command(self, mock_cmd):
        """main() routes 'maintain' to cmd_maintain."""
        from engine.nexus.bridge import main

        with patch("sys.argv", ["bridge", "maintain", "dedup"]):
            main()

        mock_cmd.assert_called_once()
        args = mock_cmd.call_args[0][0]
        assert args.action == "dedup"

    def test_cli_no_command_exits(self):
        """main() with no subcommand exits with error."""
        from engine.nexus.bridge import main

        with patch("sys.argv", ["bridge"]):
            with pytest.raises(SystemExit):
                main()

    def test_cli_exception_outputs_error_json(self, capsys):
        """main() wraps exceptions in JSON error output."""
        from engine.nexus.bridge import main

        with patch("sys.argv", ["bridge", "search", "test"]):
            with patch("engine.nexus.bridge.cmd_search", side_effect=RuntimeError("boom")):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1

        output = json.loads(capsys.readouterr().out)
        assert "error" in output
        assert "boom" in output["error"]


# ═══════════════════════════════════════════════════════════════════════
# MCP TOOL WRAPPERS — seed_nexus, nexus_maintain
# ═══════════════════════════════════════════════════════════════════════


def _call_mcp(tool_or_fn, *args, **kwargs):
    """Call an MCP tool, unwrapping FunctionTool wrapper if needed."""
    fn = getattr(tool_or_fn, "fn", tool_or_fn)
    return fn(*args, **kwargs)


class TestMCPSeedNexus:
    """Tests for the seed_nexus MCP tool in cosysim_server.py."""

    def test_seed_nexus_all(self):
        """seed_nexus('all') calls seeder and returns JSON result."""
        from engine.mcp.cosysim_server import seed_nexus

        mock_seeder_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.seed.return_value = {"docs": 10, "qa": 5}
        mock_seeder_cls.return_value = mock_instance

        # Mock the import that happens inside seed_nexus
        fake_module = MagicMock()
        fake_module.NexusSeeder = mock_seeder_cls
        with patch.dict("sys.modules", {"engine.nexus.nexus_seeder": fake_module}):
            result = json.loads(_call_mcp(seed_nexus, "all"))

        assert result["status"] == "ok"
        assert result["source"] == "all"
        assert result["created"] == {"docs": 10, "qa": 5}

    def test_seed_nexus_invalid_source(self):
        """seed_nexus with invalid source returns error JSON."""
        from engine.mcp.cosysim_server import seed_nexus

        mock_seeder_cls = MagicMock()
        mock_instance = MagicMock()
        mock_seeder_cls.return_value = mock_instance

        fake_module = MagicMock()
        fake_module.NexusSeeder = mock_seeder_cls
        with patch.dict("sys.modules", {"engine.nexus.nexus_seeder": fake_module}):
            result = json.loads(_call_mcp(seed_nexus, "invalid_source"))

        assert "error" in result

    def test_seed_nexus_handles_exception(self):
        """seed_nexus returns error JSON when seeder raises."""
        from engine.mcp.cosysim_server import seed_nexus

        mock_seeder_cls = MagicMock()
        mock_seeder_cls.side_effect = RuntimeError("Nexus down")

        fake_module = MagicMock()
        fake_module.NexusSeeder = mock_seeder_cls
        with patch.dict("sys.modules", {"engine.nexus.nexus_seeder": fake_module}):
            result = json.loads(_call_mcp(seed_nexus, "all"))

        assert "error" in result
        assert "Nexus down" in result["error"]


class TestMCPNexusMaintain:
    """Tests for the nexus_maintain MCP tool in cosysim_server.py."""

    @patch("requests.get")
    @patch("engine.mcp.cosysim_server._get_nexus")
    def test_maintain_health_returns_stats(self, mock_get_nexus, mock_get):
        """nexus_maintain('health') returns entry/qa/rule counts."""
        from engine.mcp.cosysim_server import nexus_maintain

        mock_nx = MagicMock()
        mock_get_nexus.return_value = mock_nx

        entries_resp = MagicMock()
        entries_resp.ok = True
        entries_resp.json.return_value = {
            "data": [
                {"content_type": "note", "category": "dev", "content": "x" * 30},
                {"content_type": "code", "category": "arch", "content": "y" * 5},
            ]
        }

        qa_resp = MagicMock()
        qa_resp.ok = True
        qa_resp.json.return_value = {"data": [{"q": "Q1"}]}

        rules_resp = MagicMock()
        rules_resp.ok = True
        rules_resp.json.return_value = {"data": []}

        mock_get.side_effect = [entries_resp, qa_resp, rules_resp]

        result = json.loads(_call_mcp(nexus_maintain, "health"))

        assert result["status"] == "ok"
        assert result["entries"] == 2
        assert result["qa_pairs"] == 1
        assert result["rules"] == 0
        assert result["low_quality"] == 1  # "y" * 5 < 20 chars

    @patch("requests.delete")
    @patch("requests.get")
    @patch("engine.mcp.cosysim_server._get_nexus")
    def test_maintain_dedup_removes_duplicates(self, mock_get_nexus, mock_get, mock_delete):
        """nexus_maintain('dedup') finds duplicate titles and deletes them."""
        from engine.mcp.cosysim_server import nexus_maintain

        mock_nx = MagicMock()
        mock_get_nexus.return_value = mock_nx

        entries_resp = MagicMock()
        entries_resp.ok = True
        entries_resp.json.return_value = {
            "data": [
                {"id": "1", "title": "Test"},
                {"id": "2", "title": "Test"},  # dup
                {"id": "3", "title": "Unique"},
            ]
        }

        mock_get.return_value = entries_resp
        mock_delete.return_value = MagicMock(ok=True)

        result = json.loads(_call_mcp(nexus_maintain, "dedup"))

        assert result["status"] == "ok"
        assert result["found"] == 1
        assert result["removed"] == 1

    @patch("requests.delete")
    @patch("requests.get")
    @patch("engine.mcp.cosysim_server._get_nexus")
    def test_maintain_cleanup_removes_short_content(self, mock_get_nexus, mock_get, mock_delete):
        """nexus_maintain('cleanup') removes entries with content < 10 chars."""
        from engine.mcp.cosysim_server import nexus_maintain

        mock_nx = MagicMock()
        mock_get_nexus.return_value = mock_nx

        entries_resp = MagicMock()
        entries_resp.ok = True
        entries_resp.json.return_value = {
            "data": [
                {"id": "1", "content": "tiny"},
                {"id": "2", "content": "A" * 100},
            ]
        }

        mock_get.return_value = entries_resp
        mock_delete.return_value = MagicMock(ok=True)

        result = json.loads(_call_mcp(nexus_maintain, "cleanup"))

        assert result["status"] == "ok"
        assert result["low_quality_found"] == 1
        assert result["removed"] == 1

    @patch("requests.post")
    @patch("engine.mcp.cosysim_server._get_nexus")
    def test_maintain_reindex_posts_to_api(self, mock_get_nexus, mock_post):
        """nexus_maintain('reindex') POSTs to /api/reindex."""
        from engine.mcp.cosysim_server import nexus_maintain

        mock_nx = MagicMock()
        mock_get_nexus.return_value = mock_nx

        mock_post.return_value = MagicMock(ok=True)

        result = json.loads(_call_mcp(nexus_maintain, "reindex"))

        assert result["status"] == "ok"
        assert "reindex" in result["message"].lower()

    @patch("engine.mcp.cosysim_server._get_nexus")
    def test_maintain_returns_error_when_nexus_unavailable(self, mock_get_nexus):
        """nexus_maintain returns error when Nexus client is None."""
        from engine.mcp.cosysim_server import nexus_maintain

        mock_get_nexus.return_value = None

        result = json.loads(_call_mcp(nexus_maintain, "health"))

        assert "error" in result
        assert "unavailable" in result["error"].lower()

    @patch("engine.mcp.cosysim_server._get_nexus")
    def test_maintain_unknown_action_returns_error(self, mock_get_nexus):
        """nexus_maintain with unknown action returns error JSON."""
        from engine.mcp.cosysim_server import nexus_maintain

        mock_nx = MagicMock()
        mock_get_nexus.return_value = mock_nx

        result = json.loads(_call_mcp(nexus_maintain, "nonsense"))

        assert "error" in result
        assert "nonsense" in result["error"]


# ═══════════════════════════════════════════════════════════════════════
# SEED_NEXUS.PY — Legacy seeder script
# ═══════════════════════════════════════════════════════════════════════

class TestSeedNexusLegacy:
    """Tests for the legacy seed_nexus.py module."""

    @patch("engine.nexus.seed_nexus.urllib.request.urlopen")
    def test_legacy_post_sends_request(self, mock_urlopen):
        """_post in seed_nexus.py sends correct HTTP request."""
        from engine.nexus.seed_nexus import _post

        mock_urlopen.return_value = _mock_urlopen_response({"ok": True, "id": "x"})

        result = _post("/api/entries", {"title": "Profile"})

        assert result is not None
        assert result["ok"] is True

    @patch("engine.nexus.seed_nexus.urllib.request.urlopen")
    def test_legacy_post_returns_none_on_url_error(self, mock_urlopen):
        """_post returns None on URLError."""
        import urllib.error
        from engine.nexus.seed_nexus import _post

        mock_urlopen.side_effect = urllib.error.URLError("refused")

        result = _post("/api/entries", {"title": "Test"})

        assert result is None

    @patch("engine.nexus.seed_nexus._post")
    def test_legacy_seed_profiles(self, mock_post):
        """seed_profiles posts each agent profile."""
        from engine.nexus.seed_nexus import seed_profiles, AGENT_PROFILES

        mock_post.return_value = {"ok": True}

        count = seed_profiles()

        assert count == len(AGENT_PROFILES)
        assert mock_post.call_count == len(AGENT_PROFILES)

    @patch("engine.nexus.seed_nexus._post")
    def test_legacy_seed_qa(self, mock_post):
        """seed_qa posts each Q&A pair."""
        from engine.nexus.seed_nexus import seed_qa, QA_PAIRS

        mock_post.return_value = {"ok": True}

        count = seed_qa()

        assert count == len(QA_PAIRS)

    @patch("engine.nexus.seed_nexus._post")
    def test_legacy_seed_profiles_counts_failures(self, mock_post):
        """seed_profiles only counts successful posts."""
        from engine.nexus.seed_nexus import seed_profiles

        # First two succeed, rest fail
        mock_post.side_effect = [{"ok": True}, {"ok": True}] + [None] * 10

        count = seed_profiles()

        assert count == 2
