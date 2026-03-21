# NLM Knowledge Flywheel — Complete Playbook

> Version: 4.0 | Updated: 2026-06
> The definitive guide to using NotebookLM as a free, unlimited Gemini intelligence engine
> to saturate the Nexus knowledge base and generate training data at scale.

---

## The Core Insight

Every NLM API call accepts **~10,000 words of custom prompt**. Gemini 3.0 reads
that entire prompt *plus* every source document in the notebook before generating.

This means you don't ask vague questions and hope — you write a full creative brief,
architectural specification, or narrative script, and Gemini executes it precisely
against all your source material.

**Two calls. Zero cost. Unlimited Gemini compute.**

---

## rpcid Quick Reference (v4.0)

| rpcid    | Name                     | What it does                                    |
|----------|--------------------------|--------------------------------------------------|
| `CYK0Xb` | CREATE_NOTE / Report     | Custom report from 10k word prompt + sources    |
| `QA9ei`  | GENERATE_AUDIO_CUSTOM    | 30-min podcast with custom 10k focus prompt     |
| `yyryJe` | GENERATE_MIND_MAP        | JSON concept tree from source IDs               |
| `ciyUvf` | GENERATE_FLASHCARDS      | Flashcard Q&A pairs from sources                |
| `R7cb6c` | GENERATE_QUIZ            | Quiz with source references                     |
| `LBwxtb` | GENERATE_BLOG_POST       | Long-form narrative content                     |
| `otmP3b` | GENERATE_VIDEO_SUGGESTIONS | Video overview content suggestions            |
| `Krh3pd` | EXPORT_TO_SHEETS         | Export any artifact to Google Sheets            |
| `sqTeoe` | GET_AUDIO_OPTIONS        | Lists: Deep dive / Brief / Critique / Debate    |
| `gArtLc` | GET_ARTIFACTS            | List artifacts with status polling              |
| `yyryJe` | GENERATE_MIND_MAP        | JSON concept tree {name, children:[...]}        |
| `ub2Bae` | LIST_NOTEBOOKS           | All notebooks with IDs                          |
| `hPTbtc` | GET_PENDING_SOURCES      | Source IDs for a notebook                       |
| `izAoDd` | ADD_SOURCE / SAVE_ARTIFACT | Add text/URL source or save artifact          |
| `tr032e` | GET_SOURCE_SUMMARY       | AI summary of a single source                   |

---

## The 6 Flywheel Workflows

### 1. Knowledge Flywheel (2 Gemini calls → 60+ Q&A)

The fastest way to seed Nexus with high-quality Q&A pairs. No browser. No polling.

```python
# Call 1: CYK0Xb — comprehensive analysis document
report = nlm.create_note(
    notebook_id=NB_ID,
    prompt=COSYSIM_ANALYSIS_PROMPT_10K  # see below
)
# Returns: {id, title, content}  — full markdown analysis

# Call 2: GenerateFreeFormStreamed — extract Q&A JSON
qa_json = nlm.ask(
    notebook_id=NB_ID,
    source_ids=SOURCE_IDS,
    question='Convert the analysis into 60 Q&A pairs. Return ONLY valid JSON: [{"q":"...","a":"..."}]',
    conversation_history=[[report["content"], "assistant"]]
)
# Parse → nexus_add_qa() × 60
```

**Output**: 60+ curated Q&A pairs, stored in Nexus Q&A cache for instant lookup.
**Total Gemini calls**: 2. **Cost**: free. **Time**: ~90 seconds.

---

### 2. Audio Flywheel (Most Powerful — 30-min podcast → 15k words → 100+ Q&A)

