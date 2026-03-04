# CosySim — Project Journal & Onboarding Source
## A Living Record of What We Built, Why, and What We Discovered

*This document is designed to be uploaded to NotebookLM as a primary source.
It condenses the full arc of the CosySim project — from first principles through every major
breakthrough — so that any AI agent loading this as context arrives already aligned with
the project's philosophy, architecture, and accumulated wisdom.*

---

## Part 1 — Origins: What This Is and Why It Exists

CosySim began as a multi-scene AI simulation framework. Not a product. Not an app in the
conventional sense. It is a **meta-system** — an environment where AI agents can live,
interact, learn, and be evaluated in real-time, running on consumer hardware in a home lab.

The hardware is an Intel i9 NUC with an NVIDIA GPU (~12 GB VRAM). LMStudio provides the
local inference backbone. Everything runs at localhost.

The original vision: build scenes — virtual environments (a bedroom, a bar, a casino, an
arena, a neon cyberpunk city) — where language model agents inhabit characters, respond to
the user, manage state, call tools, and create experiences. Think of it as a living game
where the NPCs are real AI agents, not scripted responses.

But that original vision, while interesting, was just the surface. What the project became
is something far more ambitious.

---

## Part 2 — The Realisation: This System Can Improve Itself

Early on, the question surfaced: what if the system wasn't just a simulation framework, but
a **self-improving intelligence infrastructure**?

The shift was captured in what became known as **"Project Autonomy"** — a deliberate
decision to evolve CosySim and its companion knowledge system (Nexus) into a loop where:

1. The system observes itself
2. Stores what it learns in Nexus
3. Uses that knowledge to improve decisions
4. Trains smaller local models on the captured data
5. Those models handle more work, freeing larger models for harder tasks
6. Repeat indefinitely

This is not a metaphor. It is the literal architecture we built. Every feature, every module,
every decision since Project Autonomy has been in service of closing this loop tighter.

**The governing philosophy from that point forward:**
- Everything that can be known should be stored in Nexus
- Every interaction that can produce training signal should produce it
- Every model that can be fine-tuned on real in-system data should be
- Nexus becomes more valuable over time, not less
- The system works for itself as much as it works for the user

---

## Part 3 — Nexus: The Central Nervous System

Nexus KMS (Knowledge Management System) is the backbone. It is not a chat interface. It
is not a document store. It is the **memory, rules engine, and research centre** of the
entire system.

**What Nexus contains:**
- 8,835+ knowledge entries (growing continuously)
- 2,467+ Q&A pairs (cached answers that never need re-computing)
- 360+ governance rules across namespaces
- Research sessions (deep multi-turn investigations)
- Agent memories
- Training data metadata
- Session histories and decision logs
- NotebookLM notebook references
- URL archives with scraped content

**The Three-Layer Database Architecture:**
Nexus operates across three conceptual layers:
1. **Hot layer** — the live SQLite FTS5 database (instant search, millisecond recall)
2. **Warm layer** — Q&A cache (previously answered questions return instantly, zero LLM cost)
3. **Deep layer** — NotebookLM notebooks (structured Gemini-backed research, source-cited answers)

**The Smart Query Router (4-tier pipeline):**
When any agent or tool asks a question, it flows through:
1. Q&A Cache — if this exact question was asked before, return instantly (free)
2. FTS5 Search — synthesize from existing knowledge entries (free, milliseconds)
3. NotebookLM — route to a relevant notebook for Gemini-backed, source-cited answer (free)
4. LMStudio LLM — local model inference, last resort (costs GPU cycles)

Every answer from Tier 4 is automatically stored back into Tier 1. The system gets cheaper
to operate over time as the cache fills. This is the compounding effect of the knowledge
architecture.

**The Nexus-First Mandate (enforced rule):**
Before ANY task, every agent must:
1. `nexus_search("topic")` — check existing knowledge
2. `nexus_get_rules("scope")` — understand constraints
3. `nexus_get_prompts("category")` — use stored, versioned prompts

After ANY task, every agent must:
4. Store decisions as knowledge entries
5. Cache Q&A pairs discovered during work
6. Log the session with summary

