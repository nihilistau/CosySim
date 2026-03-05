"""Tests for engine.integrations.colab_venv_manager.

Covers the NotebookCell dataclass, every cell-generator method, the
get_setup_cells() composite helper, cells_to_ipynb() serialisation,
and the get_venv_manager() factory.  No network or filesystem I/O —
this module is pure code generation.
"""
from __future__ import annotations

from typing import List

import pytest

from engine.integrations.colab_venv_manager import (
    COSYSIM_BASE_PACKAGES,
    DRIVE_MOUNT_PATH,
    OUTPUTS_PATH,
    VENV_PATH,
    ColabVenvManager,
    NotebookCell,
    get_venv_manager,
)


# ──── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def mgr() -> ColabVenvManager:
    """Default ColabVenvManager using the standard Drive venv path."""
    return ColabVenvManager()


# ──── Tests: NotebookCell dataclass ──────────────────────────────────────────

class TestNotebookCellDataclass:
    """Tests for the NotebookCell dataclass structure and defaults."""

    def test_fields_accessible(self) -> None:
        """cell_type, source, and description should be readable attributes."""
        cell = NotebookCell(
            cell_type="code", source="print('hi')", description="A test cell"
        )
        assert cell.cell_type == "code"
        assert cell.source == "print('hi')"
        assert cell.description == "A test cell"

    def test_description_defaults_to_empty_string(self) -> None:
        """description should default to '' when not supplied."""
        cell = NotebookCell(cell_type="code", source="x = 1")
        assert cell.description == ""

    def test_code_cell_type_accepted(self) -> None:
        """cell_type='code' should be stored as-is."""
        cell = NotebookCell(cell_type="code", source="")
        assert cell.cell_type == "code"

    def test_markdown_cell_type_accepted(self) -> None:
        """cell_type='markdown' should be stored as-is."""
        cell = NotebookCell(cell_type="markdown", source="## Heading")
        assert cell.cell_type == "markdown"

    def test_source_preserved_verbatim(self) -> None:
        """Multiline source strings should be preserved exactly as supplied."""
        src = "import os\nimport sys\nprint(os.getcwd())"
        cell = NotebookCell(cell_type="code", source=src)
        assert cell.source == src


# ──── Tests: mount_drive_cell ─────────────────────────────────────────────────

class TestMountDriveCell:
    """Tests for ColabVenvManager.mount_drive_cell."""

    def test_returns_notebook_cell(self, mgr: ColabVenvManager) -> None:
        """mount_drive_cell should return a NotebookCell instance."""
        assert isinstance(mgr.mount_drive_cell(), NotebookCell)

    def test_cell_type_is_code(self, mgr: ColabVenvManager) -> None:
        """The returned cell must have cell_type 'code'."""
        assert mgr.mount_drive_cell().cell_type == "code"

    def test_source_imports_google_colab(self, mgr: ColabVenvManager) -> None:
        """Source should import google.colab to access Drive mounting."""
        src = mgr.mount_drive_cell().source
        assert "google.colab" in src or "from google.colab" in src

    def test_source_calls_drive_mount(self, mgr: ColabVenvManager) -> None:
        """Source should call drive.mount() to attach Google Drive."""
        assert "drive.mount" in mgr.mount_drive_cell().source

    def test_source_uses_drive_mount_path_constant(
        self, mgr: ColabVenvManager
    ) -> None:
        """The mount path used in source should match the DRIVE_MOUNT_PATH constant."""
        assert DRIVE_MOUNT_PATH in mgr.mount_drive_cell().source

    def test_source_creates_output_directories(self, mgr: ColabVenvManager) -> None:
        """Source should call os.makedirs to create project directories."""
        assert "makedirs" in mgr.mount_drive_cell().source

    def test_description_is_non_empty(self, mgr: ColabVenvManager) -> None:
        """mount_drive_cell should set a meaningful description string."""
        assert len(mgr.mount_drive_cell().description) > 0

    def test_source_references_outputs_path(self, mgr: ColabVenvManager) -> None:
        """Source should mention the OUTPUTS_PATH Drive directory."""
        assert OUTPUTS_PATH in mgr.mount_drive_cell().source


