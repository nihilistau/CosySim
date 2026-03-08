"""Tests for ARGUS Explorer — automated API surface testing and discovery."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from scripts.argus.explorer import (
    AutoExplorer,
    CdpDiscovery,
    CoverageReport,
    DiscoveryEvent,
    ExplorationResult,
    NexusCatalogStore,
    ParameterSweepResult,
    RegistryLoader,
    RpcTester,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def loader() -> RegistryLoader:
    return RegistryLoader()


@pytest.fixture()
def mock_tester() -> RpcTester:
    tester = RpcTester()
    tester._client = MagicMock()
    return tester


# ─── RegistryLoader Tests ───────────────────────────────────────────────────

class TestRegistryLoader:
    def test_loads_yaml(self, loader: RegistryLoader) -> None:
        assert len(loader.operations) > 40

    def test_operations_are_dicts(self, loader: RegistryLoader) -> None:
        for name, op in loader.operations.items():
            assert isinstance(op, dict), f"{name} should be dict"

    def test_testable_operations(self, loader: RegistryLoader) -> None:
        testable = loader.get_testable_operations()
        assert len(testable) > 30
        for name, op in testable.items():
            assert op.get("rpcid") is not None

    def test_heap_only_operations(self, loader: RegistryLoader) -> None:
        heap = loader.get_heap_only_operations()
        assert len(heap) >= 10
        for name, op in heap.items():
            assert op.get("source") == "argus_heap"
            assert op.get("rpcid") is None

    def test_operations_by_category(self, loader: RegistryLoader) -> None:
        notebook_ops = loader.get_operations_by_category("notebook")
        assert len(notebook_ops) >= 8
        for name, op in notebook_ops.items():
            assert op.get("category") == "notebook"

    def test_parameter_options(self, loader: RegistryLoader) -> None:
        options = loader.get_parameter_options("tier_marker")
        assert "free" in options
        assert "pro" in options
        assert options["free"] == [1]
        assert options["pro"] == [2]

    def test_gemini_rpcids(self, loader: RegistryLoader) -> None:
        rpcids = loader.gemini_rpcids
        assert len(rpcids) >= 17
        assert "otAQ7b" in rpcids

    def test_aistudio_methods(self, loader: RegistryLoader) -> None:
        methods = loader.aistudio_methods
        assert len(methods) >= 27
        assert "GenerateContent" in methods

    def test_colab_methods(self, loader: RegistryLoader) -> None:
        methods = loader.colab_methods
        assert len(methods) >= 10
        assert "AgentCreateTask" in methods

    def test_quota_events(self, loader: RegistryLoader) -> None:
        events = loader.quota_events
        assert len(events) >= 4
        assert "audio_overview" in events

    def test_nlm_identity(self, loader: RegistryLoader) -> None:
        identity = loader.nlm_identity
        assert identity["service_name"] == "LabsTailwindUi"
        assert identity["product_id"] == 269


class TestCoverageReport:
    def test_build_report(self, loader: RegistryLoader) -> None:
        report = loader.build_coverage_report()
        assert report.total_operations >= 40
        assert report.tested_operations > 0
        assert report.heap_only_operations >= 10
        assert report.gemini_rpcids >= 17
        assert report.aistudio_methods >= 27
        assert report.colab_methods >= 10
        assert report.quota_events >= 4
        assert 0 <= report.coverage_pct <= 100

    def test_per_category(self, loader: RegistryLoader) -> None:
        report = loader.build_coverage_report()
        assert "notebook" in report.per_category
        assert "source" in report.per_category
        assert "chat" in report.per_category
        assert report.per_category["notebook"]["total"] >= 8

    def test_parameter_coverage(self, loader: RegistryLoader) -> None:
        report = loader.build_coverage_report()
        assert "tier_marker" in report.parameter_coverage
        assert report.parameter_coverage["tier_marker"] >= 5

    def test_report_serializable(self, loader: RegistryLoader) -> None:
        report = loader.build_coverage_report()
        d = asdict(report)
        assert isinstance(d, dict)
        assert "total_operations" in d


# ─── ExplorationResult Tests ────────────────────────────────────────────────

class TestExplorationResult:
    def test_creation(self) -> None:
        r = ExplorationResult(
            operation="list_notebooks",
            rpcid="wXbhsf",
            tier="primary",
            status_code=200,
            success=True,
            response_size=1234,
            response_preview="[[[...]]]",
            error=None,
            duration_ms=150.3,
            parameters={"tier_marker": [2]},
        )
        assert r.success
        assert r.operation == "list_notebooks"

    def test_to_dict(self) -> None:
        r = ExplorationResult(
            operation="test", rpcid="abc", tier="primary",
            status_code=200, success=True, response_size=100,
            response_preview="data", error=None, duration_ms=50,
            parameters={},
        )
        d = r.to_dict()
        assert d["operation"] == "test"
        assert d["success"] is True
        assert "timestamp" in d


# ─── RpcTester Tests ─────────────────────────────────────────────────────────

class TestRpcTester:
    def test_unknown_operation(self, mock_tester: RpcTester) -> None:
        result = mock_tester.test_operation("nonexistent_op")
        assert not result.success
        assert "Unknown operation" in result.error

    def test_null_rpcid_operation(self, mock_tester: RpcTester) -> None:
        result = mock_tester.test_operation("mutate_account")
        assert not result.success
        assert "No primary rpcid" in result.error

    def test_requires_notebook_without_id(self, mock_tester: RpcTester) -> None:
        result = mock_tester.test_operation("create_note")
        assert not result.success
        assert "requires_notebook" in result.error

    def test_successful_call(self, mock_tester: RpcTester) -> None:
        mock_tester._client._rpc_call = MagicMock(return_value=[[["data"]]])
        result = mock_tester.test_operation("list_notebooks")
        assert result.success
        assert result.status_code == 200
        assert result.rpcid == "wXbhsf"

    def test_failed_call(self, mock_tester: RpcTester) -> None:
        mock_tester._client._rpc_call = MagicMock(side_effect=Exception("400 Bad Request"))
        result = mock_tester.test_operation("list_notebooks")
        assert not result.success
        assert result.status_code == 400


class TestParameterSweep:
    def test_unknown_parameter(self, mock_tester: RpcTester) -> None:
        result = mock_tester.sweep_parameter("list_notebooks", "nonexistent_param")
        assert "No options found" in result.summary

    def test_sweep_tier_marker(self, mock_tester: RpcTester) -> None:
        mock_tester._client._rpc_call = MagicMock(return_value=[[["ok"]]])
        result = mock_tester.sweep_parameter("list_notebooks", "tier_marker")
        assert len(result.results) >= 3
        assert result.summary


# ─── CdpDiscovery Tests ─────────────────────────────────────────────────────

class TestCdpDiscovery:
    def test_known_rpcids_loaded(self) -> None:
        disc = CdpDiscovery()
        assert "wXbhsf" in disc._known_rpcids
        assert "CCqFvf" in disc._known_rpcids
        assert len(disc._known_rpcids) >= 30


# ─── NexusCatalogStore Tests ─────────────────────────────────────────────────

class TestNexusCatalogStore:
    def test_store_full_catalog_dry_run(self) -> None:
        store = NexusCatalogStore()
        store._sink = None
        counts = store.store_full_catalog()
        assert counts["nlm_operations"] >= 1
        assert counts["gemini_rpcids"] >= 1
        assert counts["aistudio_methods"] >= 1
        assert counts["colab_methods"] >= 1

    def test_store_exploration_results_empty(self) -> None:
        store = NexusCatalogStore()
        store._sink = None
        count = store.store_exploration_results([])
        assert count == 0

    def test_store_exploration_results_with_data(self) -> None:
        store = NexusCatalogStore()
        store._sink = None
        results = [
            ExplorationResult(
                operation="test", rpcid="abc", tier="primary",
                status_code=200, success=True, response_size=100,
                response_preview="data", error=None, duration_ms=50,
                parameters={},
            ),
        ]
        count = store.store_exploration_results(results)
        assert count >= 1


# ─── DiscoveryEvent Tests ────────────────────────────────────────────────────

class TestDiscoveryEvent:
    def test_creation(self) -> None:
        event = DiscoveryEvent(
            rpcid="NewRpcId",
            source="cdp_live",
            url="https://notebooklm.google.com/_/...",
            method="POST",
            context="[[[\"NewRpcId\"...",
            is_new=True,
        )
        assert event.is_new
        assert event.rpcid == "NewRpcId"
        assert "timestamp" in asdict(event)
