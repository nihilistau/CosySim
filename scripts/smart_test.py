"""
Smart Test Runner
=================

Git-diff-aware test runner for CosySim.  Inspects changed files, maps them to
test domains via ``SOURCE_TO_DOMAINS``, and runs only the affected test files.
Supports smoke mode (one test per domain), explicit domain selection, full-suite
fallback, and automatic pytest-xdist parallelism when available.

Usage:
    python scripts/smart_test.py                    # tests for git-diff (uncommitted)
    python scripts/smart_test.py --since HEAD~1     # tests for last commit
    python scripts/smart_test.py --since HEAD~5     # tests for last 5 commits
    python scripts/smart_test.py --domain tts       # all tests in a domain
    python scripts/smart_test.py --domain asset_studio,lmstudio  # multiple domains
    python scripts/smart_test.py --fast             # changed tests, skip slow
    python scripts/smart_test.py --smoke            # one key test from every domain
    python scripts/smart_test.py --full             # everything (use rarely)
    python scripts/smart_test.py --list             # show what WOULD run, don't run

Domains:
    engine_core     — config, mcp, event_chain, dialog, rules, state, scene_manager
    agents          — character_agent, virtual_agent, interceptors, stream_processor
    lmstudio        — lms_client, conversation, router_v3, orchestrator, model_manager
    skills          — skill registry, builtin skill packs, social/memory/character skills
    nexus           — nexus client, bridge, seeder, maintenance, query_router
    nexus_nlm       — notebooklm forge, nlm_engine, automation, distillers
    news            — news_system, news_sources, news_nlm_pipeline, news_feed
    scheduler       — scheduler_daemon, autonomy_skills, task_scheduler
    training        — training_pipeline, finetune, router_data, dataset_curator
    tts             — tts_manager, orpheus_tts, orpheus_native, voice_profiles, stt
    asset_studio    — asset_studio_workflows, tuning_engine, comfyui_skills
    story           — story_arc, faction_politics, daily_challenge
    shared          — particles, scene_fx, portrait_overlay, transitions, navbar, admin
    scene_bedroom   — bedroom_game, bedroom_revamp
    scene_phone     — phone_revamp, phone_skills, phone_dashboard, phone_routing
    scene_lounge    — lounge, lounge_revamp
    scene_tavern    — tavern, tavern_revamp
    scene_casino    — casino_game, casino_revamp
    scene_gallery   — gallery, gallery_revamp
    scene_arena     — arena_engine, arena_scene
    scene_realm     — realm, realm_revamp
    scene_neoncity  — neoncity, neoncity_revamp
    scene_hub       — hub_scene, hub_revamp, hub_flask
    scene_intel_hub — intel_hub_scene, intel_hub_revamp, intel_hub_mission_control
    scene_heist     — heist, heist_revamp
    scene_games     — games, games_revamp
    scene_coders    — coders, coders_revamp

Version: v1.42.1 [2026-03-21]
Author:  CosySim Team

Change Log:
    v1.42.1 [2026-03-21] — Added module header, version stamp
    v1.42.0 [2026-03-21] — Created: git-diff-aware test runner with domain mapping,
                            smoke tests, xdist parallelism, pytest plugin integration
"""
from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

# ──── Repository root ─────────────────────────────────────────────────────────

ROOT = Path(__file__).parent.parent
TESTS_DIR = ROOT / "tests"

# ──── Domain → test file mapping ──────────────────────────────────────────────
# Each entry lists all test files that belong to that domain.
# Use glob patterns (relative to TESTS_DIR) to catch test variants.