# ──── Tests: activate_venv_cell ───────────────────────────────────────────────

class TestActivateVenvCell:
    """Tests for ColabVenvManager.activate_venv_cell."""

    def test_returns_notebook_cell(self, mgr: ColabVenvManager) -> None:
        """activate_venv_cell should return a NotebookCell."""
        assert isinstance(mgr.activate_venv_cell(), NotebookCell)

    def test_cell_type_is_code(self, mgr: ColabVenvManager) -> None:
        """Returned cell should have cell_type 'code'."""
        assert mgr.activate_venv_cell().cell_type == "code"

    def test_source_contains_sys_path(self, mgr: ColabVenvManager) -> None:
        """Source must manipulate sys.path to inject the venv site-packages."""
        assert "sys.path" in mgr.activate_venv_cell().source

    def test_source_contains_venv_path(self, mgr: ColabVenvManager) -> None:
        """Source must reference the configured venv root path."""
        assert VENV_PATH in mgr.activate_venv_cell().source

    def test_source_contains_base_packages(self, mgr: ColabVenvManager) -> None:
        """Source should include at least one of the base packages."""
        src = mgr.activate_venv_cell().source
        # 'torch' is in COSYSIM_BASE_PACKAGES and should appear in source
        assert "torch" in src

    def test_extra_packages_appear_in_source(self, mgr: ColabVenvManager) -> None:
        """extra_packages should be embedded in the generated source code."""
        cell = mgr.activate_venv_cell(extra_packages=["my_special_lib==2.0"])
        assert "my_special_lib==2.0" in cell.source

    def test_custom_packages_override_base(self, mgr: ColabVenvManager) -> None:
        """Supplying packages= should replace the base package list entirely."""
        cell = mgr.activate_venv_cell(packages=["torch"])
        assert "torch" in cell.source
        # 'scipy' is in COSYSIM_BASE_PACKAGES; must not appear when overridden
        assert "scipy" not in cell.source

    def test_source_contains_venv_creation_logic(
        self, mgr: ColabVenvManager
    ) -> None:
        """Source should include logic for creating the venv when absent."""
        src = mgr.activate_venv_cell().source
        # Either 'venv' module call or a subprocess creation command
        assert "venv" in src

    def test_description_is_non_empty(self, mgr: ColabVenvManager) -> None:
        """activate_venv_cell should set a meaningful description."""
        assert len(mgr.activate_venv_cell().description) > 0


# ──── Tests: check_venv_exists_cell ──────────────────────────────────────────

class TestCheckVenvExistsCell:
    """Tests for ColabVenvManager.check_venv_exists_cell."""

    def test_returns_notebook_cell(self, mgr: ColabVenvManager) -> None:
        """check_venv_exists_cell should return a NotebookCell."""
        assert isinstance(mgr.check_venv_exists_cell(), NotebookCell)

    def test_cell_type_is_code(self, mgr: ColabVenvManager) -> None:
        """Returned cell should have cell_type 'code'."""
        assert mgr.check_venv_exists_cell().cell_type == "code"

    def test_source_checks_venv_python(self, mgr: ColabVenvManager) -> None:
        """Source should check for the existence of the venv Python binary."""
        src = mgr.check_venv_exists_cell().source
        assert "os.path.exists" in src or "exists" in src


# ──── Tests: install_packages_cell ───────────────────────────────────────────

