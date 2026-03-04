"""split_interceptors.py — CosySim Project Hindsight: interceptor file splitter.

Reads engine/agents/interceptors.py (26 classes, 2,468 lines) and splits it into:
  engine/agents/interceptors/
    __init__.py          — @register_interceptor registry + exports
    _cache.py            — _InterceptorCache (private, imported by others)
    router_message.py    — RouterMessageInjector
    auto_result.py       — AutoResultInjector
    ... one file per public class ...

After splitting, comms_framework.py can replace its 26-item hardcoded
.add() list with a single call to get_all_interceptors().

Usage::

    python scripts/hindsight/split_interceptors.py         # dry run
    python scripts/hindsight/split_interceptors.py --write # write files
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "engine" / "agents" / "interceptors.py"
OUT_DIR = ROOT / "engine" / "agents" / "interceptors"


# ──── Class → filename mapping ────────────────────────────────────────────

CLASS_FILE_MAP: dict[str, str] = {
    "_InterceptorCache": "_cache",
    "RouterMessageInjector": "router_message",
    "AutoResultInjector": "auto_result",
    "SkillAwarenessInterceptor": "skill_awareness",
    "GameInterceptor": "game",
    "PersonalityGuardInterceptor": "personality_guard",
    "ConversationVarietyInterceptor": "conversation_variety",
    "PolicyEnforcerInterceptor": "policy_enforcer",
    "MemoryEnhancerInterceptor": "memory_enhancer",
    "ResponseShaperInterceptor": "response_shaper",
    "ActivityLoggerInterceptor": "activity_logger",
    "BedroomSceneInterceptor": "bedroom_scene",
    "PhoneSceneInterceptor": "phone_scene",
    "LoungeSceneInterceptor": "lounge_scene",
    "GallerySceneInterceptor": "gallery_scene",
    "UniversalSceneInterceptor": "universal_scene",
    "AmbientEventInterceptor": "ambient_event",
    "CharacterRegistryInterceptor": "character_registry",
    "DialogDirectiveInterceptor": "dialog_directive",
    "TTSStyleInterceptor": "tts_style",
    "MoodSyncInterceptor": "mood_sync",
    "NaturalMoodDriftInterceptor": "natural_mood_drift",
    "ConversationRecapInterceptor": "conversation_recap",
    "RelationshipEventInterceptor": "relationship_event",
    "RelationshipContextInterceptor": "relationship_context",
    "NexusPromptInterceptor": "nexus_prompt",
}

# Classes that should be registered in the auto-registry (all public ones)
REGISTRY_CLASSES = [c for c in CLASS_FILE_MAP if not c.startswith("_")]


def extract_imports(source: str) -> str:
    """Extract all import statements from the top of the file."""
    lines = source.splitlines()
    import_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if re.match(r"^(import |from |#|$)", stripped):
            import_lines.append(line)
        elif stripped.startswith('"""') or stripped.startswith("'''"):
            import_lines.append(line)
        else:
            # First non-import content — stop
            if import_lines:
                break
    while import_lines and not import_lines[-1].strip():
        import_lines.pop()
    return "\n".join(import_lines)


def extract_class_source(source: str, class_name: str) -> str | None:
    """Extract the full source text of a class definition."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    source_lines = source.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            start = node.lineno - 1
            end = node.end_lineno
            return "\n".join(source_lines[start:end])
    return None


def build_class_file(class_name: str, class_source: str, imports: str) -> str:
    """Build the content of a single interceptor file."""
    module_name = CLASS_FILE_MAP[class_name]
    return f'''\
"""Interceptor: {class_name}.

Split from engine/agents/interceptors.py by scripts/hindsight/split_interceptors.py.
"""
{imports}


{class_source}
'''


def build_init_file(classes: list[str]) -> str:
    """Build __init__.py with auto-registry."""
    imports: list[str] = []
    registry_entries: list[str] = []

    for cls in classes:
        if cls.startswith("_"):
            continue
        module = CLASS_FILE_MAP[cls]
        imports.append(f"from engine.agents.interceptors.{module} import {cls}")
        registry_entries.append(f"    {cls},")

    imports_str = "\n".join(imports)
    registry_str = "\n".join(registry_entries)

    return f'''\
"""engine/agents/interceptors/__init__.py — Auto-registry for all interceptors.

Import this module and call get_all_interceptors() to get a list of all
registered interceptor classes. comms_framework.py uses this instead of
maintaining a hardcoded list.

Usage::

    from engine.agents.interceptors import get_all_interceptors

    pipeline = InterceptorPipeline()
    for cls in get_all_interceptors():
        pipeline.add(cls())
"""
from __future__ import annotations

from typing import Type

from engine.agents.interceptors._cache import _InterceptorCache  # noqa: F401 — used internally

{imports_str}

_REGISTRY: list[Type] = [
{registry_str}
]


def get_all_interceptors() -> list[Type]:
    """Return the ordered list of all registered interceptor classes."""
    return list(_REGISTRY)


def register_interceptor(cls: Type) -> Type:
    """Class decorator that registers an interceptor in the global registry.

    Usage::

        @register_interceptor
        class MyCustomInterceptor(InterceptorBase):
            ...
    """
    if cls not in _REGISTRY:
        _REGISTRY.append(cls)
    return cls


__all__ = [
    "get_all_interceptors",
    "register_interceptor",
    "_InterceptorCache",
{chr(10).join(f"    {chr(34)}{c}{chr(34)}," for c in classes if not c.startswith("_"))}
]
'''


def run(write: bool = False) -> None:
    source = SRC.read_text(encoding="utf-8-sig")
    imports = extract_imports(source)

    print(f"\nSplitting: {SRC.relative_to(ROOT)}")
    print(f"Output dir: {OUT_DIR.relative_to(ROOT)}")
    print()

    class_sources: dict[str, str | None] = {}
    for class_name in CLASS_FILE_MAP:
        src = extract_class_source(source, class_name)
        class_sources[class_name] = src
        status = "OK" if src else "NOT FOUND"
        lines = len(src.splitlines()) if src else 0
        print(f"  [{status:8}] {class_name}  ({lines} lines)")

    # Build __init__
    init_content = build_init_file(list(CLASS_FILE_MAP.keys()))
    init_path = OUT_DIR / "__init__.py"

    print(f"\n  -> {init_path.relative_to(ROOT)}  (auto-registry)")

    if write:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        init_path.write_text(init_content, encoding="utf-8")

    # Write each class file
    written = 0
    for class_name, cls_src in class_sources.items():
        if not cls_src:
            continue
        module = CLASS_FILE_MAP[class_name]
        content = build_class_file(class_name, cls_src, imports)
        out_path = OUT_DIR / f"{module}.py"

        if write:
            out_path.write_text(content, encoding="utf-8")
            written += 1
        else:
            lines = len(content.splitlines())
            print(f"  [dry] {out_path.name}  ({lines} lines)")

    if write:
        print(f"\n  Written {written + 1} files to {OUT_DIR.relative_to(ROOT)}/")
        print(f"\n  Next: update comms_framework.py to use get_all_interceptors()")
        print(f"  Then: delete engine/agents/interceptors.py (or move to _archive)")
    else:
        print(f"\n  Run with --write to create files.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Split interceptors.py into per-class files")
    parser.add_argument("--write", action="store_true", help="Actually write output files")
    args = parser.parse_args()
    run(write=args.write)


if __name__ == "__main__":
    main()
