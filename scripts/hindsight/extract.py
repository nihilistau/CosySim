"""extract.py — CosySim Project Hindsight: AST-based tool function extractor.

Reads cosysim_server.py (or any MCP server file), extracts all @mcp.tool()
decorated functions, groups them by domain, and writes one Python file per
domain to engine/mcp/tools/.

Usage::

    python scripts/hindsight/extract.py                        # dry run (print plan)
    python scripts/hindsight/extract.py --write                # write domain files
    python scripts/hindsight/extract.py --file engine/mcp/devtools_server.py --write
    python scripts/hindsight/extract.py --write --domain lounge  # single domain
"""
from __future__ import annotations

import argparse
import ast
import sys
import textwrap
from pathlib import Path
from typing import Dict, List, NamedTuple

ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "engine" / "mcp" / "tools"

# ──── Domain classification ───────────────────────────────────────────────
# Maps function name prefix/keyword patterns → domain name.
# Order matters: first match wins.

DOMAIN_RULES: list[tuple[list[str], str]] = [
    # lounge first — specific prefix
    (["lounge_", "serve_lounge", "start_lounge", "get_lounge", "reveal_lounge", "trigger_lounge"], "lounge"),
    # wardrobe
    (["wardrobe_"], "wardrobe"),
    # character (register/query/assign etc.)
    (["character_"], "character"),
    # game logic
    (["game_", "start_game", "end_game", "launch_game", "get_active_game", "get_game_state", "set_game_state", "roll_dice", "get_random_topic", "random_pick"], "game"),
    # interaction / timed actions
    (["perform_interaction", "list_available_interactions", "get_interaction_details", "start_timed_action", "poll_timed_action", "abort_timed_action", "list_active_timed_actions"], "interaction"),
    # dialog / speech / directives
    (["get_dialog_options", "speech_enhance", "set_response_directive", "get_active_directive", "clear_directive", "get_conversation_heat", "start_timer", "check_timer", "cancel_timer"], "dialog"),
    # consequence system
    (["schedule_consequence", "get_pending_consequences", "cancel_consequence"], "consequence"),
    # narrative / advanced agent effects
    (["dream_whisper", "mirror_soul", "time_echo", "enforce_behavior", "speak_as", "scene_broadcast"], "narrative"),
    # memory
    (["search_memory", "store_memory", "memory_recall"], "memory"),
    # character state helpers
    (["get_character_state", "adjust_relationship", "list_characters", "check_relationship",
      "get_character_scene_stats", "update_character_scene_stats", "set_character_scene_stat",
      "reset_character_scene_stats", "check_character_consent", "get_character_agency_summary",
      "update_mood", "apply_effect"], "character"),
    # event chain
    (["get_chain_events", "log_event", "get_chain"], "event_chain"),
    # media generation
    (["generate_image", "send_selfie", "send_voice_message"], "media"),
    # agent / scene control
    (["send_to_agent", "get_my_skills", "get_scene_context", "intercept_and_enhance",
      "get_all_tools_for_scene", "director_action", "resolve_random_scene_event", "suggest_activity"], "agent"),
    # scene state / rules
    (["add_scene_narrative", "get_scene_narrative", "get_full_scene_snapshot",
      "set_scene_atmosphere", "get_scene_rules", "get_scene_available_actions", "apply_scene_rule",
      "get_scene_rules_summary", "get_framework_status", "mood_contagion"], "scene"),
    # conversation threading
    (["query_stateless", "get_conversation_info", "fork_conversation",
      "get_conversation_heat_level", "bump_conversation_heat", "check_conversation_history",
      "cross_scene_message", "get_cross_scene_inbox"], "conversation"),
    # system / health (cosysim + devtools)
    (["get_system_stats", "search_web", "resource_config", "resource_benchmarks",
      "resource_character", "resource_chain", "resource_scene_status",
      "system_status", "list_all_skills", "get_skill_info", "get_benchmark_stats"], "system"),
    # nexus knowledge tools
    (["nexus_", "seed_nexus", "resource_nexus_status"], "nexus"),
    # home assistant
    (["ha_"], "home_assistant"),
    # notebooklm / NLM node tools
    (["notebooklm_node_", "nlm_notebook_"], "nlm"),
    # anythingllm
    (["allm_"], "allm"),
    # phone assistant
    (["phone_assistant_"], "phone_assistant"),
    # training / finetune / model
    (["training_", "finetune_", "model_", "teacher_", "finetuned_router_",
      "capture_training_data", "generate_content"], "training"),
    # scheduler / agent tasks
    (["scheduler_", "agent_create_task", "agent_update_task", "agent_complete_task",
      "agent_list_tasks", "local_agent_", "task_auto_generate", "task_from_template",
      "task_list_templates"], "scheduler"),
    # news
    (["news_"], "news"),
    # governance / rules
    (["governance_"], "governance"),
    # knowledge graph
    (["knowledge_graph_"], "knowledge_graph"),
    # deep storage
    (["deep_storage_"], "deep_storage"),
    # cache pipeline
    (["cache_pipeline_"], "cache_pipeline"),
    # master notebook
    (["master_notebook_"], "master_notebook"),
    # qa expander
    (["qa_expander_"], "qa"),
    # diagnostics / metrics / reflection / experiments
    (["diagnose_", "metrics_", "reflection_", "experiment_"], "diagnostics"),
    # review sheet
    (["review_sheet_"], "review"),
    # backup
    (["backup_"], "backup"),
    # user profile
    (["user_profile_"], "user_profile"),
    # copilot config / instructions sync
    (["copilot_sync_config", "copilot_config_status", "copilot_list_instructions",
      "copilot_list_agents", "copilot_store_snippet", "copilot_store_discovery",
      "copilot_log_progress", "copilot_context_primer", "copilot_local_model_guide"], "copilot"),
]


