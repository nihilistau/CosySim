"""Tests for the centralised NLM notebook factory."""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.nlm_notebook_factory import (
    EPHEMERAL_CATEGORIES,
    PERSISTENT_CATEGORIES,
    NLMNotebookFactory,
    NotebookRecord,
    _week_label,
)


@pytest.fixture()
def factory(tmp_path):
    """Create a factory with a temporary state file."""
    state_file = str(tmp_path / "state.json")
    return NLMNotebookFactory(state_file=state_file)


# ──── NotebookRecord ────


def test_notebook_record_roundtrip():
    """NotebookRecord serialises and deserialises correctly."""
    rec = NotebookRecord(
        notebook_id="abc-123",
        name="Test Notebook",
        category="news",
        created_at="2026-03-12T00:00:00+00:00",
    )
    data = rec.to_dict()
    restored = NotebookRecord.from_dict(data)
    assert restored.notebook_id == "abc-123"
    assert restored.category == "news"


# ──── Dedup Key Building ────


def test_ephemeral_key_includes_week(factory):
    """Ephemeral categories include the week label in the dedup key."""
    key = factory._build_dedup_key("News Digest", "news")
    assert key.startswith("news:News Digest:")
    assert _week_label() in key


def test_persistent_key_no_week(factory):
    """Persistent categories do NOT include the week label."""
    key = factory._build_dedup_key("System Knowledge", "bootstrap")
    assert key == "bootstrap:System Knowledge"
    assert _week_label() not in key


# ──── Get or Create ────


@patch("engine.nexus.nlm_notebook_factory.NLMNotebookFactory._create_notebook")
def test_get_or_create_new(mock_create, factory):
    """Factory creates a new notebook when none exists."""
    mock_create.return_value = "nb-new-123"
    nb_id = factory.get_or_create("Test NB", category="news")
    assert nb_id == "nb-new-123"
    assert factory._metrics.created == 1
    assert factory._metrics.reused == 0


@patch("engine.nexus.nlm_notebook_factory.NLMNotebookFactory._create_notebook")
def test_get_or_create_reuses(mock_create, factory):
    """Factory reuses an existing notebook within the same key."""
    mock_create.return_value = "nb-reused-456"
    nb1 = factory.get_or_create("Test NB", category="bootstrap")
    nb2 = factory.get_or_create("Test NB", category="bootstrap")
    assert nb1 == nb2
    assert factory._metrics.created == 1
    assert factory._metrics.reused == 1
    mock_create.assert_called_once()


@patch("engine.nexus.nlm_notebook_factory.NLMNotebookFactory._create_notebook")
def test_get_or_create_failure(mock_create, factory):
    """Factory returns None and tracks failure when creation fails."""
    mock_create.return_value = None
    nb_id = factory.get_or_create("Broken NB", category="news")
    assert nb_id is None
    assert factory._metrics.failed == 1


# ──── State Persistence ────


@patch("engine.nexus.nlm_notebook_factory.NLMNotebookFactory._create_notebook")
def test_state_persists_to_file(mock_create, factory, tmp_path):
    """State file is written after notebook creation."""
    mock_create.return_value = "nb-persisted"
    factory.get_or_create("Persistent", category="master")

    state_file = tmp_path / "state.json"
    assert state_file.exists()
    with open(state_file) as f:
        data = json.load(f)
    assert len(data["notebooks"]) == 1


# ──── Listing ────


@patch("engine.nexus.nlm_notebook_factory.NLMNotebookFactory._create_notebook")
def test_list_notebooks_filter(mock_create, factory):
    """list_notebooks filters by category."""
    mock_create.side_effect = ["nb-1", "nb-2", "nb-3"]
    factory.get_or_create("A", category="news")
    factory.get_or_create("B", category="bootstrap")
    factory.get_or_create("C", category="news")

    all_nbs = factory.list_notebooks()
    assert len(all_nbs) == 3

    news_only = factory.list_notebooks(category="news")
    assert len(news_only) == 2

    bootstrap_only = factory.list_notebooks(category="bootstrap")
    assert len(bootstrap_only) == 1


# ──── Cleanup ────


@patch("engine.nexus.nlm_notebook_factory.NLMNotebookFactory._create_notebook")
def test_cleanup_removes_old_ephemeral(mock_create, factory):
    """cleanup_stale removes old ephemeral records."""
    mock_create.return_value = "nb-old"
    factory.get_or_create("Old NB", category="news", dedup_key="old-key")

    # Manually backdate the record
    factory._state["notebooks"]["old-key"]["created_at"] = "2020-01-01T00:00:00+00:00"
    factory._save_state()

    removed = factory.cleanup_stale(max_age_days=1)
    assert removed == 1
    assert factory._metrics.cleaned == 1
    assert len(factory._state["notebooks"]) == 0


@patch("engine.nexus.nlm_notebook_factory.NLMNotebookFactory._create_notebook")
def test_cleanup_preserves_persistent(mock_create, factory):
    """cleanup_stale does NOT remove persistent category records."""
    mock_create.return_value = "nb-perm"
    factory.get_or_create("Perm NB", category="bootstrap", dedup_key="perm-key")
    factory._state["notebooks"]["perm-key"]["created_at"] = "2020-01-01T00:00:00+00:00"

    removed = factory.cleanup_stale(max_age_days=1)
    assert removed == 0
    assert len(factory._state["notebooks"]) == 1


# ──── Stats ────


@patch("engine.nexus.nlm_notebook_factory.NLMNotebookFactory._create_notebook")
def test_stats(mock_create, factory):
    """stats() returns correct counts."""
    mock_create.side_effect = ["nb-1", "nb-2"]
    factory.get_or_create("A", category="news")
    factory.get_or_create("B", category="bootstrap")

    s = factory.stats()
    assert s["total_tracked"] == 2
    assert s["by_category"]["news"] == 1
    assert s["by_category"]["bootstrap"] == 1
    assert s["metrics"]["created"] == 2


# ──── Source Tracking ────


@patch("engine.nexus.nlm_notebook_factory.NLMNotebookFactory._create_notebook")
def test_record_source_added(mock_create, factory):
    """record_source_added increments source count."""
    mock_create.return_value = "nb-src"
    factory.get_or_create("Src NB", category="bootstrap", dedup_key="src-key")
    factory.record_source_added("src-key")
    factory.record_source_added("src-key")

    rec = factory.get_notebook("src-key")
    assert rec is not None
    assert rec.source_count == 2


# ──── Week Label ────


def test_week_label_format():
    """_week_label returns a properly formatted ISO week string."""
    label = _week_label()
    assert label.startswith("20")
    assert "-W" in label
    parts = label.split("-W")
    assert len(parts) == 2
    assert int(parts[1]) >= 1


# ──── Category Definitions ────


def test_category_sets_no_overlap():
    """Ephemeral and persistent categories do not overlap."""
    assert len(EPHEMERAL_CATEGORIES & PERSISTENT_CATEGORIES) == 0
