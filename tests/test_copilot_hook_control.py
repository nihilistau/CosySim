"""Tests for the Copilot hook control runtime."""

from __future__ import annotations

import json
from pathlib import Path

from engine.nexus import copilot_hook_control as hook_mod


def test_build_hook_snapshot_collects_service_and_log_state(monkeypatch, tmp_path: Path) -> None:
    """Snapshots should include payload summary, service health, and tailed logs."""
    log_file = tmp_path / "session.log"
    log_file.write_text("a\nb\nc\n", encoding="utf-8")

    monkeypatch.setattr(hook_mod, "_load_session_state", lambda: {"last_hook_event": "sessionStart"})
    monkeypatch.setattr(
        hook_mod,
        "collect_service_snapshot",
        lambda target_ids=None: [{"id": "nexus", "health": {"ok": True}}],
    )

    snapshot = hook_mod.build_hook_snapshot(
        "checkpoint",
        payload={"toolName": "apply_patch", "error": "none", "input": {"path": "x"}},
        log_targets={"hook_session": log_file},
    )

    assert snapshot["event"] == "checkpoint"
    assert snapshot["payload"]["toolName"] == "apply_patch"
    assert snapshot["payload"]["input_keys"] == ["path"]
    assert snapshot["services"][0]["id"] == "nexus"
    assert snapshot["log_tails"]["hook_session"] == ["a", "b", "c"]


def test_run_hook_updates_session_state(monkeypatch) -> None:
    """Hook runs should store snapshot metadata back into the hook session state."""
    merged: dict = {}
    monkeypatch.setattr(hook_mod, "build_hook_snapshot", lambda *args, **kwargs: {"event": "sessionStart", "captured_at": "now"})
    monkeypatch.setattr(hook_mod, "store_hook_snapshot", lambda snapshot: "entry-1")
    monkeypatch.setattr(hook_mod, "_merge_session_state", lambda updates: merged.update(updates) or updates)

    snapshot = hook_mod.run_hook("sessionStart")

    assert snapshot["entry_id"] == "entry-1"
    assert merged["last_hook_event"] == "sessionStart"
    assert merged["last_hook_snapshot_id"] == "entry-1"


def test_main_tail_command_prints_requested_lines(monkeypatch, capsys) -> None:
    """CLI tail mode should emit log contents as JSON."""
    monkeypatch.setattr(hook_mod, "_tail_lines", lambda path, max_lines=20: ["x", "y"])

    code = hook_mod.main(["tail", "hook_errors", "--lines", "2"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["log_key"] == "hook_errors"
    assert payload["lines"] == ["x", "y"]


def test_render_hook_control_reference_mentions_lifecycle_events() -> None:
    """Notebook references should describe the lifecycle hook runtime."""
    reference = hook_mod.render_hook_control_reference()

    assert "sessionStart" in reference
    assert "preCompaction" in reference
    assert "checkpoint (triggered by the session logger)" in reference