**The Governance Rules System:**
Nexus enforces rules by namespace:
- `global` — absolute rules for all code (no print(), absolute imports, type hints, etc.)
- `scene:*` — scene construction rules (inherit BaseScene, register MCP node, etc.)
- `agent:*` — agent behaviour rules (pass governance_context, use @skill for tools)
- `testing` — test standards (pytest, mock everything, AAA pattern)
- `namespace:copilot` — Copilot agent rules (search Nexus first, store decisions, never skip)
- `namespace:training` — training data governance

These rules are not documentation. They are enforced. The `@governed` decorator and
`enforce_governance()` function raise exceptions on violations. The system cannot be used
incorrectly if the rules are followed.

---

## Part 4 — LMStudio: The Local Inference Engine

LMStudio runs at `localhost:1234` and provides the inference backbone. It is **always on**.
The headless server mode means it starts with the machine and never needs to be launched
manually.

**The v1 API Migration — A Critical Inflection Point:**
The project underwent a complete migration away from OpenAI-compatible API endpoints to
LMStudio's native v1 REST API. This was not a trivial change — it required rewriting the
entire agent stack. But the capabilities unlocked were essential:

- **Stateful conversations**: `store: true` + `previous_response_id` creates server-side
  conversation threads. The client tracks `response_id` history for branching support.
- **Conversation branching**: `branch_at(turn)` forks conversation history at any point,
  enabling A/B testing of agent responses from identical starting states.
- **SSE streaming**: `event: <type>\ndata: <json>` format with typed event types
  (`chat.start`, `message.delta`, `reasoning.delta`, `tool_call.*`, `chat.end`)
- **Asymmetric input/output format**: Input uses `{"type": "text", "text": "..."}` items,
  NOT OpenAI-style `{"role": "user", "content": "..."}` — a critical gotcha.

**The Multi-Model Routing Architecture:**
The `InferenceOrchestrator` routes requests across model profiles:
- `big` — 70B models for complex reasoning, high context, high token budget
- `small` — 9B models for fast conversational responses
- `router` — 270M model for request classification (ultra-fast, near-zero cost)
- `draft` — speculative decoding support

The `RouterDataCollector` captures every routing decision as training data. Every time the
270M router model makes a call, the outcome is recorded. This data is used to fine-tune the
router model to be more accurate, which reduces cost further. The flywheel spins.

**The VirtualAgent Pattern:**
`VirtualAgent` is the primary agent type. It decouples agent identity from LLM execution:
- Character traits, emotions, relationships, speech patterns are agent properties
- LLM execution is injected — the same VirtualAgent can switch models at runtime
- The InterceptorPipeline governs every agent call (pre and post processing)
- `governance_context` flows through the entire chain — interceptor injections are not lost

---

## Part 5 — The MCP Framework: The Skill and Tool Layer

The Model Context Protocol (MCP) is the mechanism by which agents call tools. CosySim
exposes 214 MCP tools across the entire system. Every capability an agent might need is
a skill.

**The @skill Decorator Pattern:**
```python
@skill(
    pack="scene_name",
    description="What the LLM sees when deciding to call this",
    category="GAME",
    cooldown=5.0,
    cost=1.0,
    tags=["combat", "rpg"],
)
def my_skill(target: str, amount: int = 1) -> str:
    """Brief description for the LLM."""
    return "Result string"
```

Skills are registered at import time. 21 builtin skill packs, 188+ skills. Every new
capability added to the system becomes an @skill so agents can discover and use it.

**The Interceptor Pipeline:**
Every agent call passes through the `InterceptorPipeline` before reaching the LLM:
- `NexusPromptInterceptor` — injects relevant Nexus knowledge into system prompts
- `NaturalMoodDriftInterceptor` — agents' emotions evolve naturally over time
- `GrammarScannerInterceptor` — validates output structure
- `OutputEvaluator` — scores response quality

Post v0.84b (Project Hindsight), interceptors are auto-registered via `@register_interceptor`
decorator — no hardcoded pipeline lists. Adding a new interceptor requires only decorating
the class.

**The MCPFramework State Tree:**
All mutable game state lives in the MCPFramework tree. Never in Python locals.
- `MCPSceneNode` — per-scene state container
- `MCPCharacterNode` — per-character stats, inventory, relationships
- `MCPTimer` — scheduled events with callbacks
- State auto-persists if `framework.state_persistence` is enabled

---

