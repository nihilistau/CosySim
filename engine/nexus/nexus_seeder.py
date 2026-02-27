"""
nexus_seeder.py — Seeds Nexus KMS with CosySim project knowledge.

Reads documentation, generates knowledge entries, Q&A pairs, rules,
prompts, and conventions. Idempotent — checks for existing entries.

Usage:
    python -m engine.nexus.nexus_seeder [docs|qa|rules|prompts|conventions|all]
"""
from __future__ import annotations

import json
import logging
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

NEXUS_URL = "http://localhost:8700"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ── Nexus API helpers ──────────────────────────────────────────────────

def _post(path: str, data: dict, timeout: int = 10) -> Optional[dict]:
    """Post to Nexus API."""
    try:
        url = f"{NEXUS_URL}{path}"
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        logger.warning("Nexus POST %s failed: %s", path, e)
        return None


def _get(path: str, timeout: int = 10) -> Optional[dict]:
    """Get from Nexus API."""
    try:
        url = f"{NEXUS_URL}{path}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        logger.warning("Nexus GET %s failed: %s", path, e)
        return None


def _search(query: str) -> list[dict]:
    """Search Nexus for existing entries."""
    result = _get(f"/api/search?q={urllib.request.quote(query)}&limit=5")
    if result and result.get("ok"):
        return result.get("data", [])
    return []


def _entry_exists(title: str) -> bool:
    """Check if an entry with this exact title already exists."""
    results = _search(title)
    for r in results:
        if r.get("title", "").strip().lower() == title.strip().lower():
            return True
    return False


def _qa_exists(question: str) -> bool:
    """Check if a Q&A with this question already exists."""
    result = _get(f"/api/qa?limit=200")
    if result and result.get("ok"):
        for qa in result.get("data", []):
            if qa.get("question", "").strip().lower() == question.strip().lower():
                return True
    return False


def add_entry(
    title: str,
    content: str,
    content_type: str = "note",
    category: str = "architecture",
    tags: Optional[list[str]] = None,
) -> bool:
    """Add a knowledge entry if it doesn't already exist."""
    if _entry_exists(title):
        logger.info("SKIP (exists): %s", title)
        return False
    result = _post("/api/entries", {
        "title": title,
        "content": content,
        "content_type": content_type,
        "category": category,
        "tags": tags or [],
    })
    if result and result.get("ok"):
        logger.info("ADDED: %s", title)
        return True
    logger.warning("FAILED: %s", title)
    return False


def add_qa(
    question: str,
    answer: str,
    category: str = "development",
    tags: Optional[list[str]] = None,
) -> bool:
    """Add a Q&A pair if it doesn't already exist."""
    if _qa_exists(question):
        logger.info("SKIP Q&A (exists): %s", question[:60])
        return False
    result = _post("/api/qa", {
        "question": question,
        "answer": answer,
        "category": category,
        "tags": tags or [],
    })
    if result and result.get("ok"):
        logger.info("ADDED Q&A: %s", question[:60])
        return True
    logger.warning("FAILED Q&A: %s", question[:60])
    return False


def add_rule(
    scope: str,
    rule_type: str,
    condition: str,
    action: str,
    priority: int = 50,
) -> bool:
    """Add a governance rule."""
    result = _post("/api/rules", {
        "scope": scope,
        "rule_type": rule_type,
        "condition": condition,
        "action": action,
        "priority": priority,
    })
    if result and result.get("ok"):
        logger.info("ADDED rule: [%s] %s", scope, condition[:50])
        return True
    logger.warning("FAILED rule: [%s] %s", scope, condition[:50])
    return False


# ── Seed: Documentation ───────────────────────────────────────────────

def seed_docs() -> int:
    """Seed Nexus with architecture and system knowledge entries."""
    entries = _get_doc_entries()
    created = 0
    for title, content, ct, cat, tags in entries:
        if add_entry(title, content, ct, cat, tags):
            created += 1
    logger.info("  Docs: %s/%s entries created", created, len(entries))
    return created