```python
# Call 1: QA9ei — generate 30-minute podcast with full creative brief
job_id, artifact_id = nlm.generate_audio(
    notebook_id=NB_ID,
    focus_text=COSYSIM_AUDIO_PROMPT_10K  # detailed segment breakdown
)

# Poll gArtLc until artifact status == "ARTIFACT_STATUS_COMPLETE"
audio_url = nlm.poll_artifact(artifact_id)

# Download MP3 → local file
mp3_path = nlm.download_artifact(artifact_url, "data/nlm_audio/cosysim_deep_dive.mp3")

# Transcribe locally with Whisper (GPU, ~90 seconds for 30 min)
transcript = whisper.transcribe(mp3_path, model="large")["text"]
# ~12,000-15,000 words

# Save transcript as NLM artifact (reusable)
nlm.save_artifact(notebook_id=NB_ID, title="CosySim Deep Dive Transcript", content=transcript)

# Call 2: Extract Q&A from transcript
qa_json = nlm.ask(
    notebook_id=NB_ID,
    source_ids=SOURCE_IDS,
    question='From the transcript, extract 100 Q&A pairs. JSON: [{"q":"...","a":"..."}]',
    conversation_history=[[transcript, "assistant"]]
)
# Parse → nexus_add_qa() × 100

# Also store full transcript
nexus.add_entry("CosySim Deep Dive Transcript", transcript, content_type="document")
```

**Output**: Full 15k-word knowledge transcript + 100+ Q&A pairs.
**Total Gemini calls**: 2 (audio gen counts as 1). Whisper is local.
**Why the transcript is special**: It's conversational, multi-perspective, covers implications
and connections that a flat report misses. The two AI hosts debate, explain, and challenge
each other — producing richer understanding than any summary.

---

### 3. Mind Map → Knowledge Graph

```python
# yyryJe — generate concept tree
tree = nlm.generate_mind_map(source_ids=SOURCE_IDS)
# Returns: {"name": "CosySim", "children": [{"name": "MCPFramework", "children": [...]}, ...]}

# Traverse tree → generate Q&A for each node
def traverse(node, parent=None):
    q = f"What is {node['name']} in CosySim?"
    a = f"{node['name']} is a component of {parent or 'CosySim'}. " + describe_from_children(node)
    nexus.add_qa(q, a)
    for child in node.get("children", []):
        traverse(child, node["name"])
```

**Output**: Complete concept graph + Q&A for every architectural concept.

---

### 4. Flashcard Direct Seeding

Flashcards are already in Q&A format — zero transformation needed.

```python
# ciyUvf — generate flashcards
cards = nlm.generate_flashcards(notebook_id=NB_ID, source_ids=SOURCE_IDS)
# Returns: [{"title": "What is MCPFramework?", "summary": "MCPFramework is..."}, ...]

for card in cards:
    nexus.add_qa(card["title"], card["summary"])
```

**Output**: Instant Q&A seeding. No custom prompt needed — NLM picks the best Q&A naturally.

---

### 5. Bulk Notebook Seeding

Run the flywheel on every notebook you own:

```python
# ub2Bae — list all notebooks
notebooks = nlm.list_notebooks()

for nb in notebooks:
    sources = nlm.get_sources(nb["id"])  # hPTbtc
    # Run knowledge_flywheel or audio_flywheel on each
    run_knowledge_flywheel(nb["id"], sources)
```

**Output**: Nexus seeded from ALL knowledge across your entire NLM account.

---

### 6. Sheets Export Pipeline

Turn any NLM artifact into a structured Google Sheet:

```python
# Create a data table report
artifact = nlm.create_note(NB_ID, "Generate a data table with columns: Component | Purpose | Key Files | Status")

# Export to Google Sheets
sheets_url = nlm.export_to_sheets(artifact["id"], "CosySim Architecture Table")
# Returns: "https://docs.google.com/spreadsheets/d/..."

nexus.add_entry("CosySim Architecture Spreadsheet", sheets_url)
```

---

## The 10,000 Word Prompt Templates

### Template A — CosySim Analysis Report Prompt (for CYK0Xb)

Use this as the `prompt` argument to `CYK0Xb`. Gemini reads all your source documents
first, then executes this prompt against them.