class TestInstallPackagesCell:
    """Tests for ColabVenvManager.install_packages_cell."""

    def test_returns_notebook_cell(self, mgr: ColabVenvManager) -> None:
        """install_packages_cell should return a NotebookCell."""
        assert isinstance(mgr.install_packages_cell(["numpy"]), NotebookCell)

    def test_cell_type_is_code(self, mgr: ColabVenvManager) -> None:
        """Returned cell should have cell_type 'code'."""
        assert mgr.install_packages_cell(["numpy"]).cell_type == "code"

    def test_source_invokes_pip_install(self, mgr: ColabVenvManager) -> None:
        """Source must contain a pip install invocation."""
        src = mgr.install_packages_cell(["torch", "transformers"]).source
        assert "pip" in src and "install" in src

    def test_all_package_names_in_source(self, mgr: ColabVenvManager) -> None:
        """Every requested package name should appear in the source."""
        packages = ["torch", "transformers", "datasets"]
        src = mgr.install_packages_cell(packages).source
        for pkg in packages:
            assert pkg in src, f"Package '{pkg}' not found in source"

    def test_uses_venv_python_binary(self, mgr: ColabVenvManager) -> None:
        """The install command should target the Drive venv Python, not the system one."""
        src = mgr.install_packages_cell(["numpy"]).source
        # VENV_PATH is in the source (bin/python path embedded)
        assert VENV_PATH in src

    def test_description_mentions_package_count(
        self, mgr: ColabVenvManager
    ) -> None:
        """Description should mention how many packages will be installed."""
        cell = mgr.install_packages_cell(["torch", "numpy", "pandas"])
        assert "3" in cell.description


# ──── Tests: setup_ngrok_cell ─────────────────────────────────────────────────

class TestSetupNgrokCell:
    """Tests for ColabVenvManager.setup_ngrok_cell."""

    def test_returns_notebook_cell(self, mgr: ColabVenvManager) -> None:
        """setup_ngrok_cell should return a NotebookCell."""
        assert isinstance(mgr.setup_ngrok_cell(port=8000), NotebookCell)

    def test_cell_type_is_code(self, mgr: ColabVenvManager) -> None:
        """Returned cell should have cell_type 'code'."""
        assert mgr.setup_ngrok_cell(port=8000).cell_type == "code"

    def test_source_imports_or_uses_ngrok(self, mgr: ColabVenvManager) -> None:
        """Source should reference pyngrok or ngrok."""
        src = mgr.setup_ngrok_cell(port=8000).source
        assert "ngrok" in src

    def test_source_contains_port_number(self, mgr: ColabVenvManager) -> None:
        """Source should embed the requested port number as a literal."""
        src = mgr.setup_ngrok_cell(port=9000).source
        assert "9000" in src

    def test_default_port_8000_in_source(self, mgr: ColabVenvManager) -> None:
        """Default port 8000 should appear in the source when no port is specified."""
        src = mgr.setup_ngrok_cell().source
        assert "8000" in src

    def test_description_contains_port(self, mgr: ColabVenvManager) -> None:
        """Description should mention the port used for the ngrok tunnel."""
        cell = mgr.setup_ngrok_cell(port=7777)
        assert "7777" in cell.description


# ──── Tests: save_outputs_cell ────────────────────────────────────────────────

class TestSaveOutputsCell:
    """Tests for ColabVenvManager.save_outputs_cell."""

    def test_returns_notebook_cell(self, mgr: ColabVenvManager) -> None:
        """save_outputs_cell should return a NotebookCell."""
        assert isinstance(
            mgr.save_outputs_cell(["/tmp/result.json"]), NotebookCell
        )

    def test_cell_type_is_code(self, mgr: ColabVenvManager) -> None:
        """Returned cell should have cell_type 'code'."""
        assert mgr.save_outputs_cell(["/tmp/result.json"]).cell_type == "code"

    def test_source_uses_shutil(self, mgr: ColabVenvManager) -> None:
        """Source should import and use shutil for file/directory copying."""
        assert "shutil" in mgr.save_outputs_cell(["/tmp/f"]).source

    def test_source_references_outputs_path(self, mgr: ColabVenvManager) -> None:
        """Source should reference OUTPUTS_PATH as the copy destination."""
        assert OUTPUTS_PATH in mgr.save_outputs_cell(["/tmp/f"]).source

    def test_source_contains_each_provided_path(
        self, mgr: ColabVenvManager
    ) -> None:
        """Every supplied source path should appear in the generated source."""
        paths = ["/tmp/model.bin", "/tmp/logs/run1"]
        src = mgr.save_outputs_cell(paths).source
        for p in paths:
            assert p in src, f"Path '{p}' missing from source"

    def test_handles_directory_copy(self, mgr: ColabVenvManager) -> None:
        """Source should include copytree logic to handle directory inputs."""
        src = mgr.save_outputs_cell(["/tmp/dir"]).source
        assert "copytree" in src or "isdir" in src


