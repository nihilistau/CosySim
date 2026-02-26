"""
Codespace MCP skills — remote test/build/eval via GitHub Codespaces.

Gives LLM agents the ability to execute code, run tests, and manage
cloud-based development environments through the Codespace manager.
"""
from __future__ import annotations

import logging
from typing import Optional

from engine.codespace.manager import get_codespace_manager
from engine.skills.skill import skill

logger = logging.getLogger(__name__)


@skill(
    pack="codespace",
    description="List GitHub Codespaces. Shows name, repo, state, machine type.",
    category="SYSTEM",
    tags=["codespace", "cloud", "infrastructure"],
)
def codespace_list(repo: Optional[str] = None) -> str:
    """List active GitHub Codespaces."""
    mgr = get_codespace_manager()
    spaces = mgr.list_codespaces(repo=repo)
    if not spaces:
        return "No codespaces found."
    lines = []
    for s in spaces:
        lines.append(
            f"• {s.name} | {s.repository} | {s.state} | {s.machine}"
        )
    return f"Found {len(spaces)} codespace(s):\n" + "\n".join(lines)


@skill(
    pack="codespace",
    description=(
        "Run a shell command inside a GitHub Codespace via SSH. "
        "Returns stdout, stderr, and exit code."
    ),
    category="SYSTEM",
    tags=["codespace", "remote", "execution"],
    cooldown=5.0,
)
def codespace_exec(
    name: str,
    command: str,
    timeout: int = 120,
    workdir: Optional[str] = None,
) -> str:
    """Execute a command remotely inside a codespace.

    Args:
        name: Codespace name (e.g. super-waffle-5rv545x6wv2pg57).
        command: Shell command to run.
        timeout: Max execution time in seconds.
        workdir: Working directory inside the codespace.
    """
    mgr = get_codespace_manager()
    result = mgr.ssh_exec(name, command, timeout=timeout, workdir=workdir)

    parts = []
    if result.stdout:
        parts.append(f"stdout:\n{result.stdout.rstrip()}")
    if result.stderr:
        parts.append(f"stderr:\n{result.stderr.rstrip()}")
    parts.append(f"exit_code: {result.returncode}")
    if result.timed_out:
        parts.append("⚠️ Command timed out")

    return "\n".join(parts)


@skill(
    pack="codespace",
    description=(
        "Run the CosySim test suite inside a GitHub Codespace. "
        "Tests run in an isolated cloud environment with full dependencies."
    ),
    category="SYSTEM",
    tags=["codespace", "testing", "ci"],
    cooldown=10.0,
    cost=2.0,
)
def codespace_run_tests(
    name: str,
    path: str = "tests/",
    extra_args: str = "",
    timeout: int = 600,
) -> str:
    """Run pytest inside a codespace.

    Args:
        name: Codespace name.
        path: Test path relative to workspace root (default: tests/).
        extra_args: Additional pytest flags (e.g. -v -k test_foo).
        timeout: Max execution time in seconds.
    """
    mgr = get_codespace_manager()
    result = mgr.run_tests(name, path=path, extra_args=extra_args, timeout=timeout)

    output = result.stdout + result.stderr
    if result.timed_out:
        return f"⚠️ Tests timed out after {timeout}s.\n\nPartial output:\n{output[-2000:]}"

    # Extract summary line
    lines = output.strip().split("\n")
    summary = lines[-1] if lines else "No output"
    return f"Test Results ({summary}):\n\n{output[-3000:]}"


@skill(
    pack="codespace",
    description=(
        "Execute Python code inside a GitHub Codespace. "
        "Code runs in an isolated cloud environment."
    ),
    category="SYSTEM",
    tags=["codespace", "python", "evaluation"],
    cooldown=5.0,
)
def codespace_eval_code(
    name: str,
    code: str,
    timeout: int = 30,
) -> str:
    """Evaluate Python code remotely in a codespace.

    Args:
        name: Codespace name.
        code: Python code to execute.
        timeout: Max execution time in seconds.
    """
    mgr = get_codespace_manager()
    result = mgr.eval_code(name, code, timeout=timeout)

    parts = []
    if result.stdout:
        parts.append(result.stdout.rstrip())
    if result.stderr:
        parts.append(f"stderr: {result.stderr.rstrip()}")
    if result.timed_out:
        parts.append(f"⚠️ Timed out after {timeout}s")
    if result.returncode != 0:
        parts.append(f"exit_code: {result.returncode}")

    return "\n".join(parts) if parts else "(no output)"


@skill(
    pack="codespace",
    description="Check status of a GitHub Codespace — state, machine type, ports.",
    category="SYSTEM",
    tags=["codespace", "status"],
)
def codespace_status(name: str) -> str:
    """Get detailed status of a specific codespace.

    Args:
        name: Codespace name.
    """
    mgr = get_codespace_manager()
    info = mgr.get_codespace(name)
    if not info:
        return f"Codespace '{name}' not found."

    lines = [
        f"Name: {info.name}",
        f"Repository: {info.repository}",
        f"State: {info.state}",
        f"Machine: {info.machine}",
        f"Created: {info.created_at}",
    ]

    if info.state == "Available":
        ports = mgr.get_ports(name)
        if ports:
            lines.append("Ports:")
            for p in ports:
                lines.append(
                    f"  • {p.get('sourcePort', '?')} ({p.get('visibility', 'private')})"
                )

    return "\n".join(lines)


@skill(
    pack="codespace",
    description="Create a new GitHub Codespace for a repository.",
    category="SYSTEM",
    tags=["codespace", "create", "infrastructure"],
    cooldown=30.0,
    cost=5.0,
)
def codespace_create(
    repo: Optional[str] = None,
    machine: Optional[str] = None,
    branch: Optional[str] = None,
) -> str:
    """Create a new codespace.

    Args:
        repo: Repository (default: nihilistau/CosySim).
        machine: Machine type (default: standardLinux32gb).
        branch: Git branch to use.
    """
    mgr = get_codespace_manager()
    name = mgr.create(repo=repo, machine=machine, branch=branch)
    if name:
        return f"✅ Created codespace: {name}"
    return "❌ Failed to create codespace. Check gh auth and permissions."
