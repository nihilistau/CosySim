"""Tests for the canonical CosySim system-domain registry."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from engine.system_registry import (
    build_system_inventory,
    find_domains_for_path,
    get_system_domain,
    list_system_domains,
    render_system_inventory_text,
    store_system_inventory_snapshot,
)


class TestSystemDomains:
    """Tests for system-domain definitions."""

    def test_list_system_domains_contains_expected_domains(self):
        """The registry exposes the user-defined system-first split."""
        domain_ids = [domain.id for domain in list_system_domains()]
        assert "control_plane" in domain_ids
        assert "nexus" in domain_ids
        assert "google_research" in domain_ids
        assert "scenes" in domain_ids
        assert len(domain_ids) >= 10

    def test_get_system_domain_returns_metadata(self):
        """Domain lookups return the expected architecture metadata."""
        domain = get_system_domain("google_research")
        assert "NotebookLM" in domain.description
        assert "engine/mcp/nlm_live_proxy.py" in domain.roots
        assert "nexus" in domain.depends_on

    def test_find_domains_for_path_matches_declared_roots(self):
        """Paths can be classified into one or more system domains."""
        matches = find_domains_for_path("engine/nexus/copilot_bridge.py")
        match_ids = {domain.id for domain in matches}
        assert "copilot_assistant" in match_ids
        assert "nexus" in match_ids


class TestSystemInventory:
    """Tests for inventory rendering and Nexus storage."""

    def test_build_system_inventory_contains_summary_and_domains(self):
        """Inventory includes summary counts and resolved domain targets."""
        inventory = build_system_inventory()
        assert inventory["summary"]["domain_count"] >= 10
        assert inventory["summary"]["service_count"] >= 10
        assert inventory["summary"]["scene_count"] >= 10

        control_plane = next(
            domain for domain in inventory["domains"] if domain["id"] == "control_plane"
        )
        scenes = next(domain for domain in inventory["domains"] if domain["id"] == "scenes")
        assert any(target["id"] == "system_control" for target in control_plane["service_targets"])
        assert any(target["id"] == "bedroom" for target in scenes["scene_targets"])

    def test_build_system_inventory_compact_mode_omits_catalogues(self):
        """Compact inventory keeps the split without full service/scene catalogues."""
        inventory = build_system_inventory(include_catalog=False)
        assert "services" not in inventory
        assert "scenes" not in inventory

    def test_render_system_inventory_text_mentions_core_policy(self):
        """Text rendering includes the high-level Nexus-first policy."""
        text = render_system_inventory_text(include_catalog=False)
        assert "CosySim System Inventory" in text
        assert "CONTROL PLANE" in text
        assert "Nexus-first: yes" in text

    @patch("engine.nexus.client.get_nexus_client")
    def test_store_system_inventory_snapshot_stores_document_and_qa(self, mock_get_client):
        """Storing the system inventory writes both a document and Q&A pair."""
        mock_client = MagicMock()
        mock_client.add_entry.return_value = "entry-001"
        mock_client.add_qa.return_value = "qa-001"
        mock_get_client.return_value = mock_client

        result = store_system_inventory_snapshot(title="Architecture snapshot")

        _, entry_kwargs = mock_client.add_entry.call_args
        _, qa_kwargs = mock_client.add_qa.call_args
        assert entry_kwargs["title"] == "Architecture snapshot"
        assert entry_kwargs["content_type"] == "document"
        assert entry_kwargs["category"] == "architecture"
        assert qa_kwargs["question"] == "How is CosySim currently split into systems?"
        assert result["entry_id"] == "entry-001"
        assert result["qa_id"] == "qa-001"
