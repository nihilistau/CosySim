"""Google Drive .venv manager for Colab notebooks.

Generates Python cell code strings that manage a persistent virtual environment
stored on Google Drive. The venv persists across Colab sessions, eliminating
the need to reinstall packages every time a new runtime starts.

Usage:
    mgr = ColabVenvManager()

    # Get cell source code to include in a notebook
    cells = mgr.get_setup_cells()  # Returns list of NotebookCell

    # Or generate specific snippets
    mount_code = mgr.mount_drive_cell()
    activate_code = mgr.activate_venv_cell()

    # Check if venv exists before building a notebook
    check_code = mgr.check_venv_exists_cell()
"""
from __future__ import annotations

import logging
import textwrap
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ──── Constants ────

DRIVE_MOUNT_PATH = "/content/drive"
COSYSIM_DRIVE_ROOT = "/content/drive/MyDrive/CosySim"
VENV_PATH = "/content/drive/MyDrive/CosySim/.venv"
OUTPUTS_PATH = "/content/drive/MyDrive/CosySim/outputs"
MODELS_PATH = "/content/drive/MyDrive/CosySim/models"
DATASETS_PATH = "/content/drive/MyDrive/CosySim/datasets"

COSYSIM_BASE_PACKAGES: List[str] = [
    "torch", "torchvision", "torchaudio",
    "transformers>=4.40.0", "accelerate>=0.27.0",
    "peft>=0.10.0", "bitsandbytes>=0.43.0",
    "datasets>=2.18.0", "scipy", "einops",
    "sentencepiece", "protobuf",
    "fastapi>=0.110.0", "uvicorn[standard]",
    "pyngrok>=7.0.0",
    "soundfile", "librosa",
    "pandas", "numpy", "matplotlib", "seaborn",
    "tqdm", "rich",
]

VLLM_PACKAGES: List[str] = ["vllm>=0.4.0"]
WHISPER_PACKAGES: List[str] = ["openai-whisper", "ffmpeg-python"]
COMFY_PACKAGES: List[str] = ["requests", "Pillow", "aiohttp"]


# ──── Dataclass ────

@dataclass
class NotebookCell:
    """Represents a single Jupyter notebook cell.

    Attributes:
        cell_type: Either "code" or "markdown".
        source: The cell source text.
        description: Human-readable summary used as a comment header.
    """

    cell_type: str
    source: str
    description: str = field(default="")


# ──── Manager ────