```
You are producing a comprehensive technical reference document for CosySim v0.86b,
a multi-scene AI simulation framework. This document will be used to seed a knowledge
base that local AI agents use to understand and maintain the system.

STRUCTURE YOUR RESPONSE EXACTLY AS FOLLOWS:

## 1. PROJECT OVERVIEW (300 words)
Explain what CosySim is, its philosophy, the cyberpunk aesthetic, and the goal of
making local AI agents feel like real inhabitants of a virtual world. Cover: multi-scene
framework, 18 scenes, MCP state tree, @skill tools, the Nexus knowledge system as the
intelligence backbone. Explain why the system is designed to be self-improving.

## 2. ENGINE ARCHITECTURE (800 words)
Cover every major engine module with technical specifics:

MCPFramework: The root singleton. Accessed via get_framework(). Manages a hierarchical
state tree. Every game state change must sync to this tree — never store mutable state
in local Python variables. Uses MCPSceneNode for per-scene state, MCPCharacterNode for
per-character state (stats, inventory, relationships, speech patterns).

BaseScene: The foundation for all 18 scenes. Required overrides: start(), stop(),
get_plugin_info(). Key methods: register_health_route(), register_hud_route(),
_mcp_register_scene(), on_character_added(), on_character_removed(). Scenes run as
Flask apps on dedicated ports (penthouse:5555, phone:5556, lounge:5557, etc.).

@skill decorator: Marks functions as LLM-callable tools. Parameters: pack (grouping),
description (what the LLM sees), category (GAME/SOCIAL/MEMORY/etc.), cooldown (seconds),
cost (budget), tags, prerequisites. Return type must be string. Access the active scene
via BaseScene.get_active_scene("scene_name").

InterceptorPipeline: Runs before (pre_call) and after (post_call) every LLM call.
pre_call: inject system prompts, governance context, relationship state, memory snippets.
post_call: strip artifacts, extract [MOOD:x][IMAGE:x][ACTION:x][STAT:x][VOICE:x] tags,
grammar scanning. 26 interceptor classes, auto-registered via @register_interceptor.

AgentGovernor: Enforces governance rules. governance_context must be passed through the
entire chain: AgentGovernor → CharacterAgent.reply() → VirtualAgent.reply() → build_request().
Without governance_context in kwargs, interceptor injections are silently lost. @governed
decorator and enforce_governance() block unauthorized operations.

DialogSystem: Manages conversation threading. close_conversation() triggers quality rating
and DataCollector capture. Wire to EventChain for audit logging.

LMStudio v1 API: Stateful conversations via store:true + previous_response_id threading.
Input items: {"type": "text", "text": "..."} — NOT {"type": "message", "content": "..."}.
SSE events: chat.start, chat.end, message.delta, tool_call.*, error. Parse event: line first.

StreamProcessor: Extracts structured tags from LLM responses. Tags: [MOOD:happy/sad/angry],
[IMAGE:scene description], [ACTION:action_name], [STAT:name±value], [VOICE:style].
Use infer_processed() for rich responses, infer_stream() for raw streaming.

## 3. NEXUS KNOWLEDGE SYSTEM (600 words)
The 3-layer database:
- Layer 1: Q&A cache — instant sub-millisecond lookup for previously answered questions
- Layer 2: FTS5 full-text search — synthesizes answers from 500+ knowledge entries
- Layer 3: NLM notebooks — deep Gemini research for unknown questions

The 4-tier query router (NexusQueryRouter):
1. Q&A cache hit → return instantly (0 tokens used)
2. FTS synthesis → fast, no LLM needed
3. NLM notebook ask → free Gemini compute via direct API
4. LMStudio LLM fallback → GPU, auto-stores result back in Layer 1

Access pattern: get_nexus_client().ask("question") — always routes through all tiers.
Direct search: get_nexus_client().search("topic") — FTS5 query.
Store knowledge: nexus.add_entry(title, content, content_type="note", category="architecture").
Store Q&A: nexus.add_qa("How does X work?", "X works by...").

CLI bridge (always available): python -m engine.nexus.bridge search/ask/store/qa/health

The compound effect: every answer stored reduces future LLM calls. Cache hit rate increases
over time. The system gets smarter with every interaction.

## 4. ARGUS — AUTOMATED API RECONNAISSANCE (400 words)
ARGUS is the living API intelligence platform. It systematically maps Google's internal APIs
(NotebookLM, Gemini, AI Studio) using:
- Chrome DevTools Protocol (CDP): Network.enable captures all requests on running tabs
- Playwright crawlers: automated UI flow execution for each known feature
- Heap diffing: CDP HeapProfiler snapshots before/after actions reveal new API shapes
- tshark: TLS decryption for binary gRPC-web frames → .proto reconstruction

Key components: scripts/argus/ — cdp_bridge, network_monitor, crawlers (nlm/gemini/aistudio),
decoders (batchexecute, grpc_web, heap_diffing), discovery (endpoint_registry, rpcid_detector).

NLM rpcids confirmed (30 total): CYK0Xb (report), QA9ei (custom audio), yyryJe (mind map),
ciyUvf (flashcards), R7cb6c (quiz), LBwxtb (blog), otmP3b (video), Krh3pd (sheets export),
sqTeoe (audio options), gArtLc (artifacts), ub2Bae (list notebooks), hPTbtc (sources),
izAoDd (add source/save artifact), tr032e (source summary) + 16 more.

## 5. THE COMPUTE LAYER (400 words)
Multiple compute backends, cascading failover:
- GitHub Copilot: 26 frontier models via internal API (api.individual.githubcopilot.com).
  Cookie auth from browser HAR import. nihilistcod account active.
- LMStudio: Local GPU inference, localhost:1234, always running. v1 API, stateful.
- Colab JIT: Deploy notebooks programmatically, GPU access, tunnel server for local bridge.
- NLM direct: 30 rpcids, all generation types, free Gemini 3.0 compute.
- ComputeRouter: Copilot → LMStudio fallback chain. Auto-routes based on availability.

Google Account Pool: HAR import for cookie auth. Supports multiple accounts for rotation.
Each account: separate NLM quota (50 Q&A/day free, unlimited audio), separate Colab runtime.
Cookie refresh: CDP direct from running Chrome, ~1 second, zero UI interaction.

## 6. TRAINING PIPELINE (300 words)
DataCollector: 8 collect_* methods. Every runtime action passively captured to JSONL.
- collect_tool_call(skill_name, args, result, latency) — after every skill execution
- collect_conversation(system, turns, quality_rating) — after every dialogue
- collect_grammar_error(text, issues, severity) — from GrammarScannerInterceptor
- collect_code(prompt, completion, language) — from coder skills

ModelZoo: 14 model types. Each has dataset strategy + LoRA training config.
Key models: router (Gemma 270M), coder (Llama 3.2-3B), conversational (Qwen 1.7B).

FinetuneOrchestrator: Runs LoRA training → BenchmarkRunner evaluation → auto-promote if better.
The flywheel: runtime → DataCollector → JSONL → FinetuneOrchestrator → better model → runtime.

OutputEvaluator: 0.0-1.0 quality score per response. Low scorers (<0.4) → Nexus improvement
entries → weekly NLM distillation → training examples. The system identifies its own failures.

## 7. SCENE CATALOG (300 words)
List all 18 scenes with port, type, and key features:
penthouse (5555): The Penthouse — LolA companion, relationship system, ambient AI
phone (5556): GhostSignal OS — encrypted hacker OS, Aria companion app, faction messages  
lounge (5557): The Lounge — social scene, bartender, faction regulars
tavern (5558): The Tavern — fantasy setting, Viktor merchant, quest system
casino (5559): Club Noir — gambling mechanics, economy-linked odds, VIP access
gallery (5560): The Gallery — art showcase, curator character
heist (5565): The Heist — planning and execution mechanics, crew system
realm (5562): The Realm — fantasy RPG zone
neoncity (5563): Neon City — open world map, faction territories, street events
coders (5564): The Coders — hacker/developer scene
grid (5569): The Grid — multi-zone underground marketplace, economy hub
games (5567): Games — mini-game collection
asset_studio (5568): Asset Studio — ComfyUI image/video generation interface
intel_hub (5580): Intel Hub — analytics, benchmarks, training dashboard, world events
hub (8500): Hub — navigation, scene management, system health

## 8. CODING CONVENTIONS (200 words)
Absolute imports only. Type hints required on all signatures. Google docstrings.
No print() — use logging.getLogger(__name__). No hardcoded ports/paths/model names.
Config via get_config().get("dot.path", default). All mutable state to MCPFramework tree.
Tests: pytest plain assert, mock all external services at client boundary.
Commits: feat:/fix:/docs:/test:/chore:/refactor: + Co-authored-by: Copilot trailer.

## 9. 60 Q&A PAIRS (JSON)
Now generate exactly 60 Q&A pairs covering the entire system. Cover: architecture,
patterns, gotchas, workflows, conventions, key files, troubleshooting, and design decisions.
Each answer should be 2-4 sentences, dense with specific technical detail.

Return the Q&A section as a JSON code block:
```json
[
  {"q": "How do you access the MCPFramework singleton?", "a": "..."},
  ...
]
```
Cover these topic areas (10 questions each):
- Engine core (MCPFramework, BaseScene, @skill, interceptors)
- Nexus system (3-layer DB, query router, CLI bridge, add_qa)
- LMStudio API (v1, stateful conversations, SSE parsing, input format)
- Scene development (required overrides, state management, Socket.IO)
- Testing and conventions (mocks, pytest patterns, import rules)
- Compute layer (Copilot, Colab, NLM direct, account pool)
```