DOMAIN_TESTS: Dict[str, List[str]] = {
    "engine_core": [
        "test_config.py",
        "test_config_validator.py",
        "test_mcp_server.py",
        "test_dialog_system.py",
        "test_event_chain.py",
        "test_event_bus.py",
        "test_scene_rules_engine.py",
        "test_scene_imports.py",
        "test_scene_routes.py",
        "test_port_registry.py",
        "test_database.py",
        "test_data_manager.py",
        "test_resource_manager.py",
        "test_resilience.py",
        "test_housekeeping.py",
        "test_activity_bus.py",
        "test_kill_switch.py",
        "test_backup_manager.py",
        "test_world_state.py",
        "test_world_sim.py",
        "test_state_coordinator.py",
    ],
    "agents": [
        "test_character_agent.py",
        "test_virtual_agent_v27.py",
        "test_agent_tags.py",
        "test_agent_workflows.py",
        "test_stream_processor.py",
        "test_interceptor_upgrades.py",
        "test_vam_pipeline_integration.py",
        "test_virtual_pipeline.py",
        "test_pipeline_smoke.py",
        "test_pipeline_result.py",
        "test_cache_pipeline.py",
        "test_overlay_router.py",
        "test_token_router.py",
        "test_content_router.py",
        "test_content_gate.py",
        "test_content_engine.py",
        "test_character_memory.py",
        "test_relationship_system.py",
        "test_relationship_interceptor.py",
        "test_dialogue_gate_reputation.py",
        "test_reputation.py",
        "test_profile_skills.py",
        "test_player_profile.py",
        "test_assistant_profile_inject.py",
    ],
    "lmstudio": [
        "test_lms_client_v27.py",
        "test_lmstudio_infra.py",
        "test_conversation.py",
        "test_conversation_analyzer.py",
        "test_orchestrator.py",
        "test_router.py",
        "test_router_v3_client.py",
        "test_router_v3_dataset.py",
        "test_router_v3_benchmark.py",
        "test_finetuned_router.py",
        "test_model_manager.py",
        "test_model_registry_and_benchmark.py",
        "test_inference_monitor.py",
        "test_sdk_client.py",
        "test_lms_task_bridge.py",
        "test_local_agent_bridge.py",
        "test_llmster_manager.py",
    ],
    "skills": [
        "test_skills.py",
        "test_skill_*.py",
        "test_tool_registry.py",
        "test_tag_registry.py",
        "test_social_skills.py",
        "test_memory_skills.py",
        "test_character_skills.py",
        "test_phone_skills.py",
        "test_board_skills.py",
        "test_art_skills.py",
        "test_coding_skills.py",
        "test_comfyui_skills.py",
        "test_scene_art.py",
        "test_scene_director.py",
        "test_npc_backstory.py",
        "test_npc_activity_ui.py",
        "test_interaction_trees.py",
        "test_investigation.py",
        "test_spatial.py",
        "test_prompts_chat_skills.py",
    ],
    "nexus": [
        "test_nexus_seeder_and_bridge.py",
        "test_nexus_phase2.py",
        "test_nexus_panel.py",
        "test_nexus_mixin.py",
        "test_nexus_maintenance.py",
        "test_nexus_distillers.py",
        "test_nexus_bridge.py",
        "test_nexus_aware_skills.py",
        "test_query_router.py",
        "test_knowledge_quality.py",
        "test_knowledge_graph.py",
        "test_knowledge_forge.py",
        "test_governance_rules.py",
        "test_governance.py",
        "test_url_manager.py",
        "test_url_ingest.py",
        "test_sync_sessions_to_nexus.py",
        "test_session_distillation.py",
        "test_source_pyramid.py",
        "test_copilot_self_config.py",
        "test_copilot_bridge.py",
    ],
    "nexus_nlm": [
        "test_nlm_rpc_mapper.py",
        "test_nlm_router.py",
        "test_nlm_notebook_manager.py",
        "test_nlm_node_bridge.py",
        "test_nlm_live_proxy.py",
        "test_nlm_hybrid.py",
        "test_nlm_generator.py",
        "test_nlm_forge_skills.py",
        "test_nlm_engine.py",
        "test_nlm_deep_storage.py",
        "test_nlm_automation.py",
        "test_notebooklm_devtools.py",
        "test_master_notebook_builder.py",
        "test_har_extractor.py",
        "test_history_miner.py",
    ],
    "news": [
        "test_news_system.py",
        "test_news_sources.py",
        "test_news_nlm_pipeline.py",
        "test_news_feed_api.py",
        "test_consumer_briefing.py",
        "test_phone_news.py",
    ],
    "scheduler": [
        "test_scheduler_daemon.py",
        "test_autonomy_skills.py",
        "test_task_scheduler.py",
        "test_qa_expander.py",
        "test_router_finetune_cycle.py",
        "test_nlm_generator.py",
        "test_master_notebook_builder.py",
        "test_npc_scheduler.py",
    ],
    "training": [
        "test_training_pipeline.py",
        "test_training_flywheel.py",
        "test_training_capture.py",
        "test_router_data.py",
        "test_router_finetune_cycle.py",
        "test_finetune_orchestrator.py",
        "test_dataset_curator.py",
        "test_micro_datasets.py",
        "test_teacher_pipeline.py",
        "test_evaluator.py",
        "test_benchmark.py",
        "test_benchmarks.py",
        "test_auto_tuner.py",
        "test_auto_diagnosis.py",
        "test_metrics_db.py",
        "test_metrics_collector.py",
        "test_monitoring_metrics_collector.py",
        "test_meta_metrics.py",
        "test_experiment_proposals.py",
    ],
    "tts": [
        "test_tts.py",
        "test_tts_manager.py",
        "test_orpheus_tts.py",
        "test_orpheus_native.py",
        "test_voice_profiles.py",
        "test_voice_system.py",
        "test_voice_endpoints.py",
        "test_voice_hardening.py",
        "test_stt_ambient.py",
        "test_web_bridge.py",
    ],
    "asset_studio": [
        "test_asset_studio.py",
        "test_asset_studio_workflows.py",
        "test_tuning_engine.py",
        "test_comfyui_skills.py",
        "test_prompt_builder.py",
        "test_media_config.py",
        "test_review_sheet.py",
    ],
    "story": [
        "test_story_arc.py",
        "test_faction_politics.py",
        "test_consequences.py",
        "test_economy.py",
        "test_economy_wiring.py",
    ],
    "shared": [
        "test_particles_engine.py",
        "test_scene_fx_css.py",
        "test_portrait_overlay.py",
        "test_transitions.py",
        "test_navbar_v2.py",
        "test_track_a_wiring.py",
        "test_stt_ambient.py",
        "test_admin_overlay.py",
        "test_admin_nexus_tabs.py",
        "test_admin_scene.py",
        "test_system_control_scene.py",
        "test_system_reflection.py",
        "test_system_assistant.py",
        "test_alerts.py",
        "test_cross_scene_relay.py",
        "test_stream_watcher.py",
    ],
    "scene_bedroom": ["test_bedroom_game.py", "test_bedroom_revamp.py"],
    "scene_phone": [
        "test_phone_revamp.py",
        "test_phone_skills.py",
        "test_phone_dashboard.py",
        "test_phone_routing.py",
        "test_phone_assistant.py",
        "test_phone_news.py",
    ],
    "scene_lounge": ["test_lounge.py", "test_lounge_revamp.py"],
    "scene_tavern": ["test_tavern.py", "test_tavern_revamp.py"],
    "scene_casino": ["test_casino_game.py", "test_casino_revamp.py"],
    "scene_gallery": ["test_gallery.py", "test_gallery_revamp.py"],
    "scene_arena": ["test_arena_engine.py", "test_arena_scene.py"],
    "scene_realm": ["test_realm.py", "test_realm_revamp.py"],
    "scene_neoncity": ["test_neoncity.py", "test_neoncity_revamp.py"],
    "scene_hub": ["test_hub_scene.py", "test_hub_revamp.py", "test_hub_flask.py"],
    "scene_intel_hub": [
        "test_intel_hub_scene.py",
        "test_intel_hub_revamp.py",
        "test_intel_hub_mission_control.py",
    ],
    "scene_heist": ["test_heist.py", "test_heist_revamp.py"],
    "scene_games": ["test_games.py", "test_games_revamp.py"],
    "scene_coders": ["test_coders.py", "test_coders_revamp.py"],
    "integration": [
        "test_integration.py",
        "test_anythingllm.py",
        "test_homeassistant.py",
    ],
}

