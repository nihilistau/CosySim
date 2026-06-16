"""
Shared pytest fixtures for CosySim tests.

Provides isolated database, config, and EventChain instances per test.

Pytest plugin flags:
    --affected     Only run tests for files changed since HEAD (git diff)
    --staged       Only run tests for staged files (git diff --cached)
    --since REF    Only run tests for files changed since REF (e.g. HEAD~3)
    --smoke-only   Run only the ~15 smoke-test files (one per domain)
    --cap N        Max test files to run; falls back to smoke if exceeded (default: 80)
"""
# v1.63.0 [2026-06-17] — Pre-seed platform.uname() BEFORE any engine imports.
# On this Windows host, a bare ``pytest`` collection hangs (~40s+ / indefinitely)
# because importing engine code transitively calls ``platform.uname()``, which on
# a cold cache fires a slow/contended Windows WMI query. On this Python build both
# the lazy ``processor`` lookup and ``platform.node()`` also probe WMI — node()
# was verified to hang for 60s here — so we use a LITERAL hostname instead of
# calling node(). Seeding ``platform._uname_cache`` up front makes every later
# ``uname()`` call a trivial cache read, eliminating the collection hang
# suite-wide. This block must run above all other (engine) imports; pytest imports
# conftest.py before test collection, so the cache is warm in time.
import collections as _collections
import platform as _platform

# Version-proof: don't rely on ``uname_result``'s constructor accepting a 6th
# positional ``processor`` arg (it raises TypeError on this build), and don't
# leave ``.processor`` lazy (accessing it re-probes WMI). Build a plain, fully
# populated namedtuple and STUB both WMI-backed functions so NO code path
# (``platform.uname()``, ``platform.uname().processor``, or the separate
# ``platform.processor()``) can trigger the slow Windows WMI lookup.
_UNAME = _collections.namedtuple(
    "uname_result", "system node release version machine processor"
)("Windows", "localhost", "11", "10.0.26200", "AMD64", "AMD64")
_platform._uname_cache = _UNAME
_platform.uname = lambda: _UNAME          # first-call uname WMI probe -> constant
_platform.processor = lambda: "AMD64"     # separate processor() WMI probe -> constant

import gc
import sys
import os
import subprocess
import tempfile
import sqlite3
from pathlib import Path
from typing import List, Set
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def temp_db_path(tmp_path):
    """Return a temporary SQLite database path."""
    return str(tmp_path / "test.db")


@pytest.fixture
def temp_db(temp_db_path):
    """Create a fresh Database instance pointing at a temp file."""
    from content.simulation.database.db import Database
    db = Database(temp_db_path)
    return db


@pytest.fixture
def event_chain(temp_db):
    """Create an EventChain backed by a temp database."""
    from content.simulation.database.events import EventChain
    return EventChain(db=temp_db)


# Modules that tests may replace with fakes; restore originals after each test.
_PROTECTED_MODULES = [
    "flask",
    "flask_socketio",
    "engine.world.world_state",
    "engine.world.world_sim",
]


# v1.62.0 [2026-06-15] — Close lingering SQLite handles after every test so
# Windows can delete the per-test tmp_path dirs. The training/metrics classes
# (MetricsDB, MetaMetrics) keep a thread-local WAL connection open for the life
# of the object; pytest's tmp_path_factory retains the last few temp dirs and
# rmtree's older ones during a *later* test, which raised
# ``PermissionError: [WinError 32]`` while that handle was still open. Forcing a
# gc pass once the test's fixture objects have gone out of scope finalises those
# connections (sqlite3.Connection releases its file handle on collection) before
# the next rmtree runs. The per-test tmp dirs themselves are already unique
# (pytest tmp_path), so this is purely a handle-lifetime fix, not a shared-dir one.
@pytest.fixture(autouse=True)
def _release_db_handles():
    yield
    # Close the DB-backed singletons whose open connection would otherwise
    # outlive this test and block rmtree on Windows. Closing the handle directly
    # is order-independent: it works even while a module global still references
    # the object. The gc pass then finalises any non-singleton instances (held
    # only by the test) and mops up TrainingFlywheel's per-call connections.
    _wipe_db_singletons()
    gc.collect()


