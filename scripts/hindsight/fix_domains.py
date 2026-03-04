"""Post-process extracted domain tool files.

Fixes all 15 files in engine/mcp/tools/ produced by extract.py:
  1. Remove stray second triple-quoted string (leftover from import comment)
  2. Remove 'from fastmcp import FastMCP'
  3. Remove the dead '# -- Server instance --' section
  4. Replace @mcp.tool() with @mcp_tool
  5. Add required imports (mcp_tool, lazy helpers)
  6. Remove duplicate 'from engine.paths import ROOT as _root' sys.path block
     (only keep it in the header ONCE)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).parent.parent.parent / "engine" / "mcp" / "tools"

IMPORT_HEADER = """\
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.paths import ROOT as _root
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from engine.mcp.decorators import mcp_tool
from engine.mcp._lazy import _get_db, _get_rag, _get_config

logger = logging.getLogger(__name__)

"""


def clean_domain_file(path: Path) -> None:
    src = path.read_text(encoding="utf-8")

    # ── 1. Extract the first (real) module docstring ──────────────────────
    # The file starts with:
    #   """MCP tool domain: X.\n...some description...\n"""
    #   """    from engine.mcp.cosysim_server import mcp\n"""   <-- STRAY
    # We keep only the first and drop the second.
    doc_pattern = re.compile(r'^(""".*?""")', re.DOTALL)
    m = doc_pattern.match(src)
    module_doc = m.group(1).rstrip() + "\n" if m else ""

    # Strip everything up to and including any second stray triple-quoted block
    # that appears right after the first docstring
    after_doc = src[m.end():] if m else src
    stray_pattern = re.compile(r'^\s*""".*?"""\s*\n?', re.DOTALL)
    after_doc = stray_pattern.sub("", after_doc, count=1)

    # ── 2. Build fresh body: drop old imports + server-instance block ──────
    # Everything from the first @mcp.tool() onwards is the actual tool defs
    # Find that point.
    mcp_tool_pos = after_doc.find("@mcp.tool()")
    if mcp_tool_pos == -1:
        print(f"  SKIP {path.name} — no @mcp.tool() found")
        return

    tool_section = after_doc[mcp_tool_pos:]

    # ── 3. Replace @mcp.tool() with @mcp_tool ────────────────────────────
    tool_section = tool_section.replace("@mcp.tool()", "@mcp_tool")

    # ── 4. Find the section-header comment that precedes the first tool ───
    # e.g. "# ──── CHARACTER TOOLS ───────────────" — keep it for readability
    section_comment_pattern = re.compile(
        r"(#\s*[─=]{4,}.*?[─=]{4,}\s*\n)", re.DOTALL
    )
    # We want to keep any section comment that appears just before the tools
    pre_tools = after_doc[:mcp_tool_pos]
    section_comments = section_comment_pattern.findall(pre_tools)
    section_header = section_comments[-1] if section_comments else ""

    # ── 5. Assemble the cleaned file ─────────────────────────────────────
    domain_name = path.stem  # e.g. "character"
    module_doc_clean = (
        f'"""MCP tool domain: {domain_name}.\n\n'
        f"Thin wrappers that delegate to *_tools.py implementations.\n"
        f'Apply @mcp_tool for unified error handling and serialisation.\n"""\n'
    )

    result = module_doc_clean + IMPORT_HEADER + section_header + tool_section

    path.write_text(result, encoding="utf-8")
    tool_count = tool_section.count("@mcp_tool")
    print(f"  FIXED {path.name} ({tool_count} tools)")


def main() -> None:
    domain_files = [
        p for p in TOOLS_DIR.glob("*.py")
        if not p.name.endswith("_tools.py")
        and p.name not in ("__init__.py", "utility_tools.py")
    ]
    domain_files.sort()
    print(f"Processing {len(domain_files)} domain files in {TOOLS_DIR}\n")
    for f in domain_files:
        clean_domain_file(f)
    print("\nDone.")


if __name__ == "__main__":
    main()