# ──── Tests: progress_header_cell ────────────────────────────────────────────

class TestProgressHeaderCell:
    """Tests for ColabVenvManager.progress_header_cell."""

    def test_returns_markdown_cell(self, mgr: ColabVenvManager) -> None:
        """progress_header_cell should return a cell with cell_type 'markdown'."""
        cell = mgr.progress_header_cell("Title", ["Step 1"])
        assert cell.cell_type == "markdown"

    def test_source_contains_title(self, mgr: ColabVenvManager) -> None:
        """Source markdown should include the supplied title."""
        cell = mgr.progress_header_cell("My Notebook", ["Step A"])
        assert "My Notebook" in cell.source

    def test_source_contains_all_steps(self, mgr: ColabVenvManager) -> None:
        """Each step description should appear in the markdown source."""
        steps = ["Mount Drive", "Install packages", "Run training"]
        cell = mgr.progress_header_cell("Pipeline", steps)
        for step in steps:
            assert step in cell.source


# ──── Tests: get_setup_cells ──────────────────────────────────────────────────

class TestGetSetupCells:
    """Tests for ColabVenvManager.get_setup_cells composite helper."""

    def test_returns_list(self, mgr: ColabVenvManager) -> None:
        """get_setup_cells should return a list."""
        assert isinstance(mgr.get_setup_cells(), list)

    def test_returns_at_least_two_cells(self, mgr: ColabVenvManager) -> None:
        """get_setup_cells must return at least 2 cells (mount + activate)."""
        assert len(mgr.get_setup_cells()) >= 2

    def test_first_cell_mounts_drive(self, mgr: ColabVenvManager) -> None:
        """First cell should contain Drive-mounting logic."""
        cell = mgr.get_setup_cells()[0]
        src_lower = cell.source.lower()
        assert "drive" in src_lower or "colab" in src_lower

    def test_second_cell_activates_venv(self, mgr: ColabVenvManager) -> None:
        """Second cell should contain sys.path manipulation for venv activation."""
        assert "sys.path" in mgr.get_setup_cells()[1].source

    def test_all_items_are_notebook_cells(self, mgr: ColabVenvManager) -> None:
        """Every item in the returned list should be a NotebookCell instance."""
        for cell in mgr.get_setup_cells():
            assert isinstance(cell, NotebookCell)

    def test_extra_packages_forwarded_to_venv_cell(
        self, mgr: ColabVenvManager
    ) -> None:
        """Extra packages should appear in the second (venv activation) cell."""
        cells = mgr.get_setup_cells(extra_packages=["my_custom_lib>=1.5"])
        assert "my_custom_lib>=1.5" in cells[1].source

    def test_both_cells_are_code_type(self, mgr: ColabVenvManager) -> None:
        """Both setup cells should have cell_type 'code' (not markdown)."""
        for cell in mgr.get_setup_cells():
            assert cell.cell_type == "code"


# ──── Tests: cells_to_ipynb ───────────────────────────────────────────────────