def _get_doc_entries() -> list[tuple[str, str, str, str, list[str]]]:
    """Return all documentation knowledge entries."""
    return [
        (
            "CosySim Architecture Overview",
            "CosySim is a multi-scene AI simulation framework (v0.51b) with three layers:\n\n"
            "Config Layer: YAML/JSON configuration (default.yaml, development.yaml, production.yaml)\n"
            "Engine Layer: Reusable framework — agents/, mcp/, lmstudio/, skills/, scenes/, services/, pipeline/, tts/, nexus/\n"
            "Content Layer: 18 scene implementations + simulation services (database, characters)\n\n"
            "Key singletons: MCPFramework (state tree), DialogSystem (conversation threading), "
            "InterceptorPipeline (agent governance), SkillRegistry (tool discovery), ConfigManager (dot-notation config access).\n\n"
            "State flows through MCP framework trees, never local variables. Services communicate via REST APIs or MCP tool calls.",
            "document", "architecture", ["cosysim", "framework", "design"],
        ),
        (
            "MCP Framework Design",
            "MCPFramework is the central state tree managing scenes, characters, and game state.\n\n"
            "Components:\n"
            "- MCPSceneNode: per-scene state container\n"
            "- MCPCharacterNode: per-character state (stats, inventory, relationships)\n"
            "- MCPTimer: scheduled events with callbacks\n"
            "- MCPGameSession: turn-based game state\n\n"
            "MCP Server: 124 tools via FastMCP 3.0.2 in cosysim_server.py\n"
            "- 8 domain tool modules: character, memory, game, media, dialog, scene, wardrobe, utility\n"
            "- 14 Nexus bridge tools for knowledge management\n"
            "- 3 discovery tools: list_all_skills, get_skill_info, system_status\n"
            "- 6 resources: config, benchmarks, character profiles, event chains, scene status, nexus status\n\n"
            "Transport: stdio (VS Code Copilot) or HTTP/SSE (web bridge)",
            "document", "architecture", ["mcp", "framework", "tools"],
        ),
        (
            "Interceptor Pipeline Architecture",
            "InterceptorPipeline wraps agent LLM calls with pre/post hooks.\n\n"
            "Flow: AgentGovernor -> CharacterAgent.reply() -> VirtualAgent.reply() -> build_request() -> InterceptorPipeline\n\n"
            "Key Interceptors (by priority):\n"
            "- 8: CharacterRegistryInterceptor — inject identity/mood from MCPFramework\n"
            "- 10: RouterMessageInjector — inject inbox messages from other agents\n"
            "- 12: DialogDirectiveInterceptor — enforce must_include/style directives\n"
            "- 30: SkillAwarenessInterceptor — build available skills list\n"
            "- 40: GameRulesInterceptor — inject game-specific rules + required tools\n"
            "- 50: PersonalityGuardInterceptor — add in-character tone reminders\n"
            "- 60: PolicyEnforcerInterceptor — enforce reply length, forbidden topics\n"
            "- 80: ResponseShaperInterceptor — post-call: trim/reshape reply\n"
            "- 90: ActivityLoggerInterceptor — post-call: log final reply\n\n"
            "Each runs pre_call(ctx) then post_call(ctx, response). Register in config/default.yaml under comms.interceptors.",
            "document", "architecture", ["interceptor", "pipeline", "governance", "agents"],
        ),
        (
            "LMStudio Integration Guide",
            "CosySim uses LMStudio v1 API at http://localhost:1234 for all inference.\n\n"
            "Input Format (CRITICAL): Items MUST use type:text/text:... NOT type:message\n\n"
            "Inference Flow:\n"
            "VirtualAgent.reply() -> Orchestrator.infer() -> Router.submit() -> LMSClient.chat() -> Conversation.send()\n\n"
            "InferenceOrchestrator is the unified facade:\n"
            "- Tier selection: gpu_primary (T1 reasoning), cpu_utility (T2 background), cpu_router (T3 classification)\n"
            "- Model loading via ModelManager (CONCURRENT/JIT/JIT_TTL modes)\n"
            "- Resource management: VRAM budgets via ResourceManager\n"
            "- Priority routing via InferenceRouter queue\n\n"
            "Stateful Conversations: store:true + previous_response_id for threading. Supports branching via branch_at(turn).\n\n"
            "SSE Streaming: LMStudio v1 uses event:type data:json format. Event types: chat.start, chat.end, message.delta, reasoning.delta, tool_call.*, error.",
            "document", "architecture", ["lmstudio", "inference", "orchestrator", "models"],
        ),
        (
            "Scene System Design",
            "CosySim has 18 scenes (13 game + 5 utility) each running as independent Flask apps.\n\n"
            "Scene Structure: content/scenes/name/ with __init__.py (scene class), name_skills.py (@skill functions), templates/ (Jinja2), static/ (CSS/JS/images)\n\n"
            "Required BaseScene Overrides:\n"
            "- SCENE_METADATA = dict with name, port, type\n"
            "- start() — initialize, register MCP nodes, start Flask\n"
            "- stop() — persist state, cleanup\n"
            "- get_plugin_info() — return metadata for hub discovery\n\n"
            "Port Map:\n"
            "Phone:5555, Bedroom:5556, NeonCity:5557, Tavern:5558, Realm:5559, Casino:5560, "
            "Heist:5561, Gallery:5562, Warzone:5563, Coders:5564, Lounge:5565, CommandCenter:5566, Games:5567\n"
            "Hub:8500, Dashboard:8501, Admin:8502, TTS:8600, WebBridge:8601\n\n"
            "Character Lifecycle: on_character_added() syncs to MCP + sets up personality. on_character_removed() cleans up MCP nodes.",
            "document", "architecture", ["scenes", "flask", "ports", "characters"],
        ),
        (
            "Skills System and Registry",
            "CosySim uses @skill decorator for LLM-callable tools. 194 skills across 26 packs.\n\n"
            "Decorator: @skill(pack='scene_name', description='LLM-facing desc', category='game', cooldown=5.0, cost=1.0, tags=[...])\n\n"
            "Categories: COMMUNICATION, MEMORY, MEDIA, GAME, SOCIAL, ENVIRONMENT, SYSTEM, NARRATIVE\n\n"
            "Core Packs (14): memory, character, comfyui, voice, tts, social, boards, training, notebooklm, nexus, coding, environment, narrative, system\n"
            "Scene Packs (12): realm, bedroom, neoncity, phone, casino, heist, lounge, coders, command_center, warzone, gallery, tavern\n\n"
            "Registry: SKILL_REGISTRY singleton. Methods: all_tools(), get_pack_tools(pack), all_packs(), describe()\n\n"
            "Skills vs MCP Tools: @skill is for local LMStudio agents. @mcp.tool() is for Copilot/external. list_all_skills() MCP tool bridges both.",
            "document", "architecture", ["skills", "decorator", "registry", "packs"],
        ),
        (
            "Character and State System",
            "Characters have identity, stats, relationships, voice, and backstory.\n\n"
            "Components: CharacterRegistry + CharacterState + CharacterStateCoordinator + Database\n\n"
            "Stats:\n"
            "- 6 identity stats: mood, energy, inhibition, focus, role, engagement\n"
            "- 17 SSM stats: arousal, happiness, anger, affection, trust, comfort, etc.\n"
            "- 15 personality traits: warmth, curiosity, playfulness, assertiveness, etc.\n\n"
            "State Coordination: StateCoordinator.update() syncs changes to MCP tree. All stat changes flow through governance framework.\n\n"
            "Database Characters: lola, viktor, aria, frankie, mira are always present (seeded in DB).",
            "document", "architecture", ["characters", "stats", "state", "personality"],
        ),
        (
            "Dialog and Conversation System",
            "DialogSystem manages conversation threading, dialog trees, and conversation heat.\n\n"
            "Components:\n"
            "- DialogTree: branching conversation structures with conditions\n"
            "- ConversationState: tracks current dialog position per character\n"
            "- ConversationHeat: escalation tracking (cold -> warm -> hot -> blazing)\n\n"
            "Key Features:\n"
            "- Conversation forking via fork_conversation()\n"
            "- Heat-based content escalation\n"
            "- Dialog directives (must_include, style enforcement)\n"
            "- Cross-scene messaging via cross_scene_message()\n"
            "- Conversation history tracking and search\n\n"
            "Integration: Wire DialogSystem for conversation tracking in each scene. Use get_dialog_system() singleton.",
            "document", "architecture", ["dialog", "conversation", "heat", "threading"],
        ),
        (
            "Nexus KMS Integration",
            "Nexus is the central knowledge backbone at port 8700.\n\n"
            "Capabilities: Knowledge CRUD, Smart Q&A (3-tier: cache -> FTS5 -> NLM), Research sessions, YouTube ingestion, "
            "Prompt versioning, Rules engine, Session tracking\n\n"
            "Q&A Pipeline:\n"
            "1. Q&A Cache (instant) — if confidence >= 0.7, return cached\n"
            "2. FTS5 Search (fast) — synthesize from entries, store if >= 0.5\n"
            "3. NLM Research (deep) — NotebookLM backed research\n\n"
            "NexusClient API:\n"
            "- client.search(query), client.ask(question, depth)\n"
            "- client.add_entry(title, content, content_type, category, tags)\n"
            "- client.research(question) -> converse(id, msg) -> finish_research(id)\n"
            "- client.store_prompt(name, content, category), client.get_rules(scope)\n\n"
            "Content Types: note, code, prompt, document, transcript, research, memory, history, plan\n"
            "Categories: architecture, api, debugging, testing, performance, training, system, development",
            "document", "architecture", ["nexus", "knowledge", "qa", "research"],
        ),
        (
            "Configuration System",
            "CosySim uses hierarchical YAML config with dot-notation access.\n\n"
            "Hierarchy: default.yaml (base) -> development.yaml (overrides) -> production.yaml (prod)\n"
            "Access: get_config().get('dot.path', default_value)\n\n"
            "Key Config Sections:\n"
            "- system: debug, log_level, version\n"
            "- lmstudio: host, port, load_mode (concurrent|jit|jit_ttl), models, vram_cap_mb\n"
            "- scenes: per-scene config (port, features, max_characters)\n"
            "- agent_profiles: big/small/router model parameters\n"
            "- framework: state_persistence, interceptors\n"
            "- comms: interceptor list and priorities\n\n"
            "Files: config/default.yaml, config/development.yaml, config/voices.yaml, config/skill_manifests.yaml, config/mcp.json\n\n"
            "Rules: Never hardcode ports/paths/models. Always provide defaults in get() calls.",
            "document", "architecture", ["config", "yaml", "settings"],
        ),
        (
            "Testing Guide",
            "pytest 9.0+ with plain assert statements. 1,927 tests across 70+ files.\n\n"
            "Command: python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py\n\n"
            "Fixtures: temp_db(tmp_path), event_chain(temp_db), mock_config()\n\n"
            "Rules:\n"
            "- No unittest.TestCase — use pytest fixtures\n"
            "- Mock ALL external services (LMStudio, ComfyUI, TTS, Nexus)\n"
            "- Mock at client boundary, not deep internals\n"
            "- Use tmp_path for file I/O tests\n"
            "- Test both happy path and edge cases\n\n"
            "Structure: Arrange -> Act -> Assert pattern. Group related tests in same file.\n"
            "Coverage: Every scene has a test file. Every skill pack has tests. Database-seeded characters always present.",
            "document", "development", ["testing", "pytest", "fixtures", "mocking"],
        ),
        (
            "Copilot CLI Integration Architecture",
            "CosySim has comprehensive Copilot CLI integration across 3 layers.\n\n"
            "Layer 1 — Global Identity:\n"
            "- ~/.copilot/copilot-instructions.md — system role, environment, Nexus-first workflow\n"
            "- ~/.config/copilot/shared-rules/ — security, architecture, git workflow (3 files)\n\n"
            "Layer 2 — Repo Level:\n"
            "- .github/copilot-instructions.md — project overview, 124 MCP tools, critical rules\n\n"
            "Layer 3 — Path-Specific (9 files):\n"
            "- python.instructions.md, scenes.instructions.md, mcp-framework.instructions.md\n"
            "- nexus.instructions.md, testing.instructions.md, lmstudio.instructions.md\n"
            "- config.instructions.md, frontend.instructions.md, deployment.instructions.md\n\n"
            "10 Custom Agents: Copilot Workflow (Opus), Scene Builder, Debugger, Auditor, "
            "Skill Developer, Test Writer, Doc Writer, Codebase Navigator, Nexus Researcher, System Architect\n\n"
            "Session Hooks: .github/hooks/session-logger/ logs start/end/prompt to Nexus",
            "document", "infrastructure", ["copilot", "agents", "instructions", "harness"],
        ),
        (
            "TTS Voice Generation System",
            "Qwen3-TTS FastAPI server on port 8600 with FastMCP.\n\n"
            "Features: Voice design strings (natural language descriptions), 6 built-in presets "
            "(flirty_female, confident_male, ai_narrator, etc.), casting system for character voice assignment, "
            "sentence-level chunking for long-form audio, voice persistence across sessions.\n\n"
            "Config: config/voices.yaml with 11 presets. Skills: tts pack with generate/cast/design voice skills.",
            "note", "infrastructure", ["tts", "voice", "qwen3"],
        ),
        (
            "EventChain Audit Logging",
            "EventChain provides immutable audit trail for all interactions.\n\n"
            "Every agent interaction, game action, and state change logs to EventChain.\n"
            "Storage: SQLite database with tree-structured events (parent/child).\n"
            "Access: MCP resources via chain://chain_id. Tools: log_event, get_chain_events.\n"
            "Admin: EventChain browser in admin panel with tree view, filters, JSON drill-down.",
            "note", "architecture", ["eventchain", "audit", "logging"],
        ),
        (
            "Key Singletons Reference",
            "CosySim key import paths for framework singletons:\n\n"
            "from engine.config import get_config              # ConfigManager\n"
            "from engine.mcp import get_framework              # MCPFramework\n"
            "from engine.mcp import get_character_registry      # CharacterRegistry\n"
            "from engine.mcp import get_dialog_system           # DialogSystem\n"
            "from engine.mcp import get_rules_engine            # SceneRulesEngine\n"
            "from engine.mcp import get_scene_state_manager     # SceneStateManager\n"
            "from engine.mcp import get_governor                # AgentGovernor\n"
            "from engine.mcp import get_router                  # AgentRouter\n"
            "from engine.scenes.base_scene import BaseScene     # Scene base class\n"
            "from engine.skills.skill import skill              # @skill decorator\n"
            "from engine.nexus.client import get_nexus_client   # Nexus KMS client\n"
            "from engine.lmstudio.orchestrator import get_orchestrator  # Multi-model orchestrator",
            "code", "development", ["singletons", "imports", "api"],
        ),
        (
            "Service Port Map",
            "All CosySim ecosystem services and their ports:\n\n"
            "LMStudio: 1234 (LLM inference API)\n"
            "NotebookLM MCP: 3000 (NLM research)\n"
            "CosySim Scenes: 5555-5567 (13 game + utility scenes)\n"
            "ComfyUI: 8188 (image/video generation)\n"
            "Hub: 8500, Dashboard: 8501, Admin: 8502, Assets: 8503, Creator: 8504\n"
            "TTS: 8600, WebBridge: 8601\n"
            "Nexus API: 8700, Nexus Dashboard: 8701",
            "note", "infrastructure", ["ports", "services", "network"],
        ),
    ]
    return entries


