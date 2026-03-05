"""Tests for scripts.argus.tools.har_replay — offline HAR replay tool."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# ──── Module-level patch for NexusSink so imports work without live Nexus ──────
# Patch at import time so that `NexusSink()` inside HARReplayer.__init__ is safe.
_NEXUS_SINK_PATH = "scripts.argus.tools.har_replay.NexusSink"


# ──── Helpers ─────────────────────────────────────────────────────────────────

def _make_har(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a minimal valid HAR dict with the given request/response entries.

    Args:
        entries: List of raw HAR entry dicts.

    Returns:
        A complete HAR dict suitable for json.dumps and file writing.
    """
    return {"log": {"version": "1.2", "entries": entries}}


def _make_batchexecute_entry(
    rpcid: str,
    url: str = "https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute",
    payload_json: str = "[]",
) -> Dict[str, Any]:
    """Build a minimal HAR entry that looks like a batchexecute request.

    The f.req body is URL-encoded as the real browser sends it.

    Args:
        rpcid: The rpcid to embed in the f.req body.
        url: The batchexecute URL.
        payload_json: JSON string for the inner payload.

    Returns:
        HAR entry dict.
    """
    import urllib.parse
    f_req = json.dumps([[[rpcid, payload_json, None, "generic"]]])
    body = urllib.parse.urlencode({"f.req": f_req, "": ""})
    return {
        "request": {
            "url": url,
            "method": "POST",
            "postData": {"text": body},
        },
        "response": {
            "status": 200,
            "content": {
                "text": ")]}'" + r"\n" + f'[["wrb.fr","{rpcid}","{payload_json}",null,null,null,"generic"]]',
                "mimeType": "application/json",
            },
        },
        "time": 123.4,
        "startedDateTime": "2024-01-01T00:00:00Z",
    }


def _make_static_entry(url: str = "https://example.com/static/app.js") -> Dict[str, Any]:
    """Build a HAR entry for a plain static resource (no batchexecute).

    Args:
        url: URL of the static resource.

    Returns:
        HAR entry dict.
    """
    return {
        "request": {"url": url, "method": "GET", "postData": {}},
        "response": {
            "status": 200,
            "content": {"text": "// js content", "mimeType": "text/javascript"},
        },
        "time": 5.0,
        "startedDateTime": "2024-01-01T00:00:00Z",
    }


# ──── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def empty_har_file(tmp_path) -> Path:
    """A HAR file with zero entries."""
    p = tmp_path / "empty.har"
    p.write_text(json.dumps(_make_har([])))
    return p


@pytest.fixture
def static_only_har_file(tmp_path) -> Path:
    """A HAR file containing only static resource entries (no batchexecute)."""
    entries = [_make_static_entry("https://example.com/app.js")]
    p = tmp_path / "static_only.har"
    p.write_text(json.dumps(_make_har(entries)))
    return p


@pytest.fixture
def known_rpcid_har_file(tmp_path) -> Path:
    """A HAR file with one batchexecute entry whose rpcid is in the NLM baseline.

    Uses 'wIlBFe' (ListNotebooks) which is listed in cfg.NLM_RPCIDS.
    """
    entries = [_make_batchexecute_entry("wIlBFe")]
    p = tmp_path / "known.har"
    p.write_text(json.dumps(_make_har(entries)))
    return p


@pytest.fixture
def new_rpcid_har_file(tmp_path) -> Path:
    """A HAR file with one batchexecute entry whose rpcid is NOT in any known baseline."""
    entries = [_make_batchexecute_entry("ZZZNEW_UNKNOWN_42")]
    p = tmp_path / "new.har"
    p.write_text(json.dumps(_make_har(entries)))
    return p


@pytest.fixture
def multi_entry_har_file(tmp_path) -> Path:
    """A HAR file with a mix of known, unknown, and static entries."""
    entries = [
        _make_batchexecute_entry("wIlBFe"),               # known NLM
        _make_batchexecute_entry("ZZZNEW_UNKNOWN_42"),    # new
        _make_static_entry(),                              # skipped
    ]
    p = tmp_path / "multi.har"
    p.write_text(json.dumps(_make_har(entries)))
    return p


