"""
CosySim Quick Start
===================

Hardcoded multi-scene launcher. Bypasses launcher.py entirely.
Each scene is started as its own Python process via a tiny inline script.

Usage:
    python start.py              # Launch core scenes + services
    python start.py --all        # Launch everything
    python start.py --kill       # Kill all CosySim processes

Version: v1.52.1 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.52.1 [2026-03-25] — Created as reliable replacement for launcher.py --core
"""
from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent

# ──── Resolve venv Python ─────────────────────────────────────────────────
VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
if not VENV_PYTHON.exists():
    VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"
if not VENV_PYTHON.exists():
    VENV_PYTHON = Path(sys.executable)
PYTHON = str(VENV_PYTHON)

# ──── Hardcoded Targets ───────────────────────────────────────────────────
# (name, port, import_path, class_name)

CORE_SERVICES = [
    ("hub",            8500, "content.scenes.hub.hub_scene",                       "HubScene"),
    ("nexus_panel",    5570, "content.scenes.nexus_panel.nexus_panel_scene",       "NexusPanelScene"),
    ("creator",        8504, "content.scenes.creator.creator_scene",               "CreatorScene"),
    ("bridge",         8601, "content.scenes.bridge.bridge_scene",                 "BridgeScene"),
    ("canvas_api",     5595, "content.scenes.canvas_api.canvas_api_scene",         "CanvasApiScene"),
    ("nlm_proxy",      8800, "content.scenes.nlm_proxy.nlm_proxy_scene",           "NlmProxyScene"),
    ("system_control", 5575, "content.scenes.system_control.system_control_scene", "SystemControlScene"),
]

CORE_SCENES = [
    ("phone",     5555, "content.scenes.phone.phone_scene",         "PhoneScene"),
    ("lounge",    5557, "content.scenes.lounge.lounge_scene",       "LoungeScene"),
    ("tavern",    5558, "content.scenes.tavern.tavern_scene",       "TavernScene"),
    ("casino",    5559, "content.scenes.casino.casino_scene",       "CasinoScene"),
    ("neoncity",  5563, "content.scenes.neoncity.neoncity_scene",   "NeonCityScene"),
    ("grid",      5569, "content.scenes.grid.grid_scene",           "GridScene"),
    ("intel_hub", 5580, "content.scenes.intel_hub.intel_hub_scene", "IntelHubScene"),
    ("lab_break", 5571, "content.scenes.lab_break.lab_break_scene", "LabBreakScene"),
]

EXTRA_SCENES = [
    ("penthouse",      5556, "content.scenes.penthouse.penthouse_scene",             "PenthouseScene"),
    ("gallery",        5560, "content.scenes.gallery.gallery_scene",                 "GalleryScene"),
    ("arena",          5561, "content.scenes.arena.arena_scene",                     "ArenaScene"),
    ("realm",          5562, "content.scenes.realm.realm_scene",                     "RealmScene"),
    ("coders",         5564, "content.scenes.coders.coders_scene",                   "CodersScene"),
    ("heist",          5565, "content.scenes.heist.heist_scene",                     "HeistScene"),
    ("command_center", 5566, "content.scenes.command_center.command_center_scene",   "CommandCenterScene"),
    ("games",          5567, "content.scenes.games.games_scene",                     "GamesScene"),
    ("asset_studio",   5568, "content.scenes.asset_studio.asset_studio_scene",       "AssetStudioScene"),
    ("oracle",         5572, "content.scenes.oracle.oracle_scene",                   "OracleScene"),
    ("cyberspace",     5573, "content.scenes.cyberspace.cyberspace_scene",           "CyberspaceScene"),
    ("auction",        5574, "content.scenes.auction.auction_scene",                 "AuctionScene"),
    ("neonos",         5593, "content.scenes.neonos.neonos_scene",                   "NeonosScene"),
]


# ──── Helpers ─────────────────────────────────────────────────────────────

def port_up(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def get_pids_on_port(port: int) -> list[str]:
    """Get PIDs listening on a port via netstat."""
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"], stderr=subprocess.DEVNULL, text=True, timeout=5,
        )
        pids = []
        for line in out.splitlines():
            if f":{port} " in line and "LISTENING" in line:
                pid = line.split()[-1]
                if pid.isdigit() and int(pid) > 4:
                    pids.append(pid)
        return pids
    except Exception:
        return []