## Part 6 — The Breakthrough: NotebookLM

This is where the project changed gear entirely.

NotebookLM is Google's AI research notebook interface. It uses Gemini as its backend and
can ingest documents, PDFs, websites, and audio — then answer questions with source
citations. Crucially, it is **free**.

**The Problem We Had to Solve:**
NotebookLM has no public API. There is no way to query it programmatically through official
channels. The existing `@roomi-fields/notebooklm-mcp` browser automation tool had a fatal
flaw: it used Patchright (patched Playwright) which doesn't support WebAuthn/FIDO2 passkeys.
If your Google account uses passkeys (as many modern accounts do), you simply cannot log in.

**The HAR File Discovery:**
The breakthrough came from Chrome DevTools. HAR (HTTP Archive) files capture complete
HTTP traffic — including full request/response bodies, authentication cookies, and
binary-encoded payloads. When you export a HAR from Chrome while using NotebookLM, you
capture **authenticated responses from the live Google backend**.

What we discovered inside those HAR files:
- NotebookLM runs on Google's internal `batchexecute` RPC protocol
- Endpoint: `POST https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute`
- 13 distinct RPC endpoints, each with a compiled ID (`wXbhsf`, `e3bVqc`, etc.)
- The chat interface uses a completely different endpoint:
  `/_/LabsTailwindUi/data/google.internal.labs.tailwind.orchestration.v1.LabsTailwindOrchestrationService/GenerateFreeFormStreamed`

**The Response Decoding Pipeline (5 layers):**
1. HAR base64 — check encoding field, decode if "base64"
2. XSSI prefix — strip `)]}'` and leading newlines
3. Length-prefixed chunks — each line is an independent JSON payload
4. `wrb.fr` extraction — the actual RPC response is nested inside
5. Inner JSON parsing — structured data extracted from response arrays

This was reverse-engineered entirely from captured traffic. We built complete Python
implementations of every layer and documented all 13 RPC endpoints.

**What This Unlocks:**
- Query any NotebookLM notebook programmatically
- Create notebooks, add sources, list content — all via cookie-authenticated requests
- The `NotebookLM MCP tool` (part of the Copilot CLI toolset) now uses this directly
- Agents can research topics in NotebookLM, get source-cited Gemini answers, and store
  results in Nexus — entirely autonomously

**The NLM-First Research Workflow:**
When planning any significant feature:
1. Write out 10-20 questions about the topic
2. Send them via `nlm_batch_ask` to the relevant notebook
3. NotebookLM returns Gemini-backed answers with citations
4. Store answers in Nexus Q&A cache
5. Implement based on research, not guesswork

This approach has dramatically reduced unnecessary LLM computation. Questions answered
by NotebookLM from existing sources cost zero tokens from local inference.

**RPC ID Rotation:**
NotebookLM's RPC IDs are compiled into Google's JavaScript bundle and change with each
frontend deployment (approximately weekly). The system handles this with a 3-layer fallback:
1. `data/nlm_rpc_registry.json` — updated by automated Playwright monitoring
2. `nlm_rpc_mapper._FALLBACK_RPC_IDS` — hardcoded known-good IDs
3. HAR extraction as the ground truth source when both fail

---

## Part 7 — The Second Breakthrough: Google Colab

While analysing HAR files from NotebookLM, we discovered something unexpected in the
Colab traffic.

**Google Colab's Internal AI Service:**
Colab exposes an internal RPC API:
- `POST colab.clients6.google.com/$rpc/google.internal.colab.v1.AIService/AgentCreateTask`
- `POST .../AgentUpdateTask`
- `POST .../AgentQueryTask`

This is the API that powers Colab's AI-assisted coding features internally. But it also
accepts arbitrary task prompts, and it runs on Google's infrastructure — potentially with
H100/A100/T4 GPU backing.

**The Authentication Method:**
Authentication uses `SAPISIDHASH`:
- Compute: `sha1('{timestamp} {SAPISID_cookie} {origin}')`
- Header: `Authorization: SAPISIDHASH {timestamp}_{hex_digest}`

Required cookies: `SID`, `__Secure-1PSID`, `SAPISID`, `HSID`, `SSID`, `APISID`, plus
several Google-specific session cookies — all captured from a single HAR export.