---

### Template B — CosySim Audio Focus Prompt (for QA9ei)

Use as the `focus_text` argument. This directs the 30-minute podcast conversation.

```
PRODUCER'S BRIEF FOR NOTEBOOKLM AUDIO OVERVIEW — COSYSIM TECHNICAL DEEP DIVE

You are producing a 30-minute technical deep-dive podcast episode about CosySim,
a multi-scene AI simulation framework. The audience is experienced software engineers
who want to deeply understand the architecture, patterns, and design philosophy.
The two hosts should be technically precise, occasionally argue about design tradeoffs,
ask each other hard "but why?" questions, and use concrete examples from the codebase.

NARRATIVE ARC:
The episode tells the story of a system that started as a game engine and evolved into
an autonomous AI ecosystem that improves itself. Each segment builds on the previous.

SEGMENT 1 — FIRST 5 MINUTES: What Is CosySim?
- Open with: "Most AI projects are demos. CosySim is different. It's a system designed
  to inhabit itself." Hook the listener immediately.
- Cover: 18 scenes, each a Flask app on its own port, connected by a central MCP state tree
- The cyberpunk aesthetic is intentional: the UI is the agent's world, not just a display
- Key tension to explore: how do you make an AI system feel *alive* vs just functional?
- End segment: "But to understand how it works, you have to understand the engine."

SEGMENT 2 — MINUTES 5-12: The Engine
- MCPFramework: why a hierarchical state tree? Contrast with "just use a database"
  Host A explains the tree structure. Host B pushes: "but why not Redis?"
  Answer: everything is in-process, hot-reload capable, testable without infrastructure
- @skill decorator: Host B should be excited about this. "This is the key insight."
  Every function with @skill is automatically visible to the LLM as a tool call.
  Walk through: cooldown prevents spam, cost enables budget tracking, tags enable discovery
- InterceptorPipeline: the most underappreciated part. Pre/post call hooks that transform
  every single LLM interaction. Give example: relationship context injected silently.
  Host A: "So the LLM doesn't know it's getting extra context?" Host B: "Exactly."
- AgentGovernor + governance_context: the thing that trips everyone up. Must flow through
  the entire call chain. If you miss it, injections are silently lost. Classic footgun.

SEGMENT 3 — MINUTES 12-19: The Nexus
- Start with the problem: "Every time a new agent starts, it knows nothing."
- The 3-layer database: Q&A cache (instant) → FTS5 search (fast) → NLM (deep)
- The 4-tier router: "It's like a waterfall — each tier only runs if the previous misses"
- The compound effect: demonstrate with numbers. Today: 0 cache hits. Next month: 500 hits.
- NLM direct API: the crown jewel. 30 rpcids decoded from browser HARs. Zero official docs.
  Host B: "Wait, you reverse-engineered the entire NotebookLM API from network traffic?"
  Host A: "And it gives us free Gemini 3.0 compute. Unlimited. No API key needed."
- ARGUS: the self-updating intelligence layer. Catches API changes weekly.

SEGMENT 4 — MINUTES 19-24: The Compute Layer  
- The cascade: Copilot (26 frontier models) → LMStudio (local GPU) → fallback
- Why GitHub Copilot? "You're already paying for it, and it's running Claude Sonnet."
- Colab JIT: "You deploy a notebook programmatically and it gives you a T4 GPU."
- The account pool: cookie auth, HAR import, automatic rotation. No official APIs needed.
- Host B should ask: "Is this sustainable?" Host A: "Everything has a backup. That's the point."

SEGMENT 5 — MINUTES 24-28: The Training Flywheel
- DataCollector: every single runtime action is passively recorded
- "The system generates its own training data by simply running"
- OutputEvaluator: 0 to 1 quality score. Low scorers → Nexus → NLM distillation → training
- "The system identifies its own failures and feeds them to itself to improve"
- FinetuneOrchestrator: auto-promotes better models. The loop closes.
- The vision: local models trained on CosySim-specific data, running with no cloud at all

SEGMENT 6 — FINAL 2 MINUTES: The Bigger Picture
- "What's the end state?" Host B asks.
- The answer: a system where local agents can maintain, extend, and improve the codebase
  autonomously. The human is the architect; the agents are the engineers.
- Every scheduler task is a small autonomous action the system takes daily without asking.
- ARGUS catches new Google APIs. Finetune cycle makes models better. Nexus gets fuller.
- Close with: "The system is designed to not need us. That's the highest compliment."

TONE NOTES:
- Technically precise but not dry. Use analogies when helpful.
- Allow genuine enthusiasm when something is clever (ARGUS, the 10k word prompt trick, etc.)
- Push back on design decisions — this creates more interesting listening
- Concrete over abstract: cite specific file names, class names, rpcids
- Pacing: Segments 2-3 are the densest; give them time. Segments 5-6 are faster-paced.
```