def kill_port(port: int) -> bool:
    """Kill processes on port using PowerShell (taskkill hangs in Git Bash)."""
    pids = get_pids_on_port(port)
    if not pids:
        return False
    for pid in pids:
        try:
            subprocess.run(
                ["powershell", "-Command", f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
            )
        except Exception:
            pass
    return True


def kill_all() -> None:
    all_targets = CORE_SERVICES + CORE_SCENES + EXTRA_SCENES
    all_ports = [t[1] for t in all_targets] + [8700]
    # Collect all PIDs first (one netstat call), then kill
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"], stderr=subprocess.DEVNULL, text=True, timeout=5,
        )
    except Exception:
        print("  Failed to read netstat.", flush=True)
        return
    port_set = set(all_ports)
    pids = set()
    for line in out.splitlines():
        if "LISTENING" not in line:
            continue
        for port in port_set:
            if f":{port} " in line:
                pid = line.split()[-1]
                if pid.isdigit() and int(pid) > 4:
                    pids.add(pid)
    if pids:
        pid_csv = ",".join(pids)
        cmd = f"({pid_csv}) | ForEach-Object {{ Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }}"
        subprocess.run(
            ["powershell", "-Command", cmd],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
        )
    print(f"  Killed {len(pids)} processes.", flush=True)


def spawn(name: str, port: int, module: str, cls: str) -> subprocess.Popen | None:
    """Spawn a scene as its own process — no launcher.py dependency."""
    # Inline Python script that imports and starts the scene directly
    script = (
        f"import sys; sys.path.insert(0, r'{PROJECT_ROOT}'); "
        f"from {module} import {cls}; "
        f"app = {cls}(); app.start()"
    )
    log_path = PROJECT_ROOT / "data" / f"scene_{name}.log"
    try:
        log_file = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            [PYTHON, "-c", script],
            stdout=subprocess.DEVNULL,
            stderr=log_file,
            cwd=str(PROJECT_ROOT),
        )
        return proc
    except Exception as exc:
        print(f"    [{name:<15}] FAILED: {exc}", flush=True)
        return None


# ──── Main ────────────────────────────────────────────────────────────────

def run(targets: list, label: str) -> list[subprocess.Popen]:
    procs = []
    print(f"\n  {label}:", flush=True)
    for name, port, module, cls in targets:
        if port_up(port):
            print(f"    {name:<15} :{port}  (already up, skipping)", flush=True)
            continue

        proc = spawn(name, port, module, cls)
        if proc:
            procs.append(proc)
            print(f"    {name:<15} :{port}  PID {proc.pid}", flush=True)
    return procs


def main() -> None:
    parser = argparse.ArgumentParser(description="CosySim Quick Start")
    parser.add_argument("--all", action="store_true", help="Launch everything")
    parser.add_argument("--kill", action="store_true", help="Kill all CosySim processes")
    args = parser.parse_args()

    if args.kill:
        kill_all()
        return

    print("=" * 50, flush=True)
    print("  CosySim Quick Start", flush=True)
    print(f"  Python: {PYTHON}", flush=True)
    print("=" * 50, flush=True)

    all_procs: list[subprocess.Popen] = []

    # 1. Nexus KMS
    if port_up(8700):
        print(f"\n  [UP] Nexus KMS :8700 (already running)", flush=True)
    else:
        nexus_dir = Path(r"C:\Files\Nexus")
        if nexus_dir.is_dir():
            proc = subprocess.Popen(
                [PYTHON, "-m", "nexus", "api"],
                cwd=str(nexus_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            all_procs.append(proc)
            for _ in range(30):
                if port_up(8700):
                    break
                time.sleep(0.5)
            status = "UP" if port_up(8700) else "--"
            print(f"\n  [{status}] Nexus KMS :8700  PID {proc.pid}", flush=True)

    # 2. Services + scenes
    all_procs += run(CORE_SERVICES, "Services")
    all_procs += run(CORE_SCENES, "Scenes")
    if args.all:
        all_procs += run(EXTRA_SCENES, "Extra Scenes")

    # 3. Wait for ports
    all_targets = CORE_SERVICES + CORE_SCENES
    if args.all:
        all_targets += EXTRA_SCENES

    print(f"\n  Waiting for {len(all_targets)} targets...", flush=True)
    time.sleep(8)

    up = 0
    print(flush=True)
    for name, port, _, _ in all_targets:
        is_up = port_up(port)
        if is_up:
            up += 1
        mark = "UP" if is_up else "--"
        print(f"    [{mark}] {name:<15} :{port}", flush=True)

    print(f"\n  {up}/{len(all_targets)} UP.  Hub: http://localhost:8500", flush=True)
    print(f"  Logs: data/scene_*.log", flush=True)
    print(f"  Ctrl+C to stop all.\n", flush=True)

    # 4. Watchdog
    shutdown = False
    def _sig(s, f):
        nonlocal shutdown
        shutdown = True
    signal.signal(signal.SIGINT, _sig)

    try:
        while not shutdown:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    print("\n  Shutting down...", flush=True)
    for proc in all_procs:
        try:
            proc.terminate()
        except Exception:
            pass
    time.sleep(1)
    kill_all()
    print("  Done.", flush=True)


if __name__ == "__main__":
    main()
