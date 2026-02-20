#!/usr/bin/env python3
"""
CosySim System Launcher

Unified entry point for all system modes:
- hub:       Central hub (recommended starting point, port 8500)
- phone:     Phone scene  (port 5555)
- bedroom:   Bedroom scene (port 5556)
- dashboard: Dashboard (port 8501, Streamlit)
- admin:     Admin panel (port 8502, Streamlit)
- assets:    Asset generator (port 8503, Streamlit)
- tts:       TTS voice server (port 8600)
- bridge:    MCP web bridge (port 8601)
- all:       Hub + Phone + Bedroom + TTS + Bridge in one terminal
- test:      Run test suite
"""

import argparse
import sys
import os
import subprocess
from pathlib import Path

# Ensure stdout/stderr can handle Unicode (emoji) on Windows cp1252 consoles
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass  # Not supported or already fine

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))


def launch_admin_mode():
    """Launch admin mode - system administration panel."""
    print("🎛️  Launching Admin Control Panel...")
    print("")
    print("=" * 60)
    print("  SYSTEM ADMINISTRATION PANEL")
    print("=" * 60)
    print("")
    
    # Check if Streamlit is available
    try:
        import streamlit
    except ImportError:
        print("❌ Streamlit not installed!")
        print("   Install with: pip install streamlit")
        sys.exit(1)
    
    # Launch admin panel
    admin_script = Path(__file__).parent / "content" / "scenes" / "admin" / "admin_panel.py"
    
    if not admin_script.exists():
        print(f"❌ Admin panel not found: {admin_script}")
        sys.exit(1)
    
    print("🚀 Starting admin panel on http://localhost:8502")
    print("")
    print("Press Ctrl+C to stop")
    print("")
    
    try:
        subprocess.run([
            "streamlit", "run",
            str(admin_script),
            "--server.port=8502",
            "--server.address=localhost",
            "--browser.gatherUsageStats=false"
        ])
    except KeyboardInterrupt:
        print("\n\n👋 Admin panel stopped!")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error launching admin panel: {e}")
        sys.exit(1)


def launch_test_mode():
    """Run test suite."""
    print("🧪 Running Test Suite...")
    print("")
    print("=" * 60)
    print("  COSYSIM TEST SUITE")
    print("=" * 60)
    print("")
    
    # Check if pytest is installed
    try:
        import pytest
    except ImportError:
        print("❌ pytest not installed!")
        print("Install with: pip install pytest pytest-cov")
        sys.exit(1)
    
    # Run tests
    test_args = [
        "tests/",
        "-v",
        "--tb=short",
        "--color=yes"
    ]
    
    print("Running tests with pytest...")
    print("")
    
    exit_code = pytest.main(test_args)
    
    if exit_code == 0:
        print("\n✅ All tests passed!")
    else:
        print(f"\n❌ Tests failed with exit code {exit_code}")
    
    sys.exit(exit_code)


def init_database():
    """Initialize the database."""
    print("🗄️  Initializing Database...")
    print("")
    
    from content.simulation.database.db import Database
    
    try:
        db = Database()
        print("✅ Database initialized successfully!")
        print(f"   Location: {db.db_path}")
        
        # Show table counts
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            tables = ['characters', 'personalities', 'roles', 'conversations', 
                     'interactions', 'media', 'character_states']
            
            print("\nDatabase tables:")
            for table in tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]
                    print(f"  ✓ {table}: {count} rows")
                except Exception:
                    print(f"  ✗ {table}: not found")
        
        print("\n✅ Database ready!")
        
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        sys.exit(1)