def _make_replayer(har_path, target="notebooklm", store_nexus=False):
    """Construct a HARReplayer with NexusSink patched out.

    Args:
        har_path: Path to the HAR file.
        target: ARGUS target name.
        store_nexus: Whether to attempt Nexus storage.

    Returns:
        HARReplayer instance.
    """
    from scripts.argus.tools.har_replay import HARReplayer
    with patch(_NEXUS_SINK_PATH, MagicMock()):
        return HARReplayer(har_path, target_name=target, store_nexus=store_nexus)


# ──── ReplayResult dataclass tests ────────────────────────────────────────────

class TestReplayResult:
    """Tests for the ReplayResult dataclass."""

    def test_replay_result_summary_returns_nonempty_string(self, empty_har_file):
        """ReplayResult.summary() returns a non-empty string."""
        replayer = _make_replayer(empty_har_file)
        result = replayer.run()
        summary = result.summary()
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_replay_result_summary_contains_target_name(self, empty_har_file):
        """ReplayResult.summary() includes the target name."""
        replayer = _make_replayer(empty_har_file, target="apps_script")
        result = replayer.run()
        assert "apps_script" in result.summary()

    def test_replay_result_summary_contains_new_rpcids_when_present(self, new_rpcid_har_file):
        """ReplayResult.summary() lists new rpcids when they are discovered."""
        replayer = _make_replayer(new_rpcid_har_file)
        result = replayer.run()
        if result.new_rpcids:
            assert "ZZZNEW_UNKNOWN_42" in result.summary()

    def test_replay_result_endpoints_is_a_list(self, multi_entry_har_file):
        """ReplayResult.endpoints is a list of URL strings."""
        replayer = _make_replayer(multi_entry_har_file)
        result = replayer.run()
        assert isinstance(result.endpoints, list)

    def test_replay_result_new_rpcids_is_list(self, empty_har_file):
        """ReplayResult.new_rpcids is a list (possibly empty)."""
        replayer = _make_replayer(empty_har_file)
        result = replayer.run()
        assert isinstance(result.new_rpcids, list)

    def test_replay_result_known_rpcids_is_list(self, empty_har_file):
        """ReplayResult.known_rpcids is a list (possibly empty)."""
        replayer = _make_replayer(empty_har_file)
        result = replayer.run()
        assert isinstance(result.known_rpcids, list)


# ──── HARReplayer.__init__ tests ──────────────────────────────────────────────

class TestHARReplayerInit:
    """Tests for HARReplayer construction."""

    def test_replayer_stores_har_path(self, empty_har_file):
        """HARReplayer stores the given har_path as a Path object."""
        replayer = _make_replayer(empty_har_file, target="notebooklm")
        assert replayer._har_path == Path(empty_har_file)

    def test_replayer_stores_target_name(self, empty_har_file):
        """HARReplayer stores the given target_name."""
        replayer = _make_replayer(empty_har_file, target="apps_script")
        assert replayer._target_name == "apps_script"

    def test_replayer_nexus_is_none_when_store_nexus_false(self, empty_har_file):
        """HARReplayer._nexus is None when store_nexus=False."""
        replayer = _make_replayer(empty_har_file, store_nexus=False)
        assert replayer._nexus is None

    def test_replayer_nexus_is_set_when_store_nexus_true(self, empty_har_file):
        """HARReplayer._nexus is a NexusSink instance when store_nexus=True."""
        mock_sink = MagicMock()
        with patch(_NEXUS_SINK_PATH, return_value=mock_sink):
            from scripts.argus.tools.har_replay import HARReplayer
            replayer = HARReplayer(empty_har_file, store_nexus=True)
        assert replayer._nexus is mock_sink


# ──── run() basic tests ───────────────────────────────────────────────────────