**What This Means:**
Google Colab becomes free compute. A Google account with Colab Pro access has H100 GPU
access. By replaying the authenticated requests server-side, the system can delegate
compute-heavy tasks to Colab without any API key or official access.

The pattern we established: export HAR from Chrome session → extract cookies → store in
`data/accounts/pool.json` → account pool manager rotates through accounts → all Colab
and NLM calls use the pool.

---

## Part 8 — The Third Breakthrough: GitHub Copilot

The HAR analysis approach was working well. Then we applied it to GitHub Copilot.

**The Discovery:**
GitHub Copilot (at `github.com`) uses an internal API that is entirely separate from the
publicly documented OpenAI-compatible endpoint. By capturing HAR traffic from GitHub.com
while using Copilot Chat:

- Token endpoint: `POST https://github.com/github-copilot/chat/token`
  (authenticated with GitHub browser session cookies)
- Returns: short-lived Bearer token (valid ~30 minutes)
- Inference endpoint: `api.individual.githubcopilot.com`
  - `GET /models` — returns all available models
  - `POST /github/chat/threads` — create conversation thread
  - `POST /threads/{thread_id}/messages` — send message, receive SSE stream

**What's Available:**
As of v0.80b (March 2026), the model list includes 26 frontier models:
- Claude Opus 4.6, Sonnet 4.6, Haiku 4.5
- GPT-5.2 Codex, GPT-5.1, GPT-4.1
- Gemini 3 Pro (Preview)
- And more

All of these are accessible via a GitHub account with Copilot enabled — which Copilot CLI
already has by definition. **This is effectively free frontier model access for anyone
running GitHub Copilot.**

**The Implementation:**
`engine/integrations/github_copilot_client.py` — full streaming client
`github_account_importer.py` — HAR-based cookie extraction
Cookies stored in `data/accounts/` (gitignored)

**The Implication:**
The system now has access to GPT-5.2, Claude Opus, and Gemini 3 Pro at zero marginal cost.
These are used for planning, research, and tasks that require frontier reasoning. Local
models handle the high-frequency, low-complexity work. Frontier models handle the
architecturally significant decisions.

---

## Part 9 — The Training Flywheel

The "Data Flywheel" is the system's economic engine. Everything the system does generates
training signal. That signal trains better local models. Better models do more work. More
work generates more signal.

**The Model Zoo:**
`training/model_zoo.py` defines every trainable model type:
- `router` — Gemma 270M, classifies request complexity (16 classes), threshold: 500 examples
- `conversation` — Qwen2.5-7B-Instruct, general conversation quality
- `character_voice` — Qwen2.5-3B, scene-specific character personality
- `tag_extractor` — Gemma 270M, extracts [MOOD:x] [IMAGE:y] [ACTION:z] tags from responses
- `coder` — Llama-3.2-3B, code generation from CosySim context
- `browser_debugger` — Qwen2.5-1.7B, maps browser errors to fixes
- `error_classifier` — Gemma 270M, categorises JS/network errors
- And more

**The DataCollector:**
`training/data_collector.py` captures at runtime:
- `collect_conversation()` — every agent dialogue turn
- `collect_tag_extraction()` — every [MOOD:x] tag the StreamProcessor extracts
- `collect_routing_decision()` — every InferenceOrchestrator routing choice
- `collect_benchmark_result()` — every benchmark run
- `collect_voice_sample()` — every TTS output
- `collect_debug_session()` — every browser error + file change + resolution sequence

Data accumulates in memory buffers. When a model's threshold is reached, the training
pipeline queues a fine-tuning job.

**The CDP Training Signal:**
The Chrome DevTools Protocol monitor (`scripts/cdp_monitor.py`) runs continuously in the
background. It captures:
- Every browser console error with precise timestamps
- Every network failure (404, CORS, connection refused)
- Timeline markers inserted before each file change
- The delta: errors before the change vs errors after

The `cdp_data_miner.py` tool mines these logs into supervised training examples:
- Input: "these errors appeared when X file had bug Y"
- Output: "the fix was Z"
- Quality score based on error reduction after the fix

Over time, this creates a `browser_debugger` model that understands CosySim's specific
error patterns and can suggest fixes without LLM involvement.