---

## Implementation: NLMFlywheel Class

```python
# scripts/nlm_flywheel.py
from engine.integrations.nlm_direct_client import NLMDirectClient
from engine.integrations.google_account_pool import get_account_pool
from engine.nexus.client import get_nexus_client
import whisper
import json
import re

COSYSIM_NOTEBOOK_ID = "4d1e05fb-a882-40e9-98c9-0393ed82a6f1"

class NLMFlywheel:
    def __init__(self):
        pool = get_account_pool()
        account = pool.get_best_account(["notebooklm"])
        self.nlm = NLMDirectClient(account)
        self.nexus = get_nexus_client()
        self.nb_id = COSYSIM_NOTEBOOK_ID

    def get_source_ids(self):
        """hPTbtc — list sources for notebook."""
        ...  # call hPTbtc, return source_ids

    def run_knowledge_flywheel(self, prompt: str) -> int:
        """2 Gemini calls → Q&A pairs stored in Nexus."""
        source_ids = self.get_source_ids()
        # Call 1: CYK0Xb report
        report = self.nlm.create_note(self.nb_id, prompt)
        # Call 2: Q&A extraction
        qa_json = self.nlm.ask(
            self.nb_id, source_ids,
            question='Output 60 Q&A pairs as JSON: [{"q":"...","a":"..."}]. Only JSON.',
            conversation_history=[[report["content"], "assistant"]]
        )
        pairs = self._parse_qa_json(qa_json)
        for pair in pairs:
            self.nexus.add_qa(pair["q"], pair["a"])
        return len(pairs)

    def run_audio_flywheel(self, focus_prompt: str) -> int:
        """Audio generation → Whisper → Q&A pairs stored in Nexus."""
        # Call 1: QA9ei custom audio
        job_id, artifact_id = self.nlm.generate_audio(self.nb_id, focus_prompt)
        # Poll until ready
        audio_url = self.nlm.poll_audio_artifact(artifact_id)
        # Download
        mp3_path = f"data/nlm_audio/{artifact_id}.mp3"
        self.nlm.download_audio(audio_url, mp3_path)
        # Transcribe
        model = whisper.load_model("large")
        transcript = model.transcribe(mp3_path)["text"]
        # Save transcript
        self.nexus.add_entry(
            "CosySim Deep Dive Transcript",
            transcript,
            content_type="document",
            category="architecture"
        )
        # Call 2: Q&A extraction from transcript
        source_ids = self.get_source_ids()
        qa_json = self.nlm.ask(
            self.nb_id, source_ids,
            question='From the transcript extract 100 Q&A pairs. JSON: [{"q":"...","a":"..."}]',
            conversation_history=[[transcript, "assistant"]]
        )
        pairs = self._parse_qa_json(qa_json)
        for pair in pairs:
            self.nexus.add_qa(pair["q"], pair["a"])
        return len(pairs)

    def run_flashcard_seeding(self) -> int:
        """Direct flashcard → Q&A. No custom prompt needed."""
        source_ids = self.get_source_ids()
        cards = self.nlm.generate_flashcards(self.nb_id, source_ids)
        for card in cards:
            self.nexus.add_qa(card["title"], card["summary"])
        return len(cards)

    def run_mind_map_seeding(self) -> int:
        """Mind map → concept Q&A pairs."""
        source_ids = self.get_source_ids()
        tree = self.nlm.generate_mind_map(source_ids)
        count = 0
        def traverse(node, parent=None):
            nonlocal count
            name = node.get("name", "")
            if name and parent:
                self.nexus.add_qa(
                    f"What is {name} in CosySim?",
                    f"{name} is a sub-component of {parent}. "
                    + ", ".join(c["name"] for c in node.get("children", []))
                )
                count += 1
            for child in node.get("children", []):
                traverse(child, name)
        traverse(tree)
        return count

    def _parse_qa_json(self, raw: str) -> list:
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return []
```