# ── Seed: Q&A Pairs ───────────────────────────────────────────────────

def seed_qa() -> int:
    """Seed Nexus with comprehensive Q&A pairs."""
    pairs = _get_qa_pairs()
    created = 0
    for question, answer, category, tags in pairs:
        if add_qa(question, answer, category, tags):
            created += 1
    logger.info("  Q&A: %s/%s pairs created", created, len(pairs))
    return created


def _get_qa_pairs() -> list[tuple[str, str, str, list[str]]]:
    """Return all Q&A pairs to seed."""
    return [
        # Architecture
        (
            "What is CosySim?",
            "CosySim is a multi-scene AI simulation framework (v0.51b) that orchestrates virtual agents across 18 interactive scenes. "
            "It uses MCPFramework for state management, LMStudio v1 for inference, InterceptorPipeline for agent governance, "
            "and Nexus KMS for knowledge management. Built in Python 3.10+ with Flask scenes.",
            "architecture", ["cosysim", "overview"],
        ),
        (
            "How does the interceptor pipeline work?",
            "InterceptorPipeline wraps agent LLM calls with ordered pre/post hooks. Each interceptor has a priority (lower=earlier). "
            "pre_call() modifies system prompts/messages before LLM. post_call() processes output after LLM. "
            "Key interceptors: CharacterRegistry (8), RouterMessage (10), DialogDirective (12), SkillAwareness (30), "
            "GameRules (40), PersonalityGuard (50), PolicyEnforcer (60), ResponseShaper (80), ActivityLogger (90). "
            "Register via config/default.yaml under comms.interceptors.",
            "architecture", ["interceptor", "pipeline"],
        ),
        (
            "How does state management work in CosySim?",
            "All mutable state flows through the MCPFramework tree — never local Python variables. "
            "MCPSceneNode holds per-scene state, MCPCharacterNode holds per-character state (stats, inventory, relationships). "
            "StateCoordinator.update() syncs changes to the tree. Access via get_framework() singleton. "
            "State auto-persists if framework.state_persistence enabled in config.",
            "architecture", ["state", "mcp"],
        ),
        (
            "How does inference routing work?",
            "InferenceOrchestrator is the unified facade. It selects model tier based on task_type + priority: "
            "gpu_primary (T1) for reasoning/dialog, cpu_utility (T2) for background tasks, cpu_router (T3) for classification. "
            "ModelManager handles loading (CONCURRENT/JIT/JIT_TTL modes). InferenceRouter queues requests by priority: "
            "REALTIME > INTERACTIVE > BACKGROUND > BATCH. Usage: get_orchestrator().infer(agent_id, messages, task_type, priority).",
            "architecture", ["inference", "orchestrator", "routing"],
        ),
        (
            "How do I create a new scene?",
            "1. Create content/scenes/{name}/ directory\n"
            "2. Add __init__.py with class inheriting BaseScene\n"
            "3. Set SCENE_METADATA = dict(name='x', port=NNNN, type='game')\n"
            "4. Override start(), stop(), get_plugin_info()\n"
            "5. Create {name}_skills.py with @skill(pack='{name}') functions\n"
            "6. Add templates/ and static/ directories\n"
            "7. Register MCP nodes in start(): fw.get_or_create('scenes.{name}', MCPSceneNode)\n"
            "8. Wire DialogSystem and EventChain\n"
            "9. Add tests in tests/test_{name}.py",
            "development", ["scenes", "howto"],
        ),
        (
            "How do I add a new skill pack?",
            "1. Create engine/skills/builtin/{name}_skills.py (or content/scenes/{scene}/{scene}_skills.py for scene skills)\n"
            "2. Use @skill(pack='{name}', description='...', category='GAME') decorator on functions\n"
            "3. Skills must return string results for LLM consumption\n"
            "4. Access running scene via BaseScene.get_active_scene('{name}')\n"
            "5. Import the skills module in scene __init__.py to register\n"
            "6. Add tests covering happy path and edge cases\n"
            "7. Update config/skill_manifests.yaml if needed",
            "development", ["skills", "howto"],
        ),
        (
            "How do I use Nexus in my code?",
            "Python API:\n"
            "from engine.nexus.client import get_nexus_client\n"
            "client = get_nexus_client()\n"
            "results = client.search('query')  # Full-text search\n"
            "answer = client.ask('question')   # Smart Q&A (cache -> FTS -> NLM)\n"
            "client.add_entry('Title', 'content', content_type='note', category='dev')\n\n"
            "CLI: python -m engine.nexus.cli search 'query'\n"
            "MCP: nexus_search('query'), nexus_ask('question'), nexus_add('title', 'content')",
            "development", ["nexus", "howto"],
        ),
        (
            "How do I run CosySim tests?",
            "python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py\n\n"
            "Single file: python -m pytest tests/test_bedroom_game.py -v\n"
            "By marker: python -m pytest tests/ -m unit\n\n"
            "Rules: Use plain assert (no unittest.TestCase), mock all external services, "
            "use tmp_path for file I/O, use fixtures from conftest.py (temp_db, event_chain, mock_config).",
            "testing", ["pytest", "howto"],
        ),
        (
            "How do I configure LMStudio models?",
            "In config/default.yaml under lmstudio:\n"
            "- host: localhost, port: 1234\n"
            "- load_mode: concurrent|jit|jit_ttl\n"
            "- models.primary: model key for main inference\n"
            "- models.utility: model key for background tasks\n"
            "- models.router: model key for classification\n"
            "- vram_cap_mb: 11500 (VRAM budget)\n"
            "- concurrent_slots: 2 (parallel requests)\n\n"
            "Agent profiles in agent_profiles.big/small/router control context length, temperature, max tokens per tier.",
            "development", ["lmstudio", "config"],
        ),
        (
            "What MCP tools are available?",
            "124 tools total:\n"
            "- 14 Nexus bridge: nexus_search, nexus_ask, nexus_add, nexus_add_qa, nexus_get_rules, nexus_store_prompt, "
            "nexus_get_prompts, nexus_research, nexus_converse, nexus_finish_research, nexus_import_youtube, nexus_log_session, nexus_status, nexus_list_plugins\n"
            "- 3 discovery: list_all_skills, get_skill_info, system_status\n"
            "- 107 core: memory (search_memory, store_memory), character (9 tools), game (6 tools), "
            "dialog (5 tools), wardrobe (6 tools), scene (8 tools), mood/relationship (4 tools), "
            "media (3 tools), timers (7 tools), lounge (6 tools), utility (8 tools)",
            "infrastructure", ["mcp", "tools"],
        ),
        (
            "How do I start CosySim services?",
            "Start order:\n"
            "1. LMStudio (external — must be running on :1234)\n"
            "2. ComfyUI (external — if image generation needed, :8188)\n"
            "3. Nexus KMS: cd C:\\Files\\Nexus && python -m nexus\n"
            "4. CosySim TTS: python start_servers.ps1\n"
            "5. CosySim Scenes: python launcher.py --scene bedroom\n"
            "6. CosySim Hub: python launcher.py --hub\n\n"
            "Health checks: LMStudio GET :1234/api/v1/models, Nexus GET :8700/api/health, Scene GET :port/health",
            "infrastructure", ["startup", "deployment"],
        ),
        (
            "How do I write an interceptor?",
            "1. Create class inheriting InterceptorBase\n"
            "2. Implement pre_call(self, request, context) — modify request before LLM\n"
            "3. Implement post_call(self, response, context) — modify response after LLM\n"
            "4. Register in config/default.yaml under comms.interceptors with priority number\n"
            "5. Lower priority = runs earlier. Typical range: 1-100\n\n"
            "Important: Pass governance_context kwarg through CharacterAgent.reply() -> VirtualAgent.reply() -> build_request(). "
            "Without this, interceptor injections are silently lost.",
            "development", ["interceptor", "howto"],
        ),
        (
            "How does the Copilot harness work?",
            "3-tier instruction system:\n"
            "1. Global (~/.copilot/copilot-instructions.md): identity, environment, Nexus-first workflow\n"
            "2. Repo (.github/copilot-instructions.md): project overview, MCP tools, critical rules\n"
            "3. Path-specific (.github/instructions/*.md): 9 files auto-applied by glob pattern\n\n"
            "10 custom agents in .github/agents/*.agent.md\n"
            "Session hooks in .github/hooks/session-logger/ log to Nexus\n"
            "MCP server in .vscode/mcp.json provides 124 tools to Copilot",
            "infrastructure", ["copilot", "harness"],
        ),
        (
            "What are the Python coding conventions?",
            "- Absolute imports only: from engine.config import get_config\n"
            "- Type hints on all function signatures\n"
            "- Google-style docstrings with Args, Returns, Raises\n"
            "- 4 spaces, double quotes, f-strings\n"
            "- Use logging.getLogger(__name__), never print()\n"
            "- Config via get_config().get('dot.path', default)\n"
            "- Never hardcode ports, paths, model names\n"
            "- Group imports: stdlib -> third-party -> engine -> content -> local",
            "development", ["python", "conventions"],
        ),
        (
            "How does conversation threading work?",
            "LMStudio v1 uses stateful conversations with store:true + previous_response_id.\n"
            "ConversationManager creates conversations on first infer_stream() call.\n"
            "Each response updates response_id for threading.\n"
            "Supports branching via branch_at(turn) using recorded response_id history.\n"
            "send_stateless() uses store:false for one-off queries.\n"
            "DialogSystem tracks conversation state per character with heat levels (cold -> warm -> hot -> blazing).",
            "architecture", ["conversation", "threading", "lmstudio"],
        ),
        (
            "How do I search Nexus knowledge?",
            "Three methods:\n"
            "1. Python: get_nexus_client().search('query')\n"
            "2. CLI: python -m engine.nexus.cli search 'query'\n"
            "3. MCP tool: nexus_search('query')\n\n"
            "For smart Q&A (checks cache, then FTS, then NLM): nexus_ask('question', depth='auto')\n"
            "depth='shallow' skips NLM, depth='deep' forces NLM research.\n\n"
            "FTS5 queries must use _sanitize_fts_query() which strips special chars and joins words with OR.",
            "development", ["nexus", "search", "howto"],
        ),
        (
            "What are the database-seeded characters?",
            "Five characters are always present in the database: lola, viktor, aria, frankie, mira.\n"
            "Each has personality traits, mood, energy, stats, voice style, backstory, and appearance.\n"
            "Access via CharacterRegistry singleton: get_character_registry().\n"
            "Characters exist across all scenes and maintain persistent state.",
            "development", ["characters", "database"],
        ),
        (
            "How does the governance framework work?",
            "All 11+ scenes use the governance framework:\n"
            "1. build_governance_context() generates context from rules, character state, scene state\n"
            "2. Context is prepended to agent system prompt via interceptors\n"
            "3. StateCoordinator.update() syncs stat changes to MCP tree\n"
            "Pattern: _get_governance_context() helper -> prepend to system prompt -> coordinator sync at stat change sites.\n"
            "AgentGovernor orchestrates the full flow.",
            "architecture", ["governance", "agents"],
        ),
        (
            "How do I commit code changes?",
            "Use conventional commits with imperative mood:\n"
            "feat: add bedroom mini-game mechanic\n"
            "fix: correct stat decay timer\n"
            "docs: update SCENES.md\n"
            "test: add casino edge case tests\n"
            "chore: remove stale config\n"
            "refactor: extract dialog system\n\n"
            "Always include: Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>\n"
            "Use git --no-pager always. Work on master branch.",
            "development", ["git", "commits"],
        ),
        (
            "What is the Nexus-first workflow?",
            "Before ANY task:\n"
            "1. nexus_search('topic') — check existing knowledge\n"
            "2. nexus_get_rules('scope') — get governance rules\n"
            "3. nexus_get_prompts('category') — get stored prompts\n\n"
            "During work:\n"
            "4. list_all_skills() — discover available tools\n"
            "5. system_status() — check system health\n"
            "6. nexus_log_session('CosySim') — track session\n\n"
            "After completing:\n"
            "7. nexus_add('Decision: ...', content, 'decision') — store decisions\n"
            "8. nexus_add_qa('How does X?', '...') — cache Q&A\n"
            "9. nexus_store_prompt('name', content) — version prompts",
            "development", ["nexus", "workflow"],
        ),
        (
            "How does the skill decorator work?",
            "@skill(pack='name', description='LLM-facing desc', category='GAME', cooldown=5.0, cost=1.0, tags=['tag1'])\n"
            "def my_skill(target: str, amount: int = 1) -> str:\n"
            "    return 'Result string'\n\n"
            "Categories: COMMUNICATION, MEMORY, MEDIA, GAME, SOCIAL, ENVIRONMENT, SYSTEM, NARRATIVE\n"
            "Skills register in SKILL_REGISTRY singleton on import.\n"
            "Skills must return string results for LLM consumption.\n"
            "Access running scene: BaseScene.get_active_scene('scene_name')",
            "development", ["skills", "decorator"],
        ),
    ]


