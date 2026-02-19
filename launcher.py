#!/usr/bin/env python3
"""
CosySim System Launcher

Unified entry point for all system modes:
- hub:     Central hub (recommended starting point)
- phone:   Phone scene  (port 5555)
- bedroom: Bedroom scene (port 5556)
- dashboard: Dashboard (port 8501)
- admin:   Admin panel (port 8502)
- assets:  Asset generator (port 8503)
- dev:     Development mode with debugging
- test:    Run test suite
"""

import argparse
import sys
import os
import subprocess
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))


def launch_play_mode():
    """Launch play mode - virtual companion simulation."""
    print("🎮 Launching Play Mode...")
    print("")
    print("=" * 60)
    print("  COSYVOICE VIRTUAL COMPANION SYSTEM")
    print("=" * 60)
    print("")
    print("Available scenes:")
    print("  1. Hub            - Central launcher (recommended)")
    print("  2. Phone Scene    - Android phone UI with messaging")
    print("  3. Dashboard      - Character management interface")
    print("  4. Bedroom Scene  - 3D interactive environment")
    print("")
    
    # Ask which scene to launch
    try:
        choice = input("Select scene (1-4) or 'all' to launch all: ").strip()
        
        if choice == "1":
            # Launch hub
            print("\n🏠 Launching Central Hub...")
            import subprocess
            hub_script = PROJECT_ROOT / "content" / "simulation" / "scenes" / "hub" / "hub_scene.py"
            
            subprocess.run([
                "streamlit", "run",
                str(hub_script),
                "--server.port=8500",
                "--server.address=localhost",
                "--browser.gatherUsageStats=false"
            ])
        
        elif choice == "all":
            print("\n🚀 Launching all scenes...")
            import multiprocessing
            from content.simulation.scenes.phone.phone_scene import PhoneScene
            from content.simulation.scenes.dashboard.dashboard_v2 import main as dashboard_main
            from content.simulation.scenes.bedroom.bedroom_scene import BedroomScene
            
            # Launch phone scene in separate process
            phone_proc = multiprocessing.Process(
                target=lambda: PhoneScene().start(),
                name="PhoneScene"
            )
            phone_proc.start()
            
            # Launch dashboard
            dashboard_proc = multiprocessing.Process(
                target=dashboard_main,
                name="Dashboard"
            )
            dashboard_proc.start()
            
            # Launch bedroom scene
            bedroom_proc = multiprocessing.Process(
                target=lambda: BedroomScene().start(),
                name="BedroomScene"
            )
            bedroom_proc.start()
            
            print("✅ All scenes launched!")
            print("  - Phone: http://localhost:5555")
            print("  - Dashboard: http://localhost:8501")
            print("  - Bedroom: http://localhost:5556")
            print("\nPress Ctrl+C to stop all scenes...")
            
            try:
                phone_proc.join()
                dashboard_proc.join()
                bedroom_proc.join()
            except KeyboardInterrupt:
                print("\n\n🛑 Stopping all scenes...")
                phone_proc.terminate()
                dashboard_proc.terminate()
                bedroom_proc.terminate()
                
        elif choice == "2":
            print("\n🚀 Launching Phone Scene...")
            from content.simulation.scenes.phone.phone_scene import PhoneScene
            scene = PhoneScene()
            scene.start()
            
        elif choice == "3":
            print("\n🚀 Launching Dashboard...")
            import subprocess
            subprocess.run(["streamlit", "run", "content/simulation/scenes/dashboard/dashboard_v2.py"])
            
        elif choice == "4":
            print("\n🚀 Launching Bedroom Scene...")
            from content.simulation.scenes.bedroom.bedroom_scene import BedroomScene
            scene = BedroomScene()
            scene.start()
            
        elif choice == "4":
            print("\n⚠️  Hub scene coming soon!")
            print("For now, please select another scene.")
            
        else:
            print("❌ Invalid choice. Please run again and select 1-4 or 'all'.")
            
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error launching scene: {e}")
        sys.exit(1)


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
    admin_script = Path(__file__).parent / "content" / "simulation" / "scenes" / "admin" / "admin_panel.py"
    
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


def launch_dev_mode():
    """Launch development mode with debugging."""
    print("🛠️  Launching Development Mode...")
    print("")
    print("=" * 60)
    print("  DEVELOPMENT ENVIRONMENT")
    print("=" * 60)
    print("")
    
    # Set development environment variables
    os.environ['FLASK_ENV'] = 'development'
    os.environ['FLASK_DEBUG'] = '1'
    os.environ['PYTHONDEVMODE'] = '1'
    
    print("✅ Development settings enabled:")
    print("  - Flask debug mode: ON")
    print("  - Python dev mode: ON")
    print("  - Auto-reload: ON")
    print("")
    
    # Launch with development database
    print("📊 Using development database: simulation_dev.db")
    print("")
    
    # Launch play mode with dev settings
    launch_play_mode()


def launch_test_mode():
    """Run test suite."""
    print("🧪 Running Test Suite...")
    print("")
    print("=" * 60)
    print("  COSYVOICE TEST SUITE")
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
    print("  COSYVOICE SYSTEM STATUS")
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


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="CosyVoice Virtual Companion System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                      # Default: play mode
  %(prog)s --mode play          # Launch virtual companion
  %(prog)s --mode admin         # System administration
  %(prog)s --mode dev           # Development mode
  %(prog)s --mode test          # Run tests
  %(prog)s --init-db            # Initialize database
  %(prog)s --status             # Show system status

For more information, see: docs/README.md
        """
    )
    
    parser.add_argument(
        "--mode",
        choices=["hub", "phone", "bedroom", "dashboard", "admin", "assets", "play", "dev", "test"],
        default="hub",
        help="Launch mode (default: hub)"
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
        "--version",
        action="version",
        version="CosyVoice v1.0.0"
    )
    
    args = parser.parse_args()
    
    # Handle special flags
    if args.init_db:
        init_database()
        return
    
    if args.status:
        show_status()
        return
    
    # Launch appropriate mode
    mode_map = {
        "hub":       _launch_streamlit(PROJECT_ROOT / "content" / "scenes" / "hub" / "hub_scene.py", 8500),
        "dashboard": _launch_streamlit(PROJECT_ROOT / "content" / "scenes" / "dashboard" / "dashboard_v2.py", 8501),
        "admin":     _launch_streamlit(PROJECT_ROOT / "content" / "scenes" / "admin" / "admin_panel.py", 8502),
        "assets":    _launch_streamlit(PROJECT_ROOT / "content" / "scenes" / "assets" / "asset_generator.py", 8503),
    }

    if args.mode == "play":
        launch_play_mode()
    elif args.mode in mode_map:
        mode_map[args.mode]()
    elif args.mode == "phone":
        from content.scenes.phone.phone_scene import PhoneScene
        PhoneScene().start()
    elif args.mode == "bedroom":
        from content.scenes.bedroom.bedroom_scene import BedroomScene
        BedroomScene().start()
    elif args.mode == "dev":
        launch_dev_mode()
    elif args.mode == "test":
        launch_test_mode()


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
