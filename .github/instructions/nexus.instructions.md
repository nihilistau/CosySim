---
description: 'Nexus Knowledge System usage patterns — how coding agents and the Copilot CLI should leverage Nexus for research, Q&A, knowledge storage, and development workflows'
applyTo: 'engine/nexus/**/*.py,engine/skills/builtin/nexus_skills.py,engine/skills/builtin/coding_skills.py'
---

# Nexus Knowledge System — Agent Usage Guide

Nexus is the central knowledge backbone. Treat CosySim governance as
**repository + Nexus synchronized**: the repo is the live editable surface, and
Nexus is the durable mirrored memory/rules layer.

Every coding agent should use Nexus as the **first port of call** for
information retrieval, storage, and rules.

## When to Use Nexus

### Before Starting Work
1. **Query Nexus first** — `nexus_smart_query("question")` before writing code.
   Use `nexus_search("topic")` or `nexus_ask("question")` when you need more
   explicit control. Check if there's an existing answer, design decision, or
   pattern before spending more compute.
2. **Check rules** — `nexus_get_rules(scope="scene:X")` to understand constraints.
3. **Load prompts** — `nexus_get_prompts(category="system")` for stored system prompts.

### During Work
4. **Store decisions** — When making an architecture or design decision, store it:
   `nexus_add(title="Decision: X", content="...", content_type="note", category="architecture")`
5. **Log sessions** — `nexus_log_session(project="CosySim", summary="what I did")`
6. **Store code snippets** — Reusable patterns, templates, boilerplate via
   `coding_store_snippet(title, code, language, tags)`
7. **Keep durable outputs recoverable** — histories, changelog notes, memories,
   rules, decisions, and learned improvements belong in Nexus rather than only
   transient chat context.
8. **Backfill Nexus misses** — If Nexus does not contain the answer and you find
   it elsewhere, write it back into Nexus before finishing the task. Prefer
   both:
   - a reusable knowledge entry
   - a direct Q&A pair for the discovered question

### After Work
9. **Store Q&A** — If you answered a question during work, cache it for future agents:
   `nexus_ask` stores answers automatically, or explicitly via `add_qa()`
10. **Research results** — `nexus_finish_research(research_id)` distills Q&A pairs
11. **Preserve session outputs** — make sure histories, changelog-worthy outcomes,
    decisions, and improvements are stored back into Nexus for reuse by later
    agents.

## Smart Query Router (Preferred Entry Point)

**Always use `nexus_smart_query` as the primary way to ask questions.**
It provides a 4-tier pipeline that checks all Nexus sources before falling
back to an LLM, and auto-stores LLM answers for future reuse:

```
1. Q&A Cache (instant)  →  Previously answered questions
2. FTS5 Search (fast)   →  Synthesize from existing knowledge entries
3. Nexus Ask (smart)    →  Server-side pipeline (cache → FTS → NLM)
4. LLM Fallback (last)  →  LMStudio call, auto-stored back in Nexus
```

- MCP tool: `nexus_smart_query(question, min_confidence=0.3, use_llm=true, category="")`
- Python: `from engine.nexus.query_router import get_query_router; get_query_router().query("question")`
- Returns: `{answer, source, confidence, cached, tokens_saved, query_time_ms}`
- Stats: `nexus_router_stats()` — shows hit rates, cache performance, tokens saved

**Every LLM answer is auto-cached** — the next time anyone asks the same question,
Nexus answers instantly without using tokens. This is the core of the
"always be improving Nexus" loop.

If MCP tools are unavailable, fall back to `python -m engine.nexus.bridge ...`,
but do not invert the order: the bridge is fallback, `nexus_smart_query` is the
preferred front door whenever the MCP path is available.

Useful bridge helpers:

```powershell
python -m engine.nexus.bridge backfill "Question?" "Answer." --source "docs/path"
python -m engine.nexus.bridge inventory --store
```

- `backfill` stores a reusable note plus a Q&A pair when knowledge was found
  outside Nexus.
- `inventory --store` snapshots the canonical system split into Nexus for later
  retrieval by agents and operators.

## Smart Q&A Pipeline

The `nexus_ask(question, depth)` skill uses a 3-tier lookup:

```
1. Q&A Cache (instant)  →  Previously answered questions
2. FTS5 Search (fast)   →  Synthesize from existing knowledge entries
3. NLM Research (deep)  →  NotebookLM notebook-backed research
```

The `NexusQueryRouter` adds a 4th tier (LLM fallback) and auto-stores answers:
```
4. LLM Fallback (slow)  →  Send to LMStudio, store answer in Nexus
```

- Use `depth="shallow"` for quick lookups (no NLM)
- Use `depth="deep"` when you need thorough research
- Use `depth="auto"` (default) to let the system decide

## NotebookLM Sequencing

NotebookLM is a deep-research lane, not the first operational dependency.

Required order:
1. restore or verify NotebookLM authentication
2. restore or verify library health and notebook inventory
3. use NotebookLM for deeper research/distillation
4. store distilled outputs back into Nexus
5. let future `nexus_smart_query` calls reuse that result

Do not describe NotebookLM as the main working dependency while auth or library
recovery is still unfinished.

## Research Sessions

For multi-step research:
```
1. nexus_research("question")        → starts session, returns research_id
2. nexus_converse(research_id, msg)  → follow-up questions
3. nexus_finish_research(research_id) → distill Q&A, store artifacts
```

## YouTube Import

Import video knowledge: `nexus_youtube(url, category="tutorial")`
Extracts: metadata, full transcript, timestamps, concepts, auto-tags.

## NexusClient API (Python)

```python
from engine.nexus.client import get_nexus_client
client = get_nexus_client()

# Smart Q&A
result = client.ask("How does the interceptor pipeline work?")
# → {answer, source, confidence, sources, qa_id}

# Research
session = client.research("Best practices for MCP state management")
followup = client.converse(session["research_id"], "What about persistence?")
done = client.finish_research(session["research_id"])

# YouTube
transcript = client.import_youtube("https://youtube.com/watch?v=...")

# Knowledge CRUD
client.add_entry("Title", "Content", content_type="note", category="dev")
results = client.search("query")
client.add_qa("Question?", "Answer.", category="dev")
```

## Content Types

| Type | Use For |
|------|---------|
| `note` | General knowledge, observations |
| `code` | Code snippets, patterns, templates |
| `prompt` | System/agent prompts (versioned) |
| `document` | Design docs, specs, guides |
| `transcript` | YouTube/video transcripts |
| `research` | Research session artifacts |
| `memory` | Agent memories/observations |
| `history` | Session histories, changelogs |
| `plan` | Implementation plans |

## Categories for Development

| Category | Scope |
|----------|-------|
| `architecture` | Design decisions, patterns |
| `api` | API docs, endpoint specs |
| `debugging` | Bug analysis, fixes, workarounds |
| `testing` | Test strategies, patterns |
| `performance` | Optimization notes, benchmarks |
| `training` | Fine-tuning, prompt engineering |
| `system` | System-level config, rules |
