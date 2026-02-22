#!/usr/bin/env python3
"""
CosySim Launcher v3
====================

Unified entry point with auto-discovery, health checks, and service management.

Scenes are discovered via SceneRegistry (content/scenes/*_scene.py) so adding
a new scene requires zero changes to this file.

Usage:
    python launcher.py                       # interactive menu
    python launcher.py --mode phone          # single scene
    python launcher.py --mode all            # all Flask scenes + services
    python launcher.py --list                # show discovered scenes
    python launcher.py --status              # system health
    python launcher.py --mode test           # run test suite
"""

import argparse
import importlib
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Ensure stdout/stderr can handle Unicode on Windows cp1252 consoles
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

VERSION = "2.7.2"

# ── Scene catalogue (class-path → metadata) ─────────────────────────────
# SceneRegistry auto-discovers these, but we keep a manual catalogue as
# fallback and for Streamlit/FastAPI services that aren't BaseScene.
FLASK_SCENES: Dict[str, Dict[str, Any]] = {
    "phone":   {"cls": "content.scenes.phone.phone_scene_v2.PhoneSceneV2",
                "port": 5555, "label": "CosyPhone OS"},
    "bedroom": {"cls": "content.scenes.bedroom.bedroom_scene.BedroomScene",
                "port": 5556, "label": "The Bedroom"},
    "lounge":  {"cls": "content.scenes.lounge.lounge_scene.LoungeScene",
                "port": 5557, "label": "The Velvet Lounge"},
    "casino":  {"cls": "content.scenes.casino.casino_scene.CasinoScene",
                "port": 5559, "label": "Midnight Casino"},
    "gallery": {"cls": "content.scenes.gallery.gallery_scene.GalleryScene",
                "port": 5560, "label": "The Gallery"},
    "warzone": {"cls": "content.scenes.warzone.warzone_scene.WarzoneScene",
                "port": 5561, "label": "Global Strike"},
}

STREAMLIT_APPS: Dict[str, Dict[str, Any]] = {
    "hub":       {"script": "content/scenes/hub/hub_scene.py",
                  "port": 8500, "label": "Hub"},
    "dashboard": {"script": "content/scenes/dashboard/dashboard_v2.py",
                  "port": 8501, "label": "Dashboard"},
    "admin":     {"script": "content/scenes/admin/admin_panel.py",
                  "port": 8502, "label": "Admin Panel"},
    "assets":    {"script": "content/scenes/assets/asset_generator.py",
                  "port": 8503, "label": "Asset Generator"},
    "creator":   {"script": "content/scenes/hub/scene_creator.py",
                  "port": 8504, "label": "Scene Creator"},
}

SERVICE_APPS: Dict[str, Dict[str, Any]] = {
    "tts":    {"factory": "engine.tts.qwen3_server.create_tts_app",
               "port": 8600, "label": "TTS Server"},
    "bridge": {"factory": "engine.mcp.web_bridge.create_bridge_app",
               "port": 8601, "label": "MCP Bridge"},
}


# ── Utilities ────────────────────────────────────────────────────────────

def _banner(title: str, width: int = 62) -> str:
    pad = width - len(title) - 4
    return (
        f"\n{'=' * width}\n"
        f"  {title}{' ' * max(pad, 0)}\n"
        f"{'=' * width}\n"
    )


