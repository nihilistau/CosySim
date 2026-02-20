# Working With Copilot CLI — A Practical Guide

How to get the most out of GitHub Copilot CLI when working on CosySim
(or any large codebase).

---

## Quick Reference

| What you want | What to say |
|---|---|
| Fix a bug | Describe the error message or behavior |
| Add a feature | Describe what it should do, where it fits |
| Review code | `Review my code changes` or `/review` |
| Run tests | `Run the tests` |
| Understand code | `How does the EventChain system work?` |
| Plan first | Press `Shift+Tab` to enter Plan mode, then describe the task |
| Multiple things at once | Tell Copilot to use sub-agents (see below) |

---

## Modes

Press **Shift+Tab** to cycle between modes:

| Mode | When to use |
|---|---|
| **Interactive** | Default. Good for conversation, small fixes, exploration |
| **Plan** | Prefix with `[[PLAN]]`. Copilot writes a plan first, then you review/edit before executing |
| **Autopilot** | (Experimental) Copilot keeps working until the task is done. Best for well-defined tasks |

**Tip:** For large tasks, start in Plan mode. Review the plan (press `Ctrl+Y` to
view `plan.md`), edit if needed, then say "start" to execute.

---

## Sub-Agents

Copilot can spin up specialized sub-agents that run in parallel. This is
the single biggest efficiency lever for large tasks.

### What are sub-agents?

Each sub-agent is an independent AI instance with its own context window.
They can run simultaneously, which means Copilot can search 5 files,
review 3 modules, and check syntax — all at once.

### Agent types

| Type | Model | Best for | Can modify files? |
|---|---|---|---|
| **explore** | Haiku (fast) | Searching code, answering questions | No |
| **task** | Haiku (fast) | Running commands (tests, builds, lints) | Yes |
| **general-purpose** | Sonnet (smart) | Complex multi-step coding tasks | Yes |
| **code-review** | Sonnet (smart) | Reviewing diffs for real bugs | No |

### When to tell Copilot to use sub-agents

Say things like:

- *"Audit the entire codebase for X — use sub-agents to check in parallel"*
- *"Fix these 5 files — spin off agents for each"*
- *"Search for all uses of EventChain and check they match the schema"*
- *"Review the phone scene and bedroom scene at the same time"*

### When sub-agents help most

✅ **Searching/reading many files** — "Find every place that imports X"
✅ **Running independent checks** — "Lint Python, check JS syntax, run tests"
✅ **Parallel code review** — "Review engine/ and content/ simultaneously"
✅ **Large refactors** — "Rename this across 20 files"

### When NOT to use them

❌ Sequential work where step 2 depends on step 1's output
❌ Simple single-file edits (just do it directly)
❌ When you need to see the full output in your conversation

### Example prompts

```
Audit all Python files for silent except blocks — use explore agents
to check engine/, content/, and tests/ in parallel.
```

```
Run the test suite and lint check at the same time using task agents.
```

```
Fix the scrolling bug in phone.js and the lighting bug in bedroom.js —
use separate general-purpose agents for each.
```

---

## How to Write Good Prompts

### Be specific about what you want

❌ *"Fix the bugs"*
✅ *"The phone scene messages appear below the input box. Fix the CSS so messages scroll above a fixed input bar."*

### Include error messages

❌ *"It's broken"*
✅ *"I get `AttributeError: 'NoneType' object has no attribute 'rstrip'` in comfyui_client.py line 232"*

### Tell it the scope

❌ *"Clean up the code"*
✅ *"Add debug logging to all silent except blocks in engine/agents/ and engine/mcp/"*

### Reference files directly

Use `@` to include file contents:

```
@engine/agents/agent_loop.py — the shared_log list grows forever.
Add pruning after each append to cap it at 200 entries.
```

### Batch related requests

Instead of 5 separate messages, combine related work:

```
Fix these 3 issues:
1. bedroom.js line 825 has orphaned code outside any function
2. launcher.py docstring references non-existent 'dev' mode
3. Add 'menace' to ACTION_ICONS in bedroom.js
```

---

## Useful Slash Commands

| Command | What it does |
|---|---|
| `/review` | Run code review on your uncommitted changes |
| `/diff` | See what files you've changed |
| `/model` | Switch AI model (Sonnet, Haiku, Opus, GPT) |
| `/tasks` | See running background agents |
| `/compact` | Shrink context when conversation gets long |
| `/context` | See how much context window is used |
| `/plan` | Create an implementation plan |
| `/mcp` | Configure MCP servers |
| `!command` | Run a shell command directly (bypass AI) |

---

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Shift+Tab` | Cycle modes (interactive → plan → autopilot) |
| `Ctrl+P` | Run command preserving your input |
| `Ctrl+T` | Toggle model reasoning display |
| `Ctrl+O` | Expand recent timeline |
| `Ctrl+L` | Clear screen |
| `Ctrl+C` | Cancel current operation |
| `Esc` | Cancel current operation |
| `↑` / `↓` | Navigate command history |

---

## CosySim-Specific Tips

### The EventChain is sacred

When asking Copilot to add features, remind it:

> "Make sure this logs to EventChain with proper chain_id linking."

### Config over code

Before hardcoding values:

> "Put this setting in config/default.yaml and read it with get_config()."

### Test after every change

> "Run the tests after making changes" — or Copilot will forget.

### The Three Pillars pattern

When adding integrations:

> "This should follow the Three Pillars pattern — CosySim orchestrates,
> LMStudio does inference, ComfyUI does generation. Don't bypass the framework."

### Graceful degradation

> "Make sure this works even if LMStudio/ComfyUI/TTS is offline."

---

## Common Workflows

### Adding a new scene

```
Create a new scene called 'cafe' following the pattern in
content/scenes/bedroom/. It should have its own Flask app on port 5557,
Three.js UI, and connect to the agent loop. Register it in launcher.py.
```

### Adding a new skill pack

```
Create a skill pack called 'weather' in engine/skills/builtin/.
Follow the pattern of memory_skills.py. It should expose 2 tools:
get_weather and set_mood_by_weather. Register in engine/skills/__init__.py.
```

### Debugging a chain issue

```
The EventChain isn't recording voice messages. Trace the flow from
content/simulation/services/voice_message.py through to the DB insert
and find where the chain breaks.
```

### Full audit

```
Audit the entire codebase for robustness:
- Check all EventChain log() calls match the schema
- Find silent except blocks
- Check for None-safety on .strip()/.rstrip() calls
Use sub-agents to parallelize across engine/ and content/.
```
