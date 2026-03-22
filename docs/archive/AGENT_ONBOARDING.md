# CosySim Agent Onboarding Guide

> Practical operating manual for Copilot-facing agents working in CosySim.
> This guide is intentionally aligned with the current audited priorities,
> active hook/runtime assets, and the Nexus-first knowledge loop.

## Mission

CosySim is being operated with a clear execution order:

1. **First wave = core stabilization + enforcement**
2. **Governance source of truth = repository + Nexus synchronized**
3. **NotebookLM = restore auth/library first, then integrate deeply**
4. **Advanced GUI comes after foundations are stable**
5. **Agents must store and reuse histories, changelogs, memories, rules, and improvements through Nexus**

If you are unsure what to do next, choose the action that strengthens these
priorities instead of widening scope.

## The Operating Loop

```text
repo files define the live working surface
        ↓
Copilot runtime executes instructions, agents, and hooks
        ↓
bridge/logger/scheduler capture context and maintenance tasks
        ↓
Nexus stores reusable history, rules, memory, changelog, and improvements
        ↓
future agents query Nexus first instead of rediscovering the same answers
        ↓
NotebookLM deep research feeds back into Nexus once auth/library are healthy
```

Your task is not only to complete work. Your task is to make the next work block
cheaper, safer, and better informed.

## Source of Truth Model

Treat CosySim as a synchronized two-surface system:

| Surface | Role |
|--------|------|
| Repository | Editable instructions, agent definitions, hooks, docs, code, and bootstrap configuration |
| Nexus | Durable operational memory: rules, histories, changelogs, reusable Q&A, decisions, plans, improvements |

Do not describe one as replacing the other. The target state is **repo + Nexus
synchronized**.

`engine/nexus/copilot_self_config.py` exists specifically to support that model
by syncing instructions, agents, hooks, and preferences between the repository
and Nexus-backed storage.

## Step 1: Query Nexus First

### Preferred entry point
Use **`nexus_smart_query(question)` first** whenever MCP tools are available.
It is the preferred front door for retrieval because it checks shared knowledge
before spending more compute.

Supporting tools:
- `nexus_search(query)`
- `nexus_ask(question)`
- `nexus_get_rules(scope)`
- `nexus_add(...)`
- `nexus_add_qa(...)`
- `nexus_router_stats()`

### CLI bridge fallback
If MCP tools are unavailable, fall back to the standalone bridge:

```powershell
python -m engine.nexus.bridge search "topic"
python -m engine.nexus.bridge ask "How does this work?" --depth auto
python -m engine.nexus.bridge rules "global"
python -m engine.nexus.bridge store "Decision: ..." "..." --type decision --category architecture
python -m engine.nexus.bridge qa "Question?" "Answer." --category development
python -m engine.nexus.bridge backfill "Question?" "Answer." --source "where it was found"
python -m engine.nexus.bridge inventory --store
python -m engine.nexus.bridge health
```

The bridge is the fallback path. It does not replace the MCP-first workflow.

## Step 2: Understand the Runtime Assets

These files are part of the operating system for Copilot work, not background
implementation details.

| Asset | Why it matters |
|------|-----------------|
| `engine/nexus/copilot_bridge.py` | Pulls task-aware context from Nexus/NLM at session boundaries and records session metrics |
| `engine/nexus/copilot_self_config.py` | Syncs repo instructions, agents, hooks, and preferences with Nexus |
| `engine/nexus/copilot_validation.py` | Validates Copilot Nexus sync drift, hook integrity, and runtime health |
| `engine/nexus/seed_copilot_rules.py` | Refreshes Copilot/docs mirrors in Nexus and deduplicates stale exact-title mirrors |
| `engine/nexus/nexus_session_logger.py` | Exports session history, checkpoints, compaction snapshots, and git context |
| `engine/nexus/scheduler_daemon.py` | Runs recurring maintenance and autonomous tasks |
| `engine/nexus/task_scheduler.py` | Manages generated and template-based agent tasks |
| `.github/hooks/cosysim-hooks.json` | Main hook pack for session lifecycle, safety checks, tool logging, and compaction export |
| `.github/hooks/session-logger/hooks.json` | Dedicated start/prompt/end session export hooks |