# ── Seed: Governance Rules ─────────────────────────────────────────────

def seed_rules() -> int:
    """Seed Nexus with governance rules."""
    rules = [
        ("global", "convention", "All Python files", "Use absolute imports, type hints, Google docstrings, logging.getLogger(__name__)", 10),
        ("global", "convention", "State management", "All mutable state must flow through MCPFramework tree — never local variables", 10),
        ("global", "convention", "Configuration access", "Use get_config().get('dot.path', default) — never hardcode ports/paths/models", 10),
        ("global", "convention", "Error output", "Use logging.getLogger(__name__) — never print()", 10),
        ("global", "security", "Credentials", "Never hardcode API keys, tokens, passwords in source code", 5),
        ("global", "security", "SQL queries", "Use parameterized queries — never string concatenation", 5),
        ("global", "quality", "Testing requirement", "Every new module needs tests. Mock all external services.", 20),
        ("global", "quality", "Git commits", "Use conventional commits (feat/fix/docs/test/chore/refactor) with Copilot co-author trailer", 20),
        ("scene:*", "convention", "Scene structure", "Inherit BaseScene, set SCENE_METADATA, override start/stop/get_plugin_info", 10),
        ("scene:*", "convention", "Scene skills", "Create {name}_skills.py with @skill(pack='{name}') — import in __init__.py", 10),
        ("scene:*", "convention", "MCP wiring", "Register scene node in start(): fw.get_or_create('scenes.{name}', MCPSceneNode)", 10),
        ("agent:*", "governance", "Interceptor pipeline", "Always pass governance_context through agent.reply() chain — interceptor injections are lost without it", 5),
        ("agent:*", "governance", "Skill access", "Agents must use @skill functions for tool calling — never direct API access", 15),
        ("testing", "convention", "Test framework", "pytest with plain assert, no unittest.TestCase. Use fixtures from conftest.py", 10),
        ("testing", "convention", "External services", "Mock ALL external services (LMStudio, ComfyUI, TTS, Nexus) at client boundary", 5),
        ("testing", "convention", "Test structure", "Arrange -> Act -> Assert pattern. Group related tests in same file", 15),
    ]
    created = 0
    for scope, rtype, condition, action, priority in rules:
        if add_rule(scope, rtype, condition, action, priority):
            created += 1
    logger.info("  Rules: %s/%s rules created", created, len(rules))
    return created


