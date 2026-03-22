"""
Creation Kit Launcher
=====================

Launches only CosySim creation-pillar targets: Creation Kit, Asset Studio,
Asset Generator, Scene Creator, Canvas, Canvas API.

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


# ──── Main ───────────────────────────────────────────────────────────────

def main() -> None:
    """Creation Kit launcher entry point."""
    from launcher import (
        _load_config, _port_up, launch_multi, launch_single,
        SERVICES, SCENES, ALL_TARGETS,
    )
    _load_config()

    parser = argparse.ArgumentParser(
        description="CosySim — Creation Kit Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --core          # Start auto_start creation tools
  %(prog)s --all           # Start ALL creation tools
  %(prog)s --list          # List creation targets + port status
  %(prog)s creation_kit    # Start a single creation tool
""",
    )
    parser.add_argument("target", nargs="?", help="Single target name to start")
    parser.add_argument("--core", action="store_true", help="Start auto_start creation targets")
    parser.add_argument("--all", action="store_true", help="Start all creation targets")
    parser.add_argument("--list", action="store_true", help="List creation targets + port status")

    args = parser.parse_args()

    creation_ids = set(PILLAR_IDS.get("creation", ()))

    if args.list:
        print("\n  CosySim — Creation Kit")
        print(f"  {len(creation_ids)} targets in creation pillar\n")
        print(f"  {'name':<20}  {'port':>5}  auto  status  label")
        print(f"  {'-' * 56}")
        for tid in sorted(creation_ids):
            info = ALL_TARGETS.get(tid, {})
            if not info:
                continue
            up = "UP  " if _port_up(info["port"]) else "down"
            auto = "[x]" if info.get("auto_start") else "   "
            print(f"  {tid:<20}  {info['port']:>5}  {auto}  {up}    {info['label']}")
        print()
        return

    if args.target:
        if args.target not in creation_ids:
            print(f"  '{args.target}' is not a creation tool.")
            print(f"  Creation tools: {', '.join(sorted(creation_ids))}")
            sys.exit(1)
        launch_single(args.target)
        return

    # Filter to creation pillar
    svcs = [t for t in creation_ids if t in SERVICES]
    scns = [t for t in creation_ids if t in SCENES]

    if args.core:
        svcs = [t for t in svcs if ALL_TARGETS.get(t, {}).get("auto_start")]
        scns = [t for t in scns if ALL_TARGETS.get(t, {}).get("auto_start")]
    elif not args.all:
        svcs = [t for t in svcs if ALL_TARGETS.get(t, {}).get("auto_start")]
        scns = [t for t in scns if ALL_TARGETS.get(t, {}).get("auto_start")]

    print(f"\n  Launching CREATION pillar ({len(svcs)} services, {len(scns)} scenes)")
    launch_multi(svcs, scns)


if __name__ == "__main__":
    main()