def _wipe_db_singletons() -> None:
    """Close + clear the metrics/training DB singletons (handle-release)."""
    try:
        import engine.observability.metrics_db as _m
        if getattr(_m, "_instance", None) is not None:
            try:
                _m._instance.close()
            except Exception:
                pass
            _m._instance = None
    except Exception:
        pass
    try:
        import engine.nexus.meta_metrics as _m
        if getattr(_m, "_metrics", None) is not None:
            try:
                _m._metrics.close()
            except Exception:
                pass
            _m._metrics = None
    except Exception:
        pass
    try:
        import engine.lmstudio.router_data as _m
        if getattr(_m.RouterDataCollector, "_instance", None) is not None:
            _m.RouterDataCollector._instance = None
    except Exception:
        pass
    try:
        import engine.nexus.training_flywheel as _m
        _m._flywheel = None
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _restore_protected_modules():
    """Restore sys.modules entries that test isolation bugs may have replaced."""
    saved = {k: sys.modules.get(k) for k in _PROTECTED_MODULES}
    yield
    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


@pytest.fixture
def mock_config():
    """Return a dict-based mock config that mimics get_config()."""
    # v1.49.1 [2026-03-22] — Expanded defaults to cover more config paths
    defaults = {
        "lmstudio.base_url": "http://localhost:1234",
        "comfyui.base_url": "http://localhost:8188",
        "comfyui.output_dir": "data/art/output",
        "tts.engine": "placeholder",
        "database.path": ":memory:",
        "hardware.vram_cap_mb": 11500,
        "nexus.base_url": "http://localhost:8700",
        "nexus.enabled": False,
        "paths.project_root": str(Path(__file__).resolve().parent.parent),
        "paths.data_dir": "data",
        "mcp.enabled": True,
        "scenes.default_port": 5555,
    }
    mock = MagicMock()
    mock.get = lambda key, default=None: defaults.get(key, default)
    return mock


def _wipe_singletons() -> None:
    """Set all stateful module-level singletons back to None.

    SKILL_REGISTRY is intentionally excluded — @skill decorators fire only
    once at import time and the registry is safe to share across modules.
    """
    try:
        import engine.config as _m
        _m._config_instance = None
    except Exception:
        pass
    try:
        import engine.port_registry as _m
        _m._registry = None
        if hasattr(_m, "_control_plane_catalogue"):
            _m._control_plane_catalogue.cache_clear()
    except Exception:
        pass
    try:
        import engine.mcp.framework as _m
        _m._FW_INSTANCE = None
    except Exception:
        pass
    try:
        import engine.mcp.character_registry as _m
        _m._REGISTRY_INSTANCE = None
    except Exception:
        pass
    try:
        import engine.mcp.dialog_system as _m
        _m._DIALOG_INSTANCE = None
    except Exception:
        pass
    try:
        import engine.mcp.scene_rules_engine as _m
        _m._ENGINE_INSTANCE = None
    except Exception:
        pass
    try:
        import engine.mcp.scene_state as _m
        _m._SSM_INSTANCE = None
    except Exception:
        pass
    try:
        import engine.world.world_state as _m
        _m._WORLD_STATE = None
    except Exception:
        pass
    try:
        import engine.world.world_sim as _m
        _m._WORLD_SIM = None
    except Exception:
        pass
    try:
        import engine.world.player_state as _m
        _m._PLAYER_STATE = None
    except Exception:
        pass
    # v1.49.1 [2026-03-22] — Add missing singleton clears for comms_framework,
    # LMStudio manager, and Nexus client to prevent test contamination
    try:
        import engine.mcp.comms_framework as _m
        _m._manifest = None
        _m._game_state = None
        _m._router = None
    except Exception:
        pass
    try:
        import engine.lmstudio.lmstudio_manager as _m
        if hasattr(_m, "_instance"):
            _m._instance = None
    except Exception:
        pass
    try:
        import engine.nexus.client as _m
        if hasattr(_m, "_client"):
            _m._client = None
    except Exception:
        pass
    # v1.62.0 [2026-06-15] — Reset the training/metrics DB singletons. The
    # test_singleton_* cases store a MetricsDB/MetaMetrics (each holding an open
    # thread-local WAL connection) in these module globals; left set, the handle
    # outlives the test's tmp_path dir and blocks rmtree on Windows (WinError 32).
    # Close the connection before clearing so the backing file is released.
    _wipe_db_singletons()


@pytest.fixture(autouse=True, scope="module")
def _reset_singletons_per_module():
    """Wipe stateful singletons before and after each test module.

    This prevents cross-module contamination where module A creates real
    singleton objects that module B's mocked tests inadvertently pick up.
    Within a single test module, singletons persist normally.
    """
    _wipe_singletons()
    yield
    _wipe_singletons()


# ──── Optional-dependency skip markers ───────────────────────────────────────