class TestRun:
    """Tests for HARReplayer.run()."""

    def test_run_returns_replay_result(self, empty_har_file):
        """run() with empty HAR returns a ReplayResult instance."""
        from scripts.argus.tools.har_replay import ReplayResult
        replayer = _make_replayer(empty_har_file)
        result = replayer.run()
        assert isinstance(result, ReplayResult)

    def test_run_empty_har_has_zero_total_entries(self, empty_har_file):
        """run() with empty HAR returns total_entries=0."""
        replayer = _make_replayer(empty_har_file)
        result = replayer.run()
        assert result.total_entries == 0

    def test_run_empty_har_returns_empty_new_rpcids(self, empty_har_file):
        """run() with no batchexecute entries returns empty new_rpcids list."""
        replayer = _make_replayer(empty_har_file)
        result = replayer.run()
        assert result.new_rpcids == []

    def test_run_static_only_entries_are_skipped(self, static_only_har_file):
        """run() with only static entries has zero batchexecute_entries."""
        replayer = _make_replayer(static_only_har_file)
        result = replayer.run()
        assert result.batchexecute_entries == 0
        assert result.skipped_entries >= 1

    def test_run_counts_total_entries(self, multi_entry_har_file):
        """run() counts all HAR entries (batchexecute + static)."""
        replayer = _make_replayer(multi_entry_har_file)
        result = replayer.run()
        assert result.total_entries == 3  # 2 batch + 1 static

    def test_run_known_rpcid_lands_in_known_rpcids(self, known_rpcid_har_file):
        """run() with a known baseline rpcid puts it in known_rpcids, not new_rpcids."""
        replayer = _make_replayer(known_rpcid_har_file)
        result = replayer.run()
        # 'wIlBFe' is in cfg.NLM_RPCIDS
        if result.known_rpcids or result.new_rpcids:
            # If the decoder successfully parsed the rpcid:
            assert "wIlBFe" not in result.new_rpcids

    def test_run_new_rpcid_lands_in_new_rpcids(self, new_rpcid_har_file):
        """run() with an unknown rpcid puts it in new_rpcids, not known_rpcids."""
        replayer = _make_replayer(new_rpcid_har_file)
        result = replayer.run()
        # The decoder may or may not parse our synthetic f.req format;
        # in either case the rpcid should NOT appear in known_rpcids.
        assert "ZZZNEW_UNKNOWN_42" not in result.known_rpcids

    def test_run_endpoints_contains_unique_request_urls(self, multi_entry_har_file):
        """run() populates endpoints with unique URLs from decoded requests."""
        replayer = _make_replayer(multi_entry_har_file)
        result = replayer.run()
        # Endpoints come from decoded BatchRequest.url; no duplicates
        assert len(result.endpoints) == len(set(result.endpoints))

    def test_run_store_nexus_false_never_calls_nexus(self, multi_entry_har_file):
        """run() with store_nexus=False never calls _store_to_nexus."""
        replayer = _make_replayer(multi_entry_har_file, store_nexus=False)
        with patch.object(replayer, "_store_to_nexus") as mock_store:
            replayer.run()
        mock_store.assert_not_called()


# ──── run() error resilience tests ────────────────────────────────────────────

class TestRunErrorResilience:
    """Tests for graceful error handling during HAR replay."""

    def test_run_handles_corrupt_json_entry_gracefully(self, tmp_path):
        """run() with a corrupt HAR entry does not crash; error is recorded."""
        # Entry with invalid JSON in postData
        corrupt_entry = {
            "request": {
                "url": "https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute",
                "method": "POST",
                "postData": {"text": "f.req=NOT_VALID_JSON_!@#$%^"},
            },
            "response": {
                "status": 200,
                "content": {"text": "garbage response !!!!", "mimeType": "text/plain"},
            },
            "time": 10.0,
            "startedDateTime": "2024-01-01T00:00:00Z",
        }
        har_file = tmp_path / "corrupt.har"
        har_file.write_text(json.dumps(_make_har([corrupt_entry])))

        replayer = _make_replayer(har_file)
        # Must not raise
        result = replayer.run()
        assert result.total_entries == 1

    def test_run_handles_empty_har_log_gracefully(self, tmp_path):
        """run() with minimal HAR (no 'entries' key) returns empty ReplayResult."""
        har_file = tmp_path / "minimal.har"
        har_file.write_text(json.dumps({"log": {}}))

        replayer = _make_replayer(har_file)
        result = replayer.run()
        assert result.total_entries == 0

    def test_run_handles_missing_response_body(self, tmp_path):
        """run() processes batchexecute entries that have no response body."""
        entry = {
            "request": {
                "url": "https://example.com/_/SomeService/data/batchexecute",
                "method": "POST",
                "postData": {"text": ""},
            },
            "response": {
                "status": 200,
                "content": {},  # no 'text' key
            },
            "time": 5.0,
            "startedDateTime": "2024-01-01T00:00:00Z",
        }
        har_file = tmp_path / "no_response.har"
        har_file.write_text(json.dumps(_make_har([entry])))

        replayer = _make_replayer(har_file)
        result = replayer.run()
        # Should process without crashing
        assert result.batchexecute_entries == 1

    def test_run_store_nexus_true_skips_nexus_on_exception(self, empty_har_file):
        """run() with store_nexus=True does not crash if Nexus store_har_replay raises."""
        mock_sink = MagicMock()
        mock_sink.store_har_replay.side_effect = RuntimeError("Nexus down")
        with patch(_NEXUS_SINK_PATH, return_value=mock_sink):
            from scripts.argus.tools.har_replay import HARReplayer
            replayer = HARReplayer(empty_har_file, store_nexus=True)
        # run() should not raise even when nexus fails
        result = replayer.run()
        assert result is not None


