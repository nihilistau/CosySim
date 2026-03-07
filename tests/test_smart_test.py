"""Tests for the smart CosySim test runner."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import scripts.smart_test as smart_test


class TestDomainResolution:
    def test_tests_for_domains_preserves_requested_order(self) -> None:
        """Domain selection should preserve the caller's requested order."""
        with (
            patch.object(
                smart_test,
                "DOMAIN_TESTS",
                {"second": ["test_second.py"], "first": ["test_first.py"]},
            ),
            patch.object(
                smart_test,
                "_resolve_test_files",
                side_effect=[[Path("tests/test_second.py")], [Path("tests/test_first.py")]],
            ),
        ):
            files = smart_test._tests_for_domains(["second", "first"])

        assert files == [Path("tests/test_second.py"), Path("tests/test_first.py")]

    def test_tests_for_domains_keeps_changed_test_files_first(self, tmp_path: Path) -> None:
        """Directly changed test files should be executed before domain expansions."""
        changed_test = tmp_path / "tests" / "test_changed.py"
        changed_test.parent.mkdir(parents=True, exist_ok=True)
        changed_test.write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")

        with (
            patch.object(smart_test, "ROOT", tmp_path),
            patch.object(smart_test, "_resolve_test_files", return_value=[Path("tests/test_domain.py")]),
        ):
            files = smart_test._tests_for_domains(
                ["_self", "shared"],
                changed_files=["tests/test_changed.py"],
            )

        assert files[0] == changed_test
        assert files[1] == Path("tests/test_domain.py")


class TestParallelPytestCommand:
    def test_build_pytest_command_adds_xdist_args_by_default(self) -> None:
        """Automatic parallel mode should enable xdist when running multi-file selections."""
        with patch.object(smart_test, "_xdist_available", return_value=True):
            cmd = smart_test._build_pytest_command(
                pytest_targets=["tests/test_a.py", "tests/test_b.py"],
                extra_args=["--tb=short"],
                enable_parallel=True,
                serial=False,
                workers="auto",
                xdist_dist="loadfile",
            )

        assert "-n" in cmd
        assert "auto" in cmd
        assert "--dist=loadfile" in cmd

    def test_build_pytest_command_respects_existing_parallel_override(self) -> None:
        """Explicit pytest parallel flags should not be duplicated by the wrapper."""
        with patch.object(smart_test, "_xdist_available", return_value=True):
            cmd = smart_test._build_pytest_command(
                pytest_targets=["tests/test_a.py"],
                extra_args=["-n", "1", "--tb=short"],
                enable_parallel=True,
                serial=False,
                workers="auto",
                xdist_dist="loadfile",
            )

        assert cmd.count("-n") == 1
        assert "--dist=loadfile" not in cmd
