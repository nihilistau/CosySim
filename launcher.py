#!/usr/bin/env python3
"""
CosySim Launcher v4
====================
Config-driven launcher with clean services / scenes separation.

  Services  — persistent infrastructure (hub, nexus_panel, dashboard, tts …)
  Scenes    — interactive game environments (bedroom, phone, realm …)

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

Auto-start flags live in config/launcher.yaml - edit that file to control
which targets launch with --core / --services / --scenes.
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

# Unicode on Windows cp1252 consoles
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

VERSION = "0.76b"

# ── Catalogues ────────────────────────────────────────────────────────────
# type: "flask" | "streamlit" | "fastapi"
# auto_start defaults here; config/launcher.yaml overrides them at runtime.

SERVICES: Dict[str, Dict[str, Any]] = {
    "hub": {
        "type": "flask",
        "cls":  "content.scenes.hub.hub_flask.HubScene",
        "port": 8500, "label": "CosySim Hub",
        "auto_start": True,
    },
    "nexus_panel": {
        "type": "flask",
        "cls":  "content.scenes.nexus_panel.nexus_panel_scene.NexusPanelScene",
        "port": 5570, "label": "Nexus Control Panel",
        "auto_start": True,
    },
    "dashboard": {
        "type": "streamlit",
        "script": "content/scenes/dashboard/dashboard_v2.py",
        "port": 8501, "label": "System Dashboard",
        "auto_start": False,
    },
    "admin": {
        "type": "streamlit",
        "script": "content/scenes/admin/admin_panel.py",
        "port": 8502, "label": "Admin Panel",
        "auto_start": False,
    },
    "assets": {
        "type": "streamlit",
        "script": "content/scenes/assets/asset_generator.py",
        "port": 8503, "label": "Asset Generator",
        "auto_start": False,
    },
    "creator": {
        "type": "streamlit",
        "script": "content/scenes/hub/scene_creator.py",
        "port": 8504, "label": "Scene Creator",
        "auto_start": False,
    },
    "tts": {
        "type": "fastapi",
        "factory": "engine.tts.qwen3_server.create_tts_app",
        "port": 8600, "label": "TTS Server",
        "auto_start": False,
    },
    "bridge": {
        "type": "fastapi",
        "factory": "engine.mcp.web_bridge.create_bridge_app",
        "port": 8601, "label": "MCP Bridge",
        "auto_start": False,
    },
    "nlm_proxy": {
        "type": "flask",
        "cls":  "engine.mcp.nlm_live_proxy.NLMProxyServer",
        "port": 8800, "label": "NLM Live Proxy",
        "auto_start": False,
    },
    "system_control": {
        "type": "flask",
        "cls": "content.scenes.system_control.system_control_scene.SystemControlScene",
        "port": 5575, "label": "System Control Panel",
        "auto_start": True,
    },
}

SCENES: Dict[str, Dict[str, Any]] = {
    "phone":          {"type": "flask", "cls": "content.scenes.phone.phone_scene_v2.PhoneSceneV2",
                       "port": 5555, "label": "SIGNAL",                 "auto_start": True},
    "bedroom":        {"type": "flask", "cls": "content.scenes.bedroom.bedroom_scene.BedroomScene",
                       "port": 5556, "label": "THE PENTHOUSE",          "auto_start": True},
    "lounge":         {"type": "flask", "cls": "content.scenes.lounge.lounge_scene.LoungeScene",
                       "port": 5557, "label": "THE VELVET PIT",         "auto_start": False},
    "tavern":         {"type": "flask", "cls": "content.scenes.tavern.tavern_scene.TavernScene",
                       "port": 5558, "label": "THE RUSTY ANCHOR",       "auto_start": False},
    "casino":         {"type": "flask", "cls": "content.scenes.casino.casino_scene.CasinoScene",
                       "port": 5559, "label": "CLUB NOIR",              "auto_start": False},
    "gallery":        {"type": "flask", "cls": "content.scenes.gallery.gallery_scene.GalleryScene",
                       "port": 5560, "label": "THE OBSCURA",            "auto_start": False},
    "arena":          {"type": "flask", "cls": "content.scenes.arena.ArenaScene",
                       "port": 5561, "label": "THE COLOSSEUM",          "auto_start": False},
    "realm":          {"type": "flask", "cls": "content.scenes.realm.realm_scene.RealmScene",
                       "port": 5562, "label": "THE SHATTERED THRONE",   "auto_start": False},
    "neoncity":       {"type": "flask", "cls": "content.scenes.neoncity.neoncity_scene.NeonCityScene",
                       "port": 5563, "label": "NEON CITY",              "auto_start": False},
    "coders":         {"type": "flask", "cls": "content.scenes.coders.coders_scene.CodersRoomScene",
                       "port": 5564, "label": "THE LAB",                "auto_start": False},
    "heist":          {"type": "flask", "cls": "content.scenes.heist.heist_scene.HeistScene",
                       "port": 5565, "label": "THE SCORE",              "auto_start": False},
    "command_center": {"type": "flask",
                       "cls": "content.scenes.command_center.command_center_scene.CommandCenterScene",
                       "port": 5566, "label": "Command Center",         "auto_start": False},
    "games":          {"type": "flask", "cls": "content.scenes.games.games_scene.GamesScene",
                       "port": 5567, "label": "THE ARCADE",             "auto_start": False},
    "grid":           {"type": "flask", "cls": "content.scenes.grid.grid_scene.GridScene",
                       "port": 5569, "label": "THE GRID",               "auto_start": False},
    "intel_hub":      {"type": "flask",
                       "cls": "content.scenes.intel_hub.intel_hub_scene.IntelHubScene",
                       "port": 5580, "label": "THE BRIEFING ROOM",      "auto_start": False},
    "asset_studio":   {"type": "flask",
                       "cls": "content.scenes.asset_studio.asset_studio_scene.AssetStudioScene",
                       "port": 5568, "label": "ASSET STUDIO",           "auto_start": False},
}

ALL_TARGETS: Dict[str, Dict[str, Any]] = {**SERVICES, **SCENES}

# ── Config loader ─────────────────────────────────────────────────────────

_LAUNCHER_CFG = PROJECT_ROOT / "config" / "launcher.yaml"


def _load_config() -> None:
    """Apply auto_start overrides from config/launcher.yaml."""
    if not _LAUNCHER_CFG.exists():
        return
    try:
        import yaml  # type: ignore
        with open(_LAUNCHER_CFG) as fh:
            cfg = yaml.safe_load(fh) or {}
        for group_key, catalogue in (("services", SERVICES), ("scenes", SCENES)):
            for name, settings in (cfg.get(group_key) or {}).items():
                if name in catalogue and isinstance(settings, dict):
                    if "auto_start" in settings:
                        catalogue[name]["auto_start"] = bool(settings["auto_start"])
    except Exception as exc:
        print(f"  Warning: launcher.yaml load error: {exc}")


# ── Low-level helpers ─────────────────────────────────────────────────────

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


# ── Single-target runner (foreground / blocking) ──────────────────────────

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
    else:
        print(f"Unknown type '{t}' for '{name}'")
        sys.exit(1)


# ── Multi-launch engine ───────────────────────────────────────────────────

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
            else:
                _start_in_thread(name, info, failed)
                print(f"    [OK] {info['label']} -> :{info['port']}")
            time.sleep(0.4)

    _launch_group(service_names, "Services")
    if service_names and scene_names:
        time.sleep(2)
    _launch_group(scene_names, "Scenes")

    # After all scenes are started, activate the living world
    try:
        from engine.world.world_sim import get_world_sim
        _world_sim = get_world_sim()
        _world_sim.start()
        print("  🌍 WorldSim daemon started")
    except Exception as exc:
        print(f"  ⚠️  WorldSim start failed: {exc}")

    try:
        from engine.events.cross_scene_relay import get_cross_scene_relay
        get_cross_scene_relay().start()
        print("  🔗 Cross-scene relay active")
    except Exception as exc:
        print(f"  ⚠️  Cross-scene relay: {exc}")

    try:
        from engine.world.event_cascade import get_event_cascade
        get_event_cascade().start()
        print("  🌊 EventCascade active")
    except Exception as exc:
        print(f"  ⚠️  EventCascade start failed: {exc}")

    time.sleep(5)
    print("\n  Health check:")
    for name in service_names + scene_names:
        port = ALL_TARGETS[name]["port"]
        label = ALL_TARGETS[name]["label"]
        icon = "[UP]" if _port_up(port) else "[--]"
        note = " FAILED" if name in failed else ""
        print(f"    {icon} {label:.<35s} :{port}{note}")
    print(f"\n  {total} target(s) launched.  Hub -> http://localhost:8500\n")

    try:
        signal.signal(signal.SIGINT, signal.default_int_handler)
        while True:
            time.sleep(60)
            down = [n for n in service_names + scene_names
                    if not _port_up(ALL_TARGETS[n]["port"])]
            if down:
                print(f"  Warning: not responding: {', '.join(down)}")
    except KeyboardInterrupt:
        print("\n  Shutting down...")
        for proc in all_procs:
            try:
                proc.terminate()
            except Exception:
                pass
        print("  Done.\n")


# ── High-level launchers ──────────────────────────────────────────────────

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


# ── Info commands ─────────────────────────────────────────────────────────

def cmd_list() -> None:
    print(f"\n  CosySim v{VERSION} -- Target List")
    print(f"  Config: {_LAUNCHER_CFG}\n")
    for group_label, catalogue in (("SERVICES", SERVICES), ("SCENES", SCENES)):
        print(f"  -- {group_label} " + "-" * 45)
        print(f"  {'name':<20}  {'port':>5}  auto  status  label")
        print(f"  {'-' * 56}")
        for name, info in catalogue.items():
            up   = "UP  " if _port_up(info["port"]) else "down"
            auto = "[x]" if info.get("auto_start") else "   "
            print(f"  {name:<20}  {info['port']:>5}  {auto}  {up}    {info['label']}")
        print()


def cmd_status() -> None:
    print(f"\n  CosySim v{VERSION} -- System Status")
    print(f"  Python {sys.version.split()[0]}  |  {PROJECT_ROOT}\n")

    print("  External Services:")
    for label, port in [("LMStudio", 1234), ("Nexus KMS", 8700)]:
        print(f"    {'[UP]' if _port_up(port) else '[--]'} {label:.<22} :{port}")

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


# ── Interactive menu ──────────────────────────────────────────────────────

def interactive_menu() -> None:
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
    phone  bedroom  lounge  casino  gallery  arena
    realm  neoncity  coders  heist  games  intel_hub

  Single Service  (type name):
    hub  nexus_panel  dashboard  admin  tts  bridge

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


# ── CLI ───────────────────────────────────────────────────────────────────

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