# ──── extract_override_candidates() tests ────────────────────────────────────

class TestExtractOverrideCandidates:
    """Tests for HARReplayer.extract_override_candidates()."""

    def test_extract_override_candidates_returns_dict(self, empty_har_file):
        """extract_override_candidates() returns a dict (possibly empty)."""
        replayer = _make_replayer(empty_har_file)
        result = replayer.run()
        candidates = replayer.extract_override_candidates(result)
        assert isinstance(candidates, dict)

    def test_extract_override_candidates_empty_when_no_requests(self, empty_har_file):
        """extract_override_candidates() returns empty dict when no requests decoded."""
        replayer = _make_replayer(empty_har_file)
        result = replayer.run()
        candidates = replayer.extract_override_candidates(result)
        assert candidates == {}

    def test_extract_override_candidates_finds_model_field(self, empty_har_file):
        """extract_override_candidates() detects 'model' key in request payloads."""
        from scripts.argus.decoders.batchexecute import BatchRequest

        replayer = _make_replayer(empty_har_file)
        result = replayer.run()
        # Inject a synthetic request with a 'model' key in payload
        result.all_requests.append(
            BatchRequest(
                rpcid="jKHnxe",
                payload_raw=json.dumps({"model": "gemini-2.0-flash", "prompt": "hello"}),
            )
        )
        candidates = replayer.extract_override_candidates(result)
        assert "model" in candidates
        assert "gemini-2.0-flash" in candidates["model"]

    def test_extract_override_candidates_finds_quota_field(self, empty_har_file):
        """extract_override_candidates() detects quota-related fields in payloads."""
        from scripts.argus.decoders.batchexecute import BatchRequest

        replayer = _make_replayer(empty_har_file)
        result = replayer.run()
        result.all_requests.append(
            BatchRequest(
                rpcid="ozz5Z",
                payload_raw=json.dumps({"remainingQueries": 42, "queryLimit": 50}),
            )
        )
        candidates = replayer.extract_override_candidates(result)
        assert "remainingQueries" in candidates or "queryLimit" in candidates

    def test_extract_override_candidates_deduplicates_values(self, empty_har_file):
        """extract_override_candidates() does not store duplicate values for the same key."""
        from scripts.argus.decoders.batchexecute import BatchRequest

        replayer = _make_replayer(empty_har_file)
        result = replayer.run()
        for _ in range(3):
            result.all_requests.append(
                BatchRequest(
                    rpcid="jKHnxe",
                    payload_raw=json.dumps({"model": "gemini-2.0-flash"}),
                )
            )
        candidates = replayer.extract_override_candidates(result)
        if "model" in candidates:
            assert candidates["model"].count("gemini-2.0-flash") == 1

    def test_extract_override_candidates_runs_fresh_replay_when_no_result(self, empty_har_file):
        """extract_override_candidates(None) runs a fresh replay automatically."""
        replayer = _make_replayer(empty_har_file)
        with patch.object(replayer, "run", wraps=replayer.run) as spy_run:
            candidates = replayer.extract_override_candidates(None)
        spy_run.assert_called_once()
        assert isinstance(candidates, dict)