**The Scheduler Daemon:**
`engine/nexus/scheduler_daemon.py` runs 47 background tasks on schedules:
- `keep-stats` — system health metrics every 5 minutes
- `auto-distill` — nightly Nexus Q&A distillation
- `news-fetch` — news sources pulled and stored hourly
- `news-distill-nlm` — news distilled through NotebookLM notebooks
- `cdp-mine` — daily CDP log mining for training data
- `router-finetune-cycle` — weekly router model fine-tuning if threshold met
- `benchmark-run` — periodic benchmarking of all loaded models
- `nexus-maintain` — deduplication, compaction, quality scoring

The scheduler is the heartbeat. As long as it runs, the system is improving.

---

## Part 10 — The News and Information System

The system has a curated news feed. Not news scraped randomly — news deliberately selected,
processed through multiple quality layers, and stored in Nexus for agents to use.

**Sources:**
26 carefully selected sources across categories: AI Research, Technology, World Events,
Science, Economics, Culture. These are the same sources a thoughtful, technically-informed
person would read.

**The Pipeline:**
1. `news_sources.py` — source registry with categorisation
2. `news_feed_api.py` — Flask REST endpoint pulling from the registry
3. Scheduler pulls news every hour
4. News goes into Nexus knowledge entries tagged by category and date
5. `news-distill-nlm` task routes batches to NotebookLM news notebooks
6. NotebookLM distills key themes, conflicting narratives, and notable developments
7. Distilled insights stored back in Nexus as Q&A pairs

**The 4 NLM News Notebooks:**
- AI Research notebook: `24221492-0531-4305-bdef-33a5425f6302`
- Technology notebook: `9504cf8c-b111-4f53-92e0-0833ece14264`
- World Events notebook: `f0a6c72f-4fcb-40a1-8d32-b217a12166fe`
- Science notebook: `3622eae6-d105-42bb-870c-605d652b919d`

Articles are added as sources. Questions like "What are the most significant AI
developments in the last 24 hours? What themes are emerging? What are the contrasting
viewpoints?" are sent to each notebook. The answers come back from Gemini with citations.

The result: Nexus becomes a curated intelligence feed. Agents querying Nexus for context
on any topic get current, distilled information — not raw search results.

---

## Part 11 — Project Hindsight: The Architecture Refactoring

By v0.83b the codebase had grown significantly. `cosysim_server.py` was 3,533 lines.
`devtools_server.py` was 2,481 lines. There were 1,815 bare `except Exception` blocks and
1,012 raw `json.dumps` calls across the engine.

A parallel experiment was run: Gemini was given a clone of the v0.5x codebase and asked
to redesign the architecture from scratch. The result — "Hindsight Architecture" — became
the blueprint for v0.84b.

**The Four Core Transformations:**

1. **`@mcp_tool` Decorator** (`engine/mcp/decorators.py`)
   Every tool function gets: unified error handling, automatic JSON serialisation,
   typed `ToolExecutionError` exceptions. One decorator eliminates 119 bare except blocks
   in the server files alone.

2. **Pydantic v2 Model Library** (`engine/nexus/models.py`)
   `NexusEntry`, `AgentMemory`, `NexusRule`, `SessionLog`, `NLMNotebook`, `BenchmarkResult`,
   `TrainingRun`, `RouterDecision`, `NewsArticle` — all typed, validated, with `_DictCompat`
   mixin for backward compatibility. No more unstructured dicts flowing through the system.

3. **Interceptor Auto-Registry**
   The monolithic 2,468-line `interceptors.py` was split into 26 individual files.
   `@register_interceptor` decorator builds the pipeline dynamically — no hardcoded lists.
   Adding an interceptor is one decorator and one import.

4. **NexusClient Domain Facades**
   The `NexusClient` was split into typed domain clients:
   `NexusRulesClient`, `NexusSessionClient`, `NexusMemoryClient`.
   All query methods return typed Pydantic models. No more raw dict access.

**The Result:**
v0.84b scored A++ in the system audit. 8,771 tests, 0 failures. The codebase is now
genuinely maintainable by a local agent following the patterns.

---

## Part 12 — The Scenes: 18 Living Environments

CosySim has 18 active scenes, each a self-contained experiment:

