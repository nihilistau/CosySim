"""patch.py — CosySim Project Hindsight: thin-wrapper patcher.

After extract.py has created domain files, this script rewrites the source
server file so each @mcp.tool() function body becomes a one-line import
delegation to its domain file.

Produces a patched server file that is ~10% the original size, with zero
inline business logic.

The patch strategy is deliberately conservative:
  - Only touches @mcp.tool() decorated functions that have a matching
    domain file present in engine/mcp/tools/
  - Helper functions (_get_db, etc.) are left untouched
  - Imports and mcp instantiation are preserved unchanged
  - Original file is backed up to {file}.bak before patching

Usage::

    # 1. First run extract.py --write to create domain files
    # 2. Dry-run to preview changes
    python scripts/hindsight/patch.py

    # 3. Apply the patch
    python scripts/hindsight/patch.py --write

    # 4. Verify tests still pass, then delete .bak file
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "engine" / "mcp" / "tools"

# Import the domain classifier from extract.py
sys.path.insert(0, str(Path(__file__).parent))
from extract import classify, extract_tools  # noqa: E402


_THIN_BODY = '''\
    from engine.mcp.tools.{domain} import {fn_name}
    return {fn_name}({args})'''

_THIN_BODY_NO_ARGS = '''\
    from engine.mcp.tools.{domain} import {fn_name}
    return {fn_name}()'''


def _format_args(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Render the call arguments for the thin wrapper."""
    parts: list[str] = []
    args = node.args

    for arg in args.args:
        if arg.arg == "self":
            continue
        parts.append(arg.arg)
    for arg in args.kwonlyargs:
        parts.append(f"{arg.arg}={arg.arg}")
    if args.vararg:
        parts.append(f"*{args.vararg.arg}")
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}")

    return ", ".join(parts)


def build_thin_wrapper(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    domain: str,
    original_lines: list[str],
) -> list[str]:
    """Return the replacement lines for a single tool function.

    Preserves:
    - The decorator line(s)
    - The ``def`` signature line(s)
    - The original docstring (first string literal in body)
    """
    # Find the decorator start line (0-indexed in original_lines)
    deco_start_abs = min(d.lineno for d in node.decorator_list)
    fn_end_abs = node.end_lineno

    # Lines for just this function (0-indexed into file lines)
    fn_raw = original_lines[deco_start_abs - 1 : fn_end_abs]

    # Extract decorators + def signature: everything up to first body line
    header: list[str] = []
    body_started = False
    docstring: str | None = None
    in_signature = False

    for i, line in enumerate(fn_raw):
        stripped = line.strip()
        if stripped.startswith("@"):
            header.append(line)
        elif stripped.startswith("def ") or stripped.startswith("async def "):
            header.append(line)
            in_signature = not stripped.endswith(":")
        elif in_signature:
            header.append(line)
            if stripped.endswith(":"):
                in_signature = False
        else:
            # We've hit the body — grab the docstring if present
            if not body_started:
                body_started = True
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    # Collect multi-line docstring
                    doc_lines = [line]
                    if not (stripped.endswith('"""') and len(stripped) > 3) and not (stripped.endswith("'''") and len(stripped) > 3):
                        for j in range(i + 1, len(fn_raw)):
                            doc_lines.append(fn_raw[j])
                            if fn_raw[j].strip().endswith('"""') or fn_raw[j].strip().endswith("'''"):
                                break
                    docstring = "\n".join(doc_lines)
            break

    args_str = _format_args(node)
    indent = "    "

    replacement: list[str] = []
    replacement.extend(header)

    if docstring:
        replacement.append(docstring)

    if args_str:
        replacement.append(f"{indent}from engine.mcp.tools.{domain} import {node.name}")
        replacement.append(f"{indent}return {node.name}({args_str})")
    else:
        replacement.append(f"{indent}from engine.mcp.tools.{domain} import {node.name}")
        replacement.append(f"{indent}return {node.name}()")

    replacement.append("")

    return replacement


def patch_file(
    source_file: Path,
    write: bool = False,
) -> None:
    source = source_file.read_text(encoding="utf-8-sig")
    original_lines = source.splitlines()
    tools = extract_tools(source)

    if not tools:
        print(f"No tools found in {source_file}")
        return

    print(f"\nPatching: {source_file.relative_to(ROOT)}")
    print(f"Tools to thin: {len(tools)}")

    # Build a map: line_number → replacement lines
    # Key = (start_line_abs, end_line_abs) 1-indexed
    replacements: list[tuple[int, int, list[str]]] = []

    for tool in tools:
        domain = tool.domain
        domain_file = TOOLS_DIR / f"{domain}.py"

        if not domain_file.exists():
            print(f"  [skip] {tool.name} — domain file {domain}.py not found (run extract.py --write first)")
            continue

        # Re-parse to get full AST node for arg info
        tree = ast.parse(source)
        node = None
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == tool.name:
                if n.lineno == tool.start_line or any(d.lineno == tool.start_line for d in n.decorator_list):
                    node = n
                    break

        if node is None:
            print(f"  [skip] {tool.name} — could not re-locate in AST")
            continue

        deco_start = min(d.lineno for d in node.decorator_list)
        fn_end = node.end_lineno
        wrapper = build_thin_wrapper(node, domain, original_lines)
        replacements.append((deco_start, fn_end, wrapper))
        print(f"  -> {tool.name}  ({fn_end - deco_start + 1} lines -> {len(wrapper)} lines)")

    if not replacements:
        print("Nothing to patch.")
        return

    # Apply replacements from bottom to top (to preserve line numbers)
    replacements.sort(key=lambda r: r[0], reverse=True)
    patched = list(original_lines)

    for start, end, wrapper in replacements:
        # Convert to 0-indexed
        patched[start - 1 : end] = wrapper

    result = "\n".join(patched)
    original_size = len(original_lines)
    patched_size = len(patched)
    reduction = (1 - patched_size / original_size) * 100

    print(f"\n  Original: {original_size:,} lines")
    print(f"  Patched:  {patched_size:,} lines")
    print(f"  Reduction: {reduction:.1f}%")

    if write:
        # Backup
        bak = source_file.with_suffix(".py.bak")
        source_file.rename(bak)
        source_file.write_text(result, encoding="utf-8")
        print(f"\n  Backup: {bak.name}")
        print(f"  Written: {source_file.relative_to(ROOT)}")
    else:
        print("\n  Run with --write to apply patch.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Patch MCP server file with thin wrappers")
    parser.add_argument(
        "--file",
        default="engine/mcp/cosysim_server.py",
        help="Server file to patch (relative to project root)",
    )
    parser.add_argument("--write", action="store_true", help="Actually write patched file")
    args = parser.parse_args()

    src = ROOT / args.file
    if not src.exists():
        print(f"File not found: {src}", file=sys.stderr)
        sys.exit(1)

    patch_file(src, write=args.write)


if __name__ == "__main__":
    main()
