"""Tests for engine/observability/service_registry.py.

Covers:
- ServiceRecord and ServiceType dataclasses/enums
- register / deregister lifecycle
- heartbeat updates last_seen
- discover() filtering by type, tags, capabilities, status
- expire_stale() marks old entries as unknown
- get_by_capability() returns correct services
- Auto-registered built-ins exist on init
- broadcast_event() triggers all callbacks
- register_callback() works correctly
- SQLite persistence round-trip
- Singleton get_service_registry()
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from engine.observability.service_registry import (
    DiscoveryResult,
    ServiceRecord,
    ServiceRegistry,
    ServiceType,
    get_service_registry,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_record(
    name: str = "test_svc",
    service_type: ServiceType = ServiceType.TOOL,
    tags: list | None = None,
    capabilities: list | None = None,
    status: str = "active",
    host: str = "localhost",
    port: int = 9000,
    service_id: str | None = None,
) -> ServiceRecord:
    now = datetime.now()
    return ServiceRecord(
        service_id=service_id or f"test-{name}",
        name=name,
        service_type=service_type,
        host=host,
        port=port,
        health_url=f"http://{host}:{port}/health",
        metadata={"test": True},
        registered_at=now,
        last_seen=now,
        status=status,
        tags=tags or [],
        capabilities=capabilities or [],
    )


@pytest.fixture()
def registry(tmp_path: Path) -> ServiceRegistry:
    """Fresh ServiceRegistry backed by a temp SQLite DB."""
    return ServiceRegistry(db_path=str(tmp_path / "registry.db"))


# ---------------------------------------------------------------------------
# ServiceType enum
# ---------------------------------------------------------------------------


def test_service_type_values() -> None:
    assert ServiceType.SCENE.value == "scene"
    assert ServiceType.AGENT.value == "agent"
    assert ServiceType.LLM.value == "llm"
    assert ServiceType.SKILL_PACK.value == "skill_pack"
    assert ServiceType.TOOL.value == "tool"
    assert ServiceType.EXTERNAL.value == "external"


# ---------------------------------------------------------------------------
# Auto-registration of built-in services
# ---------------------------------------------------------------------------


def test_builtins_registered_on_init(registry: ServiceRegistry) -> None:
    all_ids = {s.service_id for s in registry.list_all()}
    expected = {
        "builtin-lmstudio",
        "builtin-nexus",
        "builtin-scheduler",
        "builtin-secret_manager",
        "builtin-rate_limiter",
        "builtin-structured_logger",
    }
    assert expected.issubset(all_ids)


def test_builtin_lmstudio_capabilities(registry: ServiceRegistry) -> None:
    svc = registry.get("builtin-lmstudio")
    assert svc is not None
    assert "inference" in svc.capabilities
    assert "embeddings" in svc.capabilities
    assert "vision" in svc.capabilities


def test_builtin_lmstudio_type(registry: ServiceRegistry) -> None:
    svc = registry.get("builtin-lmstudio")
    assert svc.service_type == ServiceType.LLM


def test_builtin_nexus_capabilities(registry: ServiceRegistry) -> None:
    svc = registry.get("builtin-nexus")
    assert "knowledge" in svc.capabilities
    assert "search" in svc.capabilities
    assert "qa" in svc.capabilities


def test_builtin_secret_manager_capabilities(registry: ServiceRegistry) -> None:
    svc = registry.get("builtin-secret_manager")
    assert "secrets" in svc.capabilities
    assert "vault" in svc.capabilities


def test_builtin_rate_limiter_capabilities(registry: ServiceRegistry) -> None:
    svc = registry.get("builtin-rate_limiter")
    assert "rate_limiting" in svc.capabilities
    assert "backpressure" in svc.capabilities


def test_builtin_structured_logger_capabilities(registry: ServiceRegistry) -> None:
    svc = registry.get("builtin-structured_logger")
    assert "logging" in svc.capabilities
    assert "tracing" in svc.capabilities


def test_builtins_not_re_registered_on_second_init(tmp_path: Path) -> None:
    db = str(tmp_path / "reg.db")
    r1 = ServiceRegistry(db_path=db)
    initial_count = len(r1.list_all())
    r2 = ServiceRegistry(db_path=db)
    assert len(r2.list_all()) == initial_count


# ---------------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------------


def test_register_adds_service(registry: ServiceRegistry) -> None:
    rec = _make_record("my_svc")
    returned_id = registry.register(rec)
    assert returned_id == rec.service_id
    assert registry.get(rec.service_id) is not None


def test_register_updates_existing(registry: ServiceRegistry) -> None:
    rec = _make_record("svc", service_id="svc-001")
    registry.register(rec)
    orig_registered_at = registry.get("svc-001").registered_at

    rec2 = _make_record("svc_updated", service_id="svc-001")
    registry.register(rec2)

    updated = registry.get("svc-001")
    assert updated.name == "svc_updated"
    assert updated.registered_at == orig_registered_at  # preserved


def test_register_updates_last_seen(registry: ServiceRegistry) -> None:
    rec = _make_record("svc", service_id="svc-t")
    before = datetime.now()
    registry.register(rec)
    after = datetime.now()
    svc = registry.get("svc-t")
    assert before <= svc.last_seen <= after


# ---------------------------------------------------------------------------
# deregister()
# ---------------------------------------------------------------------------


def test_deregister_existing(registry: ServiceRegistry) -> None:
    rec = _make_record("to_remove", service_id="rem-001")
    registry.register(rec)
    assert registry.deregister("rem-001") is True
    assert registry.get("rem-001") is None


def test_deregister_nonexistent(registry: ServiceRegistry) -> None:
    assert registry.deregister("does-not-exist") is False


def test_deregister_removes_callbacks(registry: ServiceRegistry) -> None:
    rec = _make_record("cb_svc", service_id="cb-001")
    registry.register(rec)
    registry.register_callback("cb-001", lambda e, d: None)
    registry.deregister("cb-001")
    assert "cb-001" not in registry._callbacks


# ---------------------------------------------------------------------------
# heartbeat()
# ---------------------------------------------------------------------------


def test_heartbeat_updates_last_seen(registry: ServiceRegistry) -> None:
    rec = _make_record("hb_svc", service_id="hb-001")
    registry.register(rec)
    time.sleep(0.01)
    before = registry.get("hb-001").last_seen
    registry.heartbeat("hb-001")
    after = registry.get("hb-001").last_seen
    assert after >= before


def test_heartbeat_resets_status_to_active(registry: ServiceRegistry) -> None:
    rec = _make_record("hb_svc2", service_id="hb-002", status="unknown")
    registry.register(rec)
    registry.heartbeat("hb-002")
    assert registry.get("hb-002").status == "active"


def test_heartbeat_returns_false_unknown_id(registry: ServiceRegistry) -> None:
    assert registry.heartbeat("no-such-id") is False


# ---------------------------------------------------------------------------
# discover()
# ---------------------------------------------------------------------------


def test_discover_all(registry: ServiceRegistry) -> None:
    rec = _make_record("disc_svc", service_id="disc-001")
    registry.register(rec)
    result = registry.discover()
    assert isinstance(result, DiscoveryResult)
    ids = {s.service_id for s in result.services}
    assert "disc-001" in ids


def test_discover_by_type(registry: ServiceRegistry) -> None:
    rec = _make_record("scene_svc", service_type=ServiceType.SCENE, service_id="sc-001")
    registry.register(rec)
    result = registry.discover(service_type=ServiceType.SCENE)
    assert all(s.service_type == ServiceType.SCENE for s in result.services)
    ids = {s.service_id for s in result.services}
    assert "sc-001" in ids


def test_discover_by_tags(registry: ServiceRegistry) -> None:
    rec = _make_record("tagged_svc", tags=["alpha", "beta"], service_id="tag-001")
    registry.register(rec)
    result = registry.discover(tags=["alpha"])
    ids = {s.service_id for s in result.services}
    assert "tag-001" in ids


def test_discover_by_tags_all_required(registry: ServiceRegistry) -> None:
    rec = _make_record("partial_tags", tags=["alpha"], service_id="tag-002")
    registry.register(rec)
    # Requires both alpha AND beta — should not match
    result = registry.discover(tags=["alpha", "beta"])
    ids = {s.service_id for s in result.services}
    assert "tag-002" not in ids


def test_discover_by_capabilities(registry: ServiceRegistry) -> None:
    rec = _make_record("cap_svc", capabilities=["render", "stream"], service_id="cap-001")
    registry.register(rec)
    result = registry.discover(capabilities=["render"])
    ids = {s.service_id for s in result.services}
    assert "cap-001" in ids


def test_discover_by_status(registry: ServiceRegistry) -> None:
    rec = _make_record("unknown_svc", status="unknown", service_id="unk-001")
    registry.register(rec)
    active_result = registry.discover(status="active")
    ids = {s.service_id for s in active_result.services}
    assert "unk-001" not in ids

    unk_result = registry.discover(status="unknown")
    ids = {s.service_id for s in unk_result.services}
    assert "unk-001" in ids


def test_discover_filtered_by_populated(registry: ServiceRegistry) -> None:
    result = registry.discover(service_type=ServiceType.LLM, capabilities=["inference"])
    assert "service_type" in result.filtered_by
    assert "capabilities" in result.filtered_by


def test_discover_total_matches_services_len(registry: ServiceRegistry) -> None:
    result = registry.discover()
    assert result.total == len(result.services)


# ---------------------------------------------------------------------------
# get() / list_all()
# ---------------------------------------------------------------------------


def test_get_returns_none_for_missing(registry: ServiceRegistry) -> None:
    assert registry.get("phantom") is None


def test_list_all_includes_builtins(registry: ServiceRegistry) -> None:
    all_svcs = registry.list_all()
    names = {s.name for s in all_svcs}
    assert "lmstudio" in names
    assert "nexus" in names


def test_list_all_returns_snapshot(registry: ServiceRegistry) -> None:
    lst = registry.list_all()
    assert isinstance(lst, list)


# ---------------------------------------------------------------------------
# expire_stale()
# ---------------------------------------------------------------------------


def test_expire_stale_marks_old_as_unknown(registry: ServiceRegistry) -> None:
    rec = _make_record("stale_svc", service_id="stale-001")
    registry.register(rec)
    # Manually backdate last_seen
    registry._services["stale-001"].last_seen = datetime.now() - timedelta(seconds=300)
    count = registry.expire_stale(max_age_seconds=120)
    assert count >= 1
    assert registry.get("stale-001").status == "unknown"


def test_expire_stale_does_not_expire_builtins(registry: ServiceRegistry) -> None:
    # Backdate a builtin
    registry._services["builtin-lmstudio"].last_seen = datetime.now() - timedelta(seconds=9999)
    registry.expire_stale(max_age_seconds=1)
    assert registry.get("builtin-lmstudio").status == "active"


def test_expire_stale_skips_already_unknown(registry: ServiceRegistry) -> None:
    rec = _make_record("old_svc", status="unknown", service_id="old-001")
    registry.register(rec)
    registry._services["old-001"].last_seen = datetime.now() - timedelta(seconds=300)
    count = registry.expire_stale(max_age_seconds=120)
    # Should NOT count already-unknown services
    assert count == 0


def test_expire_stale_returns_count(registry: ServiceRegistry) -> None:
    for i in range(3):
        rec = _make_record(f"svc_{i}", service_id=f"exp-{i}")
        registry.register(rec)
        registry._services[f"exp-{i}"].last_seen = datetime.now() - timedelta(seconds=300)
    count = registry.expire_stale(max_age_seconds=120)
    assert count == 3


# ---------------------------------------------------------------------------
# get_by_capability()
# ---------------------------------------------------------------------------


def test_get_by_capability_found(registry: ServiceRegistry) -> None:
    rec = _make_record("cap_svc", capabilities=["search", "rank"], service_id="gc-001")
    registry.register(rec)
    results = registry.get_by_capability("search")
    ids = {s.service_id for s in results}
    assert "gc-001" in ids


def test_get_by_capability_not_found(registry: ServiceRegistry) -> None:
    results = registry.get_by_capability("no_such_capability_xyz")
    assert results == []


def test_get_by_capability_multiple(registry: ServiceRegistry) -> None:
    for i in range(3):
        rec = _make_record(f"svc_{i}", capabilities=["magic"], service_id=f"magic-{i}")
        registry.register(rec)
    results = registry.get_by_capability("magic")
    assert len(results) >= 3


# ---------------------------------------------------------------------------
# broadcast_event() / register_callback()
# ---------------------------------------------------------------------------


def test_broadcast_event_calls_callbacks(registry: ServiceRegistry) -> None:
    received: list = []
    rec = _make_record("listener", service_id="lst-001")
    registry.register(rec)
    registry.register_callback("lst-001", lambda et, d: received.append((et, d)))

    registry.broadcast_event("test_event", {"key": "value"})
    assert len(received) == 1
    assert received[0] == ("test_event", {"key": "value"})


def test_broadcast_event_multiple_callbacks(registry: ServiceRegistry) -> None:
    calls: list = []
    rec = _make_record("multi_listener", service_id="ml-001")
    registry.register(rec)
    registry.register_callback("ml-001", lambda e, d: calls.append(1))
    registry.register_callback("ml-001", lambda e, d: calls.append(2))

    registry.broadcast_event("ping", {})
    assert sorted(calls) == [1, 2]


def test_broadcast_event_callback_exception_does_not_propagate(registry: ServiceRegistry) -> None:
    rec = _make_record("bad_listener", service_id="bl-001")
    registry.register(rec)
    registry.register_callback("bl-001", lambda e, d: (_ for _ in ()).throw(RuntimeError("cb error")))

    # Should not raise
    registry.broadcast_event("event", {})


def test_broadcast_event_returns_notified_count(registry: ServiceRegistry) -> None:
    for i in range(3):
        rec = _make_record(f"svc_{i}", service_id=f"bcast-{i}")
        registry.register(rec)
        registry.register_callback(f"bcast-{i}", lambda e, d: None)
    count = registry.broadcast_event("bulk_event", {})
    assert count == 3


def test_register_callback_appends(registry: ServiceRegistry) -> None:
    rec = _make_record("cb_svc2", service_id="cb2-001")
    registry.register(rec)
    registry.register_callback("cb2-001", lambda e, d: None)
    registry.register_callback("cb2-001", lambda e, d: None)
    assert len(registry._callbacks["cb2-001"]) == 2


# ---------------------------------------------------------------------------
# SQLite persistence round-trip
# ---------------------------------------------------------------------------


def test_sqlite_persistence_roundtrip(tmp_path: Path) -> None:
    db = str(tmp_path / "reg.db")
    r1 = ServiceRegistry(db_path=db)
    rec = _make_record("persist_svc", service_id="persist-001", capabilities=["cap_a"])
    r1.register(rec)

    # Reload from DB
    r2 = ServiceRegistry(db_path=db)
    loaded = r2.get("persist-001")
    assert loaded is not None
    assert loaded.name == "persist_svc"
    assert "cap_a" in loaded.capabilities


def test_sqlite_deregister_removes_from_db(tmp_path: Path) -> None:
    db = str(tmp_path / "reg.db")
    r1 = ServiceRegistry(db_path=db)
    rec = _make_record("del_svc", service_id="del-001")
    r1.register(rec)
    r1.deregister("del-001")

    r2 = ServiceRegistry(db_path=db)
    assert r2.get("del-001") is None


def test_sqlite_heartbeat_persisted(tmp_path: Path) -> None:
    db = str(tmp_path / "reg.db")
    r1 = ServiceRegistry(db_path=db)
    rec = _make_record("hb_persist", service_id="hbp-001")
    r1.register(rec)
    time.sleep(0.01)
    r1.heartbeat("hbp-001")
    updated_last_seen = r1.get("hbp-001").last_seen

    r2 = ServiceRegistry(db_path=db)
    loaded = r2.get("hbp-001")
    assert loaded is not None
    diff = abs((loaded.last_seen - updated_last_seen).total_seconds())
    assert diff < 1.0


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


def test_get_service_registry_singleton() -> None:
    import engine.observability.service_registry as mod

    orig = mod._registry_instance
    mod._registry_instance = None
    try:
        r1 = get_service_registry()
        r2 = get_service_registry()
        assert r1 is r2
    finally:
        mod._registry_instance = orig


def test_get_service_registry_returns_instance() -> None:
    import engine.observability.service_registry as mod

    orig = mod._registry_instance
    mod._registry_instance = None
    try:
        reg = get_service_registry()
        assert isinstance(reg, ServiceRegistry)
    finally:
        mod._registry_instance = orig