class ColabVenvManager:
    """Generates Colab notebook cell source code for Drive-backed .venv management."""

    def __init__(self, venv_path: str = VENV_PATH) -> None:
        """Initialise with the target venv path on Google Drive.

        Args:
            venv_path: Absolute path to the .venv directory on Drive.
        """
        self._venv_path = venv_path
        self._venv_python = f"{venv_path}/bin/python"
        self._venv_site_packages = (
            f"{venv_path}/lib/python3.10/site-packages"
        )

    # ──── Cell Generators ────

    def mount_drive_cell(self) -> NotebookCell:
        """Generate a cell that mounts Google Drive and creates project directories.

        Returns:
            NotebookCell that mounts Drive and ensures required dirs exist.
        """
        source = textwrap.dedent(f"""\
            from google.colab import drive
            drive.mount("{DRIVE_MOUNT_PATH}")
            import os
            for path in ["{OUTPUTS_PATH}", "{MODELS_PATH}", "{DATASETS_PATH}"]:
                os.makedirs(path, exist_ok=True)
            print("[SETUP] Drive mounted, directories ready")
        """).rstrip()
        return NotebookCell(
            cell_type="code",
            source=source,
            description="Mount Google Drive and create CosySim project directories",
        )

    def activate_venv_cell(
        self,
        packages: Optional[List[str]] = None,
        extra_packages: Optional[List[str]] = None,
    ) -> NotebookCell:
        """Generate a cell that activates the Drive venv or creates it if absent.

        When the venv already exists, its site-packages are prepended to
        sys.path and sys.executable is updated. When it is missing, a new
        venv is created and COSYSIM_BASE_PACKAGES plus any additional
        packages are installed.

        Args:
            packages: Replacement package list (overrides COSYSIM_BASE_PACKAGES).
            extra_packages: Additional packages appended to the install list.

        Returns:
            NotebookCell with venv activation or creation logic.
        """
        base = packages if packages is not None else COSYSIM_BASE_PACKAGES
        all_packages = list(base) + (extra_packages or [])
        packages_repr = repr(all_packages)

        source = textwrap.dedent(f"""\
            import os, sys, subprocess

            _VENV_PYTHON = "{self._venv_python}"
            _VENV_SITE = "{self._venv_site_packages}"
            _VENV_ROOT = "{self._venv_path}"

            if os.path.exists(_VENV_PYTHON):
                # Activate existing venv
                if _VENV_SITE not in sys.path:
                    sys.path.insert(0, _VENV_SITE)
                sys.executable = _VENV_PYTHON
                print("[VENV] Activated from Drive")
            else:
                # Create venv and install packages
                packages = {packages_repr}
                print(f"[VENV] Creating venv at {{_VENV_ROOT}} ...")
                subprocess.run([sys.executable, "-m", "venv", _VENV_ROOT], check=True)
                subprocess.run(
                    [_VENV_PYTHON, "-m", "pip", "install", "--upgrade", "pip"],
                    check=True, capture_output=True,
                )
                subprocess.run(
                    [_VENV_PYTHON, "-m", "pip", "install"] + packages,
                    check=True,
                )
                if _VENV_SITE not in sys.path:
                    sys.path.insert(0, _VENV_SITE)
                sys.executable = _VENV_PYTHON
                print(f"[VENV] Created and installed {{len(packages)}} packages")
        """).rstrip()
        return NotebookCell(
            cell_type="code",
            source=source,
            description="Activate or create the persistent Drive-backed virtual environment",
        )

    def check_venv_exists_cell(self) -> NotebookCell:
        """Generate a cell that prints whether the venv is ready.

        Returns:
            NotebookCell that reports venv presence as a quick sanity check.
        """
        source = textwrap.dedent(f"""\
            import os
            _VENV_PYTHON = "{self._venv_python}"
            ready = os.path.exists(_VENV_PYTHON)
            print(f"[VENV] Ready: {{ready}}  ({{_VENV_PYTHON}})")
        """).rstrip()
        return NotebookCell(
            cell_type="code",
            source=source,
            description="Check whether the Drive venv exists",
        )

    def install_packages_cell(self, packages: List[str]) -> NotebookCell:
        """Generate a cell that pip-installs packages into the active venv.

        Args:
            packages: List of pip-installable package specifiers.

        Returns:
            NotebookCell that runs pip install via the venv Python.
        """
        packages_repr = repr(packages)
        source = textwrap.dedent(f"""\
            import subprocess, sys
            _VENV_PYTHON = "{self._venv_python}"
            packages = {packages_repr}
            subprocess.run(
                [_VENV_PYTHON, "-m", "pip", "install"] + packages,
                check=True,
            )
            print(f"[VENV] Installed {{len(packages)}} package(s)")
        """).rstrip()
        return NotebookCell(
            cell_type="code",
            source=source,
            description=f"Install {len(packages)} package(s) into the Drive venv",
        )

    def setup_ngrok_cell(self, port: int = 8000) -> NotebookCell:
        """Generate a cell that opens a public ngrok tunnel on the given port.

        Args:
            port: Local port to expose via ngrok.

        Returns:
            NotebookCell that starts ngrok and prints the public URL.
        """
        source = textwrap.dedent(f"""\
            from pyngrok import ngrok
            public_url = ngrok.connect({port})
            print(f"[NGROK] Public URL: {{public_url}}")
        """).rstrip()
        return NotebookCell(
            cell_type="code",
            source=source,
            description=f"Start ngrok tunnel on port {port}",
        )

    def save_outputs_cell(self, output_paths: List[str]) -> NotebookCell:
        """Generate a cell that copies output files to Google Drive.

        Args:
            output_paths: List of local (Colab runtime) file or directory paths
                          to copy into OUTPUTS_PATH on Drive.

        Returns:
            NotebookCell that copies files and prints each destination path.
        """
        paths_repr = repr(output_paths)
        source = textwrap.dedent(f"""\
            import shutil, os
            _OUTPUTS = "{OUTPUTS_PATH}"
            os.makedirs(_OUTPUTS, exist_ok=True)
            for src in {paths_repr}:
                if os.path.isdir(src):
                    dest = os.path.join(_OUTPUTS, os.path.basename(src))
                    shutil.copytree(src, dest, dirs_exist_ok=True)
                else:
                    dest = shutil.copy2(src, _OUTPUTS)
                print(f"[OUTPUT] Saved: {{dest}}")
        """).rstrip()
        return NotebookCell(
            cell_type="code",
            source=source,
            description="Copy output files to Google Drive outputs directory",
        )

    def progress_header_cell(self, title: str, steps: List[str]) -> NotebookCell:
        """Generate a markdown cell with a task title and numbered step list.

        Args:
            title: Notebook or section title.
            steps: Ordered list of step descriptions.

        Returns:
            Markdown NotebookCell with title and step list.
        """
        steps_md = "\n".join(f"{i + 1}. {step}" for i, step in enumerate(steps))
        source = f"## {title}\n\n{steps_md}"
        return NotebookCell(
            cell_type="markdown",
            source=source,
            description=f"Progress header: {title}",
        )

    def get_setup_cells(
        self, extra_packages: Optional[List[str]] = None
    ) -> List[NotebookCell]:
        """Return the standard two-cell setup sequence for any CosySim notebook.

        These cells should always be the first two cells in a generated notebook.

        Args:
            extra_packages: Additional packages to install alongside base packages.

        Returns:
            [mount_drive_cell, activate_venv_cell]
        """
        return [
            self.mount_drive_cell(),
            self.activate_venv_cell(extra_packages=extra_packages),
        ]

    # ──── Notebook Serialisation ────

    def cells_to_ipynb(self, cells: List[NotebookCell]) -> Dict[str, Any]:
        """Convert a list of NotebookCells to a .ipynb format dict.

        Args:
            cells: Cells to include in the notebook.

        Returns:
            Dict conforming to the nbformat 4 specification.
        """
        nb_cells: List[Dict[str, Any]] = []
        for cell in cells:
            if cell.cell_type == "code":
                nb_cells.append({
                    "cell_type": "code",
                    "source": cell.source,
                    "metadata": {},
                    "outputs": [],
                    "execution_count": None,
                })
            elif cell.cell_type == "markdown":
                nb_cells.append({
                    "cell_type": "markdown",
                    "source": cell.source,
                    "metadata": {},
                })
            else:
                logger.warning(f"Skipping unknown cell_type '{cell.cell_type}'")

        return {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {
                "kernelspec": {
                    "display_name": "Python 3",
                    "language": "python",
                    "name": "python3",
                }
            },
            "cells": nb_cells,
        }


# ──── Factory ────

def get_venv_manager(venv_path: str = VENV_PATH) -> ColabVenvManager:
    """Return a ColabVenvManager for the given venv path.

    Args:
        venv_path: Path to the Drive-backed .venv directory.

    Returns:
        ColabVenvManager instance.
    """
    return ColabVenvManager(venv_path=venv_path)