# ──── Smoke Tests ────────────────────────────────────────────────────────────
# One representative test from each domain for very fast sanity checks (~30s)
SMOKE_TESTS: List[str] = [
    "test_config.py",
    "test_dialog_system.py",
    "test_skills.py",
    "test_nexus_bridge.py",
    "test_query_router.py",
    "test_router_v3_client.py",
    "test_asset_studio.py",
    "test_scheduler_daemon.py",
    "test_story_arc.py",
    "test_scene_imports.py",
    "test_hub_scene.py",
    "test_bedroom_revamp.py",
    "test_tts.py",
    "test_voice_profiles.py",
    "test_transitions.py",
]

# ──── Source path → domain(s) mapping ────────────────────────────────────────
# Ordered: more-specific prefixes first. First match wins per prefix segment.

SOURCE_TO_DOMAINS: List[tuple[str, List[str]]] = [
    # TTS
    ("engine/tts/", ["tts"]),
    # Asset Studio
    ("engine/asset_studio/", ["asset_studio"]),
    ("content/scenes/asset_studio/", ["asset_studio"]),
    # Nexus NLM / news / scheduler / nexus
    ("engine/nexus/nlm", ["nexus_nlm", "nexus"]),
    ("engine/nexus/news", ["news", "nexus"]),
    ("engine/nexus/scheduler", ["scheduler", "nexus"]),
    ("engine/nexus/", ["nexus"]),
    # LMStudio
    ("engine/lmstudio/router", ["lmstudio", "training"]),
    ("engine/lmstudio/", ["lmstudio"]),
    # Agents / pipeline
    ("engine/agents/", ["agents"]),
    ("engine/pipeline/", ["agents"]),
    # Skills
    ("engine/skills/", ["skills"]),
    # Story / economy / world
    ("engine/story/", ["story"]),
    ("engine/economy/", ["story"]),
    ("engine/world/", ["engine_core"]),
    # Training
    ("training/", ["training"]),
    # Integrations
    ("engine/integrations/", ["engine_core"]),
    # Engine core
    ("engine/mcp/", ["engine_core"]),
    ("engine/services/", ["engine_core"]),
    ("engine/scenes/", ["engine_core"]),
    ("engine/config", ["engine_core"]),
    ("engine/control_plane_registry", ["engine_core"]),
    ("engine/port_registry", ["engine_core"]),
    ("engine/utils", ["engine_core"]),
    ("engine/creation/", ["asset_studio"]),
    # Config files
    ("config/", ["engine_core"]),
    # Launcher / TUI (infrastructure, run engine_core smoke)
    ("launcher.py", ["engine_core"]),
    ("tui.py", ["engine_core"]),
    # Shared
    ("content/shared/", ["shared"]),
    # Content simulation
    ("content/simulation/", ["engine_core"]),
    # Individual scenes (must come before generic content/scenes/)
    ("content/scenes/bedroom/", ["scene_bedroom"]),
    ("content/scenes/phone/", ["scene_phone"]),
    ("content/scenes/lounge/", ["scene_lounge"]),
    ("content/scenes/tavern/", ["scene_tavern"]),
    ("content/scenes/casino/", ["scene_casino"]),
    ("content/scenes/gallery/", ["scene_gallery"]),
    ("content/scenes/arena/", ["scene_arena"]),
    ("content/scenes/realm/", ["scene_realm"]),
    ("content/scenes/neoncity/", ["scene_neoncity"]),
    ("content/scenes/hub/", ["scene_hub"]),
    ("content/scenes/intel_hub/", ["scene_intel_hub"]),
    ("content/scenes/heist/", ["scene_heist"]),
    ("content/scenes/games/", ["scene_games"]),
    ("content/scenes/coders/", ["scene_coders"]),
    ("content/scenes/grid/", ["engine_core"]),
    ("content/scenes/penthouse/", ["engine_core"]),
    ("content/scenes/lab_break/", ["engine_core"]),
    ("content/scenes/command_center/", ["shared"]),
    ("content/scenes/system_control/", ["shared"]),
    ("content/scenes/nexus_panel/", ["nexus"]),
    # Fallback for content/scenes (base_scene etc)
    ("content/scenes/", ["engine_core"]),
    # Docs (no tests needed)
    ("docs/", []),
    # Tests themselves → run just that file
    ("tests/test_", ["_self"]),
    # conftest changes → run smoke (affects all tests)
    ("tests/conftest", ["_smoke"]),
]