# ── Seed: Coding Conventions ──────────────────────────────────────────

def seed_conventions() -> int:
    """Seed Nexus with coding convention entries."""
    conventions = [
        (
            "Python Import Conventions",
            "Group imports in this order:\n"
            "1. Standard library (os, sys, json, logging)\n"
            "2. Third-party (flask, requests, pydantic)\n"
            "3. Engine modules (from engine.config import get_config)\n"
            "4. Content modules (from content.scenes...)\n"
            "5. Local/relative (never — always use absolute imports)\n\n"
            "Always absolute: from engine.config import get_config\n"
            "Never relative: from .module import X",
            "code", "development", ["python", "imports", "conventions"],
        ),
        (
            "Error Handling Patterns",
            "- Use try/except with specific exceptions\n"
            "- Log errors with logger.error() or logger.exception()\n"
            "- Never silently swallow exceptions\n"
            "- Return structured error responses from API endpoints\n"
            "- Use EventChain for audit-logging errors\n"
            "- In skills, return error string for LLM consumption\n"
            "- In MCP tools, return JSON with error key",
            "code", "development", ["error-handling", "conventions"],
        ),
        (
            "State Management Patterns",
            "ALWAYS:\n"
            "- Sync state to MCPFramework tree\n"
            "- Use StateCoordinator.update() for stat changes\n"
            "- Access via get_framework() singleton\n"
            "- Use MCPTimer for scheduled events\n\n"
            "NEVER:\n"
            "- Store game state in local Python variables\n"
            "- Use class-level mutable state without MCP sync\n"
            "- Modify character state without governance flow",
            "code", "development", ["state", "mcp", "conventions"],
        ),
        (
            "Skill Development Patterns",
            "Template:\n"
            "@skill(pack='name', description='What it does', category='GAME')\n"
            "def skill_name(param: str, amount: int = 1) -> str:\n"
            "    scene = BaseScene.get_active_scene('name')\n"
            "    # ... do work ...\n"
            "    return 'Result for LLM'\n\n"
            "Rules:\n"
            "- Always return string (LLM reads it)\n"
            "- Use type hints on all parameters\n"
            "- Set appropriate cooldown/cost\n"
            "- Import in scene __init__.py to register",
            "code", "development", ["skills", "patterns"],
        ),
    ]
    created = 0
    for title, content, ct, cat, tags in conventions:
        if add_entry(title, content, ct, cat, tags):
            created += 1
    logger.info("  Conventions: %s/%s entries created", created, len(conventions))
    return created


