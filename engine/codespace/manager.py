"""
Codespace lifecycle manager — wraps ``gh codespace`` CLI for remote execution.

Provides a programmatic interface for creating, managing, and executing
commands inside GitHub Codespaces. Used by codespace MCP skills to give
LLM agents access to cloud-based test/build environments.

Usage::

    from engine.codespace import get_codespace_manager
    mgr = get_codespace_manager()

    # List active codespaces
    spaces = mgr.list_codespaces()

    # Run a command remotely
    result = mgr.ssh_exec("super-waffle-abc123", "python -m pytest tests/ -q")

    # Create a new codespace
    name = mgr.create(repo="nihilistau/CosySim", machine="standardLinux32gb")
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)

_GH_EXE = "gh.exe"

# ──── Data Classes ────


@dataclass
class CodespaceInfo:
    """Snapshot of a GitHub Codespace."""

    name: str
    repository: str
    state: str
    machine: str = ""
    created_at: str = ""
    idle_timeout: str = ""


@dataclass
class ExecResult:
    """Result of a remote command execution."""

    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    timed_out: bool = False


# ──── Manager ────


class CodespaceManager:
    """Manages GitHub Codespace lifecycle and remote execution.

    All operations delegate to ``gh.exe codespace`` CLI commands via
    subprocess. Requires ``gh`` CLI authenticated with ``codespace`` scope.
    """

    def __init__(self, gh_path: Optional[str] = None) -> None:
        self._gh = gh_path or get_config().get("codespace.gh_path", _GH_EXE)
        self._default_repo = get_config().get(
            "codespace.default_repo", "nihilistau/CosySim"
        )
        self._default_machine = get_config().get(
            "codespace.default_machine", "standardLinux32gb"
        )
        self._default_idle = get_config().get(
            "codespace.idle_timeout", "30m"
        )

    # ──── Discovery ────

    def is_available(self) -> bool:
        """Check if gh CLI is installed and has codespace scope."""
        if not shutil.which(self._gh):
            return False
        try:
            result = self._run(["auth", "status"], timeout=10)
            return "codespace" in result.stdout
        except Exception:
            return False

    def list_codespaces(self, repo: Optional[str] = None) -> List[CodespaceInfo]:
        """List codespaces, optionally filtered by repository.

        Args:
            repo: Filter by repository (e.g. ``nihilistau/CosySim``).

        Returns:
            List of CodespaceInfo objects.
        """
        cmd = [
            "codespace", "list",
            "--json", "name,repository,state,machineName,createdAt",
        ]
        if repo:
            cmd.extend(["--repo", repo])

        result = self._run(cmd)
        if result.returncode != 0:
            logger.error("Failed to list codespaces: %s", result.stderr)
            return []

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            logger.error("Invalid JSON from gh codespace list")
            return []

        return [
            CodespaceInfo(
                name=item.get("name", ""),
                repository=item.get("repository", ""),
                state=item.get("state", "Unknown"),
                machine=item.get("machineName", ""),
                created_at=item.get("createdAt", ""),
            )
            for item in data
        ]

    def get_codespace(self, name: str) -> Optional[CodespaceInfo]:
        """Get info for a specific codespace by name.

        Args:
            name: Codespace name (e.g. ``super-waffle-5rv545x6wv2pg57``).

        Returns:
            CodespaceInfo or None if not found.
        """
        spaces = self.list_codespaces()
        return next((s for s in spaces if s.name == name), None)

    # ──── Lifecycle ────

    def create(
        self,
        repo: Optional[str] = None,
        machine: Optional[str] = None,
        idle_timeout: Optional[str] = None,
        branch: Optional[str] = None,
    ) -> Optional[str]:
        """Create a new codespace.

        Args:
            repo: Repository (default from config).
            machine: Machine type (default: standardLinux32gb).
            idle_timeout: Idle timeout (default: 30m).
            branch: Git branch to use.

        Returns:
            Codespace name string, or None on failure.
        """
        cmd = [
            "codespace", "create",
            "--repo", repo or self._default_repo,
            "--machine", machine or self._default_machine,
            "--idle-timeout", idle_timeout or self._default_idle,
        ]
        if branch:
            cmd.extend(["--branch", branch])

        result = self._run(cmd, timeout=120)
        if result.returncode != 0:
            logger.error("Failed to create codespace: %s", result.stderr)
            return None

        name = result.stdout.strip().split("\n")[-1].strip()
        logger.info("Created codespace: %s", name)
        return name

    def stop(self, name: str) -> bool:
        """Stop a running codespace.

        Args:
            name: Codespace name.

        Returns:
            True if stopped successfully.
        """
        result = self._run(["codespace", "stop", "--codespace", name], timeout=30)
        if result.returncode != 0:
            logger.error("Failed to stop codespace %s: %s", name, result.stderr)
            return False
        logger.info("Stopped codespace: %s", name)
        return True

    def delete(self, name: str, force: bool = False) -> bool:
        """Delete a codespace.

        Args:
            name: Codespace name.
            force: Force delete even if running.

        Returns:
            True if deleted successfully.
        """
        cmd = ["codespace", "delete", "--codespace", name]
        if force:
            cmd.append("--force")

        result = self._run(cmd, timeout=30)
        if result.returncode != 0:
            logger.error("Failed to delete codespace %s: %s", name, result.stderr)
            return False
        logger.info("Deleted codespace: %s", name)
        return True

    # ──── Remote Execution ────

    def ssh_exec(
        self,
        name: str,
        command: str,
        timeout: int = 120,
        workdir: Optional[str] = None,
    ) -> ExecResult:
        """Execute a command inside a codespace via SSH.

        Args:
            name: Codespace name.
            command: Shell command to run remotely.
            timeout: Maximum execution time in seconds.
            workdir: Working directory inside the codespace.

        Returns:
            ExecResult with stdout, stderr, returncode.
        """
        if workdir:
            command = f"cd {workdir} && {command}"

        result = self._run(
            ["codespace", "ssh", "--codespace", name, "--", command],
            timeout=timeout,
        )
        return ExecResult(
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
            timed_out=result.timed_out,
        )

    def run_tests(
        self,
        name: str,
        path: str = "tests/",
        extra_args: str = "",
        timeout: int = 600,
    ) -> ExecResult:
        """Run pytest inside a codespace.

        Args:
            name: Codespace name.
            path: Test path relative to workspace root.
            extra_args: Additional pytest arguments.
            timeout: Maximum execution time in seconds.

        Returns:
            ExecResult with test output.
        """
        cmd = (
            f"cd /workspaces/CosySim && python -m pytest {path} "
            f"--tb=short -q --ignore=tests/test_agent_loop.py "
            f"--ignore=tests/live_wire_test.py {extra_args}"
        )
        return self.ssh_exec(name, cmd.strip(), timeout=timeout)

    def eval_code(
        self,
        name: str,
        code: str,
        timeout: int = 30,
    ) -> ExecResult:
        """Execute Python code inside a codespace.

        Args:
            name: Codespace name.
            code: Python code to execute.
            timeout: Maximum execution time in seconds.

        Returns:
            ExecResult with code output.
        """
        # Escape for shell transport
        escaped = code.replace("\\", "\\\\").replace("'", "'\\''")
        cmd = f"cd /workspaces/CosySim && python3 -c '{escaped}'"
        return self.ssh_exec(name, cmd, timeout=timeout)

    def get_ports(self, name: str) -> List[Dict[str, Any]]:
        """List forwarded ports for a codespace.

        Args:
            name: Codespace name.

        Returns:
            List of port forwarding info dicts.
        """
        result = self._run(
            ["codespace", "ports", "--codespace", name, "--json", "label,sourcePort,visibility"],
            timeout=15,
        )
        if result.returncode != 0:
            return []
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return []

    # ──── Internal ────

    def _run(
        self, args: List[str], timeout: int = 30
    ) -> ExecResult:
        """Run a gh CLI command.

        Args:
            args: Arguments after ``gh``.
            timeout: Maximum execution time.

        Returns:
            ExecResult with command output.
        """
        cmd = [self._gh] + args
        logger.debug("Running: %s", " ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return ExecResult(
                stdout=proc.stdout,
                stderr=proc.stderr,
                returncode=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Command timed out after %ds: %s", timeout, " ".join(cmd))
            return ExecResult(
                stderr=f"Command timed out after {timeout}s",
                returncode=-1,
                timed_out=True,
            )
        except FileNotFoundError:
            logger.error("gh CLI not found at %s", self._gh)
            return ExecResult(
                stderr=f"gh CLI not found at {self._gh}",
                returncode=-1,
            )


# ──── Singleton ────

_instance: Optional[CodespaceManager] = None


def get_codespace_manager() -> CodespaceManager:
    """Get the singleton CodespaceManager instance."""
    global _instance
    if _instance is None:
        _instance = CodespaceManager()
    return _instance
