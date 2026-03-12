"""Parametrized tests that validate all CosySim skill files can be imported.

Auto-discovers every *_skills.py in engine/skills/builtin/ and verifies
each module is importable and contains at least one callable.
"""
from __future__ import annotations

import importlib
import inspect
import logging
from pathlib import Path
from typing import List

import pytest

logger = logging.getLogger(__name__)

# ──── Discovery ────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUILTIN_DIR = PROJECT_ROOT / "engine" / "skills" / "builtin"


def _discover_skill_modules() -> List[str]:
    """Walk engine/skills/builtin/ and return dotted module paths.

    Returns:
        Sorted list of module paths like 'engine.skills.builtin.coding_skills'.
    """
    modules: List[str] = []
    for path in sorted(BUILTIN_DIR.glob("*_skills.py")):
        rel = path.relative_to(PROJECT_ROOT)
        dotted = str(rel.with_suffix("")).replace("\\", ".").replace("/", ".")
        modules.append(dotted)
    return modules


SKILL_MODULES = _discover_skill_modules()
SKILL_IDS = [m.rsplit(".", 1)[-1] for m in SKILL_MODULES]

# ──── Parametrized Tests ────


@pytest.mark.parametrize("skill_module_path", SKILL_MODULES, ids=SKILL_IDS)
def test_skill_file_imports(skill_module_path: str) -> None:
    """Verify each skill module can be imported without error."""
    try:
        mod = importlib.import_module(skill_module_path)
    except ImportError as exc:
        pytest.xfail(f"Optional dependency missing: {exc}")
    except Exception as exc:
        pytest.fail(f"Import failed for {skill_module_path}: {exc}")
    assert mod is not None, f"Module {skill_module_path} imported as None"
    logger.debug("Successfully imported %s", skill_module_path)


@pytest.mark.parametrize("skill_module_path", SKILL_MODULES, ids=SKILL_IDS)
def test_skill_file_has_decorated_functions(skill_module_path: str) -> None:
    """Verify the module exposes at least one callable (sanity check)."""
    try:
        mod = importlib.import_module(skill_module_path)
    except ImportError as exc:
        pytest.xfail(f"Optional dependency missing: {exc}")
        return

    public_callables = [
        name for name, obj in inspect.getmembers(mod, inspect.isfunction)
        if not name.startswith("_") and obj.__module__ == mod.__name__
    ]
    assert len(public_callables) > 0, (
        f"{skill_module_path} has no public functions — "
        f"expected at least one @skill-decorated function"
    )
    logger.debug(
        "%s exposes %d public function(s): %s",
        skill_module_path,
        len(public_callables),
        ", ".join(public_callables[:5]),
    )


# ──── Aggregate Checks ────


def test_minimum_skill_count() -> None:
    """Assert the builtin directory contains at least 30 skill files."""
    count = len(SKILL_MODULES)
    logger.info("Discovered %d builtin skill modules", count)
    assert count >= 30, (
        f"Expected at least 30 builtin skill files, found {count}. "
        f"Skill files may have been deleted or renamed."
    )


def test_no_duplicate_module_names() -> None:
    """Guard against two skill files resolving to the same module path."""
    assert len(SKILL_MODULES) == len(set(SKILL_MODULES)), (
        "Duplicate module paths detected in skill discovery"
    )