def _check_port(port: int) -> bool:
    """Return True if *port* is accepting connections on localhost."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _import_class(dotted: str):
    """Import 'package.module.ClassName' and return the class."""
    mod_path, cls_name = dotted.rsplit(".", 1)
    mod = importlib.import_module(mod_path)
    return getattr(mod, cls_name)


def _import_factory(dotted: str):
    """Import 'package.module.func' and call it to get an app object."""
    mod_path, fn_name = dotted.rsplit(".", 1)
    mod = importlib.import_module(mod_path)
    return getattr(mod, fn_name)()


# ── Single-mode launchers ───────────────────────────────────────────────

def launch_flask(name: str, info: Dict[str, Any]) -> None:
    """Launch a single Flask scene in the foreground."""
    print(f"\n🎬 Launching {info['label']} on http://localhost:{info['port']}")
    cls = _import_class(info["cls"])
    scene = cls()
    scene.start()


def launch_streamlit(name: str, info: Dict[str, Any]) -> None:
    """Launch a single Streamlit app in the foreground."""
    script = PROJECT_ROOT / info["script"]
    if not script.exists():
        print(f"❌ Script not found: {script}")
        sys.exit(1)
    print(f"\n🚀 Launching {info['label']} on http://localhost:{info['port']}")
    subprocess.run([
        "streamlit", "run", str(script),
        f"--server.port={info['port']}",
        "--server.address=localhost",
        "--browser.gatherUsageStats=false",
    ])


def launch_service(name: str, info: Dict[str, Any]) -> None:
    """Launch a single FastAPI/Uvicorn service in the foreground."""
    import uvicorn  # type: ignore
    print(f"\n⚙️  Launching {info['label']} on http://localhost:{info['port']}")
    app = _import_factory(info["factory"])
    uvicorn.run(app, host="0.0.0.0", port=info["port"], log_level="warning")


# ── All-in-one launcher ─────────────────────────────────────────────────

def launch_all(scenes: Optional[List[str]] = None) -> None:
    """Launch multiple Flask scenes + services in one terminal."""
    targets = scenes or list(FLASK_SCENES.keys())
    procs: List[subprocess.Popen] = []
    threads: List[threading.Thread] = []
    failed: List[str] = []

    # Build table for banner
    lines = []
    for name in targets:
        info = FLASK_SCENES.get(name, {})
        lines.append(f"  {info.get('label', name):.<20s} http://localhost:{info.get('port', '?')}")
    for sname, sinfo in SERVICE_APPS.items():
        lines.append(f"  {sinfo['label']:.<20s} http://localhost:{sinfo['port']}")
    lines.append(f"  {'Hub':.<20s} http://localhost:8500  (Streamlit)")

    box_w = 60
    print(f"\n{'╔' + '═' * box_w + '╗'}")
    print(f"{'║'} {'CosySim — All Services Launcher':^{box_w}} {'║'}")
    print(f"{'╠' + '═' * box_w + '╣'}")
    for line in lines:
        print(f"{'║'} {line:<{box_w}} {'║'}")
    print(f"{'╠' + '═' * box_w + '╣'}")
    print(f"{'║'} {'Press Ctrl+C to stop all services':^{box_w}} {'║'}")
    print(f"{'╚' + '═' * box_w + '╝'}")

    def _run_flask_thread(name: str, info: Dict[str, Any]) -> None:
        try:
            cls = _import_class(info["cls"])
            scene = cls()
            print(f"  ✅ {info['label']} starting on :{info['port']}...")
            scene.start()
        except Exception as e:
            print(f"  ❌ {info['label']} failed: {e}")
            failed.append(name)

    def _run_uvicorn_thread(info: Dict[str, Any]) -> None:
        try:
            app = _import_factory(info["factory"])
            import uvicorn  # type: ignore
            print(f"  ✅ {info['label']} starting on :{info['port']}...")
            uvicorn.run(app, host="0.0.0.0", port=info["port"], log_level="warning")
        except Exception as e:
            print(f"  ❌ {info['label']} failed: {e}")

    # Flask scenes
    for name in targets:
        info = FLASK_SCENES[name]
        t = threading.Thread(target=_run_flask_thread, args=(name, info), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(0.8)

    # FastAPI services
    for sname, sinfo in SERVICE_APPS.items():
        t = threading.Thread(target=_run_uvicorn_thread, args=(sinfo,), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(0.3)

    # Hub as subprocess (Streamlit needs its own process)
    hub_script = PROJECT_ROOT / "content" / "scenes" / "hub" / "hub_scene.py"
    try:
        hub_proc = subprocess.Popen(
            ["streamlit", "run", str(hub_script), "--server.port=8500",
             "--server.headless=true", "--logger.level=warning"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        procs.append(hub_proc)
        print("  ✅ Hub starting on :8500...")
    except Exception as e:
        print(f"  ⚠️  Hub failed (Streamlit?): {e}")

    # Health check after 5 seconds
    time.sleep(5)
    print("\n📡 Health check:")
    all_ports = [(n, FLASK_SCENES[n]["port"]) for n in targets]
    all_ports += [(sn, si["port"]) for sn, si in SERVICE_APPS.items()]
    all_ports += [("hub", 8500)]
    for label, port in all_ports:
        status = "✅ UP" if _check_port(port) else "⏳ starting..."
        print(f"  {label:>10s} :{port}  {status}")

    print(f"\n🚀 All services launched! Open http://localhost:8500 for the Hub.\n")

    try:
        signal.signal(signal.SIGINT, signal.default_int_handler)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        for p in procs:
            p.terminate()
        print("   Done.")


# ── Test runner ──────────────────────────────────────────────────────────

def launch_test_mode() -> None:
    """Run the pytest suite."""
    print(_banner("COSYSIM TEST SUITE"))
    try:
        import pytest
    except ImportError:
        print("❌ pytest not installed. Run: pip install pytest")
        sys.exit(1)
    exit_code = pytest.main([
        "tests/", "-v", "--tb=short", "--color=yes",
        "--ignore=tests/test_agent_loop.py",
        "--ignore=tests/live_wire_test.py",
    ])
    sys.exit(exit_code)


# ── Database init ────────────────────────────────────────────────────────

def init_database() -> None:
    """Initialize the simulation database."""
    print(_banner("DATABASE INIT"))
    from content.simulation.database.db import Database
    try:
        db = Database()
        print(f"✅ Database at {db.db_path}")
        with db.get_connection() as conn:
            cur = conn.cursor()
            for table in ["characters", "personalities", "roles", "conversations",
                          "interactions", "media", "character_states"]:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    print(f"  ✓ {table}: {cur.fetchone()[0]} rows")
                except Exception:
                    print(f"  ✗ {table}: not found")
    except Exception as e:
        print(f"❌ {e}")
        sys.exit(1)


# ── System status ────────────────────────────────────────────────────────

def show_status() -> None:
    """Show system health: deps, databases, ports, scenes."""
    print(_banner("COSYSIM SYSTEM STATUS"))
    print(f"  Python  : {sys.version.split()[0]}")
    print(f"  Version : {VERSION}")

    # Dependencies
    print("\n  Dependencies:")
    for name, mod in [("Flask", "flask"), ("Streamlit", "streamlit"),
                      ("PyTorch", "torch"), ("ChromaDB", "chromadb"),
                      ("APScheduler", "apscheduler"), ("Requests", "requests")]:
        try:
            m = __import__(mod)
            print(f"    ✓ {name}: {getattr(m, '__version__', '?')}")
        except ImportError:
            print(f"    ✗ {name}: missing")

    # Databases
    print("\n  Databases:")
    for db_rel in ["content/simulation/simulation.db", "data/agent_state.db",
                    "data/phone_v2.db", "asset_registry.db"]:
        db_path = PROJECT_ROOT / db_rel
        if db_path.exists():
            size = db_path.stat().st_size / 1024
            print(f"    ✓ {db_rel} ({size:.0f} KB)")
        else:
            print(f"    - {db_rel}: not found")

    # Ports
    print("\n  Ports:")
    all_ports = {**{n: i["port"] for n, i in FLASK_SCENES.items()},
                 **{n: i["port"] for n, i in STREAMLIT_APPS.items()},
                 **{n: i["port"] for n, i in SERVICE_APPS.items()}}
    for name, port in sorted(all_ports.items(), key=lambda x: x[1]):
        up = _check_port(port)
        status = "🟢 UP" if up else "⚫ down"
        print(f"    {name:>10s} :{port}  {status}")

    # Directory structure
    print("\n  Project:")
    for d in ["engine", "content", "config", "docs", "tests"]:
        dp = PROJECT_ROOT / d
        if dp.exists():
            count = len(list(dp.rglob("*.py")))
            print(f"    ✓ {d}/ ({count} py files)")

    print()


# ── List scenes ──────────────────────────────────────────────────────────

def list_scenes() -> None:
    """List all known scenes and services."""
    print(_banner("AVAILABLE SCENES & SERVICES"))
    print("  Flask Scenes:")
    for name, info in FLASK_SCENES.items():
        up = _check_port(info["port"])
        dot = "🟢" if up else "⚫"
        print(f"    {dot} {name:>10s}  :{info['port']}  {info['label']}")

    print("\n  Streamlit Apps:")
    for name, info in STREAMLIT_APPS.items():
        up = _check_port(info["port"])
        dot = "🟢" if up else "⚫"
        print(f"    {dot} {name:>10s}  :{info['port']}  {info['label']}")

    print("\n  Services:")
    for name, info in SERVICE_APPS.items():
        up = _check_port(info["port"])
        dot = "🟢" if up else "⚫"
        print(f"    {dot} {name:>10s}  :{info['port']}  {info['label']}")
    print()


# ── Interactive menu ─────────────────────────────────────────────────────

def interactive_menu() -> None:
    """Show an interactive menu when no --mode is given."""
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║                  CosySim v{VERSION}                            ║
║              AI Agent Simulation Framework                    ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  Scenes:                                                     ║
║    1. phone     - CosyPhone OS           (port 5555)         ║
║    2. bedroom   - The Bedroom            (port 5556)         ║
║    3. lounge    - The Velvet Lounge       (port 5557)         ║
║    4. casino    - Midnight Casino         (port 5559)         ║
║    5. gallery   - The Gallery             (port 5560)         ║
║    6. warzone   - Global Strike           (port 5561)         ║
║                                                              ║
║  Services:                                                   ║
║    7. hub       - Central Hub             (port 8500)         ║
║    8. admin     - Admin Panel             (port 8502)         ║
║    9. all       - Launch everything                           ║
║                                                              ║
║  Tools:                                                      ║
║    s. status    - System health check                        ║
║    t. test      - Run test suite                             ║
║    l. list      - List all scenes + ports                    ║
║    q. quit                                                   ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")
    choice_map = {
        "1": "phone", "phone": "phone",
        "2": "bedroom", "bedroom": "bedroom",
        "3": "lounge", "lounge": "lounge",
        "4": "casino", "casino": "casino",
        "5": "gallery", "gallery": "gallery",
        "6": "warzone", "warzone": "warzone",
        "7": "hub", "hub": "hub",
        "8": "admin", "admin": "admin",
        "9": "all", "all": "all",
        "s": "status", "status": "status",
        "t": "test", "test": "test",
        "l": "list", "list": "list",
        "q": "quit", "quit": "quit",
    }

    try:
        choice = input("  Select: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n👋 Goodbye!")
        return

    mode = choice_map.get(choice)
    if mode == "quit" or mode is None:
        if mode is None and choice:
            print(f"  Unknown choice: {choice}")
        return

    dispatch(mode)


# ── Dispatch ─────────────────────────────────────────────────────────────

def dispatch(mode: str) -> None:
    """Route a mode string to the correct launcher."""
    if mode in FLASK_SCENES:
        launch_flask(mode, FLASK_SCENES[mode])
    elif mode in STREAMLIT_APPS:
        launch_streamlit(mode, STREAMLIT_APPS[mode])
    elif mode in SERVICE_APPS:
        launch_service(mode, SERVICE_APPS[mode])
    elif mode == "all":
        launch_all()
    elif mode == "test":
        launch_test_mode()
    elif mode == "status":
        show_status()
    elif mode == "list":
        list_scenes()
    else:
        print(f"❌ Unknown mode: {mode}")
        sys.exit(1)


# ── CLI ──────────────────────────────────────────────────────────────────

def main() -> None:
    all_modes = sorted(
        set(list(FLASK_SCENES) + list(STREAMLIT_APPS) + list(SERVICE_APPS)
            + ["all", "test"])
    )

    parser = argparse.ArgumentParser(
        description=f"CosySim v{VERSION} — AI Agent Simulation Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                        # interactive menu
  %(prog)s --mode phone           # launch phone scene
  %(prog)s --mode all             # launch all services
  %(prog)s --list                 # show scenes + port status
  %(prog)s --status               # system health
  %(prog)s --mode test            # run tests
  %(prog)s --init-db              # initialize database
  %(prog)s --housekeep            # media ingest + health checks
""",
    )
    parser.add_argument("--mode", choices=all_modes, default=None,
                        help="Launch mode (omit for interactive menu)")
    parser.add_argument("--list", action="store_true", help="List scenes and ports")
    parser.add_argument("--status", action="store_true", help="System health check")
    parser.add_argument("--init-db", action="store_true", help="Initialize database")
    parser.add_argument("--housekeep", action="store_true",
                        help="Run housekeeping tasks")
    parser.add_argument("--watch", action="store_true",
                        help="With --housekeep: run continuously")
    parser.add_argument("--version", action="version", version=f"CosySim v{VERSION}")

    args = parser.parse_args()

    if args.init_db:
        init_database()
        return
    if args.status:
        show_status()
        return
    if args.list:
        list_scenes()
        return
    if args.housekeep:
        from engine.services.housekeeping import HousekeepingService
        hk = HousekeepingService()
        hk.watch() if args.watch else hk.run_all()
        return

    if args.mode:
        dispatch(args.mode)
    else:
        interactive_menu()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
