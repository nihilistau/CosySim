"""Focused tests for Copilot rule seeding drift repair."""

from __future__ import annotations

from pathlib import Path

from engine.nexus import seed_copilot_rules as seed_mod


class _FakeSyncConfig:
    def __init__(self, *, exists: bool = False, sync_summary: dict | None = None) -> None:
        self.exists = exists
        self.sync_summary = sync_summary or {"stored": 0, "updated": 0, "skipped": 0}
        self.synced_entries: list[dict] = []
        self.sync_all_calls = 0
        self.instructions: list[dict] = []
        self.agents: list[dict] = []
        self.hooks: list[dict] = []

    def sync_all_to_nexus(self) -> dict:
        self.sync_all_calls += 1
        return dict(self.sync_summary)

    def _find_existing_entry(self, client, query: str, title: str, category: str):  # noqa: ANN001
        if self.exists:
            return {"id": "entry-1", "title": title, "category": category}
        return None

    def _sync_entry(self, client, **kwargs):  # noqa: ANN001
        self.synced_entries.append(kwargs)
        return "stored"

    def _entry_field(self, entry, field: str, default=""):  # noqa: ANN001
        if isinstance(entry, dict):
            return entry.get(field, default)
        return getattr(entry, field, default)

    def _normalized_tags(self, category: str, tags: list[str] | None = None) -> list[str]:
        return sorted({tag for tag in (tags or []) if tag})

    def list_instructions(self) -> list[dict]:
        return list(self.instructions)

    def list_agents(self) -> list[dict]:
        return list(self.agents)

    def list_hooks(self) -> list[dict]:
        return list(self.hooks)


class _FakeClient:
    def __init__(self, entries_by_category: dict[str, list[dict]] | None = None) -> None:
        self.entries_by_category = entries_by_category or {}
        self.deleted_ids: list[str] = []

    def list_entries(self, content_type: str = "", category: str = "", limit: int = 20) -> list[dict]:
        return list(self.entries_by_category.get(category, []))[:limit]

    def delete_entry(self, entry_id: str) -> bool:
        self.deleted_ids.append(entry_id)
        return True


def test_seed_source_reseeds_when_hash_matches_but_entry_is_missing(tmp_path: Path) -> None:
    """A matching local hash should not mask a deleted or drifted Nexus entry."""
    source_file = tmp_path / "guide.md"
    source_file.write_text("latest guidance", encoding="utf-8")
    source = {
        "path": source_file,
        "title": "[Copilot Rules] Guide",
        "category": "copilot-rules",
        "tags": ["copilot", "guide"],
    }
    state = {str(source_file): seed_mod._file_hash(source_file)}
    sync_config = _FakeSyncConfig(exists=False)

    status, changed = seed_mod.seed_source(
        source,
        state=state,
        client=object(),
        sync_config=sync_config,
    )

    assert status == "stored"
    assert changed is True
    assert len(sync_config.synced_entries) == 1
    assert state[str(source_file)] == seed_mod._file_hash(source_file)


