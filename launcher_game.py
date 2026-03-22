"""
Game Scenes Launcher
====================

Launches only CosySim game-pillar targets: NeonCity, Penthouse, Phone,
Lounge, Tavern, Casino, Gallery, Arena, Realm, Grid, Heist, etc.

Pre-flight checks that core system services (Nexus KMS, Hub) are running.

Version: v1.50.0 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.50.0 [2026-03-22] — Initial three-pillar separation
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.control_plane_registry import PILLAR_IDS, build_launcher_catalogues
from engine.port_registry import get_port


# ──── Pre-flight service check ───────────────────────────────────────────

# v1.50.0 [2026-03-22] — Check core system services before launching games
_REQUIRED_SERVICES = {
    "nexus_kms": 8700,
    "hub": 8500,
}


def _port_check(port: int) -> bool:
    """Quick TCP connect test."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


def _preflight() -> bool:
    """Check that required system services are running.

    Returns:
        True if all required services are up, False otherwise.
    """
    all_ok = True
    for name, port in _REQUIRED_SERVICES.items():
        if _port_check(port):
            print(f"  [OK]   {name} (:{port})")
        else:
            print(f"  [WARN] {name} (:{port}) — NOT RUNNING")
            all_ok = False
    if not all_ok:
        print("\n  Some system services are not running.")
        print("  Start them with: python launcher_system.py --core")
        print("  Continuing anyway — game scenes may have limited functionality.\n")
    return all_ok


# ──── Main ───────────────────────────────────────────────────────────────

def main() -> None:
    """Game scenes launcher entry point."""
    from launcher import (
        _load_config, _port_up, launch_multi, launch_single,
        SERVICES, SCENES, ALL_TARGETS,
    )
    _load_config()

    parser = argparse.ArgumentParser(
        description="CosySim — Game Scenes Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --core      # Start auto_start game scenes
  %(prog)s --all       # Start ALL game scenes
  %(prog)s --list      # List game targets + port status
  %(prog)s neoncity    # Start a single game scene
""",
    )
    parser.add_argument("target", nargs="?", help="Single target name to start")
    parser.add_argument("--core", action="store_true", help="Start auto_start game scenes")
    parser.add_argument("--all", action="store_true", help="Start all game scenes")
    parser.add_argument("--list", action="store_true", help="List game targets + port status")
    parser.add_argument("--status", action="store_true", help="Game scenes health check")

    args = parser.parse_args()

    game_ids = set(PILLAR_IDS.get("game", ()))

    if args.list:
        print("\n  CosySim — Game Scenes")
        print(f"  {len(game_ids)} targets in game pillar\n")
        print(f"  {'name':<20}  {'port':>5}  auto  status  label")
        print(f"  {'-' * 56}")
        for tid in sorted(game_ids):
            info = ALL_TARGETS.get(tid, {})
            if not info:
                continue
            up = "UP  " if _port_up(info["port"]) else "down"
            auto = "[x]" if info.get("auto_start") else "   "
            print(f"  {tid:<20}  {info['port']:>5}  {auto}  {up}    {info['label']}")
        print()
        return

    if args.status:
        print("\n  CosySim — Game Scenes Status\n")
        print("  System services:")
        _preflight()
        print("\n  Game scenes:")
        for tid in sorted(game_ids):
            info = ALL_TARGETS.get(tid, {})
            if not info:
                continue
            up = "UP" if _port_up(info["port"]) else "DOWN"
            print(f"  {info['label']:<25}  :{info['port']}  {up}")
        print()
        return

    if args.target:
        if args.target not in game_ids:
            print(f"  '{args.target}' is not a game scene.")
            print(f"  Game scenes: {', '.join(sorted(game_ids))}")
            sys.exit(1)
        print("\n  Pre-flight check:")
        _preflight()
        launch_single(args.target)
        return

    # Pre-flight check
    print("\n  Pre-flight check:")
    _preflight()

    # Filter to game pillar
    svcs = [t for t in game_ids if t in SERVICES]
    scns = [t for t in game_ids if t in SCENES]

    if args.core:
        svcs = [t for t in svcs if ALL_TARGETS.get(t, {}).get("auto_start")]
        scns = [t for t in scns if ALL_TARGETS.get(t, {}).get("auto_start")]
    elif not args.all:
        # Default to --core behavior
        svcs = [t for t in svcs if ALL_TARGETS.get(t, {}).get("auto_start")]
        scns = [t for t in scns if ALL_TARGETS.get(t, {}).get("auto_start")]

    print(f"\n  Launching GAME pillar ({len(svcs)} services, {len(scns)} scenes)")
    launch_multi(svcs, scns)


if __name__ == "__main__":
    main()