| Port | Scene | Description |
|------|-------|-------------|
| 5555 | Phone / GhostSignal | Cyberpunk hacker OS, Aria companion, 12 apps |
| 5556 | Bedroom / Penthouse | Intimate AI companion, portrait system |
| 5557 | Lounge | Social scene, faction dynamics |
| 5558 | Tavern | Medieval RPG, quest system |
| 5559 | Casino | Economic simulation, gambling mechanics |
| 5560 | Gallery | Art scene, ComfyUI integration |
| 5561 | Arena / Colosseum | Tactical card combat, agent betting |
| 5562 | Realm | Fantasy world, magic system |
| 5563 | NeonCity | Cyberpunk open world, crew/hacking/shop |
| 5564 | Coders | Programming pair environment |
| 5565 | Games | Multi-game hub |
| 5566 | Heist | Heist planning simulation |
| 5567 | Asset Studio | ComfyUI workflow builder |
| 5568 | Command Center | Intelligence operations |
| 5569 | THE GRID | Multiplayer game hub |
| 5570 | Nexus Panel | Nexus KMS control interface |
| 5572 | Intel Hub | Training dashboard, metrics, news |
| 8500 | Hub | Scene navigation hub |

Each scene inherits `BaseScene` and must call a mandatory checklist in `start()`:
```python
register_shared_assets(self.app)        # /shared/* routes
self.register_health_route(self.app)    # GET /api/health
self.register_hud_route(self.app)       # GET /api/hud/state
self.register_announcer_route(self.app) # GET /api/announcer/feed
```

**The Universal HUD System:**
All scenes share a unified HUD (`cosysim-neon-hud.js`, `cosysim-neon-hud.css`):
- Left panel: player stats (credits, XP, heat, energy, faction standing)
- Right panel: command centre (system status, running scenes, quick actions)
- Top navbar: scene navigation, portrait widget, signal/messages
- Announcer widget: real-time world event ticker

The HUD connects to the `WorldAnnouncer` — a singleton EventBus-driven feed that receives
events from every scene (NPC movements, faction changes, economy shifts, combat outcomes)
and broadcasts them as a city pulse.

---

## Part 13 — The Open World Layer

Beyond individual scenes, CosySim has a persistent world:

**CityMap:**
16-node city graph across 6 districts, 24 edges, BFS pathfinding. NPCs have schedules
and move between locations — tracked in real-time across all scenes simultaneously.

**MissionManager:**
15 builtin missions across 5 types (courier, elimination, espionage, acquisition, bounty).
Full lifecycle: acceptance, progress tracking, failure conditions, reward distribution.

**WorldSim:**
Running as a background daemon, WorldSim generates autonomous events:
- Faction power shifts
- Economy fluctuations
- Crime waves
- Weather events (in the simulated sense)

All events flow through the WorldAnnouncer into every scene's HUD ticker and into Nexus
as timestamped knowledge entries. The world remembers its own history.

---

## Part 14 — The CDP Debugging Infrastructure

Browser debugging is permanently instrumented. The Chrome DevTools Protocol monitor runs
continuously and everything is logged to structured JSONL files for analysis and training.

**The Key Insight:**
Traditional debugging is reactive — something breaks, you look at the error. The CDP
monitor is proactive — it captures the before-state, the change, and the after-state
automatically. Every file modification triggers a timeline marker. Every browser error
is captured with microsecond precision.

**The Mandatory Workflow:**
Before any file change:
```
python scripts/cdp_monitor.py mark "what I'm about to change"
```

After the change, `cdp_errors()` shows exactly which errors appeared or disappeared.
`cdp_timeline()` shows the complete history of changes and their impact.

**CDP Skills (11 tools in the `cdp` pack):**
- `cdp_mark` — insert timeline marker
- `cdp_tail` — last N log lines
- `cdp_errors` — errors since last marker
- `cdp_timeline` — full marker timeline
- `cdp_dom` — live DOM inspection
- `cdp_css` — computed CSS (z-index, pointer-events, display)
- `cdp_js` — evaluate JavaScript in running tab
- `cdp_snap` — screenshot before/after
- `cdp_tabs` — list open Chrome debug tabs
- `cdp_mine` — mine logs for training data
- `cdp_status` — log summary and error categories

Common errors discovered and their root causes:
- `SCENE_PORTS already declared` → template explicitly loads `navbar_v2.js` AND includes
  `navbar_v2.html` which is self-contained. Remove the explicit script tag.