def classify(fn_name: str) -> str:
    """Return the domain name for a tool function."""
    for patterns, domain in DOMAIN_RULES:
        for pat in patterns:
            if fn_name == pat or fn_name.startswith(pat):
                return domain
    return "misc"


# ──── Extraction ──────────────────────────────────────────────────────────


class ToolFunc(NamedTuple):
    name: str
    domain: str
    start_line: int  # first decorator line (1-indexed)
    end_line: int    # last line of function body (1-indexed)
    source_lines: list[str]


def extract_tools(source: str) -> list[ToolFunc]:
    """Parse source and return all @mcp.tool() decorated functions."""
    lines = source.splitlines()
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        print(f"[extract] SyntaxError: {e}", file=sys.stderr)
        return []

    tools: list[ToolFunc] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.decorator_list:
            continue

        # Check if any decorator references mcp.tool or mcp.resource
        has_mcp_decorator = False
        for dec in node.decorator_list:
            dec_src = ast.unparse(dec)
            if "mcp.tool" in dec_src or "mcp.resource" in dec_src:
                has_mcp_decorator = True
                break

        if not has_mcp_decorator:
            continue

        # Get the earliest decorator line
        deco_start = min(d.lineno for d in node.decorator_list)
        fn_end = node.end_lineno

        # Grab the raw lines (1-indexed → 0-indexed slice)
        fn_lines = lines[deco_start - 1 : fn_end]

        domain = classify(node.name)
        tools.append(ToolFunc(
            name=node.name,
            domain=domain,
            start_line=deco_start,
            end_line=fn_end,
            source_lines=fn_lines,
        ))

    return sorted(tools, key=lambda t: t.start_line)


def group_by_domain(tools: list[ToolFunc]) -> Dict[str, list[ToolFunc]]:
    groups: Dict[str, list[ToolFunc]] = {}
    for t in tools:
        groups.setdefault(t.domain, []).append(t)
    return groups


# ──── Import extraction ───────────────────────────────────────────────────