class TestCellsToIpynb:
    """Tests for ColabVenvManager.cells_to_ipynb notebook serialisation."""

    def _setup_result(self, mgr: ColabVenvManager) -> dict:
        """Helper: serialise the standard setup cells."""
        return mgr.cells_to_ipynb(mgr.get_setup_cells())

    def test_returns_dict(self, mgr: ColabVenvManager) -> None:
        """cells_to_ipynb should return a dict."""
        assert isinstance(self._setup_result(mgr), dict)

    def test_has_cells_key(self, mgr: ColabVenvManager) -> None:
        """Result must have a 'cells' key."""
        assert "cells" in self._setup_result(mgr)

    def test_has_metadata_key(self, mgr: ColabVenvManager) -> None:
        """Result must have a 'metadata' key."""
        assert "metadata" in self._setup_result(mgr)

    def test_cells_length_matches_input(self, mgr: ColabVenvManager) -> None:
        """Output cells list length should equal the number of input NotebookCells."""
        input_cells = mgr.get_setup_cells()
        result = mgr.cells_to_ipynb(input_cells)
        assert len(result["cells"]) == len(input_cells)

    def test_first_cell_type_is_code(self, mgr: ColabVenvManager) -> None:
        """First serialised cell should have cell_type 'code'."""
        assert self._setup_result(mgr)["cells"][0]["cell_type"] == "code"

    def test_cell_source_is_string(self, mgr: ColabVenvManager) -> None:
        """Cell source in the ipynb dict should be a non-empty string."""
        src = self._setup_result(mgr)["cells"][0]["source"]
        assert isinstance(src, str)
        assert len(src) > 0

    def test_markdown_cell_preserved(self, mgr: ColabVenvManager) -> None:
        """Markdown cells should be serialised with cell_type 'markdown'."""
        md = mgr.progress_header_cell("Test", ["Step 1"])
        result = mgr.cells_to_ipynb([md])
        assert result["cells"][0]["cell_type"] == "markdown"

    def test_nbformat_is_four(self, mgr: ColabVenvManager) -> None:
        """Notebook format version (nbformat) should be 4 for Jupyter compatibility."""
        assert self._setup_result(mgr).get("nbformat") == 4

    def test_nbformat_minor_present(self, mgr: ColabVenvManager) -> None:
        """nbformat_minor should be present (any non-negative int)."""
        assert self._setup_result(mgr).get("nbformat_minor") >= 0

    def test_unknown_cell_type_is_skipped(self, mgr: ColabVenvManager) -> None:
        """Cells with an unrecognised cell_type should be silently omitted."""
        bad = NotebookCell(cell_type="raw", source="??")
        result = mgr.cells_to_ipynb([bad])
        assert result["cells"] == []

    def test_kernelspec_in_metadata(self, mgr: ColabVenvManager) -> None:
        """Metadata must contain a kernelspec block with language 'python'."""
        meta = self._setup_result(mgr)["metadata"]
        assert "kernelspec" in meta
        assert meta["kernelspec"]["language"] == "python"

    def test_code_cells_have_outputs_field(self, mgr: ColabVenvManager) -> None:
        """Serialised code cells should include an 'outputs' list (nbformat4 spec)."""
        cell_data = self._setup_result(mgr)["cells"][0]
        assert "outputs" in cell_data
        assert isinstance(cell_data["outputs"], list)

    def test_code_cells_have_execution_count(self, mgr: ColabVenvManager) -> None:
        """Serialised code cells should include an 'execution_count' field."""
        cell_data = self._setup_result(mgr)["cells"][0]
        assert "execution_count" in cell_data

    def test_empty_input_produces_empty_cells_list(
        self, mgr: ColabVenvManager
    ) -> None:
        """Passing an empty cell list should produce a notebook with no cells."""
        result = mgr.cells_to_ipynb([])
        assert result["cells"] == []


# ──── Tests: get_venv_manager factory ────────────────────────────────────────

class TestGetVenvManager:
    """Tests for the get_venv_manager module-level factory."""

    def test_returns_colab_venv_manager(self) -> None:
        """get_venv_manager should return a ColabVenvManager instance."""
        assert isinstance(get_venv_manager(), ColabVenvManager)

    def test_custom_venv_path_stored(self) -> None:
        """A custom venv path should be stored on the returned manager."""
        mgr = get_venv_manager(venv_path="/custom/.venv")
        assert mgr._venv_path == "/custom/.venv"

    def test_default_venv_path_matches_constant(self) -> None:
        """Default venv path should equal the VENV_PATH module constant."""
        mgr = get_venv_manager()
        assert mgr._venv_path == VENV_PATH

    def test_each_call_returns_fresh_instance(self) -> None:
        """get_venv_manager is not a singleton — each call creates a new object."""
        mgr1 = get_venv_manager()
        mgr2 = get_venv_manager()
        assert mgr1 is not mgr2
