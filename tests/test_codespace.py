"""
Tests for engine.codespace — manager + skills.

All gh.exe subprocess calls are mocked; no real Codespace interaction.
"""
import json
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from engine.codespace.manager import CodespaceManager, CodespaceInfo, ExecResult


# ──── Fixtures ────


@pytest.fixture
def mock_config():
    """Mock config with codespace defaults."""
    defaults = {
        "codespace.gh_path": "gh.exe",
        "codespace.default_repo": "nihilistau/CosySim",
        "codespace.default_machine": "standardLinux32gb",
        "codespace.idle_timeout": "30m",
    }
    mock = MagicMock()
    mock.get = lambda key, default=None: defaults.get(key, default)
    return mock


@pytest.fixture
def manager(mock_config):
    """CodespaceManager with mocked config."""
    with patch("engine.codespace.manager.get_config", return_value=mock_config):
        mgr = CodespaceManager()
    return mgr


@pytest.fixture
def mock_subprocess():
    """Patch subprocess.run for manager._run."""
    with patch("engine.codespace.manager.subprocess.run") as mock_run:
        yield mock_run


def _make_proc(stdout="", stderr="", returncode=0):
    """Helper to create a mock CompletedProcess."""
    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = stderr
    proc.returncode = returncode
    return proc


# ──── Manager Tests ────


class TestCodespaceManagerDiscovery:
    """Tests for is_available and list_codespaces."""

    def test_is_available_true(self, manager, mock_subprocess):
        """gh CLI has codespace scope."""
        mock_subprocess.return_value = _make_proc(
            stdout="Token scopes: 'codespace', 'repo'"
        )
        with patch("engine.codespace.manager.shutil.which", return_value="gh.exe"):
            assert manager.is_available() is True

    def test_is_available_no_scope(self, manager, mock_subprocess):
        """gh CLI lacks codespace scope."""
        mock_subprocess.return_value = _make_proc(
            stdout="Token scopes: 'repo', 'workflow'"
        )
        with patch("engine.codespace.manager.shutil.which", return_value="gh.exe"):
            assert manager.is_available() is False

    def test_is_available_no_gh(self, manager):
        """gh CLI not installed."""
        with patch("engine.codespace.manager.shutil.which", return_value=None):
            assert manager.is_available() is False

    def test_list_codespaces(self, manager, mock_subprocess):
        """Parse codespace list JSON."""
        data = [
            {
                "name": "super-waffle-abc123",
                "repository": "nihilistau/CosySim",
                "state": "Available",
                "machineName": "standardLinux32gb",
                "createdAt": "2026-02-26T08:33:00Z",
            }
        ]
        mock_subprocess.return_value = _make_proc(stdout=json.dumps(data))
        spaces = manager.list_codespaces()
        assert len(spaces) == 1
        assert spaces[0].name == "super-waffle-abc123"
        assert spaces[0].state == "Available"
        assert spaces[0].repository == "nihilistau/CosySim"

    def test_list_codespaces_empty(self, manager, mock_subprocess):
        """Empty list returns empty."""
        mock_subprocess.return_value = _make_proc(stdout="[]")
        assert manager.list_codespaces() == []

    def test_list_codespaces_error(self, manager, mock_subprocess):
        """CLI error returns empty list."""
        mock_subprocess.return_value = _make_proc(
            stderr="auth required", returncode=1
        )
        assert manager.list_codespaces() == []

    def test_list_codespaces_with_repo_filter(self, manager, mock_subprocess):
        """Repo filter is passed to CLI."""
        mock_subprocess.return_value = _make_proc(stdout="[]")
        manager.list_codespaces(repo="nihilistau/CosySim")
        args = mock_subprocess.call_args[0][0]
        assert "--repo" in args
        assert "nihilistau/CosySim" in args

    def test_get_codespace_found(self, manager, mock_subprocess):
        """Find a specific codespace by name."""
        data = [
            {"name": "a", "repository": "r", "state": "Available", "machineName": "m", "createdAt": "t"},
            {"name": "b", "repository": "r", "state": "Shutdown", "machineName": "m", "createdAt": "t"},
        ]
        mock_subprocess.return_value = _make_proc(stdout=json.dumps(data))
        info = manager.get_codespace("b")
        assert info is not None
        assert info.name == "b"
        assert info.state == "Shutdown"

    def test_get_codespace_not_found(self, manager, mock_subprocess):
        """Missing codespace returns None."""
        mock_subprocess.return_value = _make_proc(stdout="[]")
        assert manager.get_codespace("nonexistent") is None