# ──── Helpers ─────────────────────────────────────────────────────────────────


def _git_changed_files(since: str = "HEAD") -> List[str]:
    """Return list of changed file paths (relative to repo root).

    Args:
        since: Git ref to diff against. 'HEAD' means staged + unstaged changes.
    """
    files: List[str] = []
    if since == "HEAD":
        # Uncommitted changes (staged + unstaged)
        for cmd in [["git", "diff", "--name-only", "--cached"],
                    ["git", "diff", "--name-only"]]:
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
            files.extend(result.stdout.strip().splitlines())
    else:
        result = subprocess.run(
            ["git", "diff", "--name-only", since, "HEAD"],
            capture_output=True, text=True, cwd=ROOT
        )
        files.extend(result.stdout.strip().splitlines())
    return list(dict.fromkeys(f for f in files if f))  # deduplicate, preserve order


def _domains_for_file(filepath: str) -> List[str]:
    """Return domain list for a changed source file."""
    # Normalise to forward slashes
    fp = filepath.replace("\\", "/")
    if fp.startswith("tests/test_"):
        return ["_self"]
    for prefix, domains in SOURCE_TO_DOMAINS:
        if fp.startswith(prefix):
            return domains
    return []


def _resolve_test_files(patterns: List[str]) -> List[Path]:
    """Expand a list of test file names/globs to existing Path objects."""
    found: List[Path] = []
    for pattern in patterns:
        if "*" in pattern:
            found.extend(sorted(TESTS_DIR.glob(pattern)))
        else:
            p = TESTS_DIR / pattern
            if p.exists():
                found.append(p)
    return found