def show_status():
    """Show system status."""
    print("📊 System Status")
    print("")
    print("=" * 60)
    print("  COSYSIM SYSTEM STATUS")
    print("=" * 60)
    print("")
    
    # Check Python version
    print(f"Python: {sys.version.split()[0]}")
    
    # Check dependencies
    print("\nCore Dependencies:")
    dependencies = [
        ("Flask", "flask"),
        ("Streamlit", "streamlit"),
        ("PyTorch", "torch"),
        ("ChromaDB", "chromadb"),
        ("APScheduler", "apscheduler"),
    ]
    
    for name, module in dependencies:
        try:
            mod = __import__(module)
            version = getattr(mod, '__version__', 'unknown')
            print(f"  ✓ {name}: {version}")
        except ImportError:
            print(f"  ✗ {name}: not installed")
    
    # Check database
    print("\nDatabase:")
    db_path = PROJECT_ROOT / "simulation.db"
    if db_path.exists():
        size_mb = db_path.stat().st_size / (1024 * 1024)
        print(f"  ✓ simulation.db: {size_mb:.2f} MB")
    else:
        print(f"  ✗ simulation.db: not found")
    
    # Check directory structure
    print("\nDirectory Structure:")
    dirs = ["engine", "content", "config", "docs", "examples", "tests"]
    for d in dirs:
        dir_path = PROJECT_ROOT / d
        if dir_path.exists():
            file_count = len(list(dir_path.rglob("*.py")))
            print(f"  ✓ {d}/: {file_count} Python files")
        else:
            print(f"  ✗ {d}/: not found")
    
    print("")


