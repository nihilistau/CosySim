# Copilot CLI System — v0.51b

Complete documentation for the GitHub Copilot CLI integration with CosySim
and Nexus. This covers the full loop: session hooks, memory persistence,
knowledge distillation, MCP tools, CLI bridge, and instruction hierarchy.

## Overview

The Copilot CLI (GitHub Copilot Agent) is deeply integrated into CosySim as
both a development tool and a first-class participant in the Nexus knowledge
system. Every Copilot session automatically logs context to Nexus, and the
agent can query, store, and distil knowledge through MCP tools, CLI commands,
and session hooks.

```
┌───────────────────────────────────────────────────┐
│  GitHub Copilot CLI Agent                         │
│                                                   │
│  ┌─────────────┐  ┌──────────────┐               │
│  │ Instructions │  │ Custom Agents│               │
│  │  (3 layers)  │  │   (10 defs)  │               │
│  └──────┬───────┘  └──────┬───────┘               │
│         │                  │                       │
│  ┌──────▼──────────────────▼───────┐              │
│  │       Session Hooks             │              │
│  │  start → prompt → end           │              │
│  └──────┬──────────────────────────┘              │
│         │                                          │
│  ┌──────▼──────┐  ┌──────────────┐               │
│  │ MCP Server  │  │  CLI Bridge  │               │
│  │ (133 tools) │  │  (fallback)  │               │
│  └──────┬──────┘  └──────┬───────┘               │
│         │                 │                        │
│  ┌──────▼─────────────────▼───────┐              │
│  │          Nexus KMS              │              │
│  │   (entries, Q&A, rules,         │              │
│  │    memories, sessions)          │              │
│  └─────────────────────────────────┘              │
└───────────────────────────────────────────────────┘
```

## Instruction Hierarchy

Copilot instructions are layered, with more specific rules overriding general
ones.

### Layer 1: Global Instructions

**File:** `~/.copilot/copilot-instructions.md`

Applies to ALL projects on this workstation. Contains:
- Environment setup (Windows 11, Python 3.10+, NVIDIA GPU)
- System map (CosySim, Nexus, MCP Servers paths)
- Nexus-first workflow (search before coding, store after)
- Terminal preferences (PowerShell, git --no-pager)
- Coding standards, testing, git conventions

### Layer 2: Repository Instructions

**File:** `.github/copilot-instructions.md`

Applies to all work within the CosySim repository. Contains:
- Project overview and version info
- MCP tools documentation (133 tools)
- Quick reference (test commands, singletons, project structure)
- Critical rules (always/never lists)
- External service port map

### Layer 3: Path-Specific Instructions

**Directory:** `.github/instructions/`

Auto-apply based on file patterns:

| File | Pattern | Content |
|------|---------|---------|
| `python.instructions.md` | `**/*.py` | Imports, typing, docstrings, naming |
| `scenes.instructions.md` | `content/scenes/**/*.py` | Scene structure, MCP integration |
| `mcp-framework.instructions.md` | `engine/mcp/**` | Skill decorator, interceptors, governance |
| `nexus.instructions.md` | `engine/nexus/**` | Nexus usage guide, API, workflows |
| `testing.instructions.md` | `tests/**/*.py` | pytest patterns, fixtures, mocking |
| `lmstudio.instructions.md` | `engine/lmstudio/**/*.py` | API format, streaming, models |
| `config.instructions.md` | `config/**/*.yaml` | Config access, file hierarchy |
| `frontend.instructions.md` | `**/templates/**, **/static/**` | Jinja2, vanilla JS, CSS |
| `deployment.instructions.md` | `start_servers.ps1, launcher.py` | Service start order, health checks |

## Custom Agents

10 specialised agents defined in `.github/agents/`:

| Agent | File | Purpose |
|-------|------|---------|
| Copilot Workflow | `copilot-workflow.agent.md` | Master orchestrator, uses all MCP tools |
| Scene Builder | `scene-builder.agent.md` | Scaffold new scenes from scratch |
| Scene Debugger | `scene-debugger.agent.md` | Diagnose and fix scene/agent issues |
| Scene Auditor | `scene-auditor.agent.md` | Rate scenes against AAA standard |
| Skill Developer | `skill-developer.agent.md` | Create and register MCP skill packs |
| Test Writer | `test-writer.agent.md` | Generate pytest test suites |
| Doc Writer | `doc-writer.agent.md` | Maintain documentation system |
| Codebase Navigator | `codebase-navigator.agent.md` | Explain architecture, trace calls |
| System Architect | `system-architect.agent.md` | Cross-project architecture decisions |
| Nexus Researcher | `nexus-researcher.agent.md` | Research topics, store in Nexus |

