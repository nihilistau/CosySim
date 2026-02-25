---
description: 'Nexus Knowledge System usage patterns — how coding agents and the Copilot CLI should leverage Nexus for research, Q&A, knowledge storage, and development workflows'
applyTo: 'engine/nexus/**/*.py,engine/skills/builtin/nexus_skills.py,engine/skills/builtin/coding_skills.py'
---

# Nexus Knowledge System — Agent Usage Guide

Nexus is the central knowledge backbone. Every coding agent should use it as
**first port of call** for information retrieval, storage, and rules.

## When to Use Nexus

### Before Starting Work
1. **Search first** — `nexus_search("topic")` or `nexus_ask("question")` before
   writing code. Check if there's an existing answer, design decision, or pattern.
2. **Check rules** — `nexus_get_rules(scope="scene:X")` to understand constraints.
3. **Load prompts** — `nexus_search_prompts(category="system")` for stored system prompts.

### During Work
4. **Store decisions** — When making an architecture or design decision, store it:
   `nexus_add(title="Decision: X", content="...", content_type="note", category="architecture")`
5. **Log sessions** — `nexus_log_session(project="CosySim", summary="what I did")`
6. **Store code snippets** — Reusable patterns, templates, boilerplate via
   `coding_store_snippet(title, code, language, tags)`

### After Work
7. **Store Q&A** — If you answered a question during work, cache it for future agents:
   `nexus_ask` stores answers automatically, or explicitly via `add_qa()`
8. **Research results** — `nexus_finish_research(research_id)` distills Q&A pairs

## Smart Q&A Pipeline

The `nexus_ask(question, depth)` skill uses a 3-tier lookup:

```
1. Q&A Cache (instant)  →  Previously answered questions
2. FTS5 Search (fast)   →  Synthesize from existing knowledge entries
3. NLM Research (deep)  →  NotebookLM notebook-backed research
```

- Use `depth="shallow"` for quick lookups (no NLM)
- Use `depth="deep"` when you need thorough research
- Use `depth="auto"` (default) to let the system decide

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
