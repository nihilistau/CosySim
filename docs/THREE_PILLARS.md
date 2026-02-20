# The Three Pillars Architecture

CosySim is built on three pillars that work together bidirectionally.

```
┌─────────────────────────────────────────────────────────────────┐
│                   CosySim Framework (Pillar 1)                  │
│                                                                 │
│  engine/          content/           config/                    │
│  ├── agents/      ├── scenes/        ├── default.yaml           │
│  ├── skills/      │   ├── phone/     ├── voices.yaml            │
│  ├── spatial/     │   ├── bedroom/   └── development.yaml       │
│  ├── media/       │   ├── hub/                                  │
│  ├── logging/     │   ├── admin/     tests/                     │
│  ├── lmstudio/    │   └── dashboard/ └── 281 tests              │
│  ├── mcp/         ├── simulation/                               │
│  ├── tts/         │   ├── database/                             │
│  └── config.py    │   └── services/                             │
│                   └── characters/                               │
├─────────────────────┬───────────────────────────────────────────┤
│  LMStudio (Pillar 2) │       ComfyUI (Pillar 3)                │
│                       │                                         │
│  Local LLM inference  │  Image / Video generation               │
│  /v1/chat/completions │  Workflow-based diffusion               │
│  MCP tool host        │  API: port 8188                         │
│  Per-request MCPs     │  PromptBuilder 5-tier escalation        │
│  SSE streaming        │  MediaConfig enforced standards         │
│  Model management     │                                         │
└───────────────────────┴─────────────────────────────────────────┘
```

## How They Connect

### Framework → LMStudio
- **client_v2.py**: REST client sends chat messages, receives completions
- **CharacterAgent**: Dual-path — SDK for tools, REST for MCP
- **MCP integrations**: Framework attaches tools per-request via `integrations` field
- **Model management**: LMStudioManager loads/unloads models via CLI

### LMStudio → Framework
- **MCP tools**: LMStudio calls CosySim tools (search_memory, adjust_relationship, etc.)
- **MCP resources**: LMStudio reads CosySim data (config, chains, character profiles)
- The LLM can both **read our data** and **act on our system**

### Framework → ComfyUI
- **ComfyUI client**: Sends workflow requests for image/video generation
- **PromptBuilder**: Constructs detailed prompts with character descriptions
- **MediaConfig**: Enforces standard dimensions (512×768 selfies, 640×480 video)

### Framework → TTS
- **qwen3_server.py**: Generates voice messages as WAV files
- **VoiceDesigner**: Manages character voice profiles
- **Skills**: Agents can generate voice autonomously

## Key Principles

1. **Three Pillars** — CosySim + LMStudio + ComfyUI. Framework orchestrates, doesn't replace.
2. **If it's not in EventChain, it didn't happen** — Every interaction gets chain_id + causal tree.
3. **Skills are the interface** — Agents → skills → services. Skills return strings.
4. **MCP is the bridge** — LMStudio calls CosySim tools, CosySim calls LMStudio for inference.
5. **Graceful degradation** — Every external service has placeholder/offline mode.
6. **Config over code** — Ports, URLs, models, dimensions — all in YAML.
7. **Framework ≠ content** — Engine is reusable. Scenes are examples.
8. **Media standards enforced** — All generated media follows MediaConfig dimensions.
9. **Agents perceive, decide, act** — Multi-agent scenes use tick-based coordination.
10. **Log everything, benchmark everything** — `@timed` on all external calls. KPIs matter.
11. **GOD mode exists** — Full override access for debugging.
12. **Voice has character** — Every character has a voice design. Consistency matters.

## Service Map

| Service | Port | Launch | Purpose |
|---------|------|--------|---------|
| Hub | 8500 | `--mode hub` | Central dashboard |
| Dashboard | 8501 | `--mode dashboard` | Streamlit dashboard |
| Admin | 8502 | `--mode admin` | Admin panel (13 pages) |
| Scene Creator | 8504 | `--mode creator` | Scene wizard |
| Phone Scene | 5555 | `--mode phone` | Flask phone simulator |
| Bedroom Scene | 5556 | `--mode bedroom` | Flask multi-agent |
| TTS Server | 8600 | `--mode tts` | Voice generation |
| Web Bridge | 8601 | `--mode bridge` | FastAPI + MCP |
| LMStudio | 1234 | External | LLM inference |
| ComfyUI | 8188 | External | Image generation |

## Data Flow Example

```
User types message in phone scene
  → Phone scene POST /api/chat
    → CharacterAgent.reply(message)
      → EventChain.log("user_message", chain_id=X)
      → RAG search for relevant memories
      → Build system prompt + history
      → client_v2.chat(messages, integrations=[MCP.plugin("mcp/cosysim")])
        → LMStudio /v1/chat/completions
          → LMStudio calls MCP tool: search_memory("birthday")
            → CosySim MCP server → ChromaDB search → result
          → LMStudio generates response using tool result
        ← SSE stream of tokens
      → EventChain.log("llm_response", chain_id=X)
      → record_llm_kpi(latency, tokens_in, tokens_out)
    ← Reply text
  ← Display in phone UI
```