## Session Hooks

Hooks fire automatically on Copilot session lifecycle events.

**Config:** `.github/hooks/session-logger/hooks.json`

```json
{
  "hooks": [
    {"event": "sessionStart",  "command": "python engine/nexus/nexus_session_logger.py start"},
    {"event": "sessionEnd",    "command": "python engine/nexus/nexus_session_logger.py end"},
    {"event": "userPromptSubmitted", "command": "python engine/nexus/nexus_session_logger.py prompt"}
  ]
}
```

### Session Start

- Records git context (branch, last commit, recent commits)
- Saves CWD and timestamp
- Creates Nexus entry tagged `[session, copilot, start]`
- Stores session state to `.github/hooks/logs/current_session.json`

### User Prompt

- Increments prompt counter
- Updates `last_prompt_at` timestamp
- Local log only (lightweight)

### Session End

Full export to Nexus:
1. **Session summary** — Git context, prompt count, files touched, checkpoints
2. **Conversation log** — All turns (USER/ASSISTANT) from Copilot session store
3. **Plan** — Contents of plan.md if it exists
4. **Checkpoints** — Each checkpoint as a separate Nexus entry
5. **Key decisions** — Auto-extracted from assistant responses as Q&A pairs

Data source: `~/.copilot/session-store/store.sqlite` (read-only access to
Copilot's internal session database).

## MCP Tools for Nexus

The CosySim MCP server (133 tools) includes these Nexus-specific tools:

### Knowledge Management

| Tool | Parameters | Description |
|------|-----------|-------------|
| `seed_nexus` | `source` (docs/rules/prompts/qa/all) | Run knowledge seeder |
| `nexus_maintain` | `action` (health/dedup/cleanup/reindex) | Maintenance operations |

### Memory

| Tool | Parameters | Description |
|------|-----------|-------------|
| `nexus_remember` | `agent_id`, `content`, `importance`, `memory_type` | Store a memory |
| `nexus_recall` | `agent_id`, `query`, `top_k` | Retrieve relevant memories |
| `nexus_memory_context` | `agent_id`, `max_chars` | Get context window for prompts |

### Training

| Tool | Parameters | Description |
|------|-----------|-------------|
| `capture_training_data` | `user_msg`, `agent_response`, `quality` | Capture for fine-tuning |
| `generate_content` | `character_id`, `content_type` | Generate greetings/reactions |

### Distillation

| Tool | Parameters | Description |
|------|-----------|-------------|
| `nexus_distill` | `action` (see below) | Run knowledge distillers |
| `nexus_export_session` | (none) | Export current session to Nexus |

**`nexus_distill` actions:**

| Action | Description |
|--------|-------------|
| `stats` | Knowledge base statistics and token estimates |
| `distill` | Extract decisions, fixes, conventions from logs |
| `compact` | Merge old daily session entries into summaries |
| `primer` | Generate compact context primer for new sessions |
| `dedup` | Find and remove duplicate Q&A pairs |
| `dedup-dry` | Preview duplicates without removing |
| `skills` | Analyse skill/tool usage patterns |
| `prompts` | Analyse prompt structural patterns |
| `lineage` | Show prompt version evolution history |
| `all` | Run all distillers in sequence |

## CLI Bridge

`engine/nexus/bridge.py` provides standalone Nexus access when the MCP server
is unavailable.

```bash
# Search knowledge base
python -m engine.nexus.bridge search "interceptor pipeline"

# Smart Q&A (cache → FTS5 → NLM)
python -m engine.nexus.bridge ask "How does state management work?"

# Store knowledge
python -m engine.nexus.bridge store "Decision" "Use FTS5 for search"

# Store Q&A pair
python -m engine.nexus.bridge qa "What is X?" "X is..."

# Get governance rules
python -m engine.nexus.bridge rules global

# Health check
python -m engine.nexus.bridge health

# Run seeder
python -m engine.nexus.bridge seed all

# Run maintenance
python -m engine.nexus.bridge maintain health
```

## Knowledge Distillers

Four distillers process raw session data into reusable knowledge:

```bash
# Run from terminal
python -m engine.nexus.nexus_distiller stats     # Knowledge base overview
python -m engine.nexus.nexus_distiller distill    # Extract from session logs
python -m engine.nexus.nexus_distiller compact    # Merge old session entries
python -m engine.nexus.nexus_distiller primer     # Generate context primer
python -m engine.nexus.nexus_distiller dedup      # Remove duplicate Q&A
python -m engine.nexus.nexus_distiller dedup-dry  # Preview duplicates
python -m engine.nexus.nexus_distiller skills     # Skill usage analysis
python -m engine.nexus.nexus_distiller prompts    # Prompt pattern analysis
python -m engine.nexus.nexus_distiller lineage    # Prompt version history
python -m engine.nexus.nexus_distiller all        # Run everything
```

### NexusDistiller

Processes conversation logs tagged `conversation-log` that haven't been
distilled yet. Extracts:
- Architectural decisions (regex patterns for "Decision:", "Created:", etc.)
- Bug fix patterns (problem/solution pairs stored as Q&A)
- File-specific conventions (file path mentions with context)

Marks processed logs with `distilled` tag to avoid reprocessing.

### QADeduplicator

Uses word-level Jaccard similarity to find near-duplicate Q&A pairs.
Default threshold: 0.75. When duplicates are found, keeps the answer with
more content and deletes the shorter one.

### SkillUsageDistiller

Scans session logs for MCP skill/tool mentions using regex patterns. Reports:
- Most frequently used skills
- Error-prone skills (mentioned near error keywords)
- Rarely used/underutilised skills

Stores findings as Nexus entries and Q&A pairs.

### PromptEvolutionDistiller

Analyses prompt entries for:
- **Lineage**: Groups prompts by base name, tracks version count and length trends
- **Patterns**: Checks for structural elements (role definition, constraints,
  output format, examples, guardrails, tool instructions, persona traits)
- Stores best-practice analysis as a Nexus entry

## Nexus-First Workflow

The recommended workflow for every Copilot session:

### Before Coding
1. `nexus_search("topic")` — Check existing knowledge
2. `nexus_get_rules("scope")` — Get governance rules
3. `nexus_recall("copilot", "context")` — Retrieve relevant memories

### During Work
4. `nexus_remember("copilot", "learning", 0.8)` — Store discoveries
5. `capture_training_data(...)` — Capture high-quality interactions
6. `nexus_distill("stats")` — Monitor knowledge base health

### After Work
7. `nexus_export_session()` — Export conversation history
8. `nexus_distill("all")` — Run all distillers
9. Decisions are auto-extracted as Q&A pairs on session end

## Token Reduction Strategy

The entire Nexus integration is designed to reduce token usage over time:

1. **Memory persistence** — Decisions and context survive across sessions,
   eliminating the need to re-explain project structure
2. **Q&A cache** — Common questions get instant answers from cache instead
   of re-analysing code
3. **Context primer** — `nexus_distill("primer")` generates a compact summary
   that can be injected instead of re-reading docs
4. **Distillation** — Raw session logs are compressed into structured knowledge,
   keeping the knowledge base searchable without bloat
5. **Deduplication** — Similar Q&A pairs are merged, reducing noise in search
6. **Namespace separation** — Targeted queries return only relevant results

## File Reference

| File | Purpose |
|------|---------|
| `~/.copilot/copilot-instructions.md` | Global agent instructions |
| `.github/copilot-instructions.md` | Repository-level instructions |
| `.github/instructions/*.md` | Path-specific instructions (9 files) |
| `.github/agents/*.agent.md` | Custom agent definitions (10 files) |
| `.github/hooks/session-logger/hooks.json` | Session lifecycle hooks |
| `engine/nexus/nexus_session_logger.py` | Session hook handler |
| `engine/nexus/nexus_distiller.py` | 4 knowledge distillers |
| `engine/nexus/nexus_memory.py` | Memory system for Copilot + characters |
| `engine/nexus/bridge.py` | Standalone CLI for Nexus access |
| `engine/nexus/nexus_seeder.py` | Knowledge base seeder |
| `engine/mcp/cosysim_server.py` | MCP server (133 tools) |
