# Copilot Instructions — CosySim

> Repository-level operating context for Copilot CLI, IDE chat, and custom agents.
> Path-specific rules live in `.github/instructions/`. Agent playbooks live in
> `.github/agents/`. See also [`.github/README.md`](./README.md) and
> [`docs/AGENT_ONBOARDING.md`](../docs/AGENT_ONBOARDING.md).

## Current Operating Priorities

1. **First wave = core stabilization + enforcement.**
   Fix correctness, governance, persistence, hooks, and knowledge reuse before
   expanding features.
2. **Governance source of truth = repository + Nexus synchronized.**
   The repo is the editable bootstrap surface; Nexus is the persistent knowledge
   and operational memory layer. They must not drift.
3. **NotebookLM comes after auth/library recovery.**
   Restore NotebookLM authentication and library health first, then deepen the
   integration and research pipeline.
4. **Advanced GUI work comes after foundations are stable.**
   Do not prioritize polish, dashboards, or ambitious UI expansion ahead of the
   enforcement and knowledge loop.
5. **Agents must continuously store and reuse history.**
   Histories, changelogs, memories, rules, learned improvements, and decisions
   belong in Nexus so later sessions can reuse them.

## Source of Truth Model

Treat CosySim's Copilot stack as a synchronized pair:

- **Repository** — live instruction files, agent definitions, hooks, docs, and
  the runtime assets Copilot executes from disk.
- **Nexus** — persistent mirror for rules, memories, prompt history, session
  history, changelog fragments, reusable Q&A, and recovered improvements.

`engine/nexus/copilot_self_config.py` exists to sync instructions, agents, and
hooks between the repo and Nexus. Use that model when describing governance:
**the repo and Nexus are jointly authoritative when synchronized**.

## Preferred Knowledge Entry Point

### MCP tools (preferred)
Use **`nexus_smart_query(question)` first** for information retrieval.

Why:
- checks cache and existing Nexus knowledge before spending more compute
- can fall through to deeper retrieval when needed
- auto-reinforces the shared knowledge loop

Use these supporting tools when the task needs more control:
- `nexus_search(query)` — explicit search and discovery
- `nexus_ask(question)` — direct smart Q&A path
- `nexus_get_rules(scope)` — governance lookup
- `nexus_add(...)` / `nexus_add_qa(...)` — persist outcomes
- `nexus_router_stats()` — inspect router effectiveness

### CLI bridge fallback (when MCP is unavailable)
If the MCP server is down or unavailable, use the standalone Nexus bridge:

```powershell
python -m engine.nexus.bridge search "topic"
python -m engine.nexus.bridge ask "What is the current pattern?" --depth auto
python -m engine.nexus.bridge rules "global"
python -m engine.nexus.bridge store "Decision: ..." "..." --type decision --category architecture
python -m engine.nexus.bridge qa "How does X work?" "..." --category development
python -m engine.nexus.bridge backfill "Question?" "Answer." --source "where it was found"
python -m engine.nexus.bridge inventory --store
python -m engine.nexus.bridge health
python -m engine.nexus.seed_copilot_rules
python -m engine.nexus.copilot_validation --json
```

The bridge is the fallback path. `nexus_smart_query` remains the preferred
entry point whenever MCP tools are available.

If Nexus is missing needed information and you find it elsewhere during work,
backfill it before you move on. Missing knowledge should become Nexus knowledge
by the end of the task, ideally as both a reusable knowledge entry and a direct
Q&A pair.

## Copilot / Nexus / NotebookLM Self-Maintaining Loop

```text
repo instructions + agents + hooks
        │
        ▼
Copilot runtime executes from .github/
        │
        ├── hooks call copilot_bridge for task-aware Nexus/NLM context
        ├── hooks call nexus_session_logger for session/checkpoint export
        └── agents follow repo rules while working
        │
        ▼
Nexus stores histories, changelogs, rules, memories, Q&A, plans, improvements
        │
        ├── copilot_self_config syncs repo assets with Nexus mirrors
        ├── scheduler_daemon/task_scheduler keep maintenance and follow-ups moving
        └── future agents query Nexus first instead of starting from scratch
        │
        ▼
NotebookLM deep research (only after auth + library are healthy)
        │
        └── distill results back into Nexus for reuse by later sessions
```

This loop is the intended operating model. The system should become easier to
operate the more sessions it records.

## Runtime Assets You Must Respect

| Asset | Purpose |
|------|---------|
| `engine/nexus/copilot_bridge.py` | Session-start/session-end bridge that pulls task context from Nexus and records usage metrics |
| `engine/nexus/copilot_self_config.py` | Synchronizes Copilot instructions, agents, hooks, and preferences with Nexus |
| `engine/nexus/copilot_validation.py` | Validates Copilot Nexus mirrors, hook integrity, and runtime health |
| `engine/nexus/seed_copilot_rules.py` | Refreshes Copilot/docs mirrors in Nexus and deduplicates stale exact-title mirrors |
| `engine/nexus/nexus_session_logger.py` | Exports session history, checkpoints, compaction snapshots, and git context to Nexus |
| `engine/nexus/scheduler_daemon.py` | Runs recurring maintenance and autonomous follow-up tasks |
| `engine/nexus/task_scheduler.py` | Tracks generated and template-based tasks for agents |
| `.github/hooks/cosysim-hooks.json` | Main Copilot hook wiring for session lifecycle, tool safety, bridge calls, and compaction export |
| `.github/hooks/session-logger/hooks.json` | Session logger hook pack for start/end/prompt export |

## Working Rules

