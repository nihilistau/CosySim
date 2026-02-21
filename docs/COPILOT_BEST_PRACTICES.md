# Copilot CLI Best Practices — A Personal Field Guide

> Tailored for: i9 NUC Beast Canyon · 32 GB RAM · RTX 2060 12 GB · LMStudio · ComfyUI · Google Colab Pro

---

## Table of Contents

1. [Mindset & Philosophy](#1-mindset--philosophy)
2. [Token & Request Economy](#2-token--request-economy)
3. [Crafting Effective Prompts](#3-crafting-effective-prompts)
4. [Models — When to Use What](#4-models--when-to-use-what)
5. [Subagents & Delegation](#5-subagents--delegation)
6. [Starting Projects from Scratch](#6-starting-projects-from-scratch)
7. [Continuing & Handing Over Projects](#7-continuing--handing-over-projects)
8. [Context Management](#8-context-management)
9. [Guidelines, Guardrails & Instructions](#9-guidelines-guardrails--instructions)
10. [CLI vs VS Code — When to Use Which](#10-cli-vs-vs-code--when-to-use-which)
11. [Google Colab Pro Integration](#11-google-colab-pro-integration)
12. [Your Local Stack — LMStudio + ComfyUI + Copilot](#12-your-local-stack--lmstudio--comfyui--copilot)
13. [Organising Thoughts & Projects](#13-organising-thoughts--projects)
14. [Templates & Examples](#14-templates--examples)
15. [Efficiency Checklist](#15-efficiency-checklist)

---

## 1. Mindset & Philosophy

### Think of Copilot as a Junior-to-Mid Developer

It's brilliant at execution but needs clear direction. Your job shifts from *writing code*
to *managing and reviewing work*. The better your direction, the better the output.

### The 80/20 Rule

- **80% of value** comes from clear problem statements, good context, and solid instructions
- **20% comes from the actual prompting syntax** — don't overthink it, focus on *what* not *how*

### Be a Director, Not a Typist

Don't describe code line-by-line. Describe **outcomes**:
- ❌ "Add a function called `calculate_total` that takes a list of items and loops through them..."
- ✅ "Add a total calculation function for the cart items. Should handle empty carts and discount codes."

### Trust but Verify

Let the agent work autonomously, then spot-check critical paths. Use `/review` and test suites to catch issues.

---

## 2. Token & Request Economy

### How Requests Are Counted

Each time you submit a prompt, **one premium request** is consumed.  Model multipliers apply:

| Model | Multiplier | Cost per Request |
|-------|-----------|-----------------|
| Claude Sonnet 4 / 4.5 | 1× | 1 request |
| GPT-5.1-Codex-Mini | 0.25× | 0.25 requests |
| GPT-5-mini | 0.25× | 0.25 requests |
| Claude Opus 4.5 / 4.6 | 3× | 3 requests |
| GPT-5.2 Codex | 1× | 1 request |

### Maximise Value Per Request

1. **Batch related asks into one prompt** — don't send 5 messages when 1 will do
2. **Front-load context** — include file references, constraints, and desired output format
3. **Use `@file` references** instead of pasting code — cheaper and the agent reads the live file
4. **Use plan mode for complex work** — one request to plan, one to execute. Far cheaper than 10 iterative requests
5. **Use subagents** (explore, task) — they're cheaper models doing focused work

### When to Use Cheap vs Expensive

| Situation | Model Choice | Why |
|-----------|-------------|-----|
| Planning, architecture, complex debugging | Opus 4.5/4.6 | Deep reasoning, fewer iterations |
| Day-to-day coding, file edits | Sonnet 4/4.5 (default) | Best balance of quality and cost |
| Running tests, builds, linting | Task subagent (Haiku) | Just needs pass/fail, very cheap |
| Codebase questions | Explore subagent (Haiku) | Fast read-only analysis |
| Code review | `/review` | Dedicated review agent |
| Bulk simple changes | GPT-5.1-Codex-Mini | 0.25× cost, good for repetitive edits |

### The Golden Rule

> Spend expensive tokens on **thinking and planning**.
> Spend cheap tokens on **executing and verifying**.

---

## 3. Crafting Effective Prompts

### Structure of a Great Prompt

```
[CONTEXT] → What the agent needs to know
[TASK]    → What you want done
[CONSTRAINTS] → Boundaries and requirements
[OUTPUT] → What success looks like
```

### Examples

**Bad prompt:**
```
fix the bug
```

**Good prompt:**
```
The phone scene's autotxt timer fires too frequently for characters with 
low trust scores. The cooldown calculation is in phone_rules_v2.py around 
line 50. Minimum cooldown should be 60 seconds regardless of trust level. 
Fix the calculation and add a test.
```

**Great prompt (for complex work):**
```
I need to add voice message support to the phone scene.

Context:
- Phone scene is in content/scenes/phone/phone_scene_v2.py
- TTS service runs on port 8600 (see docs/TTS.md)
- Voice messages should be stored in content/simulation/media/voice/
- The existing generate_voice skill in engine/skills/builtin/voice_skills.py 
  already handles TTS API calls

Requirements:
- New "voice" message type alongside "text" and "image"
- Record button in the UI sends text → TTS → audio file → message
- Playback in the chat thread with a waveform display
- Characters can also send voice messages autonomously

Don't change the database schema — use the existing media_type field.
Test that the skill generates audio and the route serves it.
```

### Prompt Templates

#### Quick Fix
```
Fix [specific issue] in @path/to/file.py. The problem is [description]. 
Expected behavior: [what should happen]. Keep changes minimal.
```

#### New Feature
```
Add [feature] to [component]. 

Context: [relevant files and how they relate]
Requirements: [bullet list]
Constraints: [what NOT to do, limits, compatibility]
```

#### Refactor
```
Refactor @path/to/file.py to [goal]. 

Keep the public API identical. Current issues:
- [issue 1]
- [issue 2]

Run existing tests after changes to verify nothing breaks.
```

#### Investigation
```
I'm seeing [symptom]. Help me trace it:
1. What code path handles [relevant flow]?
2. Where could [problem] originate?
3. Suggest a fix with minimal changes.
```

---

## 4. Models — When to Use What

### Copilot CLI Models

Switch with `/model` at any time during a session.

| Model | Strengths | Best For | Request Cost |
|-------|-----------|----------|-------------|
| **Claude Sonnet 4.5** | Fast, reliable, great at code | Default choice for everything | 1× |
| **Claude Sonnet 4** | Similar to 4.5, slightly different style | Alternative default | 1× |
| **Claude Opus 4.5** | Deepest reasoning, best at complex tasks | Architecture, hard bugs, planning | 3× |
| **Claude Opus 4.6** | Latest Opus, enhanced capabilities | Complex multi-file changes | 3× |
| **GPT-5.2 Codex** | Strong code generation | Code review, second opinion | 1× |
| **GPT-5.1-Codex** | Fast code generation | Routine implementations | 1× |
| **GPT-5.1-Codex-Mini** | Very cheap, decent quality | Bulk repetitive changes | 0.25× |
| **Claude Haiku 4.5** | Fastest, cheapest Claude | Subagent work (explore, task) | ~0.25× |

### Strategy: Model Cascade

For a big feature:

1. **Opus** → Create the plan (1 request × 3 = 3 premium)
2. **Sonnet** → Implement each task (N requests × 1 = N premium)  
3. **Task subagent (Haiku)** → Run tests after each change (cheap)
4. **Codex** → Final code review (1 request × 1 = 1 premium)

### Your Local Models (LMStudio)

Your local LLMs complement Copilot — use them for tasks that don't need Copilot's codebase awareness:

| Local Model | VRAM | Use For |
|-------------|------|---------|
| Qwen 2.5 7-14B | 5-8 GB | Character dialog, in-app AI responses |
| Qwen 2.5 3B | 2 GB | Quick classifications, structured output |
| Qwen 2.5 0.5B | 0.5 GB | Speculative decoding draft model |

**Rule of thumb:** If the task needs to read/write your codebase → Copilot. If the task is runtime AI behavior → local model.

---

## 5. Subagents & Delegation

### Built-in Subagents

The CLI automatically delegates to specialised sub-agents:

| Agent | Model | Purpose | When Used |
|-------|-------|---------|-----------|
| **explore** | Haiku (fast) | Read-only codebase analysis | "How does X work?", "Find files matching Y" |
| **task** | Haiku (fast) | Run commands, return pass/fail | Tests, builds, installs, linting |
| **general-purpose** | Sonnet | Complex multi-step tasks | Heavy work that needs isolation |
| **code-review** | Sonnet | Review diffs for real issues | `/review` or explicit review requests |

### How to Trigger Subagents

The main agent decides automatically, but you can nudge:

```
# Explicit delegation hints
"Explore the authentication flow — don't change any code"  → explore
"Run the test suite and report failures"                    → task
"Review my staged changes for bugs"                         → code-review
```

### Multiple Subagents in Parallel

The agent can launch multiple explore agents simultaneously:
```
"I need to understand both the phone scene message flow AND the bedroom 
agent loop. Explore both and summarise the key differences."
```

### `/delegate` to Cloud

Push work to GitHub Copilot coding agent (runs in the cloud):

```
/delegate Add comprehensive API documentation to the README. 
Include examples for every endpoint in the phone and bedroom scenes.
```

**Use `/delegate` for:**
- Work you don't need to watch live
- Documentation, formatting, cleanup
- Changes to other repos
- Tasks while you context-switch to something else

---

## 6. Starting Projects from Scratch

### The Recipe

```
Step 1: Think → Write a brief (2-5 sentences) about what you want
Step 2: Plan  → Use plan mode to create architecture
Step 3: Build → Implement task by task
Step 4: Test  → Verify each piece works
Step 5: Polish → Refactor, document, clean up
```

### Step 1: The Brief

Before opening Copilot, write a short description for yourself:
```
I want to build [X] that does [Y].
It should use [technology/framework].
The main features are [A, B, C].
It needs to integrate with [existing thing].
```

### Step 2: Plan with Opus

```
/model
# Select Opus 4.5

/plan I want to build a new CosySim scene called "Garden" — an outdoor 
space with a greenhouse. Two characters: Ivy (botanist) and Rex (the cat). 
Uses the full MCP framework. The scene should showcase plant growth 
mechanics where characters tend to plants and the plants grow over time 
based on care received. Include weather events.
```

Opus will ask clarifying questions, then produce a plan.md. Review it, edit
directly in your editor (`Ctrl+Y`), then switch to Sonnet for implementation:

```
/model
# Select Sonnet 4.5

Implement the plan. Start with task 1.
```

### Step 3: Build Incrementally

Don't ask for everything at once. Go task by task:

```
Complete task 1 from the plan, then run tests.
```

Wait for completion, review, then:

```
Continue with task 2.
```

### Step 4: Test Continuously

After every significant change:
```
Run the tests and fix any failures related to the changes you just made.
```

### Step 5: Polish

```
/review Check all the changes made in this session for bugs, 
missing error handling, and consistency with the existing codebase style.
```

---

## 7. Continuing & Handing Over Projects

### Resuming Work

```bash
# Resume most recent session
copilot --continue

# Browse and select a session
copilot --resume
```

Or within a session:
```
/resume
```

### Session Continuity

Copilot automatically saves session state including:
- Conversation history (compressed via checkpoints)
- Implementation plans (plan.md)
- File changes made
- Session artifacts

### Handover Documents

When handing a project to a new Copilot session (or another developer), create:

1. **`AGENT_NOTES.md`** — System architecture, file dependencies, key singletons
2. **`ONBOARDING.md`** — How to set up, build, and run the project
3. **`QUICK_START.md`** — The 5-minute version of getting started

### The Handover Prompt

When starting a new session on an existing project:

```
Read @AGENT_NOTES.md to understand the codebase architecture. Then read
@ONBOARDING.md for setup instructions. I want to [describe next task].
Start by exploring the relevant files, then propose a plan.
```

### Custom Instructions for Consistency

Create `.github/copilot-instructions.md` in your repo:

```markdown
## CosySim Project

### Build & Test
- Run tests: `python -m pytest tests/test_config.py tests/test_skills.py tests/test_event_chain.py -v --tb=short`
- Config access: `from engine.config import get_config; config = get_config()`
- Test command verified working: 23 tests, ~3.7s

### Architecture
- 3-layer: engine/ (reusable), content/ (game), config/ (YAML)
- Scenes are Flask+SocketIO apps on separate ports
- MCPFramework is the root singleton: `get_framework()`

### Code Style
- Use type hints on all function signatures
- Skills use @skill(pack="X", tags=[...]) decorator
- Prefer dataclasses over dicts for structured data
- Comment only when clarification is needed

### Git
- Conventional commits with scope: `feat(phone): add voice messages`
- Always include Co-authored-by trailer for Copilot
```

---

## 8. Context Management

### How Context Works

Copilot has a token window (~200K tokens for most models). Everything in the
conversation — your prompts, agent responses, file contents, tool results — fills this window.

### Keep Context Clean

| Do | Don't |
|----|-------|
| Reference files with `@path/to/file` | Paste large code blocks into chat |
| Use focused, specific prompts | Ask vague questions that trigger big scans |
| Clear between unrelated tasks (`/clear`) | Let unrelated history pile up |
| Use subagents for exploration | Ask the main agent to grep through everything |

### The `/compact` Command

Compresses conversation history into a summary. Use when:
- You've been chatting a while and responses feel slower
- You're switching to a different task within the same session
- `/context` shows you're above 70% utilisation

Copilot auto-compacts at 95%, but proactive compaction gives better summaries.

### The `/context` Command

Shows token usage breakdown. Check this periodically:
```
/context
```

### File References vs Pasting

```
# GOOD — Agent reads the file, efficient token use
Explain @engine/lmstudio/lms_client.py

# BAD — Wastes tokens, may be outdated
Here's the code: ```python ... 500 lines ... ```
```

### Session Files

Copilot stores session artifacts in `~/.copilot/session-state/{id}/files/`.
Use this for persistent notes that shouldn't be committed:

```
Save this architecture diagram to the session files, not the repo.
```

---

## 9. Guidelines, Guardrails & Instructions

### Instruction File Hierarchy

Copilot reads instructions from multiple sources (highest priority first):

| File | Scope | Use For |
|------|-------|---------|
| `AGENTS.md` | Repo (git root) | Agent-specific instructions |
| `.github/instructions/**/*.instructions.md` | Repo (path-specific) | Per-directory rules |
| `.github/copilot-instructions.md` | Repo | Build commands, style, conventions |
| `~/.copilot/copilot-instructions.md` | Global (all repos) | Personal preferences |

### Writing Good Instructions

**Be specific and actionable:**

```markdown
## Testing
- Always run `npm test` after making changes
- New features require at least one unit test
- Test files go in tests/ directory, named test_*.py
```

**Set boundaries:**

```markdown
## Restrictions
- Never modify files in engine/mcp/framework.py without explicit permission
- Don't add new dependencies without asking first
- Keep individual functions under 50 lines
```

**Define patterns:**

```markdown
## Patterns
- Use `get_config().get("section.key", default)` for config access
- New skills use @skill(pack="pack_name", tags=[...]) decorator
- Scene classes inherit from BaseScene and MCPSceneMixin
```

### Custom Agents

Create specialised agents for repeated workflows. Place in `.github/agents/`:

```markdown
---
name: scene-builder
description: Expert at creating new CosySim scenes
tools:
  - shell
  - edit
  - create
  - view
  - grep
  - glob
---

You are a CosySim scene developer. You create new scenes following the 
established patterns. Always:

1. Read @AGENT_NOTES.md first to understand the architecture
2. Use BaseScene + MCPSceneMixin as base classes
3. Mount the control overlay: `from engine.overlay import mount_overlay`
4. Register with the framework via MCPSceneMixin
5. Create templates/, static/, and rules files
6. Add to launcher.py
7. Run tests after changes
```

---

## 10. CLI vs VS Code — When to Use Which

### CLI Strengths

| Feature | CLI Advantage |
|---------|--------------|
| **Agentic workflows** | Full autonomous execution, tool approval flow |
| **Shell integration** | Runs commands directly, sees output, iterates |
| **Plan mode** | Structured planning with plan.md persistence |
| **Session management** | Resume, delegate, share sessions |
| **Multi-repo work** | `/add-dir` spans multiple repos easily |
| **Custom agents** | `.github/agents/` directory support |
| **Background delegation** | `/delegate` to cloud coding agent |

### VS Code Strengths

| Feature | VS Code Advantage |
|---------|-------------------|
| **Inline completions** | Tab-complete as you type |
| **Chat panel** | Side-by-side with code, visual context |
| **Diagnostics** | Language server errors, warnings |
| **Multi-cursor edits** | Visual bulk editing |
| **File explorer** | Navigate visually |
| **Extensions** | Git graph, debugger, etc. |

### Recommended Workflow

```
1. Start in VS Code for browsing, understanding code visually
2. Switch to CLI for heavy implementation work (plan → build → test)
3. Return to VS Code for visual review, manual tweaks, debugging
4. Use CLI for commit, PR creation, delegation
```

### Both Together

You can have VS Code open AND Copilot CLI running simultaneously. Use:
- VS Code: Browse files, check diagnostics, manual edits
- CLI: Execute plans, run tests, manage Git workflow

Connect them with `/ide` in the CLI to get diagnostics from VS Code.

---

## 11. Google Colab Pro Integration

### Your Budget: ~190 credits/month

Google Colab Pro gives you access to GPUs (T4, A100, L4) and high-RAM runtimes.

### When to Use Colab vs Local vs Copilot

| Task | Best Tool | Why |
|------|-----------|-----|
| **Code generation, editing** | Copilot CLI | Understands your codebase, integrated tools |
| **Model fine-tuning** | Colab (A100) | You don't have enough local VRAM |
| **Large batch inference** | Colab (A100) | 40-80 GB VRAM for big models |
| **Runtime AI (character dialog)** | Local LMStudio | Low latency, no internet dependency |
| **Image generation** | Local ComfyUI | Your RTX 2060 handles SD/SDXL fine |
| **Data processing, analysis** | Colab (high-RAM) | 50+ GB RAM for large datasets |
| **Training embeddings** | Colab (T4) | Cheap GPU for embedding models |
| **Experimentation with new models** | Colab | Try models too big for local |

### Credit-Efficient Colab Strategies

1. **Use T4 when possible** (~1 credit/hour) — sufficient for most inference and small training
2. **A100 only for training** (~6 credits/hour) — close notebook when not actively training
3. **High-RAM CPU** (~0.5 credits/hour) — for data processing, no GPU needed
4. **Disconnect when idle** — Colab still charges for connected runtimes
5. **Batch your GPU work** — queue up all GPU tasks, do them in one session

### Colab + CosySim Workflow

```
Local Development (Copilot CLI + LMStudio):
├── Write code, test, iterate
├── Run characters on local LMStudio (7-14B models)
└── Generate images locally with ComfyUI

Colab (for what local can't do):
├── Fine-tune a character personality model (needs A100)
├── Run inference benchmarks on larger models (30B+)
├── Train custom embeddings for RAG memory system
├── Process large conversation datasets
└── Experiment with models before committing to local use
```

### Colab Notebook Templates

**Fine-tuning a character model:**
```python
# Use Colab A100 runtime for this (~6 credits/hour)
# Target: 1-2 hours = ~12 credits

# Install
!pip install unsloth transformers datasets peft

# Load base model (too big for your RTX 2060)
from unsloth import FastLanguageModel
model, tokenizer = FastLanguageModel.from_pretrained(
    "unsloth/Qwen2.5-14B-Instruct",
    max_seq_length=4096,
    load_in_4bit=True,
)

# Train on your character dialog data
# Export quantized GGUF for local LMStudio use
model.save_pretrained_gguf("character_model", tokenizer, quantization_method="q4_k_m")
# Download the GGUF → load in LMStudio locally
```

**Running a big model for evaluation:**
```python
# Use Colab A100 to test if a model is worth running locally
!pip install vllm

from vllm import LLM, SamplingParams
llm = LLM(model="Qwen/Qwen2.5-32B-Instruct", tensor_parallel_size=1)

# Test with your actual CosySim prompts to see quality
prompts = [
    "You are Aria, a warm companion. User says: Hey, what are you thinking about?",
    "You are Dealer Jack, calm and precise. The player just went all-in.",
]
outputs = llm.generate(prompts, SamplingParams(temperature=0.7, max_tokens=500))
```

### Monthly Budget Allocation (190 credits)

| Activity | Credits | Frequency |
|----------|---------|-----------|
| Character fine-tuning (A100, 2h) | ~12 | 1-2× per month |
| Model evaluation (A100, 1h) | ~6 | 2-3× per month |
| Embedding training (T4, 3h) | ~3 | 2× per month |
| Data processing (High-RAM, 5h) | ~2.5 | 4× per month |
| Experimentation buffer | ~140 | As needed |

---

## 12. Your Local Stack — LMStudio + ComfyUI + Copilot

### The Ecosystem

```
┌─────────────────────────────────────────────────────────┐
│                    Your Development Setup                │
├──────────────┬──────────────┬───────────────────────────┤
│  Copilot CLI │  VS Code     │  Browser                  │
│  (code)      │  (edit)      │  (scenes, admin, overlay) │
├──────────────┴──────────────┴───────────────────────────┤
│                  Your i9 NUC + RTX 2060                 │
├──────────────┬──────────────┬───────────────────────────┤
│  LMStudio    │  ComfyUI     │  CosySim Scenes           │
│  :1234       │  :8188       │  :5555-5559               │
│  7-14B LLMs  │  SD/SDXL     │  Flask+SocketIO           │
└──────────────┴──────────────┴───────────────────────────┘
```

### VRAM Sharing Strategy

You have 12 GB VRAM. Here's how to share it:

| Configuration | LMStudio | ComfyUI | Free | Best For |
|---------------|----------|---------|------|----------|
| **Dev mode (code only)** | 0 GB | 0 GB | 12 GB | Writing code with Copilot |
| **Chat testing** | 5 GB (8B Q4) | 0 GB | 7 GB | Testing character conversations |
| **Full scene testing** | 5 GB (8B Q4) | 4 GB (SDXL) | 3 GB | Full scene with image gen |
| **Big model eval** | 8 GB (14B Q4) | 0 GB | 4 GB | Quality testing single agent |

**ResourceManager strategies** handle this automatically — set strategy in config:
- `concurrent` for chat testing (one model, parallel requests)
- `hybrid` for full scene (GPU model + CPU background)
- `jit_swap` for variety (load/unload as needed)

### When Each Tool Runs

| Time | Activity | Tool |
|------|----------|------|
| **Coding** | Writing features, debugging | Copilot CLI + VS Code |
| **Testing** | Running scenes, checking character behavior | LMStudio + Browser |
| **Content** | Generating character images, voice | ComfyUI + TTS service |
| **Training** | Fine-tuning models | Google Colab (A100) |
| **Overnight** | Background batch tasks | CosySim ResourceManager (CPU mode) |

### Overnight Processing

Use ResourceManager's background queue for CPU-bound tasks overnight:

```python
rm = get_resource_manager()
rm.queue_background_task("batch_portraits", generate_all_portraits, device="cpu")
rm.queue_background_task("memory_index", rebuild_rag_index, device="cpu")
```

These run on CPU threads while the GPU sleeps.

---

## 13. Organising Thoughts & Projects

### Documentation Hierarchy

```
Project Root/
├── README.md              ← What it is, how to install and run
├── AGENT_NOTES.md         ← System architecture (for AI agents)
├── ONBOARDING.md          ← Developer setup guide
├── QUICK_START.md         ← 5-minute getting started
├── CHANGELOG.md           ← Version history
├── docs/
│   ├── STRUCTURE_GUIDE.md ← Detailed architecture
│   ├── SKILLS.md          ← Skill system reference
│   ├── API.md             ← API endpoint reference
│   └── *.md               ← Feature-specific docs
├── .github/
│   ├── copilot-instructions.md ← Copilot repo instructions
│   ├── agents/            ← Custom Copilot agents
│   └── instructions/      ← Path-specific instructions
└── config/
    └── default.yaml       ← All configurable settings
```

### The Three Documents Every Project Needs

1. **`README.md`** — For humans: what, why, how to install, how to run
2. **`AGENT_NOTES.md`** — For AI agents: file dependencies, singletons, patterns, architecture
3. **`.github/copilot-instructions.md`** — For Copilot: build commands, style rules, conventions

### Thinking Before Prompting

Before opening Copilot, spend 2 minutes answering:

1. **What** do I want to build/fix/change?
2. **Where** in the codebase does this live?
3. **What files** are involved?
4. **What constraints** exist? (compatibility, performance, style)
5. **How will I verify** it works?

Write these answers in your prompt. This alone will 10× your results.

### Project Planning Method

For new features or projects:

```
1. BRIEF (5 min)     — Write 3-5 sentences describing the goal
2. EXPLORE (5 min)   — Ask Copilot to explore relevant code  
3. PLAN (10 min)     — Use plan mode, review the plan
4. IMPLEMENT (varies) — Execute task by task with Sonnet
5. REVIEW (5 min)    — Use /review for quality check
6. DOCUMENT (5 min)  — Update relevant docs
7. COMMIT (2 min)    — Meaningful commit message
```

---

## 14. Templates & Examples

### Template: Starting a New Session

```
I'm working on CosySim. Read @AGENT_NOTES.md for architecture context.

Today I want to: [describe goal]

Relevant files:
- @path/to/file1.py
- @path/to/file2.py

Constraints:
- [list any constraints]

Start by exploring the relevant code, then propose a plan.
```

### Template: Bug Fix

```
Bug: [describe the symptom]
Reproduction: [steps or trigger]
Expected: [correct behavior]
Actual: [wrong behavior]

Likely location: @path/to/file.py around line [N]
Related: @path/to/related.py

Fix the bug with minimal changes. Add a test if one doesn't exist.
```

### Template: Feature Addition

```
Feature: [name]
Goal: [1-2 sentences]

Must integrate with:
- [existing system 1]
- [existing system 2]

Requirements:
- [ ] [requirement 1]
- [ ] [requirement 2]
- [ ] [requirement 3]

Use plan mode. Start with architecture.
```

### Template: Code Review Request

```
/review Focus on:
1. Correctness — any logic bugs?
2. Error handling — are edge cases covered?
3. Performance — any obvious bottlenecks?
4. Consistency — does it match existing patterns in the codebase?

Ignore style and formatting issues.
```

### Template: Handover to New Session

```
Read the following files to understand this project:
1. @AGENT_NOTES.md — Full architecture
2. @CHANGELOG.md — Recent changes (see latest entry)
3. @.github/copilot-instructions.md — Build and style rules

Current state:
- [what was last done]
- [what needs to be done next]
- [any known issues]

Continue from where we left off: [specific next task]
```

---

## 15. Efficiency Checklist

### Before Every Session

- [ ] Know what you want to achieve (write it down, even if just mentally)
- [ ] Have relevant file paths ready
- [ ] Check if custom instructions are up to date

### During a Session

- [ ] Use `@file` references instead of pasting code
- [ ] Batch related requests into single prompts
- [ ] Use plan mode for complex multi-file changes
- [ ] Run tests after every significant change
- [ ] Use `/compact` proactively if context is filling up
- [ ] Switch to cheaper models for routine work

### After a Session

- [ ] Review changes with `/review` or `/diff`
- [ ] Commit with meaningful message
- [ ] Update documentation if architecture changed
- [ ] Update `AGENT_NOTES.md` if new patterns were established

### Weekly

- [ ] Check `/usage` to understand your request consumption
- [ ] Review custom instructions — are they still accurate?
- [ ] Clean up old session artifacts
- [ ] Plan Colab credit usage for the week

---

## Quick Reference Card

```
SHORTCUTS
  Shift+Tab    → Toggle plan mode
  Ctrl+T       → Toggle reasoning display
  Ctrl+S       → Send while preserving input
  Ctrl+O       → Expand recent timeline
  @file        → Include file in context
  !command     → Run shell command directly
  Esc          → Cancel current operation

SLASH COMMANDS
  /model       → Switch AI model
  /plan        → Create implementation plan
  /review      → Code review agent
  /diff        → Review uncommitted changes
  /delegate    → Push to cloud coding agent
  /compact     → Compress context
  /context     → View token usage
  /usage       → Session statistics
  /resume      → Resume previous session
  /agent       → Browse custom agents
  /mcp         → Manage MCP servers
  /clear       → Reset conversation

WORKFLOW
  Think → Plan (Opus) → Build (Sonnet) → Test (Task) → Review (Codex) → Commit
```