def launch_all():
    """Launch all core services in one terminal using threads/subprocesses."""
    import threading
    import time
    import signal

    banner = """
╔══════════════════════════════════════════════════════════╗
║             CosySim — All Services Launcher              ║
╠══════════════════════════════════════════════════════════╣
║  Hub ............ http://localhost:8500  (Streamlit)      ║
║  Phone .......... http://localhost:5555  (Flask)          ║
║  Bedroom ........ http://localhost:5556  (Flask)          ║
║  TTS Server ..... http://localhost:8600  (FastAPI)        ║
║  MCP Bridge ..... http://localhost:8601  (FastAPI)        ║
╠══════════════════════════════════════════════════════════╣
║  Press Ctrl+C to stop all services                       ║
╚══════════════════════════════════════════════════════════╝
"""
    print(banner)

    procs = []
    threads = []

    def _run_flask(scene_cls_path, name):
        """Run a Flask scene in a thread."""
        try:
            mod, cls = scene_cls_path.rsplit(".", 1)
            import importlib
            m = importlib.import_module(mod)
            scene = getattr(m, cls)()
            print(f"  ✅ {name} starting...")
            scene.start()
        except Exception as e:
            print(f"  ❌ {name} failed: {e}")

    def _run_uvicorn(factory_path, port, name):
        """Run a FastAPI app in a thread."""
        try:
            mod, func = factory_path.rsplit(".", 1)
            import importlib
            m = importlib.import_module(mod)
            app = getattr(m, func)()
            import uvicorn
            print(f"  ✅ {name} starting on :{port}...")
            uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
        except Exception as e:
            print(f"  ❌ {name} failed: {e}")

    # Flask scenes in threads
    for path, name in [
        ("content.scenes.phone.phone_scene.PhoneScene", "Phone Scene (:5555)"),
        ("content.scenes.bedroom.bedroom_scene.BedroomScene", "Bedroom Scene (:5556)"),
    ]:
        t = threading.Thread(target=_run_flask, args=(path, name), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(1)

    # FastAPI services in threads
    for factory, port, name in [
        ("engine.tts.qwen3_server.create_tts_app", 8600, "TTS Server (:8600)"),
        ("engine.mcp.web_bridge.create_bridge_app", 8601, "MCP Bridge (:8601)"),
    ]:
        t = threading.Thread(target=_run_uvicorn, args=(factory, port, name), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(0.5)

    # Hub as a subprocess (Streamlit needs its own process)
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
        print(f"  ⚠️ Hub failed (Streamlit?): {e}")

    print("\n🚀 All services launched! Open http://localhost:8500 for the Hub.\n")

    # Wait for Ctrl+C
    try:
        signal.signal(signal.SIGINT, signal.default_int_handler)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down all services...")
        for p in procs:
            p.terminate()
        print("   Done.")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="CosySim AI Playground",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                      # Default: hub mode
  %(prog)s --mode hub           # Central hub (start here)
  %(prog)s --mode phone         # Phone scene only
  %(prog)s --mode bedroom       # Bedroom scene only
  %(prog)s --mode all           # Launch all services in one terminal
  %(prog)s --mode admin         # System administration (Streamlit)
  %(prog)s --mode test          # Run tests
  %(prog)s --housekeep          # Run media ingest + health checks
  %(prog)s --init-db            # Initialize database
  %(prog)s --status             # Show system status

For more information, see: ONBOARDING.md
        """
    )
    
    parser.add_argument(
        "--mode",
        choices=["hub", "phone", "bedroom", "dashboard", "admin", "assets", "creator", "tts", "bridge", "all", "test"],
        default="hub",
        help="Launch mode (default: hub). 'all' starts hub + phone + bedroom + tts in one terminal."
    )
    
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="Initialize the database"
    )
    
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show system status"
    )
    
    parser.add_argument(
        "--housekeep",
        action="store_true",
        help="Run housekeeping (media ingest, health checks, integrity)"
    )
    
    parser.add_argument(
        "--watch",
        action="store_true",
        help="With --housekeep: run continuously"
    )
    
    parser.add_argument(
        "--version",
        action="version",
        version="CosySim v2.0.0"
    )
    
    args = parser.parse_args()
    
    # Handle special flags
    if args.init_db:
        init_database()
        return
    
    if args.status:
        show_status()
        return
    
    if args.housekeep:
        from engine.services.housekeeping import HousekeepingService
        hk = HousekeepingService()
        if args.watch:
            hk.watch()
        else:
            hk.run_all()
        return
    
    # Launch appropriate mode
    mode_map = {
        "hub":       _launch_streamlit(PROJECT_ROOT / "content" / "scenes" / "hub" / "hub_scene.py", 8500),
        "dashboard": _launch_streamlit(PROJECT_ROOT / "content" / "scenes" / "dashboard" / "dashboard_v2.py", 8501),
        "admin":     _launch_streamlit(PROJECT_ROOT / "content" / "scenes" / "admin" / "admin_panel.py", 8502),
        "assets":    _launch_streamlit(PROJECT_ROOT / "content" / "scenes" / "assets" / "asset_generator.py", 8503),
        "creator":   _launch_streamlit(PROJECT_ROOT / "content" / "scenes" / "hub" / "scene_creator.py", 8504),
    }

    if args.mode in mode_map:
        mode_map[args.mode]()
    elif args.mode == "phone":
        from content.scenes.phone.phone_scene import PhoneScene
        PhoneScene().start()
    elif args.mode == "bedroom":
        from content.scenes.bedroom.bedroom_scene import BedroomScene
        BedroomScene().start()
    elif args.mode == "test":
        launch_test_mode()
    elif args.mode == "tts":
        from engine.tts.qwen3_server import create_tts_app
        import uvicorn
        print("\n🎙️ Launching TTS Server on http://localhost:8600")
        uvicorn.run(create_tts_app(), host="0.0.0.0", port=8600)
    elif args.mode == "bridge":
        from engine.mcp.web_bridge import create_bridge_app
        import uvicorn
        print("\n🌉 Launching Web Bridge on http://localhost:8601")
        uvicorn.run(create_bridge_app(), host="0.0.0.0", port=8601)
    elif args.mode == "all":
        launch_all()


def _launch_streamlit(script_path: Path, port: int):
    """Return a callable that launches a Streamlit app."""
    def _launch():
        print(f"\n🚀 Launching {script_path.name} on http://localhost:{port}")
        subprocess.run([
            "streamlit", "run",
            str(script_path),
            f"--server.port={port}",
            "--server.address=localhost",
            "--browser.gatherUsageStats=false",
        ])
    return _launch


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