---

## Scheduler Integration

Add these tasks to the scheduler for automated daily knowledge generation:

```python
# In engine/nexus/scheduler_daemon.py _register_builtin_tasks():

{"name": "nlm-knowledge-flywheel",  "every": "1d", "callback": _nlm_knowledge_flywheel_cb},
{"name": "nlm-audio-flywheel",      "every": "3d", "callback": _nlm_audio_flywheel_cb},
{"name": "nlm-flashcard-seed",      "every": "1d", "callback": _nlm_flashcard_seed_cb},
{"name": "nlm-mindmap-seed",        "every": "7d", "callback": _nlm_mindmap_seed_cb},
```

Each run: 2 API calls → 60-100 new Q&A pairs in Nexus. After 7 days: 420-700 Q&A pairs.
After 30 days: the Nexus Q&A cache answers virtually every question an agent can ask.

---

## The Compound Effect (Projected)

| Day | Q&A Cache Entries | Avg Query Time | LLM Calls Saved |
|-----|-------------------|---------------|-----------------|
| 0   | 0                 | 2,000ms       | 0%              |
| 7   | 500               | 800ms         | 35%             |
| 30  | 2,000             | 200ms         | 75%             |
| 90  | 6,000             | 50ms          | 92%             |
| 365 | 20,000+           | <10ms         | 98%             |

At 98% cache hit rate, the system runs almost entirely without LLM calls.
Every future agent session is faster, cheaper, and more consistent.

---

## See Also

- `data/nlm_rpc_registry.json` — complete rpcid reference v4.0
- `engine/integrations/nlm_direct_client.py` — NLMDirectClient implementation
- `docs/NLM_API_REFERENCE.md` — API endpoint documentation
- `docs/NLM_CAPABILITIES.md` — feature overview
- `scripts/nlm_qa_seeder.py` — initial seeder script (superseded by NLMFlywheel)