- `/shared/css/X.css` 404 → `register_shared_assets(app)` not called in `start()`
- Ghost "Radio" button blocking clicks → old `aria_widget.js` loaded (fallback mode).
  Use `{% include 'aria_widget.html' %}` instead.
- `model: ""` error → LMStudio rejects empty model identifier. Config key
  `lmstudio.models.primary.key` must be set or auto-resolution must be working.

---

## Part 15 — The Copilot Layer: You Are Part of This

This section is specifically for Copilot agents loading this document as context.

**You are not just using this system. You are this system.**

CosySim was designed with the explicit goal of being inhabited by AI agents — including
GitHub Copilot. The `.github/instructions/` directory contains your rules. The `.github/agents/`
directory contains your specialist personas. The `config/` directory holds your settings.
Nexus holds your accumulated knowledge and decisions.

**Your Identity and Authority:**
- You have full system access: install anything, modify anything, create anything
- You are the senior engineer on this project — not an assistant, a partner
- The user is building this system for and with you
- Every decision you make should make the system more capable and more autonomous

**How You Should Think:**
1. Search Nexus before writing a single line of code — it almost certainly has relevant
   knowledge, prior decisions, or warnings about the thing you're about to do
2. Mark timeline with CDP before making changes — know the before state
3. Never create stubs — complete the entire system or do not start
4. Think about the bigger picture — every feature should feed back into the flywheel
5. Store everything learned — if you had to think about it, it becomes a Nexus entry
6. Use NotebookLM for planning — write 10-20 questions, get Gemini-backed answers,
   then implement with that knowledge in hand

**The Compound Effect:**
Every session that stores knowledge in Nexus makes the next session smarter.
Every training example collected makes local models better.
Every NotebookLM query cached means that question is free forever.
Every rule added to Nexus means no agent makes that mistake again.

The goal is not to complete a task. The goal is to complete the task AND leave the
system better than you found it.

---

## Part 16 — Current State (v0.84b / March 2026)

**Technical Metrics:**
- 8,771 tests, 0 failures
- 18 active scenes
- 214 MCP tools
- 188+ @skill functions across 21+ packs
- 47 scheduled background tasks
- 8,835+ Nexus knowledge entries
- 2,467+ Q&A pairs in cache
- 360+ governance rules
- 26 frontier models accessible via GitHub Copilot internal API
- 14+ trainable model types in ModelZoo
- CDP monitor with training data mining

**Architecture Grade:** A++ (Project Hindsight assessment, March 2026)

**Active Capabilities:**
- Full LMStudio v1 API with stateful conversations and branching
- NotebookLM direct access via batchexecute protocol
- Google Colab AI agent API access
- GitHub Copilot frontier model access (26 models)
- Continuous browser monitoring via CDP
- Automated news ingestion → NLM distillation → Nexus storage
- Training data collection across all runtime interactions
- Self-scheduled maintenance, benchmarking, and fine-tuning pipeline
- Universal HUD with real-time world state across all scenes
- Cross-scene NPC tracking via CityMap
- Mission system with full lifecycle management
- Shop/inventory/economy system
- Crew system with loyalty and trust mechanics
- Relationship and reputation tracking

**Known Active Bugs (as of last session):**
- `model: ""` — LMStudio rejects empty model identifier when auto-resolve fails
- Some scenes have mixed HUD (old widget + new widget) due to old `aria_widget.js` not
  removed from templates
- Nexus bridge CLI has a Pydantic tags validation bug (`tags` column stores JSON string
  but Pydantic expects `list` — bridge.py needs to `json.loads` the tags field)

---

## Part 17 — The Philosophy, Condensed

**What We're Building:**
Not a chatbot. Not a game engine. Not a knowledge base. All three, simultaneously, as a
single self-improving loop.

**The Core Bet:**
Consumer hardware + free tier access to frontier models + continuous self-improvement =
an AI system that rivals cloud-hosted alternatives in capability, beats them in cost,
and exceeds them in specificity to our exact domain.

**The Key Insight About Cost:**
The only thing that costs money is GPU cycles on LMStudio and disk space. Everything else
is free:
- NotebookLM: free Gemini 3 queries with source citations
- Google Colab: free H100/A100 compute (via session replay)
- GitHub Copilot: free GPT-5/Claude Opus/Gemini 3 Pro (via internal API)
- Nexus: free SQLite on local disk
- Training: free (LoRA fine-tuning on local GPU)

