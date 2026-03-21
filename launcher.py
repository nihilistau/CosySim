#!/usr/bin/env python3
"""
CosySim Launcher
================

Config-driven launcher with clean services / scenes separation.  Reads target
definitions from ``config/launcher.yaml`` via the shared control-plane registry
and supports five target types: flask, streamlit, fastapi, node, and external.

  Services  — persistent infrastructure (hub, nexus_panel, dashboard, tts ...)
  Scenes    — interactive game environments (bedroom, phone, realm ...)

Usage:
  python launcher.py                  # interactive menu
  python launcher.py --core           # auto_start services + scenes  <- recommended
  python launcher.py --services       # auto_start services only
  python launcher.py --scenes         # auto_start scenes only
  python launcher.py --all            # every known target
  python launcher.py bedroom          # single target by name
  python launcher.py nexus_panel      # single service by name
  python launcher.py --list           # show all targets + port status
  python launcher.py --status         # system health check
  python launcher.py --test           # run test suite
  python launcher.py --init-db        # initialise simulation database
  python launcher.py --housekeep      # housekeeping tasks

Auto-start flags live in config/launcher.yaml — edit that file to control
which targets launch with --core / --services / --scenes.

Version: v1.42.1 [2026-03-21]
Author:  CosySim Team

Change Log:
    v1.42.1 [2026-03-21] — Managed Nexus KMS via external type, priority-sorted
                            service launch, _start_external_proc helper
    v1.42.0 [2026-03-21] — Three-pillar architecture (game/service/creation)
    v1.41.0 [2026-03-20] — ARGUS Deep Polish, extended Gemini rpcids
    v1.40.0 [2026-03-19] — Health check aggregator, service discovery registry
"""
from __future__ import annotations

import argparse
import importlib
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.control_plane_registry import LAUNCHER_CONFIG_PATH, PILLAR_IDS, build_launcher_catalogues
from engine.port_registry import get_port, get_target_metadata

# Unicode on Windows cp1252 consoles
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from importlib.metadata import version as _pkg_version
    VERSION = _pkg_version("cosysim")
except Exception:
    VERSION = "1.05b"

# ──── Catalogues ──────────────────────────────────────────────────────────
SERVICES: Dict[str, Dict[str, Any]] = {}
SCENES: Dict[str, Dict[str, Any]] = {}
ALL_TARGETS: Dict[str, Dict[str, Any]] = {}

# ──── Config Loader ───────────────────────────────────────────────────────

_LAUNCHER_CFG = LAUNCHER_CONFIG_PATH


def _load_config() -> None:
    """Rebuild launcher catalogues from the shared control-plane registry."""
    services, scenes, all_targets = build_launcher_catalogues(get_port)
    SERVICES.clear()
    SERVICES.update(services)
    SCENES.clear()
    SCENES.update(scenes)
    ALL_TARGETS.clear()
    ALL_TARGETS.update(all_targets)


_load_config()


# ──── Low-Level Helpers ───────────────────────────────────────────────────