def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:  # type: ignore[type-arg]
    """Auto-skip tests that require optional heavy deps (torch, etc.) when unavailable.

    Also handles --affected / --staged / --smoke-only filtering.
    """
    try:
        import torch  # noqa: F401
        _torch_ok = True
    except ImportError:
        _torch_ok = False

    if not _torch_ok:
        skip_torch = pytest.mark.skip(reason="torch not installed — skipping GPU/native-TTS tests")
        _torch_test_files = {"test_orpheus_native.py"}
        for item in items:
            if Path(item.fspath).name in _torch_test_files:
                item.add_marker(skip_torch)

    # ── Affected / staged / smoke filtering ──────────────────────────────
    affected = config.getoption("--affected", default=False)
    staged = config.getoption("--staged", default=False)
    smoke_only = config.getoption("--smoke-only", default=False)
    since_ref = config.getoption("--since", default=None)
    cap = int(config.getoption("--cap", default=80))

    if not (affected or staged or smoke_only or since_ref):
        return

    from scripts.smart_test import (
        _git_changed_files,
        _domains_for_file,
        _resolve_test_files,
        _tests_for_domains,
        _ordered_unique,
        SMOKE_TESTS,
    )

    allowed_files: Set[str] = set()

    if smoke_only:
        for p in _resolve_test_files(SMOKE_TESTS):
            allowed_files.add(p.name)
    else:
        # Determine git ref
        if staged:
            ref = "_staged"
        elif since_ref:
            ref = since_ref
        else:
            ref = "HEAD"

        # Get changed files
        if ref == "_staged":
            result = subprocess.run(
                ["git", "diff", "--name-only", "--cached"],
                capture_output=True, text=True, cwd=str(PROJECT_ROOT),
            )
            changed = [f for f in result.stdout.strip().splitlines() if f]
        else:
            changed = _git_changed_files(since=ref)

        if not changed:
            # No changes — run nothing extra, let pytest defaults handle it
            return

        # Map to domains
        ordered_domains: List[str] = []
        trigger_smoke = False
        for f in changed:
            domains = _domains_for_file(f)
            if "_smoke" in domains:
                trigger_smoke = True
            for domain in domains:
                if not domain.startswith("_") and domain not in ordered_domains:
                    ordered_domains.append(domain)

        # Add _self for directly changed test files
        requested = []
        if any("_self" in _domains_for_file(f) for f in changed):
            requested.append("_self")
        requested.extend(ordered_domains)

        if trigger_smoke:
            test_files = _resolve_test_files(SMOKE_TESTS)
        else:
            test_files = _tests_for_domains(requested, changed_files=changed)

        # Cap check — if too many files, fall back to smoke
        if len(test_files) > cap:
            config._affected_capped = True  # type: ignore[attr-defined]
            print(
                f"\n[smart-test] {len(test_files)} files affected (cap={cap}) "
                f"— falling back to smoke tests ({len(SMOKE_TESTS)} files)"
            )
            test_files = _resolve_test_files(SMOKE_TESTS)

        for p in test_files:
            allowed_files.add(p.name)

    if not allowed_files:
        return

    # Deselect items not in the allowed set
    deselected = []
    selected = []
    for item in items:
        fname = Path(item.fspath).name
        if fname in allowed_files:
            selected.append(item)
        else:
            deselected.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register --affected, --staged, --smoke-only, --since, --cap flags."""
    group = parser.getgroup("smart-test", "CosySim smart test selection")
    group.addoption(
        "--affected",
        action="store_true",
        default=False,
        help="Only run tests for files changed since HEAD (uncommitted changes).",
    )
    group.addoption(
        "--staged",
        action="store_true",
        default=False,
        help="Only run tests for staged files (git diff --cached).",
    )
    group.addoption(
        "--smoke-only",
        action="store_true",
        default=False,
        help="Run only smoke tests (~15 files, one per domain).",
    )
    group.addoption(
        "--since",
        default=None,
        help="Only run tests for files changed since REF (e.g. HEAD~3).",
    )
    group.addoption(
        "--cap",
        default="80",
        help="Max test files before falling back to smoke (default: 80).",
    )


def pytest_report_header(config: pytest.Config) -> List[str]:
    """Show smart-test mode in the pytest header."""
    lines: List[str] = []
    if config.getoption("--affected", default=False):
        lines.append("smart-test: --affected (uncommitted changes)")
    elif config.getoption("--staged", default=False):
        lines.append("smart-test: --staged (staged changes only)")
    elif config.getoption("--smoke-only", default=False):
        lines.append("smart-test: --smoke-only")
    elif config.getoption("--since", default=None):
        lines.append(f"smart-test: --since {config.getoption('--since')}")
    if hasattr(config, "_affected_capped"):
        lines.append("smart-test: CAPPED — too many affected files, using smoke tests")
    return lines
