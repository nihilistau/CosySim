# .github/ — Copilot Operating Manual

This directory contains CosySim's Copilot-facing operating surface: repository
instructions, custom agents, and runtime hooks that keep Copilot aligned with
Nexus and the audited system priorities.

## Current Direction

- **First wave:** core stabilization + enforcement
- **Governance source of truth:** repository + Nexus synchronized
- **NotebookLM strategy:** restore auth and library health first, then integrate deeply
- **Advanced GUI:** after foundations are stable
- **Agent mandate:** store and reuse histories, changelogs, memories, rules, and improvements through Nexus

## What Lives Here

```text
.github/
├── copilot-instructions.md        # Repository-wide operating policy
├── instructions/                  # Path-specific rules
├── agents/                        # Custom agent playbooks
├── hooks/                         # Session/runtime hook wiring
├── workflows/                     # GitHub automation for Copilot-related setup/autofix
└── README.md                      # This operating manual
```

## Operating Model

### 1. Repository + Nexus stay synchronized
The repository is the live editable surface for instructions, agents, and hook
wiring. Nexus is the persistent operational memory and governance layer.
CosySim is designed so the two stay synchronized rather than compete.

`engine/nexus/copilot_self_config.py` is the bridge for that model. It syncs
instruction files, agent definitions, hook definitions, and preferences between
repo files and Nexus-backed storage. `engine/nexus/seed_copilot_rules.py`
refreshes the mirrored Copilot/docs entries in Nexus and now deduplicates stale
exact-title mirrors after sync.

### 2. Nexus-first retrieval
Copilot should not start from zero when the system already knows something.

Preferred order:
1. `nexus_smart_query(question)`
2. `nexus_search(query)` / `nexus_ask(question)` when more explicit control helps
3. NotebookLM-backed research after auth/library are healthy
4. local LLM fallback only after the shared knowledge paths are exhausted

If MCP tools are unavailable, use the CLI bridge in `engine/nexus/bridge.py`.
That fallback supports `search`, `ask`, `rules`, `store`, `qa`, `backfill`,
`inventory`, `health`, `seed`, and `maintain`.

### 3. Self-maintaining loop

```text
repo assets → Copilot runtime → hooks + agents → Nexus history/rules/memory
     ▲                                                │
     └──────────── copilot_self_config sync ──────────┘
                          │
                          └── NotebookLM research distills back into Nexus
```

The goal is not just task completion. The goal is a system that remembers what
it learned and improves the next session.

## Key Runtime Assets

| File | Role |
|------|------|
| `../engine/nexus/copilot_bridge.py` | Pulls task-aware Nexus context into sessions and records session metrics |
| `../engine/nexus/copilot_self_config.py` | Syncs instructions, agents, hooks, and preferences with Nexus |
| `../engine/nexus/copilot_validation.py` | Validates Copilot Nexus sync drift, hook integrity, and runtime health |
| `../engine/nexus/seed_copilot_rules.py` | Refreshes Copilot/docs mirrors in Nexus and deduplicates stale exact-title mirrors |
| `../engine/nexus/nexus_session_logger.py` | Exports histories, checkpoints, compaction snapshots, and git context |
| `../engine/nexus/scheduler_daemon.py` | Runs recurring maintenance and background follow-up work |
| `../engine/nexus/task_scheduler.py` | Generates and tracks agent tasks/templates |
| `./hooks/cosysim-hooks.json` | Main hook pack used by Copilot runtime |
| `./hooks/session-logger/hooks.json` | Dedicated session logging hooks |

## Instructions

Path-specific instructions are in [`./instructions/`](./instructions/). The set
covers Python, scenes, MCP/framework work, Nexus, tests, LMStudio, config,
frontend, deployment, and scene debugging.

Use them as the fine-grained rules. Keep `copilot-instructions.md` focused on
cross-cutting operating policy.

## Agents

Custom agents are in [`./agents/`](./agents/). They cover:
- workflow orchestration
- codebase navigation and architecture
- bug fixing, feature building, refactoring, and review
- scene building/debugging/auditing
- skills, tests, benchmarks, config optimization
- documentation and knowledge curation
- integration testing and system architecture

The Copilot workflow entry point is
[`./agents/copilot-workflow.agent.md`](./agents/copilot-workflow.agent.md).
Use it for multi-step tasks that need Nexus, hooks, system awareness, or
cross-file coordination.

## Hooks

Hooks are not incidental here; they are part of the operating model.

### Main hook pack
[`./hooks/cosysim-hooks.json`](./hooks/cosysim-hooks.json) wires:
- session start logging
- `copilot_bridge` context retrieval
- session end export
- pre-compaction checkpoint export
- tool usage logging
- pre-tool safety and governance checks
- error logging

### Session logger hook pack
[`./hooks/session-logger/hooks.json`](./hooks/session-logger/hooks.json) runs
`engine/nexus/nexus_session_logger.py` on session start, prompt submission, and
session end.

### Hook expectations
- Hooks should reinforce Nexus-first behavior, not replace it.
- Agents should still store durable learnings intentionally.
- Governance checks should be obeyed, not bypassed.

## NotebookLM Lane

NotebookLM is important, but not as the very first priority.

Current order:
1. restore browser-attached authentication reliability (`scripts\har_capture.py`,
   ARGUS token harvesting, HAR recovery)
2. restore/verify library health and notebook inventory
3. reconnect deep research workflows
4. distill results back into Nexus for long-term reuse

Do not document NotebookLM as the main operational dependency unless the
auth/library foundation is working.

## What "Done" Looks Like for Copilot Work

A Copilot-facing change is in good shape when:
- repo docs, instructions, agents, and hooks describe the same system
- Nexus-first behavior is explicit and practical
- `nexus_smart_query` is presented as the preferred entry point
- CLI bridge fallback is documented without replacing MCP-first guidance
- histories, changelogs, memories, rules, and improvements are routed into Nexus
- NotebookLM is framed as a deep-research lane after auth/library recovery
- GUI ambitions are clearly sequenced after stabilization and enforcement

## Maintenance Notes

When you add or change:
- **instructions** → update this README if the role of the instruction set changes
- **agents** → keep the agent roster and responsibilities coherent
- **hooks** → document the operational consequence here
- **knowledge workflow** → keep `copilot-instructions.md`, the workflow agent,
  and onboarding docs in sync

After changing Copilot instructions, hooks, agents, or the Copilot operating
docs, run:

```powershell
python -m engine.nexus.seed_copilot_rules
python -m engine.nexus.copilot_validation --json
```

The reseed step now also removes redundant exact-title Copilot/doc mirrors from
Nexus so the validator stays clean.

## Related Documents

- Repository policy: [`./copilot-instructions.md`](./copilot-instructions.md)
- Workflow agent: [`./agents/copilot-workflow.agent.md`](./agents/copilot-workflow.agent.md)
- Agent onboarding: [`../docs/AGENT_ONBOARDING.md`](../docs/AGENT_ONBOARDING.md)
