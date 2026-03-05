"""Tests for scripts.argus.tools.heap_analyzer — V8 heap snapshot analysis."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from scripts.argus.tools.heap_analyzer import (
    GAS_RPCIDS,
    RPCID_PATTERN,
    SERVICE_PATH_PATTERN,
    build_confirmed_map,
    extract_service_paths,
    find_all_potential_rpcids,
    find_rpcid_mappings,
    load_strings,
    search_strings_near_rpcid,
)


# ──── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def minimal_snapshot(tmp_path: Path) -> str:
    """Write a minimal V8 heapsnapshot JSON to disk and return the path."""
    strings = [
        "Object",
        "prototype",
        "AvwHP",                                   # rpcid at index 2
        "Array",
        "/ArtifactService.GetDeploymentEnvironment",  # path at index 4 (dist=2)
        "Function",
        "script",
        "OOPYjd",                                  # rpcid at index 7
        "null",
        "/ArtifactService.GetProjectContent",       # path at index 9 (dist=2)
        "undefined",
    ]
    snap = {
        "snapshot": {"meta": {}, "node_count": 0, "edge_count": 0},
        "nodes": [],
        "edges": [],
        "strings": strings,
    }
    path = tmp_path / "test.heapsnapshot"
    path.write_text(json.dumps(snap), encoding="utf-8")
    return str(path)


@pytest.fixture
def sample_strings() -> list[str]:
    """A representative strings list for unit tests (no file I/O)."""
    return [
        "junk",
        "AvwHP",
        "/ArtifactService.GetDeploymentEnvironment",
        "more_junk",
        "OOPYjd",
        "/ArtifactService.GetProjectContent",
        "unrelated",
        "NFMk7c",
        "/ArtifactService.CreateProject",
        "padding",
    ]


# ──── load_strings ────────────────────────────────────────────────────────────

class TestLoadStrings:
    def test_returns_strings_list(self, minimal_snapshot: str) -> None:
        strings = load_strings(minimal_snapshot)
        assert isinstance(strings, list)
        assert len(strings) == 11

    def test_strings_contain_expected_values(self, minimal_snapshot: str) -> None:
        strings = load_strings(minimal_snapshot)
        assert "AvwHP" in strings
        assert "/ArtifactService.GetDeploymentEnvironment" in strings

    def test_missing_strings_key_returns_empty(self, tmp_path: Path) -> None:
        snap = {"snapshot": {}, "nodes": [], "edges": []}
        path = tmp_path / "empty.heapsnapshot"
        path.write_text(json.dumps(snap), encoding="utf-8")
        strings = load_strings(str(path))
        assert strings == []


# ──── extract_service_paths ───────────────────────────────────────────────────

class TestExtractServicePaths:
    def test_finds_artifact_service_paths(self, sample_strings: list[str]) -> None:
        paths = extract_service_paths(sample_strings)
        full_paths = [p for _, p, _, _ in paths]
        assert "/ArtifactService.GetDeploymentEnvironment" in full_paths
        assert "/ArtifactService.GetProjectContent" in full_paths

    def test_returns_correct_service_and_method(self, sample_strings: list[str]) -> None:
        paths = extract_service_paths(sample_strings)
        entry = next(e for e in paths if "GetDeploymentEnvironment" in e[1])
        idx, full, service, method = entry
        assert service == "ArtifactService"
        assert method == "GetDeploymentEnvironment"

    def test_does_not_return_non_path_strings(self, sample_strings: list[str]) -> None:
        paths = extract_service_paths(sample_strings)
        for _, p, _, _ in paths:
            assert p.startswith("/")
            assert "." in p

    def test_returns_correct_index(self, sample_strings: list[str]) -> None:
        paths = extract_service_paths(sample_strings)
        for idx, path, _, _ in paths:
            assert sample_strings[idx] == path

    def test_empty_strings_returns_empty(self) -> None:
        assert extract_service_paths([]) == []

    def test_no_paths_in_plain_strings(self) -> None:
        strings = ["hello", "world", "AvwHP", "some string", "1234"]
        assert extract_service_paths(strings) == []


# ──── find_rpcid_mappings ─────────────────────────────────────────────────────

class TestFindRpcidMappings:
    def test_finds_avwhp_with_high_confidence(self, sample_strings: list[str]) -> None:
        mappings = find_rpcid_mappings(sample_strings, rpcids=["AvwHP"], window=10)
        assert mappings["AvwHP"]["found"] is True
        best = mappings["AvwHP"]["best_match"]
        assert best is not None
        assert best["method"] == "GetDeploymentEnvironment"
        assert best["dist"] <= 2

    def test_not_found_rpcid(self, sample_strings: list[str]) -> None:
        mappings = find_rpcid_mappings(sample_strings, rpcids=["XXXXX"], window=10)
        assert mappings["XXXXX"]["found"] is False
        assert mappings["XXXXX"]["candidates"] == []

    def test_respects_window(self, sample_strings: list[str]) -> None:
        # "NFMk7c" is at index 7, "/ArtifactService.CreateProject" is at index 8 (dist=1)
        mappings = find_rpcid_mappings(sample_strings, rpcids=["NFMk7c"], window=1)
        assert mappings["NFMk7c"]["found"] is True
        # With window=1, dist=1 should still be found
        assert len(mappings["NFMk7c"]["candidates"]) >= 1

    def test_multiple_rpcids(self, sample_strings: list[str]) -> None:
        mappings = find_rpcid_mappings(
            sample_strings, rpcids=["AvwHP", "OOPYjd", "NFMk7c"], window=10
        )
        assert all(r in mappings for r in ["AvwHP", "OOPYjd", "NFMk7c"])
        assert mappings["AvwHP"]["found"] is True
        assert mappings["OOPYjd"]["found"] is True

    def test_defaults_to_gas_rpcids(self, sample_strings: list[str]) -> None:
        mappings = find_rpcid_mappings(sample_strings)
        # All GAS_RPCIDS should be in result keys
        for rpcid in GAS_RPCIDS:
            assert rpcid in mappings

    def test_candidates_sorted_by_distance(self, sample_strings: list[str]) -> None:
        mappings = find_rpcid_mappings(sample_strings, rpcids=["AvwHP"], window=200)
        candidates = mappings["AvwHP"]["candidates"]
        dists = [c["dist"] for c in candidates]
        assert dists == sorted(dists)


# ──── build_confirmed_map ─────────────────────────────────────────────────────

class TestBuildConfirmedMap:
    def test_includes_high_confidence_mapping(self) -> None:
        mappings = {
            "AvwHP": {
                "found": True,
                "rpcid_index": 30009,
                "candidates": [{"dist": 4, "index": 30013, "path": "/ArtifactService.GetDeploymentEnvironment", "service": "ArtifactService", "method": "GetDeploymentEnvironment"}],
                "best_match": {"dist": 4, "index": 30013, "path": "/ArtifactService.GetDeploymentEnvironment", "service": "ArtifactService", "method": "GetDeploymentEnvironment"},
            }
        }
        confirmed = build_confirmed_map(mappings)
        assert "AvwHP" in confirmed
        assert confirmed["AvwHP"] == "GetDeploymentEnvironment"

    def test_excludes_not_found(self) -> None:
        mappings = {
            "pEig0e": {"found": False, "candidates": []},
        }
        confirmed = build_confirmed_map(mappings)
        assert "pEig0e" not in confirmed

    def test_excludes_low_confidence_over_threshold(self) -> None:
        mappings = {
            "OQOG2e": {
                "found": True,
                "rpcid_index": 1000,
                "candidates": [{"dist": 150, "index": 1150, "path": "/ArtifactService.ListFiles", "service": "ArtifactService", "method": "ListFiles"}],
                "best_match": {"dist": 150, "index": 1150, "path": "/ArtifactService.ListFiles", "service": "ArtifactService", "method": "ListFiles"},
            }
        }
        # dist=150 is < 100 threshold → excluded
        confirmed = build_confirmed_map(mappings)
        assert "OQOG2e" not in confirmed

    def test_empty_mappings(self) -> None:
        assert build_confirmed_map({}) == {}

    def test_no_best_match(self) -> None:
        mappings = {
            "KKLVD": {
                "found": True,
                "rpcid_index": 5000,
                "candidates": [],
                "best_match": None,
            }
        }
        confirmed = build_confirmed_map(mappings)
        assert "KKLVD" not in confirmed


# ──── search_strings_near_rpcid ───────────────────────────────────────────────

class TestSearchStringsNearRpcid:
    def test_returns_nearby_strings(self, sample_strings: list[str]) -> None:
        # "AvwHP" is at index 1
        nearby = search_strings_near_rpcid(sample_strings, "AvwHP", window=3)
        values = [s for _, _, s in nearby]
        assert "AvwHP" in values
        assert "/ArtifactService.GetDeploymentEnvironment" in values

    def test_not_found_returns_empty(self, sample_strings: list[str]) -> None:
        result = search_strings_near_rpcid(sample_strings, "NOTEXIST", window=10)
        assert result == []

    def test_filter_fn_applied(self, sample_strings: list[str]) -> None:
        nearby = search_strings_near_rpcid(
            sample_strings, "AvwHP", window=10,
            filter_fn=lambda s: s.startswith("/")
        )
        for _, _, s in nearby:
            assert s.startswith("/")

    def test_relative_offsets_are_correct(self, sample_strings: list[str]) -> None:
        nearby = search_strings_near_rpcid(sample_strings, "AvwHP", window=5)
        rpcid_entry = next((e for e in nearby if e[2] == "AvwHP"), None)
        assert rpcid_entry is not None
        assert rpcid_entry[0] == 0  # relative offset of the rpcid itself is 0

    def test_window_respected(self, sample_strings: list[str]) -> None:
        nearby = search_strings_near_rpcid(sample_strings, "AvwHP", window=1)
        for offset, _, _ in nearby:
            assert abs(offset) <= 1


# ──── find_all_potential_rpcids ───────────────────────────────────────────────

class TestFindAllPotentialRpcids:
    def test_finds_known_rpcids(self) -> None:
        strings = ["Array", "OOPYjd", "AvwHP", "NFMk7c", "hello world", "x"]
        result = find_all_potential_rpcids(strings)
        found = [s for _, s in result]
        assert "OOPYjd" in found
        assert "AvwHP" in found
        assert "NFMk7c" in found

    def test_excludes_short_strings(self) -> None:
        strings = ["AB", "ABCDE", "Abc", "AbcDefG"]
        result = find_all_potential_rpcids(strings)
        found = [s for _, s in result]
        assert "AB" not in found
        assert "Abc" not in found

    def test_excludes_lowercase_start(self) -> None:
        strings = ["oooo1234", "OOOo1234"]
        result = find_all_potential_rpcids(strings)
        found = [s for _, s in result]
        assert "oooo1234" not in found

    def test_returns_correct_indices(self) -> None:
        strings = ["junk", "OOPYjd", "more"]
        result = find_all_potential_rpcids(strings)
        assert any(idx == 1 and s == "OOPYjd" for idx, s in result)


# ──── Pattern constants ───────────────────────────────────────────────────────

class TestPatterns:
    def test_rpcid_pattern_matches_known(self) -> None:
        for rpcid in GAS_RPCIDS:
            assert RPCID_PATTERN.match(rpcid), f"Pattern should match {rpcid}"

    def test_service_path_pattern_matches_grpc(self) -> None:
        valid = [
            "/ArtifactService.GetDeploymentEnvironment",
            "/WidgetService.GetWidget",
            "/AppsPlatformConsoleUserService.GetUserInfo",
        ]
        for path in valid:
            assert SERVICE_PATH_PATTERN.match(path), f"Pattern should match {path}"

    def test_service_path_pattern_rejects_invalid(self) -> None:
        invalid = ["ArtifactService.Method", "/lowercaseService.Method", "/Service", ""]
        for path in invalid:
            assert not SERVICE_PATH_PATTERN.match(path), f"Pattern should not match {path}"
