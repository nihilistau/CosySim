"""Tests for engine.nexus.bootstrap_notebooks flywheel history ingress."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import patch

from engine.nexus.bootstrap_notebooks import (
    NOTEBOOK_CONFIGS,
    _build_browser_bundle_source,
    _collect_control_plane_sources,
    _collect_session_history_sources,
    _get_or_create_notebook,
    _run_control_notebook_followup,
    _source_hash,
    _nexus_search,
    bootstrap_notebook,
    run_notebook_bootstrap,
)


class _FakeResponse:
    """Minimal urllib response context manager for JSON payload tests."""

    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_nexus_search_uses_search_endpoint_and_parses_results() -> None:
    """Bootstrap search must hit /api/search and parse the results field."""
    captured: Dict[str, str] = {}

    def _capture(request: Any, timeout: int = 10) -> _FakeResponse:
        captured["url"] = request.full_url
        captured["accept"] = request.headers.get("Accept", "")
        assert timeout == 10
        return _FakeResponse({"results": [{"title": "Session abc"}]})

    with patch("urllib.request.urlopen", side_effect=_capture):
        result = _nexus_search("checkpoint fix", category="copilot-history", limit=7)

    assert result == [{"title": "Session abc"}]
    assert "/api/search?" in captured["url"]
    assert "q=checkpoint+fix" in captured["url"]
    assert "category=copilot-history" in captured["url"]
    assert "limit=7" in captured["url"]
    assert captured["accept"] == "application/json"


def test_collect_session_history_sources_uses_copilot_history_category() -> None:
    """History notebook should pull from synced copilot-history entries."""
    nexus_entries: List[Dict[str, str]] = [
        {"id": "e1", "title": "Session one", "content": "Content one"},
        {"id": "e1", "title": "Session one duplicate", "content": "Duplicate"},
        {"id": "e2", "title": "Checkpoint summary", "content": "Content two"},
    ]

    with patch(
        "engine.nexus.bootstrap_notebooks._nexus_search",
        side_effect=[nexus_entries[:2], nexus_entries[2:]],
    ) as mock_search:
        with patch(
            "engine.nexus.bootstrap_notebooks._get_recent_session_checkpoints",
            return_value="",
        ):
            sources = _collect_session_history_sources()

    assert len(sources) == 1
    assert sources[0]["title"] == "Recent Session History (from Nexus)"
    assert "Session one" in sources[0]["content"]
    assert "Checkpoint summary" in sources[0]["content"]
    assert "Session one duplicate" not in sources[0]["content"]
    assert mock_search.call_args_list == [
        (("session",), {"category": "copilot-history", "limit": 50}),
        (("checkpoint",), {"category": "copilot-history", "limit": 50}),
    ]


def test_collect_session_history_sources_includes_direct_export() -> None:
    """Direct session-store export should remain part of the history notebook."""
    with patch("engine.nexus.bootstrap_notebooks._nexus_search", return_value=[]):
        with patch(
            "engine.nexus.bootstrap_notebooks._get_recent_session_checkpoints",
            return_value="# Recent Session Checkpoints\n\n## Session: abc",
        ):
            sources = _collect_session_history_sources()

    assert len(sources) == 1
    assert sources[0]["title"] == "Session Checkpoints (direct export)"
    assert "Session: abc" in sources[0]["content"]


def test_collect_control_plane_sources_includes_template_references() -> None:
    """Control notebook sources should include hook/runtime and context templates."""
    sources = _collect_control_plane_sources()
    titles = {source["title"] for source in sources}

    assert "Copilot Context Template Reference" in titles
    assert "Copilot Hook Control Runtime" in titles
    assert "Canonical System Inventory" in titles


def test_notebook_configs_include_control_plane_notebook() -> None:
    """Bootstrap config should expose the dedicated control-plane notebook."""
    config = NOTEBOOK_CONFIGS["control"]

    assert config["name"] == "copilot-system-control"
    assert len(config["questions"]) >= 5
    assert config["seed_mode"] == "browser_bundle"


def test_get_or_create_notebook_accepts_reserved_uuid_response() -> None:
    """Reserved UUID responses from the live proxy should still materialize a notebook URL."""
    state = {"notebooks": {}}

    with patch(
        "engine.nexus.bootstrap_notebooks._nlm_post",
        return_value={
            "notebook_id": "ccf725c2-ddeb-4c9f-805c-c3668c3e4abf",
            "message": "Notebook UUID reserved. Add sources to materialise on NLM backend.",
        },
    ):
        result = _get_or_create_notebook("copilot-system-control", "desc", state)

    assert result == "https://notebooklm.google.com/notebook/ccf725c2-ddeb-4c9f-805c-c3668c3e4abf"
    assert state["notebooks"]["copilot-system-control"] == result


def test_bootstrap_notebook_replaces_changed_source_and_waits_before_distill() -> None:
    """Changed source content should refresh the notebook source and re-distill."""
    source = {"title": "Doc", "content": "new content", "type": "text"}
    state = {
        "notebooks": {"nb": "https://notebooklm.google.com/notebook/nb-1"},
        "notebooks_detail": {
            "nb": {
                "seeded_sources": ["Doc"],
                "source_hashes": {"Doc": "old-hash"},
            }
        },
    }

    with (
        patch("engine.nexus.bootstrap_notebooks._delete_matching_sources", return_value=1) as mock_delete,
        patch("engine.nexus.bootstrap_notebooks._add_text_source", return_value=True) as mock_add,
        patch("engine.nexus.bootstrap_notebooks._wait_for_notebook_sources", return_value=True) as mock_wait,
        patch("engine.nexus.bootstrap_notebooks._distill_qa", return_value=2) as mock_distill,
        patch("engine.nexus.bootstrap_notebooks.time.sleep"),
    ):
        result = bootstrap_notebook(
            name="nb",
            description="desc",
            sources=[source],
            questions=["Q1"],
            state=state,
            distill=True,
            scheduled=True,
        )

    assert result["sources_added"] == 1
    assert result["sources_deleted"] == 1
    assert result["qa_stored"] == 2
    assert result["distilled"] is True
    assert result["distill_reason"] == "sources_changed"
    assert state["notebooks_detail"]["nb"]["source_hashes"]["Doc"] == _source_hash("Doc", "new content", "text")
    mock_delete.assert_called_once_with("https://notebooklm.google.com/notebook/nb-1", "Doc")
    mock_add.assert_called_once_with("https://notebooklm.google.com/notebook/nb-1", "Doc", "new content")
    mock_wait.assert_called_once_with("https://notebooklm.google.com/notebook/nb-1")
    mock_distill.assert_called_once_with(
        "https://notebooklm.google.com/notebook/nb-1",
        ["Q1"],
        category="nlm-nb",
    )


def test_bootstrap_notebook_scheduled_distills_when_stale_without_source_changes() -> None:
    """Scheduled bootstrap should re-distill stale notebooks even when sources are unchanged."""
    source = {"title": "Doc", "content": "same content", "type": "text"}
    current_hash = _source_hash("Doc", "same content", "text")
    stale_time = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    state = {
        "notebooks": {"nb": "https://notebooklm.google.com/notebook/nb-1"},
        "notebooks_detail": {
            "nb": {
                "seeded_sources": ["Doc"],
                "source_hashes": {"Doc": current_hash},
                "last_distill_attempt_at": stale_time,
            }
        },
    }

    with (
        patch("engine.nexus.bootstrap_notebooks._add_text_source") as mock_add,
        patch("engine.nexus.bootstrap_notebooks._distill_qa", return_value=3) as mock_distill,
        patch("engine.nexus.bootstrap_notebooks.time.sleep"),
    ):
        result = bootstrap_notebook(
            name="nb",
            description="desc",
            sources=[source],
            questions=["Q1"],
            state=state,
            distill=True,
            scheduled=True,
        )

    assert result["sources_added"] == 0
    assert result["qa_stored"] == 3
    assert result["distilled"] is True
    assert result["distill_reason"] == "stale_scheduled_distill"
    mock_add.assert_not_called()
    mock_distill.assert_called_once()


def test_bootstrap_notebook_scheduled_skips_recent_distill_without_changes() -> None:
    """Scheduled bootstrap should not re-distill too soon when nothing changed."""
    source = {"title": "Doc", "content": "same content", "type": "text"}
    current_hash = _source_hash("Doc", "same content", "text")
    recent_time = datetime.now(timezone.utc).isoformat()
    state = {
        "notebooks": {"nb": "https://notebooklm.google.com/notebook/nb-1"},
        "notebooks_detail": {
            "nb": {
                "seeded_sources": ["Doc"],
                "source_hashes": {"Doc": current_hash},
                "last_distill_attempt_at": recent_time,
            }
        },
    }

    with patch("engine.nexus.bootstrap_notebooks._distill_qa") as mock_distill:
        result = bootstrap_notebook(
            name="nb",
            description="desc",
            sources=[source],
            questions=["Q1"],
            state=state,
            distill=True,
            scheduled=True,
        )

    assert result["sources_added"] == 0
    assert result["qa_stored"] == 0
    assert result["distilled"] is False
    assert result["distill_reason"] == ""
    mock_distill.assert_not_called()


def test_bootstrap_notebook_browser_bundle_seeds_and_distills_via_argus() -> None:
    """Control notebook should use browser bundle seeding and ARGUS distillation."""
    source = {"title": "Doc", "content": "browser content", "type": "text"}
    state = {"notebooks": {}}

    with (
        patch(
            "engine.nexus.bootstrap_notebooks._browser_seed_notebook_bundle",
            return_value="https://notebooklm.google.com/notebook/control-1",
        ) as mock_seed,
        patch("engine.nexus.bootstrap_notebooks._distill_qa_via_argus", return_value=2) as mock_distill,
    ):
        result = bootstrap_notebook(
            name="copilot-system-control",
            description="desc",
            sources=[source],
            questions=["Q1"],
            state=state,
            distill=True,
            seed_mode="browser_bundle",
        )

    assert result["sources_added"] == 1
    assert result["qa_stored"] == 2
    assert result["distilled"] is True
    assert result["distill_reason"] == "manual_distill"
    assert state["notebooks"]["copilot-system-control"] == "https://notebooklm.google.com/notebook/control-1"
    assert state["notebooks_detail"]["copilot-system-control"]["browser_bundle_hash"]
    mock_seed.assert_called_once_with("copilot-system-control", "desc", [source], notebook_url=None)
    mock_distill.assert_called_once_with(
        "https://notebooklm.google.com/notebook/control-1",
        ["Q1"],
        category="nlm-copilot-system-control",
    )


def test_bootstrap_notebook_browser_bundle_skips_when_bundle_hash_is_current() -> None:
    """Browser bundle mode should skip re-seeding when the bundle hash is unchanged."""
    source = {"title": "Doc", "content": "same content", "type": "text"}
    bundle_title, bundle_content = _build_browser_bundle_source("copilot-system-control", "desc", [source])
    bundle_hash = _source_hash(bundle_title, bundle_content, "text")
    recent_time = datetime.now(timezone.utc).isoformat()
    state = {
        "notebooks": {"copilot-system-control": "https://notebooklm.google.com/notebook/control-1"},
        "notebooks_detail": {
            "copilot-system-control": {
                "browser_bundle_hash": bundle_hash,
                "notebook_url": "https://notebooklm.google.com/notebook/control-1",
                "last_distill_attempt_at": recent_time,
            }
        },
    }

    with (
        patch("engine.nexus.bootstrap_notebooks._browser_seed_notebook_bundle") as mock_seed,
        patch("engine.nexus.bootstrap_notebooks._distill_qa_via_argus") as mock_distill,
    ):
        result = bootstrap_notebook(
            name="copilot-system-control",
            description="desc",
            sources=[source],
            questions=["Q1"],
            state=state,
            distill=True,
            scheduled=True,
            seed_mode="browser_bundle",
        )

    assert result["sources_added"] == 0
    assert result["qa_stored"] == 0
    assert result["distilled"] is False
    assert result["distill_reason"] == ""
    mock_seed.assert_not_called()
    mock_distill.assert_not_called()


def test_run_notebook_bootstrap_enables_scheduler_safe_distillation() -> None:
    """Weekly bootstrap should run with scheduled distillation semantics enabled."""
    with (
        patch(
            "engine.nexus.bootstrap_notebooks.bootstrap_all",
            return_value={
                "arch": {"qa_stored": 1},
                "control": {"notebook_url": "https://notebooklm.google.com/notebook/control-1"},
            },
        ) as mock_bootstrap,
        patch(
            "engine.nexus.bootstrap_notebooks._run_control_notebook_followup",
            return_value={"status": "ok", "tasks_created": 2},
        ) as mock_followup,
    ):
        result = run_notebook_bootstrap()

    assert result["status"] == "ok"
    assert result["results"]["arch"]["qa_stored"] == 1
    assert result["control_flywheel"]["status"] == "ok"
    mock_bootstrap.assert_called_once_with(distill=True, scheduled=True)
    mock_followup.assert_called_once_with(
        {
            "arch": {"qa_stored": 1},
            "control": {"notebook_url": "https://notebooklm.google.com/notebook/control-1"},
        }
    )


def test_run_control_notebook_followup_invokes_control_flywheel() -> None:
    """Control bootstrap should hand the notebook URL to the control flywheel."""
    results = {
        "control": {
            "notebook_url": "https://notebooklm.google.com/notebook/control-2",
        }
    }

    with patch(
        "engine.nexus.notebooklm_flywheel.run_control_notebook_flywheel",
        return_value={"status": "ok", "tasks_created": 1},
    ) as mock_followup:
        result = _run_control_notebook_followup(results)

    assert result["status"] == "ok"
    mock_followup.assert_called_once_with(
        notebook_url="https://notebooklm.google.com/notebook/control-2",
        reason="bootstrap_refresh",
    )


def test_add_text_source_prefers_dedicated_text_route() -> None:
    """Inline text uploads should prefer the dedicated /sources/text route."""
    with patch("engine.nexus.bootstrap_notebooks._nlm_post", return_value={"ok": True}) as mock_post:
        from engine.nexus.bootstrap_notebooks import _add_text_source

        assert _add_text_source("https://notebooklm.google.com/notebook/nb-1", "Doc", "Body") is True

    first_call = mock_post.call_args_list[0]
    assert first_call.args[0] == "/notebooks/nb-1/sources/text"