def extract_header_imports(source: str) -> str:
    """Extract the import block from the top of the source file.

    Returns a string of import statements (everything before the first
    non-import, non-comment top-level statement).
    """
    lines = source.splitlines()
    import_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Stop at the FastMCP server instantiation
        if stripped.startswith("mcp = FastMCP") or stripped.startswith("@mcp."):
            break
        # Keep imports, from-imports, comments, blank lines, __future__, docstrings
        if (
            stripped.startswith("import ")
            or stripped.startswith("from ")
            or stripped.startswith("#")
            or stripped == ""
            or stripped.startswith('"""')
            or stripped.startswith("'''")
            or stripped.startswith("from __future__")
        ):
            import_lines.append(line)

    # Trim trailing blank lines
    while import_lines and not import_lines[-1].strip():
        import_lines.pop()
    return "\n".join(import_lines)


# ──── Domain file generation ──────────────────────────────────────────────

_DOMAIN_FILE_HEADER = '''\
"""MCP tool domain: {domain}.

Extracted from {source_file} by scripts/hindsight/extract.py.
All functions are decorated with @mcp.tool() and should be registered
on the mcp instance via ``from engine.mcp.tools.{domain} import register``
or imported directly.

Apply @mcp_tool for unified error handling after extraction:
    from engine.mcp.decorators import mcp_tool
"""
'''


def build_domain_file(domain: str, tools: list[ToolFunc], header_imports: str, source_name: str) -> str:
    """Build the content of a domain tool file."""
    lines: list[str] = []
    lines.append(_DOMAIN_FILE_HEADER.format(domain=domain, source_file=source_name))
    lines.append(header_imports)
    lines.append("")
    lines.append("")
    lines.append(f"# ──── {domain.upper()} TOOLS {'─' * (60 - len(domain))}─")
    lines.append("")

    for tool in tools:
        lines.append("")
        lines.extend(tool.source_lines)
        lines.append("")

    return "\n".join(lines)


# ──── CLI / Main ─────────────────────────────────────────────────────────


def run(
    source_file: Path,
    write: bool = False,
    target_domain: str | None = None,
    output_dir: Path = TOOLS_DIR,
) -> None:
    source = source_file.read_text(encoding="utf-8-sig")  # -sig strips BOM if present
    tools = extract_tools(source)
    groups = group_by_domain(tools)
    header = extract_header_imports(source)

    print(f"\n{'─' * 70}")
    print(f"  Source:  {source_file.relative_to(ROOT)}")
    print(f"  Tools:   {len(tools)} found")
    print(f"  Domains: {', '.join(sorted(groups))}")
    print(f"{'─' * 70}")

    domain_summary: list[tuple[str, int, Path]] = []
    for domain in sorted(groups):
        if target_domain and domain != target_domain:
            continue
        domain_tools = groups[domain]
        out_path = output_dir / f"{domain}.py"
        content = build_domain_file(domain, domain_tools, header, source_file.name)
        domain_summary.append((domain, len(domain_tools), out_path))

        if write:
            output_dir.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
            print(f"  ✓ {out_path.relative_to(ROOT)}  ({len(domain_tools)} tools)")
        else:
            print(f"  [dry] {out_path.relative_to(ROOT)}  ({len(domain_tools)} tools)")

    print()
    if not write:
        print("  Run with --write to create files.")

    # Print functions in misc domain so we can review classification gaps
    if "misc" in groups:
        misc = groups["misc"]
        print(f"\n  ⚠ {len(misc)} unclassified functions (domain: misc):")
        for t in misc:
            print(f"      {t.name}  (line {t.start_line})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract MCP tools into domain files")
    parser.add_argument(
        "--file",
        default="engine/mcp/cosysim_server.py",
        help="Server file to extract from (relative to project root)",
    )
    parser.add_argument("--write", action="store_true", help="Actually write output files")
    parser.add_argument("--domain", help="Only process this domain")
    parser.add_argument(
        "--output",
        default="engine/mcp/tools",
        help="Output directory for domain files",
    )
    args = parser.parse_args()

    src = ROOT / args.file
    if not src.exists():
        print(f"File not found: {src}", file=sys.stderr)
        sys.exit(1)

    run(
        source_file=src,
        write=args.write,
        target_domain=args.domain,
        output_dir=ROOT / args.output,
    )


if __name__ == "__main__":
    main()
