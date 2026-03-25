#!/usr/bin/env python3
"""
Auto-Update Documentation Counts — reads live registries and patches docs
==========================================================================

Reads actual counts from CosySim registries (interceptors, skills, packs,
scenes, ports, story packs, tests) and updates hardcoded numbers across
all documentation files. Run after adding features to keep docs in sync.

Usage:
    python scripts/update_docs.py             # Dry-run (show what would change)
    python scripts/update_docs.py --apply     # Apply changes
    python scripts/update_docs.py --verbose   # Show all scanned values

Version: v1.51.1 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.51.1 [2026-03-25] — Initial: interceptors, skills, packs, scenes, ports,
                            story packs, test count auto-detection + doc patching
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent

# ──── Registry Readers ───────────────────────────────────────────────────
# Each function returns a dict of metric_name → value

def read_interceptors() -> Dict[str, Any]:
    """Count registered interceptors."""
    try:
        sys.path.insert(0, str(ROOT))
        from engine.agents.interceptors import get_all_interceptors
        count = len(get_all_interceptors())
        return {"interceptor_count": count}
    except Exception as exc:
        print(f"  [WARN] Interceptors: {exc}")
        return {}


def read_skills() -> Dict[str, Any]:
    """Count skills and packs from SKILL_REGISTRY."""
    try:
        from engine.skills.registry import SKILL_REGISTRY
        # Force-load all builtin skill files
        import importlib
        import pkgutil
        builtin_dir = ROOT / "engine" / "skills" / "builtin"
        for _, name, _ in pkgutil.iter_modules([str(builtin_dir)]):
            try:
                importlib.import_module(f"engine.skills.builtin.{name}")
            except Exception:
                pass

        packs = SKILL_REGISTRY.all_packs()
        total = sum(len(SKILL_REGISTRY.get_pack_metas(p)) for p in packs)
        return {
            "skill_count": total,
            "pack_count": len(packs),
        }
    except Exception as exc:
        print(f"  [WARN] Skills: {exc}")
        return {}


def read_scenes() -> Dict[str, Any]:
    """Count scenes and services from control_plane_registry."""
    try:
        from engine.control_plane_registry import SCENE_DEFS, SERVICE_DEFS
        game = sum(1 for v in {**SCENE_DEFS, **SERVICE_DEFS}.values()
                   if (v.get("pillar") or "game") == "game")
        service = sum(1 for v in {**SCENE_DEFS, **SERVICE_DEFS}.values()
                      if (v.get("pillar") or "") == "service")
        creation = sum(1 for v in {**SCENE_DEFS, **SERVICE_DEFS}.values()
                       if (v.get("pillar") or "") == "creation")
        total = len(SCENE_DEFS) + len(SERVICE_DEFS)
        return {
            "target_count": total,
            "game_count": game,
            "service_count": service,
            "creation_count": creation,
        }
    except Exception as exc:
        print(f"  [WARN] Scenes: {exc}")
        return {}


def read_story_packs() -> Dict[str, Any]:
    """Count narrative story packs."""
    try:
        from engine.mcp.narrative_packs import PACK_CATALOG
        return {"story_pack_count": len(PACK_CATALOG)}
    except Exception as exc:
        print(f"  [WARN] Story packs: {exc}")
        return {}


def read_test_count() -> Dict[str, Any]:
    """Count test files."""
    try:
        test_dir = ROOT / "tests"
        count = len(list(test_dir.glob("test_*.py")))
        return {"test_file_count": count}
    except Exception as exc:
        print(f"  [WARN] Tests: {exc}")
        return {}


# ──── Replacement Rules ──────────────────────────────────────────────────
# Each rule: (regex_pattern, replacement_template, metric_key)
# The template uses {key} placeholders filled from metrics.

REPLACEMENT_RULES: List[Tuple[str, str, List[str]]] = [
    # Interceptor counts
    (r"\*\*(\d+)\*\* agent pipeline hooks", "**{interceptor_count}** agent pipeline hooks", ["interceptor_count"]),
    (r"(\d+) pipeline hooks in the agent governance layer", "{interceptor_count} pipeline hooks in the agent governance layer", ["interceptor_count"]),
    (r"(\d+)-interceptor pipeline", "{interceptor_count}-interceptor pipeline", ["interceptor_count"]),
    (r"(\d+) pre/post-call hooks", "{interceptor_count} pre/post-call hooks", ["interceptor_count"]),
    (r"(\d+) interceptors \· @mcp_tool", "{interceptor_count} interceptors \u00b7 @mcp_tool", ["interceptor_count"]),
    (r"governed by a (\d+)-interceptor pipeline", "governed by a {interceptor_count}-interceptor pipeline", ["interceptor_count"]),
    # Skill counts (approximate with ~)
    (r"\*\*~[\d,]+\*\* across \*\*(\d+) packs\*\*", "**~{skill_count_approx}** across **{pack_count} packs**", ["skill_count", "pack_count"]),
    (r"~[\d,]+ across (\d+) packs via @skill", "~{skill_count_approx} across {pack_count} packs via @skill", ["skill_count", "pack_count"]),
    (r"~[\d,]+ skills across (\d+) packs", "~{skill_count_approx} skills across {pack_count} packs", ["skill_count", "pack_count"]),
    (r"@skill decorator \· (\d+) packs \· ~(\d+)", "@skill decorator \u00b7 {pack_count} packs \u00b7 ~{skill_count_approx}", ["pack_count", "skill_count"]),
    # Target counts
    (r"\*\*(\d+)\*\* \((\d+) game \+ (\d+) service \+ (\d+) creation\)",
     "**{target_count}** ({game_count} game + {service_count} service + {creation_count} creation)",
     ["target_count", "game_count", "service_count", "creation_count"]),
    (r"(\d+) \((\d+) game \+ (\d+) service \+ (\d+) creation\)",
     "{target_count} ({game_count} game + {service_count} service + {creation_count} creation)",
     ["target_count", "game_count", "service_count", "creation_count"]),
    (r"(\d+) launch targets \((\d+) game",
     "{target_count} launch targets ({game_count} game",
     ["target_count", "game_count"]),
    # Test file counts
    (r"\*\*(\d+)\*\* test files", "**{test_file_count}** test files", ["test_file_count"]),
    (r"(\d+) test files \(smart", "{test_file_count} test files (smart", ["test_file_count"]),
]

# Files to patch
DOC_FILES = [
    "README.md",
    "CLAUDE.md",
    "context.md",
    "docs/INDEX.md",
    "docs/ARCHITECTURE.md",
    "docs/INTERCEPTORS.md",
    "docs/SKILLS.md",
    "docs/SCENES.md",
]


# ──── Patching Engine ────────────────────────────────────────────────────

def collect_metrics() -> Dict[str, Any]:
    """Collect all metrics from live registries."""
    metrics: Dict[str, Any] = {}
    print("Reading registries...")

    for reader in [read_interceptors, read_skills, read_scenes, read_story_packs, read_test_count]:
        result = reader()
        metrics.update(result)

    # Count scene-level skill files (not imported at module level)
    scene_skill_count = 0
    try:
        scene_dir = ROOT / "content" / "scenes"
        for skill_file in scene_dir.rglob("*_skills.py"):
            # Rough count: each @skill decorator = 1 skill
            text = skill_file.read_text(encoding="utf-8", errors="replace")
            scene_skill_count += text.count("@skill(") + text.count("@skill\n")
    except Exception:
        pass
    if scene_skill_count:
        metrics["scene_skill_count"] = scene_skill_count
        metrics["skill_count"] = metrics.get("skill_count", 0) + scene_skill_count
        metrics["pack_count"] = metrics.get("pack_count", 0) + len(list(
            (ROOT / "content" / "scenes").rglob("*_skills.py")
        ))

    # Compute derived values
    if "skill_count" in metrics:
        # Round to nearest 10 for approximate display
        raw = metrics["skill_count"]
        approx = (raw // 10) * 10
        metrics["skill_count_approx"] = f"{approx:,}"

    return metrics


def patch_file(filepath: Path, metrics: Dict[str, Any], apply: bool = False) -> List[str]:
    """Patch a single file with updated metrics. Returns list of changes."""
    if not filepath.exists():
        return []

    content = filepath.read_text(encoding="utf-8")
    original = content
    changes = []

    for pattern, template, required_keys in REPLACEMENT_RULES:
        # Check all required metrics are available
        if not all(k in metrics for k in required_keys):
            continue

        # Build replacement string
        replacement = template
        for key in required_keys:
            val = metrics.get(key, "")
            replacement = replacement.replace(f"{{{key}}}", str(val))
            # Handle skill_count_approx specially
            if key == "skill_count":
                replacement = replacement.replace("{skill_count_approx}", metrics.get("skill_count_approx", str(val)))

        # Apply regex substitution
        new_content = re.sub(pattern, replacement, content)
        if new_content != content:
            # Find what changed
            for i, (old_line, new_line) in enumerate(
                zip(content.splitlines(), new_content.splitlines())
            ):
                if old_line != new_line:
                    changes.append(f"  L{i+1}: {old_line.strip()[:80]}")
                    changes.append(f"     -> {new_line.strip()[:80]}")
            content = new_content

    if content != original and apply:
        filepath.write_text(content, encoding="utf-8")

    return changes


def main():
    parser = argparse.ArgumentParser(description="Auto-update doc counts from live registries")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: dry-run)")
    parser.add_argument("--verbose", action="store_true", help="Show all metric values")
    args = parser.parse_args()

    metrics = collect_metrics()

    if args.verbose or not args.apply:
        print(f"\nMetrics collected:")
        for k, v in sorted(metrics.items()):
            print(f"  {k}: {v}")

    print(f"\n{'Applying' if args.apply else 'Dry-run'} — scanning {len(DOC_FILES)} files...\n")

    total_changes = 0
    for rel_path in DOC_FILES:
        filepath = ROOT / rel_path
        changes = patch_file(filepath, metrics, apply=args.apply)
        if changes:
            print(f"{'UPDATED' if args.apply else 'WOULD UPDATE'}: {rel_path}")
            for c in changes:
                print(c)
            print()
            total_changes += len(changes) // 2  # Each change is 2 lines (old + new)

    if total_changes == 0:
        print("All docs are up to date!")
    else:
        action = "Applied" if args.apply else "Would apply"
        print(f"{action} {total_changes} change(s) across {len(DOC_FILES)} files.")
        if not args.apply:
            print("Run with --apply to write changes.")


if __name__ == "__main__":
    main()