def _ordered_unique(items: Sequence[str]) -> List[str]:
    """Return items in first-seen order without duplicates."""
    ordered: List[str] = []
    seen: Set[str] = set()
    for item in items:
        if item and item not in seen:
            ordered.append(item)
            seen.add(item)
    return ordered


def _xdist_available() -> bool:
    """Return True when pytest-xdist is importable."""
    return importlib.util.find_spec("xdist") is not None


def _has_parallel_override(pytest_args: Sequence[str]) -> bool:
    """Return True when pytest args already control xdist behavior explicitly."""
    for index, arg in enumerate(pytest_args):
        if arg == "-n" or arg.startswith("-n=") or arg.startswith("--numprocesses"):
            return True
        if arg.startswith("--dist"):
            return True
        if arg == "-p" and index + 1 < len(pytest_args) and pytest_args[index + 1] == "no:xdist":
            return True
        if arg.startswith("-p") and "no:xdist" in arg:
            return True
    return False


def _parallel_pytest_args(
    enable_parallel: bool,
    pytest_args: Sequence[str],
    serial: bool,
    workers: str,
    xdist_dist: str,
) -> List[str]:
    """Return automatic pytest-xdist args when parallel execution is appropriate."""
    if not enable_parallel or serial or _has_parallel_override(pytest_args) or not _xdist_available():
        return []
    return ["-n", workers, f"--dist={xdist_dist}"]


def _build_pytest_command(
    pytest_targets: Sequence[str],
    extra_args: Sequence[str],
    enable_parallel: bool,
    serial: bool,
    workers: str,
    xdist_dist: str,
) -> List[str]:
    """Build the final pytest command, injecting automatic xdist args when useful."""
    parallel_args = _parallel_pytest_args(enable_parallel, extra_args, serial, workers, xdist_dist)
    return [sys.executable, "-m", "pytest", *pytest_targets, *parallel_args, *extra_args]


def _tests_for_domains(domains: Sequence[str], changed_files: Optional[List[str]] = None) -> List[Path]:
    """Collect all test files for the given set of domains.

    If '_self' is in domains, resolve changed test files directly.
    """
    test_files: List[Path] = []
    seen: Set[Path] = set()

    if "_self" in domains and changed_files:
        for f in changed_files:
            p = ROOT / f
            if p.exists() and p.suffix == ".py" and p.parent.name == "tests":
                if p not in seen:
                    test_files.append(p)
                    seen.add(p)

    for domain in domains:
        if domain == "_self":
            continue
        patterns = DOMAIN_TESTS.get(domain, [])
        for p in _resolve_test_files(patterns):
            if p not in seen:
                test_files.append(p)
                seen.add(p)

    return test_files


def _run_pytest(
    test_files: List[Path],
    extra_args: List[str],
    serial: bool,
    workers: str,
    xdist_dist: str,
) -> int:
    """Run pytest on the given test files. Returns exit code."""
    if not test_files:
        print("No test files to run.")
        return 0
    parallel_args = _parallel_pytest_args(
        enable_parallel=len(test_files) > 1,
        pytest_args=extra_args,
        serial=serial,
        workers=workers,
        xdist_dist=xdist_dist,
    )
    cmd = [sys.executable, "-m", "pytest"] + [str(f) for f in test_files] + parallel_args + extra_args
    print(f"\n>> Running {len(test_files)} test file(s):")
    for f in test_files:
        print(f"   {f.relative_to(ROOT)}")
    if parallel_args:
        print(f"   [parallel] {' '.join(parallel_args)}")
    print()
    return subprocess.run(cmd, cwd=ROOT).returncode