class TestCodespaceManagerLifecycle:
    """Tests for create, stop, delete."""

    def test_create_success(self, manager, mock_subprocess):
        """Create returns codespace name."""
        mock_subprocess.return_value = _make_proc(
            stdout="✔ Codespaces usage paid by nihilistau\nfunky-name-xyz123\n"
        )
        name = manager.create()
        assert name == "funky-name-xyz123"

    def test_create_with_branch(self, manager, mock_subprocess):
        """Branch parameter is passed."""
        mock_subprocess.return_value = _make_proc(stdout="my-space\n")
        manager.create(branch="feature/test")
        args = mock_subprocess.call_args[0][0]
        assert "--branch" in args
        assert "feature/test" in args

    def test_create_failure(self, manager, mock_subprocess):
        """Failed creation returns None."""
        mock_subprocess.return_value = _make_proc(
            stderr="403 Forbidden", returncode=1
        )
        assert manager.create() is None

    def test_stop_success(self, manager, mock_subprocess):
        """Stop returns True."""
        mock_subprocess.return_value = _make_proc()
        assert manager.stop("my-space") is True

    def test_stop_failure(self, manager, mock_subprocess):
        """Failed stop returns False."""
        mock_subprocess.return_value = _make_proc(
            stderr="not found", returncode=1
        )
        assert manager.stop("bad-name") is False

    def test_delete_success(self, manager, mock_subprocess):
        """Delete returns True."""
        mock_subprocess.return_value = _make_proc()
        assert manager.delete("my-space") is True

    def test_delete_force(self, manager, mock_subprocess):
        """Force delete passes --force flag."""
        mock_subprocess.return_value = _make_proc()
        manager.delete("my-space", force=True)
        args = mock_subprocess.call_args[0][0]
        assert "--force" in args


class TestCodespaceManagerExecution:
    """Tests for ssh_exec, run_tests, eval_code."""

    def test_ssh_exec_success(self, manager, mock_subprocess):
        """Successful remote command."""
        mock_subprocess.return_value = _make_proc(stdout="hello world\n")
        result = manager.ssh_exec("my-space", "echo hello world")
        assert result.stdout == "hello world\n"
        assert result.returncode == 0
        assert result.timed_out is False

    def test_ssh_exec_with_workdir(self, manager, mock_subprocess):
        """Workdir is prepended to command."""
        mock_subprocess.return_value = _make_proc(stdout="ok")
        manager.ssh_exec("my-space", "ls", workdir="/workspaces/CosySim")
        args = mock_subprocess.call_args[0][0]
        cmd_str = args[-1]
        assert "cd /workspaces/CosySim" in cmd_str

    def test_ssh_exec_failure(self, manager, mock_subprocess):
        """Remote command failure."""
        mock_subprocess.return_value = _make_proc(
            stderr="command not found", returncode=127
        )
        result = manager.ssh_exec("my-space", "bad-cmd")
        assert result.returncode == 127

    def test_ssh_exec_timeout(self, manager, mock_subprocess):
        """Command timeout handling."""
        import subprocess as sp
        mock_subprocess.side_effect = sp.TimeoutExpired(cmd="test", timeout=10)
        result = manager.ssh_exec("my-space", "sleep 999", timeout=10)
        assert result.timed_out is True
        assert result.returncode == -1

    def test_run_tests(self, manager, mock_subprocess):
        """Run tests delegates to ssh_exec with pytest command."""
        mock_subprocess.return_value = _make_proc(
            stdout="42 passed in 12.5s\n"
        )
        result = manager.run_tests("my-space")
        assert "42 passed" in result.stdout
        args = mock_subprocess.call_args[0][0]
        cmd_str = args[-1]
        assert "pytest" in cmd_str
        assert "--ignore=tests/test_agent_loop.py" in cmd_str

    def test_run_tests_with_extra_args(self, manager, mock_subprocess):
        """Extra pytest args are included."""
        mock_subprocess.return_value = _make_proc(stdout="ok")
        manager.run_tests("my-space", path="tests/test_foo.py", extra_args="-v -k bar")
        args = mock_subprocess.call_args[0][0]
        cmd_str = args[-1]
        assert "test_foo.py" in cmd_str
        assert "-v -k bar" in cmd_str

    def test_eval_code(self, manager, mock_subprocess):
        """Evaluate Python code remotely."""
        mock_subprocess.return_value = _make_proc(stdout="4\n")
        result = manager.eval_code("my-space", "print(2+2)")
        assert result.stdout == "4\n"

    def test_get_ports(self, manager, mock_subprocess):
        """Parse port forwarding info."""
        ports = [{"sourcePort": 5555, "visibility": "private", "label": "scene"}]
        mock_subprocess.return_value = _make_proc(stdout=json.dumps(ports))
        result = manager.get_ports("my-space")
        assert len(result) == 1
        assert result[0]["sourcePort"] == 5555


class TestCodespaceManagerGhNotFound:
    """Tests for missing gh CLI."""

    def test_gh_not_found(self, manager, mock_subprocess):
        """FileNotFoundError handled gracefully."""
        mock_subprocess.side_effect = FileNotFoundError("gh.exe not found")
        result = manager.ssh_exec("my-space", "ls")
        assert result.returncode == -1
        assert "not found" in result.stderr


# ──── Skill Tests ────