def _port_up(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _import_class(dotted: str):
    mod, cls = dotted.rsplit(".", 1)
    return getattr(importlib.import_module(mod), cls)


def _import_factory(dotted: str):
    mod, fn = dotted.rsplit(".", 1)
    return getattr(importlib.import_module(mod), fn)()


def _hub_url() -> str:
    """Return the canonical hub URL."""
    return f"http://localhost:{get_port('hub')}"


# ──── Single-Target Runner (Foreground / Blocking) ────────────────────────

def _run_single(name: str, info: Dict[str, Any]) -> None:
    """Start one target in the foreground. Blocks until it exits."""
    t = info["type"]
    if t == "flask":
        _import_class(info["cls"])().start()
    elif t == "streamlit":
        script = PROJECT_ROOT / info["script"]
        if not script.exists():
            print(f"Script not found: {script}")
            sys.exit(1)
        subprocess.run([
            sys.executable, "-m", "streamlit", "run", str(script),
            f"--server.port={info['port']}",
            "--server.address=0.0.0.0",
            "--server.headless=true",
            "--browser.gatherUsageStats=false",
            "--logger.level=warning",
        ])
    elif t == "fastapi":
        import uvicorn  # type: ignore
        uvicorn.run(_import_factory(info["factory"]),
                    host="0.0.0.0", port=info["port"], log_level="warning")
    elif t == "node":
        script_dir = PROJECT_ROOT / info["script"]
        subprocess.run(["npm", "run", "dev"], cwd=str(script_dir))
    elif t == "external":
        cwd = info.get("cwd", ".")
        cmd = info.get("cmd", [])
        if not cmd:
            print(f"No 'cmd' defined for external target '{name}'")
            sys.exit(1)
        subprocess.run(cmd, cwd=cwd)
    else:
        print(f"Unknown type '{t}' for '{name}'")
        sys.exit(1)


# ──── Multi-Launch Engine ─────────────────────────────────────────────────

def _start_in_thread(name: str, info: Dict[str, Any],
                     failed: List[str]) -> threading.Thread:
    def _worker() -> None:
        try:
            _run_single(name, info)
        except Exception as exc:
            print(f"\n  {info['label']} crashed: {exc}")
            failed.append(name)
    t = threading.Thread(target=_worker, daemon=True, name=f"cosysim-{name}")
    t.start()
    return t


def _start_streamlit_proc(info: Dict[str, Any],
                           failed: List[str]) -> Optional[subprocess.Popen]:
    script = PROJECT_ROOT / info["script"]
    if not script.exists():
        print(f"  {info['label']}: script not found, skipping")
        failed.append(info["label"])
        return None
    try:
        return subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", str(script),
             f"--server.port={info['port']}",
             "--server.headless=true",
             "--server.address=0.0.0.0",
             "--browser.gatherUsageStats=false",
             "--logger.level=warning"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        print(f"  {info['label']}: {exc}")
        failed.append(info["label"])
        return None


def _start_node_proc(info: Dict[str, Any],
                     failed: List[str]) -> Optional[subprocess.Popen]:
    """Start a Node.js service via 'npm run dev' in the given script directory."""
    script_dir = PROJECT_ROOT / info["script"]
    if not script_dir.exists():
        print(f"  {info['label']}: directory not found, skipping")
        failed.append(info["label"])
        return None
    try:
        return subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=str(script_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        print(f"  {info['label']}: {exc}")
        failed.append(info["label"])
        return None


# v1.42.1 [2026-03-21] — External process launcher for managed services (Nexus KMS)
def _start_external_proc(info: Dict[str, Any],
                          failed: List[str]) -> Optional[subprocess.Popen]:
    """Start an external service via subprocess (e.g. Nexus KMS).

    External targets define their own ``cmd`` and ``cwd`` in launcher.yaml.
    The launcher spawns the process and optionally waits for its health port.
    """
    cwd = info.get("cwd", ".")
    cmd = info.get("cmd", [])
    if not cmd:
        print(f"  {info['label']}: no cmd defined, skipping")
        failed.append(info["label"])
        return None
    if not Path(cwd).is_dir():
        print(f"  {info['label']}: directory {cwd} not found, skipping")
        failed.append(info["label"])
        return None
    try:
        return subprocess.Popen(
            cmd, cwd=cwd,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        print(f"  {info['label']}: {exc}")
        failed.append(info["label"])
        return None


def launch_multi(service_names: List[str], scene_names: List[str]) -> None:
    """
    Launch services first (let them settle), then scenes.
    Flask/FastAPI targets run in daemon threads.
    Streamlit targets get isolated subprocesses.
    Blocks until Ctrl+C.
    """
    total = len(service_names) + len(scene_names)
    if total == 0:
        print("Nothing to launch. Check auto_start flags in config/launcher.yaml.")
        return

    box_w = 62
    print(f"\n{'=' * (box_w + 2)}")
    print(f"  CosySim v{VERSION}")
    print(f"{'=' * (box_w + 2)}")
    if service_names:
        print("  SERVICES:")
        for n in service_names:
            i = ALL_TARGETS[n]
            print(f"    {i['label']:.<35s} :{i['port']}")
    if scene_names:
        print("  SCENES:")
        for n in scene_names:
            i = ALL_TARGETS[n]
            print(f"    {i['label']:.<35s} :{i['port']}")
    print(f"  Ctrl+C to stop all")
    print(f"{'=' * (box_w + 2)}\n")

    all_procs: List[subprocess.Popen] = []
    failed: List[str] = []

    def _launch_group(names: List[str], group: str) -> None:
        if not names:
            return
        print(f"  Starting {group}...")
        for name in names:
            info = ALL_TARGETS[name]
            if info["type"] == "streamlit":
                proc = _start_streamlit_proc(info, failed)
                if proc:
                    all_procs.append(proc)
                    print(f"    [OK] {info['label']} (PID {proc.pid})")
            elif info["type"] == "node":
                proc = _start_node_proc(info, failed)
                if proc:
                    all_procs.append(proc)
                    print(f"    [OK] {info['label']} (PID {proc.pid})")
            elif info["type"] == "external":  # v1.42.1 — external type handler
                proc = _start_external_proc(info, failed)
                if proc:
                    all_procs.append(proc)
                    # Wait up to 15s for external service to come online
                    port = info["port"]
                    for _wait in range(15):
                        if _port_up(port):
                            break
                        time.sleep(1)
                    status = "UP" if _port_up(port) else "starting"
                    print(f"    [OK] {info['label']} (PID {proc.pid}, {status})")
            else:
                _start_in_thread(name, info, failed)
                print(f"    [OK] {info['label']} -> :{info['port']}")
            time.sleep(0.4)

    # ── v1.51.0 [2026-03-22] — Four-phase launch with proper ordering ────
    # Phase A: External services (Nexus KMS) — wait for port UP
    # Phase B: World infrastructure (daemons BEFORE scenes)
    # Phase C: Flask/FastAPI services
    # Phase D: Game scenes — with per-target health verification

    # ── Phase A: External + internal services ────────────────────────
    service_names_sorted = sorted(
        service_names,
        key=lambda n: ALL_TARGETS[n].get("start_priority", 50),
    )
    _launch_group(service_names_sorted, "Services")

    # ── Phase B: World infrastructure (BEFORE scenes) ────────────────
    # v1.51.0 — Daemons start before scenes so event subscriptions work
    if scene_names:
        print("\n  Starting World Infrastructure...")
        _daemons = [
            ("WorldSim",       "engine.world.world_sim",           "get_world_sim",        "start"),
            ("CrossSceneRelay","engine.events.cross_scene_relay",  "get_cross_scene_relay", "start"),
            ("EventCascade",   "engine.world.event_cascade",       "get_event_cascade",     "start"),
        ]
        for label, mod, getter, method in _daemons:
            try:
                import importlib as _il
                m = _il.import_module(mod)
                obj = getattr(m, getter)()
                getattr(obj, method)()
                print(f"    [OK] {label}")
            except Exception as exc:
                print(f"    [--] {label}: {exc}")

        # Scheduler + feedback loops (non-critical, best-effort)
        for label, mod, getter, setup in [
            ("Scheduler", "engine.nexus.scheduler_daemon", "get_scheduler_daemon", "start"),
            ("AutoLoop",  "engine.nexus.auto_loop",        "get_auto_loop",        "register_tasks"),
            ("ConvSync",  "engine.nexus.conversation_sync", "get_conversation_sync","register_task"),
        ]:
            try:
                import importlib as _il
                m = _il.import_module(mod)
                obj = getattr(m, getter)()
                result = getattr(obj, setup)()
                detail = f" ({result} tasks)" if isinstance(result, int) else ""
                print(f"    [OK] {label}{detail}")
            except Exception as exc:
                print(f"    [--] {label}: {exc}")

    # ── Phase C+D: Scenes ────────────────────────────────────────────
    if service_names_sorted and scene_names:
        time.sleep(1)
    _launch_group(scene_names, "Scenes")

    # ── Per-target health verification ───────────────────────────────
    # v1.51.0 — Wait for each scene to actually bind its port
    if scene_names:
        print("\n  Health check (waiting for ports)...")
        for name in scene_names:
            port = ALL_TARGETS[name]["port"]
            label = ALL_TARGETS[name]["label"]
            up = False
            for _ in range(20):  # 10 seconds max
                if _port_up(port):
                    up = True
                    break
                time.sleep(0.5)
            icon = "[UP]" if up else "[FAIL]"
            print(f"    {icon} {label:.<35s} :{port}")
            if not up:
                failed.append(name)

    # Service health (quick check, already running)
    if service_names:
        for name in service_names:
            port = ALL_TARGETS[name]["port"]
            label = ALL_TARGETS[name]["label"]
            icon = "[UP]" if _port_up(port) else "[--]"
            print(f"    {icon} {label:.<35s} :{port}")

    print(f"\n  {total} target(s) launched.  Hub -> {_hub_url()}\n")

    # ── Watchdog loop ────────────────────────────────────────────────
    # v1.51.0 — Reports dead scenes every 30s instead of 60s
    try:
        signal.signal(signal.SIGINT, signal.default_int_handler)
        while True:
            time.sleep(30)
            down = [n for n in service_names + scene_names
                    if not _port_up(ALL_TARGETS[n]["port"])]
            if down:
                labels = [ALL_TARGETS[n]["label"] for n in down]
                print(f"  [WARN] Not responding: {', '.join(labels)}")
    except KeyboardInterrupt:
        print("\n  Shutting down...")
        # Gracefully stop world systems before killing subprocesses
        for mod, getter, method in [
            ("engine.world.world_sim", "get_world_sim", "stop"),
            ("engine.world.event_cascade", "get_event_cascade", "stop"),
            ("engine.events.cross_scene_relay", "get_cross_scene_relay", "stop"),
        ]:
            try:
                import importlib as _il
                m = _il.import_module(mod)
                getattr(getattr(m, getter)(), method)()
            except Exception:
                pass
        for proc in all_procs:
            try:
                proc.terminate()
            except Exception:
                pass
        print("  Done.\n")



# ──── High-Level Launchers ────────────────────────────────────────────────

def launch_core() -> None:
    """Start all auto_start services then all auto_start scenes."""
    svcs = [n for n, i in SERVICES.items() if i.get("auto_start")]
    scns = [n for n, i in SCENES.items()   if i.get("auto_start")]
    launch_multi(svcs, scns)


def launch_services_cmd(only_auto: bool = True) -> None:
    targets = [n for n, i in SERVICES.items() if not only_auto or i.get("auto_start")]
    launch_multi(targets, [])


def launch_scenes_cmd(only_auto: bool = True) -> None:
    targets = [n for n, i in SCENES.items() if not only_auto or i.get("auto_start")]
    launch_multi([], targets)


def launch_all() -> None:
    launch_multi(list(SERVICES), list(SCENES))


def launch_pillar(pillar: str) -> None:
    """Start all targets belonging to *pillar* (game, service, creation)."""
    target_ids = PILLAR_IDS.get(pillar, ())
    if not target_ids:
        print(f"  Unknown pillar: '{pillar}'")
        sys.exit(1)
    svcs = [t for t in target_ids if t in SERVICES]
    scns = [t for t in target_ids if t in SCENES]
    print(f"\n  Launching {pillar.upper()} pillar ({len(svcs)} services, {len(scns)} scenes)")
    launch_multi(svcs, scns)


def launch_single(name: str) -> None:
    info = ALL_TARGETS.get(name)
    if not info:
        print(f"Unknown target: '{name}'")
        print(f"  Services : {', '.join(SERVICES)}")
        print(f"  Scenes   : {', '.join(SCENES)}")
        sys.exit(1)
    group = "service" if name in SERVICES else "scene"
    print(f"\n  Starting {group} '{info['label']}' -> http://localhost:{info['port']}")
    _run_single(name, info)


# ──── Info Commands ───────────────────────────────────────────────────────

def cmd_list() -> None:
    print(f"\n  CosySim v{VERSION} -- Target List")
    print(f"  Config: {_LAUNCHER_CFG}\n")

    # Show pillar-grouped view
    pillar_labels = {"game": "NEONCITY (GAME)", "service": "SYSTEM SERVICES", "creation": "CREATION KIT"}
    for pillar, label in pillar_labels.items():
        ids = PILLAR_IDS.get(pillar, ())
        print(f"  -- {label} ({len(ids)}) " + "-" * 40)
        print(f"  {'name':<20}  {'port':>5}  auto  status  label")
        print(f"  {'-' * 56}")
        for tid in ids:
            info = ALL_TARGETS.get(tid, {})
            if not info:
                continue
            up   = "UP  " if _port_up(info["port"]) else "down"
            auto = "[x]" if info.get("auto_start") else "   "
            print(f"  {tid:<20}  {info['port']:>5}  {auto}  {up}    {info['label']}")
        print()


def cmd_status() -> None:
    print(f"\n  CosySim v{VERSION} -- System Status")
    print(f"  Python {sys.version.split()[0]}  |  {PROJECT_ROOT}\n")

    print("  External Services:")
    for target_id in ("lmstudio", "comfyui"):
        meta = get_target_metadata(target_id)
        print(f"    {'[UP]' if _port_up(meta['port']) else '[--]'} {meta['label']:.<22} :{meta['port']}")

    print("\n  Services:")
    for name, info in SERVICES.items():
        auto = "[auto]" if info.get("auto_start") else "      "
        print(f"    {'[UP]' if _port_up(info['port']) else '[--]'} "
              f"{name:.<22} :{info['port']}  {auto}  {info['label']}")

    print("\n  Scenes:")
    for name, info in SCENES.items():
        auto = "[auto]" if info.get("auto_start") else "      "
        print(f"    {'[UP]' if _port_up(info['port']) else '[--]'} "
              f"{name:.<22} :{info['port']}  {auto}  {info['label']}")

    print(f"\n  Edit {_LAUNCHER_CFG.name} to toggle auto_start flags.\n")


def cmd_test() -> None:
    try:
        import pytest
    except ImportError:
        print("pytest not installed.")
        sys.exit(1)
    sys.exit(pytest.main([
        "tests/", "-v", "--tb=short", "--color=yes",
        "--ignore=tests/test_agent_loop.py",
        "--ignore=tests/live_wire_test.py",
    ]))


def cmd_init_db() -> None:
    from content.simulation.database.db import Database
    try:
        db = Database()
        print(f"Database at {db.db_path}")
        with db.get_connection() as conn:
            cur = conn.cursor()
            for table in ["characters", "personalities", "roles", "conversations",
                          "interactions", "media", "character_states"]:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    print(f"  {table}: {cur.fetchone()[0]} rows")
                except Exception:
                    print(f"  {table}: not found")
    except Exception as exc:
        print(f"Error: {exc}")
        sys.exit(1)


# ──── Interactive Menu ────────────────────────────────────────────────────

def interactive_menu() -> None:
    def _format_targets(names: List[str], per_line: int = 6) -> str:
        lines = []
        for start in range(0, len(names), per_line):
            chunk = "  ".join(names[start:start + per_line])
            lines.append(f"    {chunk}")
        return "\n".join(lines)

    print(f"""
=================================================================
  CosySim v{VERSION}  --  AI Agent Simulation Framework
=================================================================

  Launch Groups:
    core      -- auto_start services + scenes  (recommended)
    services  -- auto_start services only
    scenes    -- auto_start scenes only
    all       -- every known target

  Single Scene  (type name):
{_format_targets(list(SCENES))}

  Single Service  (type name):
{_format_targets(list(SERVICES))}

  Info & Tools:
    list | status | test | init-db | housekeep | q (quit)

=================================================================
""")
    try:
        choice = input("  Select: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nGoodbye!")
        return

    if not choice or choice in ("q", "quit"):
        return
    if choice == "core":
        launch_core()
    elif choice == "services":
        launch_services_cmd()
    elif choice == "scenes":
        launch_scenes_cmd()
    elif choice == "all":
        launch_all()
    elif choice == "list":
        cmd_list()
    elif choice == "status":
        cmd_status()
    elif choice == "test":
        cmd_test()
    elif choice == "init-db":
        cmd_init_db()
    elif choice == "housekeep":
        from engine.services.housekeeping import HousekeepingService
        HousekeepingService().run_all()
    elif choice in ALL_TARGETS:
        launch_single(choice)
    else:
        print(f"  Unknown: '{choice}' -- try 'list' to see all targets.")


# ──── CLI Entry Point ────────────────────────────────────────────────────

def main() -> None:
    _load_config()  # apply launcher.yaml overrides before parsing

    parser = argparse.ArgumentParser(
        description=f"CosySim v{VERSION} -- AI Agent Simulation Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --core              # auto_start services + scenes
  %(prog)s --services          # auto_start services only
  %(prog)s --scenes            # auto_start scenes only
  %(prog)s --all               # start everything
  %(prog)s bedroom             # start a single scene
  %(prog)s nexus_panel         # start a single service
  %(prog)s --list              # list all targets + port status
  %(prog)s --status            # system health check
  %(prog)s --test              # run test suite
""",
    )
    parser.add_argument("target",      nargs="?",          help="Single target name to start")
    parser.add_argument("--core",      action="store_true", help="Start auto_start services + scenes")
    parser.add_argument("--services",  action="store_true", help="Start auto_start services only")
    parser.add_argument("--scenes",    action="store_true", help="Start auto_start scenes only")
    parser.add_argument("--all",       action="store_true", help="Start every known target")
    parser.add_argument("--list",      action="store_true", help="List all targets + port status")
    parser.add_argument("--game",      action="store_true", help="Start all game pillar scenes")
    parser.add_argument("--creation",  action="store_true", help="Start all creation pillar targets")
    parser.add_argument("--status",    action="store_true", help="System health check")
    parser.add_argument("--test",      action="store_true", help="Run test suite")
    parser.add_argument("--init-db",   action="store_true", dest="init_db",
                        help="Initialise simulation database")
    parser.add_argument("--housekeep", action="store_true", help="Run housekeeping tasks")
    parser.add_argument("--watch",     action="store_true", help="With --housekeep: run continuously")
    parser.add_argument("--version",   action="version",    version=f"CosySim v{VERSION}")
    # Legacy shims (silent)
    parser.add_argument("--mode",  default=None, help=argparse.SUPPRESS)
    parser.add_argument("--scene", default=None, help=argparse.SUPPRESS)

    args = parser.parse_args()

    # Legacy --mode shim
    if args.mode and not args.target:
        mode_map = {"all": None, "core": None, "test": None}
        if args.mode not in mode_map:
            args.target = args.mode
        elif args.mode == "all":
            args.all = True
        elif args.mode == "core":
            args.core = True
        elif args.mode == "test":
            args.test = True
    if args.scene and not args.target:
        args.target = args.scene

    if args.list:
        cmd_list()
    elif args.status:
        cmd_status()
    elif args.test:
        cmd_test()
    elif args.init_db:
        cmd_init_db()
    elif args.housekeep:
        from engine.services.housekeeping import HousekeepingService
        hk = HousekeepingService()
        hk.watch() if args.watch else hk.run_all()
    elif args.core:
        launch_core()
    elif args.game:
        launch_pillar("game")
    elif args.creation:
        launch_pillar("creation")
    elif args.services:
        launch_services_cmd()
    elif args.scenes:
        launch_scenes_cmd()
    elif args.all:
        launch_all()
    elif args.target:
        launch_single(args.target)
    else:
        interactive_menu()


if __name__ == "__main__":
    main()