### Always
- Stabilize broken or weak foundations before proposing ambitious expansion.
- Use `nexus_smart_query(...)` first when you need context.
- Keep repo docs, instructions, hooks, and Nexus knowledge internally aligned.
- Store durable outcomes in Nexus: histories, changelog notes, decisions,
  memories, rules, reusable fixes, and process improvements.
- If Nexus misses and the answer is discovered elsewhere, store it back into
  Nexus as both knowledge and Q&A when practical.
- After changing Copilot instructions, hooks, agents, or operating docs, reseed
  Nexus mirrors with `python -m engine.nexus.seed_copilot_rules` and verify the
  control plane with `python -m engine.nexus.copilot_validation --json`.
- Treat NotebookLM as a second-stage accelerator: repair auth and library state
  first, then use it for deeper research and distillation.
- Repair NotebookLM auth through the intended browser-attached path first:
  live Chrome on CDP, `scripts\har_capture.py`, ARGUS token harvesting, and HAR
  recovery when needed. Do not reduce the system description to HAR-only auth.
- Use absolute imports, type hints, structured logging, and governance-safe file
  changes in code tasks.
- Respect hook reminders and governance checks rather than working around them.

### Never
- Treat Nexus as optional memory.
- Let repo instructions and Nexus rules diverge silently.
- Prioritize advanced GUI work over stabilization, enforcement, and persistence.
- Depend on NotebookLM automation while auth or library sync is still broken.
- Discard session history, compaction context, or useful learnings that should
  be reusable later.

## Compaction and Session Persistence

Hooks already call `nexus_session_logger.py` on session events, but agents should
still understand the manual commands:

```powershell
python engine/nexus/nexus_session_logger.py checkpoint
python engine/nexus/nexus_session_logger.py compact
python engine/nexus/nexus_session_logger.py end
```

Use them when you need to preserve context before compaction, after major work
blocks, or before handing work to another agent.

## Copilot Control-Plane Maintenance

When Copilot-facing repo assets change, run:

```powershell
python -m engine.nexus.seed_copilot_rules
python -m engine.nexus.copilot_validation --json
```

The reseed command now also deduplicates exact-title Copilot/doc mirrors in
Nexus so validation stays green after refreshes.

## Three-Pillar Architecture (v1.42)

All launcher targets are organized into three pillars in `engine/control_plane_registry.py`:

| Pillar | Label | Count | Purpose |
|--------|-------|-------|---------|
| `game` | NeonCity | 14 | Interactive scenes (penthouse, phone, lounge, etc.) |
| `service` | Services | 11 | Infrastructure (nexus_kms, hub, nexus_panel, bridge, nlm_proxy, etc.) |
| `creation` | Creation Kit | 5 | Asset tools (asset_studio, canvas, creator, etc.) |

Key integration points:
- **`/api/scene-registry`** — auto-wired on every Flask scene via `register_health_route()`
- **Navbar v2** — calls `loadPillarRegistry()` on page load for pillar toggle pills
- **Hub** — groups scene cards by pillar instead of legacy neon_world/action/system
- **Config overlays** — `config/game.yaml`, `config/services.yaml`, `config/creation.yaml`
- **Launcher** — `python launcher.py --list` shows three pillar groups

When adding a new scene, add it to `SCENE_DEFS` with `"pillar": "game"|"service"|"creation"`.

## Smart Test System (v1.42)

Use the smart test runner instead of running the full 15K test suite:
```powershell
pytest tests/ --smoke-only              # ~53s, 15 files, one per domain
pytest tests/ --affected                # tests for uncommitted changes only
pytest tests/ --staged                  # tests for staged files (pre-commit)
pytest tests/ --affected --cap 40       # auto-fallback to smoke if too many
python scripts/smart_test.py --smoke    # standalone script, same engine
python scripts/smart_test.py --list     # dry-run: show what would run
```

## Code Versioning & Comment Standards (v1.42.1)

All code files created or significantly modified MUST include versioning metadata and structured comments. This is a **standing rule** for all agents (Copilot, Claude Code, local LLM agents).

### Module Headers

Every Python file gets a docstring header:

```python
"""
Module Title
============

Brief description.

Version: v1.42.1 [2026-03-21]
Author:  CosySim Team

Change Log:
    v1.42.1 [2026-03-21] — What changed
    v1.42.0 [2026-03-21] — Previous change
"""
```

JS files use `/** ... */` JSDoc. CSS/HTML use `/* ... */` or `<!-- -->`.

### Section Dividers

```python
# ──── Section Name ────────────────────────────────────────────────
```

### Version Stamps

Tag significant code blocks:

```python
# v1.42.1 [2026-03-21] — Managed Nexus KMS auto-start
def _start_external_proc(...):
```

### Versioning Scheme

- Format: `vMAJOR.MINOR.PATCH [YYYY-MM-DD]`
- MAJOR = breaking architecture. MINOR = feature sprint. PATCH = within-session.
- Current: **v1.42** (Pillar Wiring & Hub Modernization)
- Always add/update the Change Log when modifying a file
- Never remove existing version stamps — they are historical record
- Store version bumps in Nexus as changelog entries

## Priority Over Feature Breadth

When in doubt, prefer work in this order:
1. correctness and enforcement
2. knowledge capture and reuse
3. NotebookLM recovery and integration depth
4. operational automation
5. advanced GUI and polish

## References

- Overview: [`.github/README.md`](./README.md)
- Copilot workflow agent: [`./agents/copilot-workflow.agent.md`](./agents/copilot-workflow.agent.md)
- Onboarding guide: [`../docs/AGENT_ONBOARDING.md`](../docs/AGENT_ONBOARDING.md)
- Nexus usage rules: [`./instructions/nexus.instructions.md`](./instructions/nexus.instructions.md)
