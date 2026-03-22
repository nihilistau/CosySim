"""
System Services Launcher
========================

Launches only CosySim system-pillar targets: Nexus KMS, Hub, Nexus Panel,
MCP Bridge, NLM Proxy, System Control, TTS, Dashboard, Admin, etc.

Use this when you want system services running without any game scenes.

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


# ──── Build system-only catalogue ────────────────────────────────────────

def _build_system_catalogue():
    """Build launcher catalogues filtered to system pillar only."""
    services, scenes, all_targets = build_launcher_catalogues(get_port)
    system_ids = set(PILLAR_IDS.get("service", ()))
    sys_services = {k: v for k, v in services.items() if k in system_ids}
    sys_scenes = {k: v for k, v in scenes.items() if k in system_ids}
    return sys_services, sys_scenes


# ──── Main ───────────────────────────────────────────────────────────────

def main() -> None:
    """System services launcher entry point."""
    from launcher import (
        _load_config, _port_up, launch_multi, launch_single,
        SERVICES, SCENES, ALL_TARGETS,
    )
    _load_config()

    parser = argparse.ArgumentParser(
        description="CosySim — System Services Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --core     # Start auto_start system services
  %(prog)s --all      # Start ALL system services
  %(prog)s --list     # List system targets + port status
  %(prog)s nexus_kms  # Start a single system service
""",
    )
    parser.add_argument("target", nargs="?", help="Single target name to start")
    parser.add_argument("--core", action="store_true", help="Start auto_start system services")
    parser.add_argument("--all", action="store_true", help="Start all system services")
    parser.add_argument("--list", action="store_true", help="List system targets + port status")
    parser.add_argument("--status", action="store_true", help="System health check")

    args = parser.parse_args()

    system_ids = set(PILLAR_IDS.get("service", ()))

    if args.list:
        print("\n  CosySim — System Services")
        print(f"  {len(system_ids)} targets in system pillar\n")
        print(f"  {'name':<20}  {'port':>5}  auto  status  label")
        print(f"  {'-' * 56}")
        for tid in sorted(system_ids):
            info = ALL_TARGETS.get(tid, {})
            if not info:
                continue
            up = "UP  " if _port_up(info["port"]) else "down"
            auto = "[x]" if info.get("auto_start") else "   "
            print(f"  {tid:<20}  {info['port']:>5}  {auto}  {up}    {info['label']}")
        print()
        return

    if args.status:
        print("\n  CosySim — System Services Status\n")
        for tid in sorted(system_ids):
            info = ALL_TARGETS.get(tid, {})
            if not info:
                continue
            up = "UP" if _port_up(info["port"]) else "DOWN"
            print(f"  {info['label']:<25}  :{info['port']}  {up}")
        print()
        return

    if args.target:
        if args.target not in system_ids:
            print(f"  '{args.target}' is not a system service.")
            print(f"  System services: {', '.join(sorted(system_ids))}")
            sys.exit(1)
        launch_single(args.target)
        return

    # Filter to system pillar
    svcs = [t for t in system_ids if t in SERVICES]
    scns = [t for t in system_ids if t in SCENES]

    if args.core:
        svcs = [t for t in svcs if ALL_TARGETS.get(t, {}).get("auto_start")]
        scns = [t for t in scns if ALL_TARGETS.get(t, {}).get("auto_start")]
    elif not args.all:
        # Default to --core behavior
        svcs = [t for t in svcs if ALL_TARGETS.get(t, {}).get("auto_start")]
        scns = [t for t in scns if ALL_TARGETS.get(t, {}).get("auto_start")]

    print(f"\n  Launching SYSTEM pillar ({len(svcs)} services, {len(scns)} scenes)")
    launch_multi(svcs, scns)


if __name__ == "__main__":
    main()
