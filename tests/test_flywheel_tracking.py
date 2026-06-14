"""Tests for NotebookLM flywheel execution tracking.

v1.50.2 [2026-03-24] — Tests for _poll_previous_tasks and fingerprint lifecycle.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ── Poll previous tasks ──────────────────────────────────────────────────

class TestPollPreviousTasks:

    def _make_flywheel(self):
        """Create a flywheel instance with mocked config."""
        with patch("engine.nexus.notebooklm_flywheel.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock()
            mock_cfg.return_value.get = lambda k, d=None: d
            from engine.nexus.notebooklm_flywheel import NotebookLMFlywheel
            fw = NotebookLMFlywheel.__new__(NotebookLMFlywheel)
            fw._config = mock_cfg.return_value
            fw._state_path = MagicMock()
            return fw

    def test_poll_no_previous_tasks(self):
        """Empty state → zero counts."""
        fw = self._make_flywheel()
        state = {"task_fingerprints": {}}
        result = fw._poll_previous_tasks(state)
        assert result["total"] == 0

    def test_poll_completed_tasks(self):
        """Completed tasks counted, fingerprint kept."""
        fw = self._make_flywheel()
        state = {
            "task_fingerprints": {
                "fp1": {"task_id": "t1", "title": "Done task", "created_at": "2026-03-24T00:00:00+00:00"},
            }
        }
        mock_scheduler = MagicMock()
        mock_scheduler.get_task_statuses.return_value = {"t1": "completed"}
        with patch("engine.nexus.notebooklm_flywheel.get_task_scheduler", return_value=mock_scheduler):
            result = fw._poll_previous_tasks(state)

        assert result["completed"] == 1
        assert result["total"] == 1
        # Fingerprint should still be there (completed tasks stay to prevent re-creation)
        assert "fp1" in state["task_fingerprints"]

    def test_poll_failed_fingerprint_cleared(self):
        """Failed task fingerprint should be removed so it can be re-created."""
        fw = self._make_flywheel()
        state = {
            "task_fingerprints": {
                "fp-fail": {"task_id": "t-fail", "title": "Broken", "created_at": "2026-03-24T00:00:00+00:00"},
            }
        }
        mock_scheduler = MagicMock()
        mock_scheduler.get_task_statuses.return_value = {"t-fail": "failed"}
        with patch("engine.nexus.notebooklm_flywheel.get_task_scheduler", return_value=mock_scheduler):
            result = fw._poll_previous_tasks(state)

        assert result["failed"] == 1
        assert "fp-fail" not in state["task_fingerprints"]

    def test_poll_stuck_tasks_reset(self):
        """Pending tasks past timeout should be reset via fail_task(retry=True)."""
        fw = self._make_flywheel()
        # Task created 72 hours ago (well past 48h default timeout)
        old_time = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0
        )
        old_iso = (old_time.replace(year=2026, month=3, day=20)).isoformat()

        state = {
            "task_fingerprints": {
                "fp-stuck": {"task_id": "t-stuck", "title": "Stuck", "created_at": old_iso},
            }
        }
        mock_scheduler = MagicMock()
        mock_scheduler.get_task_statuses.return_value = {"t-stuck": "pending"}
        mock_scheduler.fail_task.return_value = True

        with patch("engine.nexus.notebooklm_flywheel.get_task_scheduler", return_value=mock_scheduler):
            result = fw._poll_previous_tasks(state)

        assert result["stuck_reset"] == 1
        mock_scheduler.fail_task.assert_called_once_with("t-stuck", "stuck_pending", retry=True)

    def test_poll_recent_pending_not_reset(self):
        """Recently created pending tasks should NOT be reset."""
        fw = self._make_flywheel()
        recent_iso = datetime.now(timezone.utc).isoformat()

        state = {
            "task_fingerprints": {
                "fp-new": {"task_id": "t-new", "title": "Fresh", "created_at": recent_iso},
            }
        }
        mock_scheduler = MagicMock()
        mock_scheduler.get_task_statuses.return_value = {"t-new": "pending"}

        with patch("engine.nexus.notebooklm_flywheel.get_task_scheduler", return_value=mock_scheduler):
            result = fw._poll_previous_tasks(state)

        assert result["pending"] == 1
        assert result["stuck_reset"] == 0
        mock_scheduler.fail_task.assert_not_called()
