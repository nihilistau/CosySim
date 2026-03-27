"""
CosySim Apps Bootstrap
=======================

Shared bootstrap for all standalone CLI apps. Handles:
- Auto venv re-exec (no manual activation needed)
- Project root on sys.path
- CWD set to project root

Version: v1.57.2 [2026-03-27]
Author:  CosySim Team

Usage (in each app):
    from _bootstrap import ROOT, SCRIPTS, run, run_module
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# ──── Path resolution ─────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
SCRIPTS = ROOT / "scripts"


def bootstrap() -> None:
    """Ensure we're running in the venv with correct paths.

    Call this at the top of each CLI app's __main__ guard.
    If not in the venv, re-execs the current script with venv python.
    """
    # Re-exec into venv if needed (Windows subprocess, not os.execv)
    if VENV_PYTHON.exists() and Path(sys.executable).resolve() != VENV_PYTHON.resolve():
        result = subprocess.run([str(VENV_PYTHON)] + sys.argv, cwd=str(ROOT))
        sys.exit(result.returncode)

    # Ensure project root on sys.path
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    # Ensure CWD is project root for relative paths
    os.chdir(ROOT)


# ──── Subprocess helpers ──────────────────────────────────────────────────────


def run(script: Path, args: list[str]) -> int:
    """Run a script with the venv python, forwarding all args.

    Args:
        script: Path to the .py script.
        args: Arguments to pass through.

    Returns:
        Exit code from the subprocess.
    """
    python = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
    cmd = [python, str(script)] + args
    try:
        result = subprocess.run(cmd, cwd=str(ROOT))
        return result.returncode
    except KeyboardInterrupt:
        return 130
    except FileNotFoundError:
        print(f"ERROR: Script not found: {script}")
        return 1


def run_module(module: str, args: list[str]) -> int:
    """Run a python module with -m, forwarding args.

    Args:
        module: Module path (e.g. 'engine.nexus.cli').
        args: Arguments to pass through.

    Returns:
        Exit code from the subprocess.
    """
    python = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
    cmd = [python, "-m", module] + args
    try:
        result = subprocess.run(cmd, cwd=str(ROOT))
        return result.returncode
    except KeyboardInterrupt:
        return 130