## Step 3: Follow the Priority Order

### What to optimize first
1. broken foundations
2. governance enforcement
3. persistence and session recovery
4. Nexus knowledge quality and reuse
5. NotebookLM auth/library recovery
6. deep research automation
7. advanced GUI and polish

### Practical interpretation
- If a hook, rule, session export, or knowledge sync is weak, fix that before
  proposing new visual layers.
- If NotebookLM auth or library state is unreliable, repair that before writing
  docs that assume deep NotebookLM automation already works.
- If work produces useful history, convert it into Nexus data rather than
  leaving it only in transient chat context.

## Step 4: Respect Governance and Enforcement

CosySim actively uses enforcement, not just style guidance.

### Enforcement surfaces
1. **Copilot hooks** — tool safety and reminder gates
2. **Governance rules** — validation and blocking logic for protected changes
3. **Repository instructions** — path-specific rules for file types and subsystems
4. **Nexus-backed knowledge/rules** — persistent rule and context layer

### Working stance
- obey hook and governance feedback
- prefer minimal, governed changes over broad speculative rewrites
- keep repo instructions and Nexus rules mutually consistent
- record any new durable rule or exception in Nexus
- after changing Copilot-facing instructions/hooks/docs, reseed and validate the
  Copilot control plane before moving on

## Step 5: Preserve History Deliberately

The mandate is explicit: agents must store and reuse histories, changelogs,
memories, rules, and improvements through Nexus.

### Minimum persistence expectations
Store or export, as appropriate:
- session history
- checkpoint summaries
- compaction snapshots
- changelog-worthy outcomes
- architecture decisions
- reusable Q&A
- bug analyses and fixes
- rule clarifications
- improvement ideas worth scheduling later

### Manual commands you should know

```powershell
python engine/nexus/nexus_session_logger.py checkpoint
python engine/nexus/nexus_session_logger.py compact
python engine/nexus/nexus_session_logger.py end
python -m engine.nexus.seed_copilot_rules
python -m engine.nexus.copilot_validation --json
```

Hooks already automate much of this, but you should use the manual commands when
preserving context matters.

## Step 6: Use NotebookLM in the Right Sequence

NotebookLM is part of the long-term loop, but it is not the first dependency to
assume is healthy.

### Required sequence
1. restore or verify NotebookLM authentication
2. restore or verify notebook library health
3. use NotebookLM for deeper research or distillation
4. push distilled knowledge back into Nexus
5. let future `nexus_smart_query` calls reuse that result

### Why this matters
Without auth/library recovery, deep NotebookLM integration becomes fragile and
creates documentation drift. The stable system path is **repair first, then
integrate deeply**.

## Step 7: Keep GUI Work in Its Lane

Advanced GUI work is not banned. It is sequenced.

Only prioritize it after:
- stabilization work is under control
- enforcement and governance are reliable
- session history and Nexus reuse are functioning
- NotebookLM recovery is no longer the blocker

If a task choice is ambiguous, the non-GUI foundation task wins.

## Practical Checklist for Any Task

Before work:
- identify the real priority tier the task belongs to
- query Nexus with `nexus_smart_query(...)`
- check repo instructions and any relevant agent docs
- verify whether NotebookLM health matters for the task

During work:
- follow governance and hook feedback
- keep changes practical and internally consistent
- capture durable decisions as you go
- avoid widening scope into GUI/polish unless foundations are already stable

After work:
- store decisions, reusable Q&A, and improvements in Nexus
- ensure session history/checkpoints are recoverable
- add or update changelog-style notes if the work affects the system narrative
- queue follow-up maintenance through scheduler/task systems when useful

## Related Documents

- Copilot repository policy: [`../.github/copilot-instructions.md`](../.github/copilot-instructions.md)
- Copilot operating manual: [`../.github/README.md`](../.github/README.md)
- Workflow agent: [`../.github/agents/copilot-workflow.agent.md`](../.github/agents/copilot-workflow.agent.md)
- Nexus path rules: [`../.github/instructions/nexus.instructions.md`](../.github/instructions/nexus.instructions.md)
