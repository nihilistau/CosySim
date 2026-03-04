"""scan.py — CosySim Project Hindsight: codebase audit tool.

Scans specified source files and the engine/ directory to measure:
- Lines of code
- Number of ``except Exception`` catch-alls
- Number of raw ``json.dumps()`` calls
- Number of function definitions (def + async def)

Output: JSON report + console summary table.

Usage::

    python scripts/hindsight/scan.py                    # full audit
    python scripts/hindsight/scan.py --file engine/mcp/cosysim_server.py
    python scripts/hindsight/scan.py --json > audit.json
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Primary refactoring targets always included
PRIMARY_TARGETS = [
    "engine/mcp/cosysim_server.py",
    "engine/mcp/devtools_server.py",
    "engine/agents/interceptors.py",
    "engine/scenes/base_scene.py",
]

# Additional engine files scanned for aggregate counts
ENGINE_GLOB = "engine/**/*.py"


@dataclass
class FileReport:
    path: str
    lines: int = 0
    except_exception: int = 0
    json_dumps: int = 0
    def_count: int = 0
    async_def_count: int = 0
    parse_error: str = ""

    @property
    def total_defs(self) -> int:
        return self.def_count + self.async_def_count


def _count_except_exception(source: str) -> int:
    """Count bare ``except Exception`` or ``except Exception as`` handlers."""
    return len(re.findall(r"except\s+Exception\b", source))


def _count_json_dumps(source: str) -> int:
    """Count calls to ``json.dumps(``."""
    return len(re.findall(r"\bjson\.dumps\s*\(", source))


def _count_defs(tree: ast.AST) -> tuple[int, int]:
    """Return (sync_def_count, async_def_count) from an AST."""
    sync = sum(1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    async_ = sum(1 for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef))
    return sync, async_


def scan_file(path: Path) -> FileReport:
    rel = str(path.relative_to(ROOT))
    report = FileReport(path=rel)
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        report.parse_error = str(e)
        return report

    lines = source.splitlines()
    report.lines = len(lines)
    report.except_exception = _count_except_exception(source)
    report.json_dumps = _count_json_dumps(source)

    try:
        tree = ast.parse(source, filename=str(path))
        report.def_count, report.async_def_count = _count_defs(tree)
    except SyntaxError as e:
        report.parse_error = f"SyntaxError: {e}"

    return report


def run_audit(extra_files: list[str] | None = None) -> dict:
    targets: list[Path] = []

    # Always scan primary targets
    for rel in PRIMARY_TARGETS:
        p = ROOT / rel
        if p.exists():
            targets.append(p)

    # Add any extra files specified by caller
    if extra_files:
        for f in extra_files:
            p = Path(f) if Path(f).is_absolute() else ROOT / f
            if p.exists() and p not in targets:
                targets.append(p)

    # Aggregate over all engine files
    engine_files = sorted((ROOT / "engine").rglob("*.py"))

    primary_reports = [scan_file(p) for p in targets]

    totals = FileReport(path="[engine/**/*.py aggregate]")
    for p in engine_files:
        r = scan_file(p)
        totals.lines += r.lines
        totals.except_exception += r.except_exception
        totals.json_dumps += r.json_dumps
        totals.def_count += r.def_count
        totals.async_def_count += r.async_def_count

    def _to_dict(r: FileReport) -> dict:
        d = asdict(r)
        d["total_defs"] = r.total_defs
        return d

    return {
        "root": str(ROOT),
        "primary_targets": [_to_dict(r) for r in primary_reports],
        "engine_aggregate": _to_dict(totals),
        "file_count": len(engine_files),
    }


def print_table(report: dict) -> None:
    print("\n" + "═" * 90)
    print("  CosySim Hindsight Audit")
    print("═" * 90)
    header = f"  {'File':<50} {'Lines':>7} {'except':>8} {'json.dumps':>11} {'defs':>6}"
    print(header)
    print("─" * 90)

    for r in report["primary_targets"]:
        name = r["path"].split("/")[-1]
        err = f"  *** {r['parse_error']}" if r["parse_error"] else ""
        print(
            f"  {name:<50} {r['lines']:>7,} {r['except_exception']:>8,} "
            f"{r['json_dumps']:>11,} {r['total_defs']:>6,}{err}"
        )

    print("─" * 90)
    ag = report["engine_aggregate"]
    print(
        f"  {'[engine total]':<50} {ag['lines']:>7,} {ag['except_exception']:>8,} "
        f"{ag['json_dumps']:>11,} {ag['total_defs']:>6,}"
    )
    print("═" * 90)
    print(f"  Engine files scanned: {report['file_count']}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="CosySim codebase audit tool")
    parser.add_argument("--file", action="append", dest="files", help="Extra files to scan")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of table")
    args = parser.parse_args()

    report = run_audit(extra_files=args.files)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_table(report)


if __name__ == "__main__":
    main()
