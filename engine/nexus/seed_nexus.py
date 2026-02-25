"""
seed_nexus.py — Populate Nexus with CosySim project knowledge.

Imports architecture docs, agent profiles, design decisions, and Q&A pairs
into the Nexus knowledge system for agent and developer use.

Usage:
    python engine/nexus/seed_nexus.py              # seed all
    python engine/nexus/seed_nexus.py --profiles    # only agent profiles
    python engine/nexus/seed_nexus.py --qa          # only Q&A pairs
    python engine/nexus/seed_nexus.py --docs        # only architecture docs
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.error
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
NEXUS_URL = "http://localhost:8700"


def _post(path: str, data: dict) -> dict | None:
    try:
        url = f"{NEXUS_URL}{path}"
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        logger.error("Nexus unavailable at %s: %s", NEXUS_URL, e)
        return None
    except Exception as e:
        logger.error("Failed to post to %s: %s", path, e)
        return None


def _get(path: str) -> dict | None:
    try:
        url = f"{NEXUS_URL}{path}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


# ── Agent Profiles ─────────────────────────────────────────────────────

AGENT_PROFILES = [
    {
        "title": "Agent Profile: Lola",
        "content": (
            "Name: Lola | Role: Primary companion\n"
            "Personality: Warm, playful, emotionally intelligent, occasionally sarcastic\n"
            "Speech Style: Casual, uses emojis, contractions, playful teasing\n"
            "Interests: Art, music, cooking, stargazing, deep conversations\n"
            "Quirks: Names her houseplants, collects vintage postcards, hums when thinking\n"
            "Backstory: Creative soul who values genuine connection over superficial charm\n"
            "Stats: confidence=7, wit=8, warmth=9, energy=7, flirtiness=6"
        ),
        "tags": ["agent", "character", "lola", "companion"],
        "category": "characters",
    },
    {
        "title": "Agent Profile: Viktor",
        "content": (
            "Name: Viktor | Role: Intellectual rival / advisor\n"
            "Personality: Sharp, analytical, dry wit, secretly caring\n"
            "Speech Style: Formal, precise vocabulary, occasional deadpan humor\n"
            "Interests: Chess, philosophy, architecture, classical music\n"
            "Quirks: Adjusts glasses when nervous, quotes obscure philosophers\n"
            "Backstory: Former academic who values logic but is learning to appreciate emotion\n"
            "Stats: confidence=8, wit=9, warmth=4, energy=5, intellect=9"
        ),
        "tags": ["agent", "character", "viktor", "advisor"],
        "category": "characters",
    },
    {
        "title": "Agent Profile: Aria",
        "content": (
            "Name: Aria | Role: Creative muse / artist\n"
            "Personality: Dreamy, passionate, impulsive, deeply empathetic\n"
            "Speech Style: Poetic, metaphorical, stream-of-consciousness\n"
            "Interests: Painting, poetry, nature, mythology, dreams\n"
            "Quirks: Sees colors in music, paints during conversations\n"
            "Backstory: Free spirit who communicates through art as much as words\n"
            "Stats: confidence=5, wit=6, warmth=8, energy=8, creativity=10"
        ),
        "tags": ["agent", "character", "aria", "creative"],
        "category": "characters",
    },
    {
        "title": "Agent Profile: Frankie",
        "content": (
            "Name: Frankie | Role: Streetwise hustler / dealer\n"
            "Personality: Charming, quick-witted, loyal to friends, cunning\n"
            "Speech Style: Slang-heavy, fast-talking, uses card/gambling metaphors\n"
            "Interests: Poker, pool, street food, people-watching, old movies\n"
            "Quirks: Always fidgeting with a coin, reads people's tells\n"
            "Backstory: Grew up on the streets, learned to read people before books\n"
            "Stats: confidence=8, wit=8, warmth=5, energy=7, street_smarts=9"
        ),
        "tags": ["agent", "character", "frankie", "dealer"],
        "category": "characters",
    },
    {
        "title": "Agent Profile: Mira",
        "content": (
            "Name: Mira | Role: Mysterious observer / fortune teller\n"
            "Personality: Enigmatic, perceptive, calm, occasionally unsettling\n"
            "Speech Style: Cryptic, uses riddles, speaks in third person sometimes\n"
            "Interests: Tarot, astronomy, psychology, ancient history\n"
            "Quirks: Finishes other people's sentences, knows things she shouldn't\n"
            "Backstory: Nobody knows where Mira came from. She just appeared one day.\n"
            "Stats: confidence=7, wit=7, warmth=3, energy=4, mystery=10"
        ),
        "tags": ["agent", "character", "mira", "fortune_teller"],
        "category": "characters",
    },
]


# ── Design Decisions (Q&A) ────────────────────────────────────────────

QA_PAIRS = [
    {
        "question": "What is the MCP framework and why does CosySim use it?",
        "answer": (
            "The Model Context Protocol (MCP) framework is CosySim's core architecture for agent-tool "
            "interaction. It allows LLM agents to call tools during inference — for memory retrieval, "
            "media generation, game mechanics, and state mutation. CosySim uses MCP because it enables "
            "structured agent behavior without hardcoded rules: agents discover capabilities through "
            "tool descriptions and self-select appropriate actions. The 25-interceptor governance "
            "pipeline wraps every inference call, injecting context and enforcing constraints."
        ),
        "tags": ["architecture", "mcp", "framework", "design"],
        "category": "architecture",
    },
    {
        "question": "How does the interceptor pipeline work in CosySim?",
        "answer": (
            "The interceptor pipeline is an ordered chain of InterceptorBase subclasses that modify "
            "prompts before inference (pre-call) and process responses after inference (post-call). "
            "Pre-call interceptors inject: character personality, mood state, game rules, scene context, "
            "conversation heat, and governance directives. Post-call interceptors extract: mood tags, "
            "stat changes, action tags, image requests, and validate content. Interceptors can be "
            "scene-specific (applicable_scenes field) and are cached with TTL for performance."
        ),
        "tags": ["interceptors", "pipeline", "governance", "architecture"],
        "category": "architecture",
    },
    {
        "question": "How do scenes work in CosySim?",
        "answer": (
            "Each scene is a self-contained Flask web application that inherits from BaseScene and "
            "MCPSceneMixin. A scene has: its own port, agents, state machine (SceneStateManager), "
            "rules engine, MCP skills, and frontend. Scenes register with the MCPFramework on init "
            "and expose /api/scene/info, /api/health, and scene-specific routes. The launcher.py "
            "discovers and starts scenes. Each scene defines SCENE_METADATA with its configuration."
        ),
        "tags": ["scenes", "basescene", "architecture"],
        "category": "architecture",
    },
    {
        "question": "How does CosySim integrate with LMStudio?",
        "answer": (
            "CosySim uses the LMStudio v1 REST API via LMSClient (engine/lmstudio/lms_client.py). "
            "Key features: stateful conversations with response_id chaining, SSE streaming with typed "
            "events, store=True/False for conversation persistence, conversation branching via fork(), "
            "structured output with JSON schemas, MCP ephemeral tool integrations, and speculative "
            "decoding. The InferenceConfig controls temperature, tokens, and model selection."
        ),
        "tags": ["lmstudio", "inference", "api", "integration"],
        "category": "architecture",
    },
    {
        "question": "What is Nexus and how does it integrate with CosySim?",
        "answer": (
            "Nexus is a standalone knowledge management system with a 3-layer database: NLM Mirror "
            "(NotebookLM sync), Ground Truth (immutable versioned records), and Working Layer (mutable "
            "searchable entries). CosySim accesses Nexus via NexusClient (HTTP) and nexus_skills "
            "(16 MCP skills). Key features: Q&A distillation cache, Research Manager (Q&A→FTS5→NLM), "
            "YouTube transcript ingestion, plugin hooks, and 37 MCP tools. Agents use nexus_ask for "
            "smart search and nexus_research for deep multi-turn investigation."
        ),
        "tags": ["nexus", "knowledge", "integration"],
        "category": "architecture",
    },
    {
        "question": "How do MCP skills work in CosySim?",
        "answer": (
            "Skills are Python functions decorated with @skill that get registered in the global "
            "SKILL_REGISTRY. Each skill has: name, description, parameters, cooldown, pack name. "
            "Skills are organized into packs (e.g., nexus_skills, coding_skills, memory_skills). "
            "The skills_server.py exposes them via MCP so LMStudio can call them during inference. "
            "Scene-specific skills live in content/scenes/{name}/{name}_skills.py and access the "
            "running scene via BaseScene.get_active_scene(name)."
        ),
        "tags": ["skills", "mcp", "registry", "tools"],
        "category": "architecture",
    },
    {
        "question": "What version numbering does CosySim use?",
        "answer": (
            "CosySim uses 0.xx versioning (not semver). Current: v0.50b. The version appears in "
            "config/default.yaml, pyproject.toml, launcher.py VERSION constant, and all scene "
            "SCENE_METADATA. Old 3.x numbering was retired at v0.50a. The Nexus companion project "
            "uses its own versioning (currently v1.3.1 / schema v3)."
        ),
        "tags": ["versioning", "convention"],
        "category": "conventions",
    },
    {
        "question": "How do I create a new scene in CosySim?",
        "answer": (
            "1. Create content/scenes/{name}/ directory with __init__.py\n"
            "2. Create {name}_scene.py inheriting BaseScene + MCPSceneMixin\n"
            "3. Define SCENE_METADATA dict with name, scene_id, description, version, port\n"
            "4. Implement _setup_routes() for Flask routes, _start_background() for async tasks\n"
            "5. Create {name}_skills.py with @skill functions in a pack\n"
            "6. Create {name}_state.py for scene-specific state management\n"
            "7. Create {name}_rules.py for rules engine integration\n"
            "8. Create templates/{name}.html for the frontend\n"
            "9. Register in launcher.py SCENE_CATALOGUE and config/default.yaml"
        ),
        "tags": ["howto", "scenes", "guide"],
        "category": "guides",
    },
    {
        "question": "How do I run the CosySim test suite?",
        "answer": (
            "python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py "
            "--ignore=tests/live_wire_test.py\n\n"
            "This runs all 1839 tests. The ignored files require live LMStudio connection. "
            "Tests use pytest with fixtures in conftest.py. Markers: @pytest.mark.slow, "
            "@pytest.mark.integration. Most tests mock external services."
        ),
        "tags": ["testing", "howto", "pytest"],
        "category": "guides",
    },
    {
        "question": "What is the conversation heat system?",
        "answer": (
            "ConversationHeat (scene_rules_engine.py) tracks engagement intensity on a 0-100 scale. "
            "Keywords in messages auto-bump heat, while time-based decay reduces it (2 points/min). "
            "ConversationVarietyInterceptor injects heat-level directives into system prompts to "
            "guide agent behavior: low heat → encourage variety/new topics, high heat → maintain "
            "intensity. This prevents repetitive conversations without hardcoded topic lists."
        ),
        "tags": ["conversation", "heat", "rules", "engagement"],
        "category": "architecture",
    },
]


# ── Architecture Documents ────────────────────────────────────────────

def _read_doc(rel_path: str) -> str | None:
    path = PROJECT_ROOT / rel_path
    if path.exists():
        try:
            return path.read_text(encoding="utf-8")[:8000]  # cap at 8KB
        except Exception:
            return None
    return None


DOCS_TO_SEED = [
    ("docs/ARCHITECTURE.md", "architecture", ["architecture", "overview", "design"]),
    ("docs/MCP_FRAMEWORK.md", "architecture", ["mcp", "framework", "skills", "interceptors"]),
    ("docs/SCENES.md", "guides", ["scenes", "guide", "howto"]),
    ("docs/SKILLS.md", "architecture", ["skills", "registry", "mcp"]),
    ("docs/LMSTUDIO.md", "integration", ["lmstudio", "api", "inference", "streaming"]),
    ("docs/CHARACTERS.md", "characters", ["characters", "agents", "personality"]),
    ("docs/CONFIGURATION.md", "guides", ["config", "yaml", "settings"]),
    ("docs/TESTING.md", "guides", ["testing", "pytest", "howto"]),
    ("docs/NEXUS_INTEGRATION.md", "integration", ["nexus", "knowledge", "api"]),
    ("docs/API.md", "architecture", ["api", "routes", "rest"]),
]


# ── Main Seeding Functions ─────────────────────────────────────────────

def seed_profiles():
    """Seed agent character profiles into Nexus."""
    logger.info("Seeding %d agent profiles...", len(AGENT_PROFILES))
    count = 0
    for profile in AGENT_PROFILES:
        result = _post("/api/entries", {
            "title": profile["title"],
            "content": profile["content"],
            "content_type": "profile",
            "tags": profile["tags"],
            "category": profile["category"],
        })
        if result:
            count += 1
            logger.info("  ✓ %s", profile["title"])
        else:
            logger.warning("  ✗ %s (failed)", profile["title"])
    logger.info("Seeded %d/%d profiles", count, len(AGENT_PROFILES))
    return count


def seed_qa():
    """Seed design decisions as Q&A pairs."""
    logger.info("Seeding %d Q&A pairs...", len(QA_PAIRS))
    count = 0
    for qa in QA_PAIRS:
        result = _post("/api/qa", {
            "question": qa["question"],
            "answer": qa["answer"],
            "source_type": "manual",
            "tags": qa["tags"],
            "category": qa["category"],
            "quality_score": 0.9,
        })
        if result:
            count += 1
            logger.info("  ✓ Q: %s", qa["question"][:60])
        else:
            logger.warning("  ✗ Q: %s (failed)", qa["question"][:60])
    logger.info("Seeded %d/%d Q&A pairs", count, len(QA_PAIRS))
    return count


def seed_docs():
    """Seed architecture documentation into Nexus."""
    logger.info("Seeding %d documentation files...", len(DOCS_TO_SEED))
    count = 0
    for rel_path, category, tags in DOCS_TO_SEED:
        content = _read_doc(rel_path)
        if not content:
            logger.warning("  ✗ %s (file not found or empty)", rel_path)
            continue
        title = Path(rel_path).stem.replace("_", " ").title()
        result = _post("/api/entries", {
            "title": f"CosySim Docs: {title}",
            "content": content,
            "content_type": "documentation",
            "tags": tags + ["cosysim", "docs"],
            "category": category,
        })
        if result:
            count += 1
            logger.info("  ✓ %s (%d chars)", rel_path, len(content))
        else:
            logger.warning("  ✗ %s (API error)", rel_path)
    logger.info("Seeded %d/%d docs", count, len(DOCS_TO_SEED))
    return count


def seed_all():
    """Run all seeding operations."""
    logger.info("=" * 60)
    logger.info("Nexus Knowledge Seeding — CosySim v0.50b")
    logger.info("=" * 60)

    # Check Nexus is available
    health = _get("/api/health")
    if not health:
        logger.error("Nexus is not available at %s. Start it first.", NEXUS_URL)
        return False

    logger.info("Nexus is healthy: %s", health.get("status", "unknown"))
    logger.info("")

    p = seed_profiles()
    q = seed_qa()
    d = seed_docs()

    logger.info("")
    logger.info("=" * 60)
    logger.info("Seeding complete: %d profiles, %d Q&A pairs, %d docs", p, q, d)
    logger.info("=" * 60)
    return True


def main():
    parser = argparse.ArgumentParser(description="Seed Nexus with CosySim knowledge")
    parser.add_argument("--profiles", action="store_true", help="Seed agent profiles only")
    parser.add_argument("--qa", action="store_true", help="Seed Q&A pairs only")
    parser.add_argument("--docs", action="store_true", help="Seed documentation only")
    args = parser.parse_args()

    if args.profiles:
        seed_profiles()
    elif args.qa:
        seed_qa()
    elif args.docs:
        seed_docs()
    else:
        seed_all()


if __name__ == "__main__":
    main()