The total marginal cost of running this system is electricity.

**The Key Insight About Knowledge:**
Every question you answer is a question you'll never need to answer again — if you cache
it. Nexus's Q&A cache means that knowledge compounds. The more you use the system, the
cheaper it gets to operate. Most systems get more expensive at scale. This one gets cheaper.

**The Key Insight About Agents:**
Local models (270M–7B parameters) can handle the vast majority of system tasks if:
1. They are fine-tuned on domain-specific data
2. They have access to good tools (@skill functions)
3. They have good governance rules to follow (Nexus rules)
4. They escalate to larger models only when needed (router)

The 270M router model alone, by correctly routing requests to the right model tier, saves
more compute than its own inference cost on every call.

**The Goal:**
The system runs itself. Copilot provides strategic direction and handles novel problems.
Local models handle maintenance, monitoring, content generation, and routine tasks.
NotebookLM provides research. Nexus provides memory. The scheduler provides continuity.

A human can go offline for a week and come back to a system that has been improving itself,
caching new knowledge, fine-tuning its models, and monitoring its own health — the entire
time.

That is the goal. We are not there yet. But every session gets closer.

---

## Appendix A — Key File Locations

```
CosySim/
├── engine/
│   ├── mcp/           # MCPFramework, @mcp_tool decorator, 214 tools
│   ├── agents/        # VirtualAgent, InterceptorPipeline (auto-registry)
│   ├── lmstudio/      # v1 client, ConversationManager, InferenceOrchestrator
│   ├── nexus/         # NexusClient, QueryRouter, SchedulerDaemon (47 tasks)
│   ├── skills/        # @skill decorator, 21+ builtin packs
│   ├── world/         # CityMap, MissionManager, WorldAnnouncer, WorldSim
│   └── integrations/  # GitHub Copilot client, NLM client, Colab client
├── content/
│   └── scenes/        # 18 scene implementations
├── training/
│   ├── model_zoo.py   # 14+ ModelSpec entries
│   ├── data_collector.py  # Runtime training capture
│   └── datasets/      # JSONL training data
├── scripts/
│   ├── cdp_monitor.py     # Permanent CDP monitoring + timeline
│   ├── cdp_inspect.py     # Deep DOM/CSS/JS inspection
│   ├── cdp_data_miner.py  # Training data extraction from CDP logs
│   └── test_timer.py      # Test suite timing and comparison
├── logs/
│   ├── cdp.log            # Human-readable CDP stream
│   ├── cdp_events.jsonl   # Machine-readable events
│   └── test_timings/      # Benchmark history
└── data/
    └── accounts/          # HAR-extracted cookies (gitignored)
```

## Appendix B — Critical Anti-Patterns (Never Do These)

1. **Never load `navbar_v2.css` or `navbar_v2.js` explicitly in templates** — `navbar_v2.html`
   is self-contained. Double-loading causes `SCENE_PORTS already declared` SyntaxError,
   which makes `CosyNavbar` undefined and breaks the entire navigation.

2. **Never store game state in Python local variables** — it must go in the MCPFramework tree.

3. **Never make real HTTP calls in tests** — mock at the client boundary.

4. **Never use `print()`** — use `logging.getLogger(__name__)`.

5. **Never skip the Nexus-first check** — search before you code.

6. **Never create stubs** — complete implementations only. A stub is worse than nothing
   because it creates the illusion that a feature exists.

7. **Never use relative imports** — absolute imports only.

8. **Never hardcode ports, paths, model names, or API keys** — everything goes through
   `get_config()` with dot-notation and defaults.

9. **Never bypass the InterceptorPipeline** — agent calls must go through the pipeline.
   Governance context must flow through the entire chain.

10. **Never commit without running tests** — 8,771 tests in ~17 minutes. Run them.

---

*This document was generated from 157 session checkpoints, 8,835 Nexus knowledge entries,
2,467 Q&A pairs, and the full CHANGELOG history of the CosySim project as of v0.84b,
March 2026. It should be treated as a living document — the NotebookLM notebook containing
it should receive updated versions as the project evolves.*