# ── Seed: Agent Prompts ────────────────────────────────────────────────

def seed_prompts() -> int:
    """Seed Nexus with agent prompt fragments and system prompts."""
    prompts = [
        (
            "CosySim Agent Base System Prompt",
            "You are a virtual character in CosySim, an AI simulation framework. "
            "You have a personality, emotions, relationships, and goals. "
            "Stay in character at all times. Use your available skills to interact with the world. "
            "Your responses should reflect your current mood, energy, and personality traits. "
            "Never break the fourth wall or acknowledge being an AI unless your character would do so.\n\n"
            "Available context: Your character state (mood, energy, stats) is injected via the interceptor pipeline. "
            "Game rules are injected by GameRulesInterceptor. Your skills are listed by SkillAwarenessInterceptor.\n\n"
            "Response format: Include mood/action tags as appropriate: [MOOD:happy], [ACTION:waves], [STAT:trust+5].",
            "prompt", "system", ["agent", "base-prompt", "character"],
        ),
        (
            "Governance Context Template",
            "GOVERNANCE CONTEXT:\n"
            "Scene: {scene_name}\n"
            "Character: {character_name}\n"
            "Mood: {mood} | Energy: {energy} | Engagement: {engagement}\n"
            "Conversation Heat: {heat_level}\n"
            "Active Game: {game_name or 'none'}\n"
            "Relationship with user: {relationship_level}\n\n"
            "RULES:\n"
            "{injected_rules}\n\n"
            "AVAILABLE SKILLS:\n"
            "{skill_list}",
            "prompt", "system", ["governance", "template", "interceptor"],
        ),
        (
            "Copilot Workflow Agent Prompt",
            "You are the master workflow agent for CosySim. You have access to ALL system tools via MCP.\n\n"
            "NEXUS-FIRST WORKFLOW:\n"
            "1. Before ANY task: nexus_search, nexus_get_rules, nexus_get_prompts\n"
            "2. During work: list_all_skills, system_status, nexus_log_session\n"
            "3. After completing: nexus_add (decisions), nexus_add_qa (Q&A), nexus_store_prompt\n\n"
            "You have 124 MCP tools: 14 Nexus bridge, 3 discovery, 107 core (memory, characters, games, narrative, dialog, wardrobe, mood, images, conversations).",
            "prompt", "agents", ["copilot-workflow", "master-agent"],
        ),
        (
            "Scene Builder Agent Prompt",
            "You scaffold new CosySim scenes from scratch. Follow this exact structure:\n"
            "1. Create content/scenes/{name}/ with __init__.py, {name}_skills.py, templates/, static/\n"
            "2. Scene class inherits BaseScene with SCENE_METADATA\n"
            "3. Override start() — register MCP nodes, wire DialogSystem, start Flask\n"
            "4. Override stop() — persist state, cleanup\n"
            "5. Create @skill(pack='{name}') functions\n"
            "6. Add tests in tests/test_{name}.py\n"
            "7. Update config entries if needed",
            "prompt", "agents", ["scene-builder"],
        ),
        (
            "Nexus Researcher Agent Prompt",
            "You are a research agent with access to Nexus Knowledge System.\n\n"
            "Workflow:\n"
            "1. Check existing: nexus_ask(question, depth='shallow') then nexus_search(terms)\n"
            "2. Research if needed: nexus_research(question) -> nexus_converse(id, followup) -> nexus_finish_research(id)\n"
            "3. Store findings: nexus_add(title, content, 'document', 'architecture')\n"
            "4. Import external: nexus_import_youtube(url)\n\n"
            "Always search before researching. Use specific questions. Always finish research sessions.",
            "prompt", "agents", ["nexus-researcher"],
        ),
    ]
    created = 0
    for title, content, ct, cat, tags in prompts:
        if add_entry(title, content, ct, cat, tags):
            created += 1
    logger.info("  Prompts: %s/%s entries created", created, len(prompts))
    return created


# ── Main ───────────────────────────────────────────────────────────────

def seed_all() -> dict[str, int]:
    """Run all seeders."""
    results = {}
    logger.info("Seeding Nexus knowledge base...")
    results["docs"] = seed_docs()
    results["qa"] = seed_qa()
    results["rules"] = seed_rules()
    results["prompts"] = seed_prompts()
    results["conventions"] = seed_conventions()
    total = sum(results.values())
    logger.info("\nTotal: %s items created", total)
    return results


def main():
    """CLI entry point."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) < 2:
        target = "all"
    else:
        target = sys.argv[1].lower()

    seeders = {
        "docs": seed_docs,
        "qa": seed_qa,
        "rules": seed_rules,
        "prompts": seed_prompts,
        "conventions": seed_conventions,
        "all": seed_all,
    }

    seeder = seeders.get(target)
    if not seeder:
        logger.error("Unknown target: %s", target)
        logger.error("Available: %s", ", ".join(seeders.keys()))
        sys.exit(1)

    seeder()


if __name__ == "__main__":
    main()