class TestCodespaceSkills:
    """Tests for codespace MCP skills."""

    @patch("engine.skills.builtin.codespace_skills.get_codespace_manager")
    def test_codespace_list_skill(self, mock_mgr):
        """List skill formats output correctly."""
        from engine.skills.builtin.codespace_skills import codespace_list

        mock_mgr.return_value.list_codespaces.return_value = [
            CodespaceInfo(
                name="test-space",
                repository="nihilistau/CosySim",
                state="Available",
                machine="standardLinux32gb",
            )
        ]
        result = codespace_list()
        assert "test-space" in result
        assert "Available" in result
        assert "1 codespace" in result

    @patch("engine.skills.builtin.codespace_skills.get_codespace_manager")
    def test_codespace_list_empty(self, mock_mgr):
        """Empty list gives friendly message."""
        from engine.skills.builtin.codespace_skills import codespace_list

        mock_mgr.return_value.list_codespaces.return_value = []
        result = codespace_list()
        assert "No codespaces found" in result

    @patch("engine.skills.builtin.codespace_skills.get_codespace_manager")
    def test_codespace_exec_skill(self, mock_mgr):
        """Exec skill returns formatted output."""
        from engine.skills.builtin.codespace_skills import codespace_exec

        mock_mgr.return_value.ssh_exec.return_value = ExecResult(
            stdout="hello world", returncode=0
        )
        result = codespace_exec("test-space", "echo hello world")
        assert "hello world" in result
        assert "exit_code: 0" in result

    @patch("engine.skills.builtin.codespace_skills.get_codespace_manager")
    def test_codespace_run_tests_skill(self, mock_mgr):
        """Run tests skill returns test summary."""
        from engine.skills.builtin.codespace_skills import codespace_run_tests

        mock_mgr.return_value.run_tests.return_value = ExecResult(
            stdout="42 passed, 1 failed in 15.3s\n", returncode=1
        )
        result = codespace_run_tests("test-space")
        assert "42 passed" in result
        assert "1 failed" in result

    @patch("engine.skills.builtin.codespace_skills.get_codespace_manager")
    def test_codespace_eval_code_skill(self, mock_mgr):
        """Eval code skill returns code output."""
        from engine.skills.builtin.codespace_skills import codespace_eval_code

        mock_mgr.return_value.eval_code.return_value = ExecResult(
            stdout="42", returncode=0
        )
        result = codespace_eval_code("test-space", "print(6*7)")
        assert "42" in result

    @patch("engine.skills.builtin.codespace_skills.get_codespace_manager")
    def test_codespace_status_skill(self, mock_mgr):
        """Status skill returns formatted info."""
        from engine.skills.builtin.codespace_skills import codespace_status

        mock_mgr.return_value.get_codespace.return_value = CodespaceInfo(
            name="test-space",
            repository="nihilistau/CosySim",
            state="Available",
            machine="standardLinux32gb",
            created_at="2026-02-26T08:33:00Z",
        )
        mock_mgr.return_value.get_ports.return_value = []
        result = codespace_status("test-space")
        assert "test-space" in result
        assert "Available" in result
        assert "nihilistau/CosySim" in result

    @patch("engine.skills.builtin.codespace_skills.get_codespace_manager")
    def test_codespace_status_not_found(self, mock_mgr):
        """Status skill handles missing codespace."""
        from engine.skills.builtin.codespace_skills import codespace_status

        mock_mgr.return_value.get_codespace.return_value = None
        result = codespace_status("bad-name")
        assert "not found" in result

    @patch("engine.skills.builtin.codespace_skills.get_codespace_manager")
    def test_codespace_create_skill(self, mock_mgr):
        """Create skill returns success message."""
        from engine.skills.builtin.codespace_skills import codespace_create

        mock_mgr.return_value.create.return_value = "new-space-xyz"
        result = codespace_create()
        assert "new-space-xyz" in result
        assert "✅" in result

    @patch("engine.skills.builtin.codespace_skills.get_codespace_manager")
    def test_codespace_create_failure(self, mock_mgr):
        """Create skill handles failure."""
        from engine.skills.builtin.codespace_skills import codespace_create

        mock_mgr.return_value.create.return_value = None
        result = codespace_create()
        assert "❌" in result


# ──── Singleton Tests ────


class TestCodespaceManagerSingleton:
    """Tests for singleton pattern."""

    def test_get_codespace_manager_returns_same_instance(self):
        """Singleton returns same instance."""
        import engine.codespace.manager as mod
        mod._instance = None  # Reset
        with patch("engine.codespace.manager.get_config") as mock_cfg:
            mock_cfg.return_value.get = lambda k, d=None: d
            mgr1 = mod.get_codespace_manager()
            mgr2 = mod.get_codespace_manager()
            assert mgr1 is mgr2
        mod._instance = None  # Cleanup


# ──── Data Class Tests ────


class TestDataClasses:
    """Tests for CodespaceInfo and ExecResult."""

    def test_codespace_info_defaults(self):
        """Default values for optional fields."""
        info = CodespaceInfo(name="test", repository="r", state="Available")
        assert info.machine == ""
        assert info.created_at == ""

    def test_exec_result_defaults(self):
        """Default ExecResult is success with no output."""
        result = ExecResult()
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.returncode == 0
        assert result.timed_out is False

    def test_exec_result_timeout(self):
        """Timed out result."""
        result = ExecResult(timed_out=True, returncode=-1)
        assert result.timed_out is True