# ──── CLI ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smart CosySim test runner — only runs tests affected by changes."
    )
    parser.add_argument(
        "--since",
        default="HEAD",
        help="Git ref to diff against (default: HEAD = uncommitted changes). "
             "Use HEAD~1 for last commit, HEAD~5 for last 5 commits.",
    )
    parser.add_argument(
        "--domain",
        default="",
        help="Comma-separated domain(s) to run regardless of git diff. "
             "See 'Domains' in module docstring for valid names.",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Skip tests marked @pytest.mark.slow.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run one key test from every domain (~15 files, very fast).",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run the complete test suite (use rarely — takes 10+ min).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Show which test files would run without running them.",
    )
    parser.add_argument(
        "--serial",
        action="store_true",
        help="Disable automatic pytest-xdist parallelism.",
    )
    parser.add_argument(
        "--workers",
        default="auto",
        help="Worker count for automatic pytest-xdist parallelism (default: auto).",
    )
    parser.add_argument(
        "--xdist-dist",
        default="loadfile",
        choices=["load", "loadfile", "loadscope", "worksteal"],
        help="Distribution strategy for automatic pytest-xdist parallelism.",
    )
    parser.add_argument(
        "pytest_args",
        nargs="*",
        help="Extra arguments passed through to pytest (e.g. -v --tb=short).",
    )
    args = parser.parse_args()

    extra_pytest_args = list(args.pytest_args) + [
        "--tb=short",
        "--ignore=tests/test_agent_loop.py",
        "--ignore=tests/live_wire_test.py",
    ]
    if args.fast:
        extra_pytest_args += ["-m", "not slow"]

    # ── Full suite ────────────────────────────────────────────────────────────
    if args.full:
        print("!! Running FULL test suite -- this will take 10+ minutes.")
        cmd = _build_pytest_command(
            pytest_targets=["tests/"],
            extra_args=extra_pytest_args,
            enable_parallel=True,
            serial=args.serial,
            workers=args.workers,
            xdist_dist=args.xdist_dist,
        )
        sys.exit(subprocess.run(cmd, cwd=ROOT).returncode)

    # ── Smoke test ────────────────────────────────────────────────────────────
    if args.smoke:
        smoke_files = _resolve_test_files(SMOKE_TESTS)
        if args.list:
            print(f"SMOKE ({len(smoke_files)} files):")
            for f in smoke_files:
                print(f"  {f.relative_to(ROOT)}")
            return
        sys.exit(_run_pytest(smoke_files, extra_pytest_args, args.serial, args.workers, args.xdist_dist))

    # ── Domain selector ───────────────────────────────────────────────────────
    if args.domain:
        requested = _ordered_unique([d.strip() for d in args.domain.split(",") if d.strip()])
        invalid = set(requested) - set(DOMAIN_TESTS.keys())
        if invalid:
            print(f"Unknown domain(s): {', '.join(sorted(invalid))}")
            print(f"Valid domains: {', '.join(sorted(DOMAIN_TESTS.keys()))}")
            sys.exit(1)
        test_files = _tests_for_domains(requested)
        if args.list:
            print(f"DOMAIN '{args.domain}' ({len(test_files)} files):")
            for f in test_files:
                print(f"  {f.relative_to(ROOT)}")
            return
        sys.exit(_run_pytest(test_files, extra_pytest_args, args.serial, args.workers, args.xdist_dist))

    # ── Git-diff based selection (default) ────────────────────────────────────
    changed = _git_changed_files(since=args.since)
    if not changed:
        print(f"No changed files detected (since: {args.since}).")
        print("Run --full to run everything, --smoke for a quick sanity check,")
        print("or --domain <name> to run a specific domain.")
        return

    ordered_domains: List[str] = []
    file_domain_map: Dict[str, List[str]] = {}
    trigger_smoke = False
    for f in changed:
        domains = _domains_for_file(f)
        file_domain_map[f] = domains
        if "_smoke" in domains:
            trigger_smoke = True
        for domain in domains:
            if not domain.startswith("_") and domain not in ordered_domains:
                ordered_domains.append(domain)

    # Print what triggered what
    print(f"Changed files (since {args.since}):")
    for f, domains in file_domain_map.items():
        label = ", ".join(domains) if domains else "(no domain — skipped)"
        print(f"  {f}  ->  [{label}]")
    print()

    if trigger_smoke:
        print("conftest.py changed -- upgrading to smoke test coverage.")
        test_files = _resolve_test_files(SMOKE_TESTS)
    else:
        requested_domains = []
        if any("_self" in domains for domains in file_domain_map.values()):
            requested_domains.append("_self")
        requested_domains.extend(ordered_domains)
        test_files = _tests_for_domains(requested_domains, changed_files=changed)

    if not test_files:
        print("No matching test files found for changed files.")
        print("Tip: run --smoke for a quick sanity check or --full for everything.")
        return

    if args.list:
        print(f"Would run {len(test_files)} test file(s):")
        for f in test_files:
            print(f"  {f.relative_to(ROOT)}")
        return

    sys.exit(_run_pytest(test_files, extra_pytest_args, args.serial, args.workers, args.xdist_dist))


if __name__ == "__main__":
    main()