def test_seed_all_aggregates_self_config_sync_with_supplemental_sources(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """The runtime self-sync should run before supplemental docs are seeded."""
    source_file = tmp_path / "README.md"
    source_file.write_text("repo bootstrap", encoding="utf-8")
    sync_config = _FakeSyncConfig(sync_summary={"stored": 2, "updated": 1, "skipped": 3})

    monkeypatch.setattr(
        seed_mod,
        "_get_sources",
        lambda: [{
            "path": source_file,
            "title": "[CosySim] README",
            "category": "copilot-rules",
            "tags": ["readme"],
        }],
    )
    monkeypatch.setattr(seed_mod, "_load_state", lambda: {})
    monkeypatch.setattr(seed_mod, "_save_state", lambda state: None)
    monkeypatch.setattr(seed_mod, "get_copilot_config", lambda: sync_config)
    monkeypatch.setattr(seed_mod, "get_nexus_client", lambda: object())
    monkeypatch.setattr(
        seed_mod,
        "dedupe_copilot_mirrors",
        lambda **kwargs: {"duplicate_targets": 0, "removed": 0, "unresolved": 0, "groups": []},
    )

    result = seed_mod.seed_all()

    assert sync_config.sync_all_calls == 1
    assert result["stored"] == 3
    assert result["updated"] == 1
    assert result["skipped"] == 3
    assert result["deduped"] == 0
    assert result["config_sync"] == {"stored": 2, "updated": 1, "skipped": 3}
    assert len(sync_config.synced_entries) == 1


def test_dedupe_copilot_mirrors_keeps_current_entry_and_deletes_duplicates(tmp_path: Path) -> None:
    """Exact-title mirror cleanup should keep the current seeded entry and remove stale copies."""
    source_file = tmp_path / "README.md"
    source_file.write_text("repo bootstrap", encoding="utf-8")
    source = {
        "path": source_file,
        "title": "[CosySim] README",
        "category": "copilot-rules",
        "tags": ["readme"],
    }
    sync_config = _FakeSyncConfig()
    client = _FakeClient({
        "copilot-rules": [
            {
                "id": "old",
                "title": "[CosySim] README",
                "category": "copilot-rules",
                "content": "old bootstrap",
                "content_type": "document",
                "tags": ["readme", "old"],
                "created_at": "2026-03-05T00:00:00+00:00",
            },
            {
                "id": "new",
                "title": "[CosySim] README",
                "category": "copilot-rules",
                "content": "repo bootstrap",
                "content_type": "document",
                "tags": ["readme"],
                "created_at": "2026-03-06T00:00:00+00:00",
            },
        ]
    })

    result = seed_mod.dedupe_copilot_mirrors(
        dry_run=False,
        targets=[source],
        client=client,
        sync_config=sync_config,
    )

    assert result["duplicate_targets"] == 1
    assert result["removed"] == 1
    assert result["unresolved"] == 0
    assert client.deleted_ids == ["old"]


def test_dedupe_copilot_mirrors_reports_unresolved_when_no_current_entry(tmp_path: Path) -> None:
    """Cleanup should not delete blindly when no entry matches the current source state."""
    source_file = tmp_path / "README.md"
    source_file.write_text("repo bootstrap", encoding="utf-8")
    source = {
        "path": source_file,
        "title": "[CosySim] README",
        "category": "copilot-rules",
        "tags": ["readme"],
    }
    sync_config = _FakeSyncConfig()
    client = _FakeClient({
        "copilot-rules": [
            {
                "id": "old-a",
                "title": "[CosySim] README",
                "category": "copilot-rules",
                "content": "old bootstrap",
                "content_type": "document",
                "tags": ["readme", "old"],
            },
            {
                "id": "old-b",
                "title": "[CosySim] README",
                "category": "copilot-rules",
                "content": "old bootstrap two",
                "content_type": "document",
                "tags": ["readme", "older"],
            },
        ]
    })

    result = seed_mod.dedupe_copilot_mirrors(
        dry_run=False,
        targets=[source],
        client=client,
        sync_config=sync_config,
    )

    assert result["duplicate_targets"] == 1
    assert result["removed"] == 0
    assert result["unresolved"] == 1
    assert client.deleted_ids == []


def test_entry_matches_source_ignores_tag_order() -> None:
    """Mirror matching should treat equivalent tag sets as identical."""
    source = {
        "path": Path(__file__),
        "title": "[Copilot Rules] CosySim Project Instructions",
        "category": "copilot-rules",
        "tags": ["copilot", "project", "instructions", "cosysim"],
        "content_type": "document",
    }
    entry = {
        "title": source["title"],
        "category": source["category"],
        "content": Path(__file__).read_text(encoding="utf-8"),
        "content_type": "document",
        "tags": ["copilot", "cosysim", "instructions", "project"],
    }

    assert seed_mod._entry_matches_source(entry, source, sync_config=_FakeSyncConfig()) is True
