# Changelog

All notable changes to CosySim are documented here.

## [2.0.0] — 2026-02-20

### Three Pillars Architecture
- **LMStudio Deep Integration** — REST client v2 (`engine/lmstudio/client_v2.py`) with `/api/v1/` protocol support, per-request MCP integrations, SSE streaming, abort support
- **FastMCP Server** — 9 tools + 5 resources exposing CosySim capabilities to LMStudio (`engine/mcp/cosysim_server.py`)
- **FastAPI Web Bridge** — SSE streaming proxy, file upload, CORS (`engine/mcp/web_bridge.py`)
- **CharacterAgent MCP Mode** — Agents use REST API with MCP integrations when enabled, fallback to SDK

### Voice Generation
- **Qwen3-TTS Server** — FastAPI + FastMCP on port 8600, real model loading from `pretrained_models/`, placeholder WAV fallback
- **Voice Designer** — `CASTING_OFFICE` registry with 6 presets, zero-shot support, character voice persistence
- **Voice Message Pipeline** — VoiceMessageGenerator → Qwen3-TTS HTTP → WAV files in `content/media/voice_messages/`
- **Long-form Audio** — Sentence-boundary chunking for 10s to 60min generation
- **TTS Skills** — 4 skills: generate_voice_message, list_voicemails, cast_voice, get_voice_status

### KPI & Benchmarking
- **KPI Dashboard** — LLM latency, token throughput, system monitor (CPU/RAM/VRAM), chain analytics
- **LLM KPI Tracking** — Per-call timing, tokens/sec, model comparison
- **Timeseries Store** — Rolling window benchmarks with export support

### Agent System
- **CharacterAgent in Scenes** — Phone and bedroom scenes use CharacterAgent with skill packs
- **AgentLoop Skill Cascade** — agent.reply() → quick_query() → HTTP → random fallback
- **Location-Aware Perception** — Agents know what activities are available and whether location is private
- **Enriched Idle Actions** — Context-sensitive idle descriptions based on current location

### Scenes
- **Phone Scene** — Arousal engine (5 NSFW tiers), spontaneous media, autonomous voice messages, dynamic mood
- **Bedroom Scene** — Multi-agent spatial system, 7 locations, 2-character AgentLoop, emergent behavior
- **Hub Scene** — Three Pillars status panel, health strip (4 services), scene launcher cards
- **Admin Panel** — 12-page modular admin with GOD mode, RAG editor, chain browser, config editor, KPI dashboard
- **Scene Creator** — Wizard with 4 templates, scaffolding, onboarding

### Framework
- **EventChain Ground Truth** — chain_id/parent_id causal trees, 16+ event types, complete interaction logging
- **DB CRUD** — 10 tables (incl. character_relationships), full CRUD + search/pagination
- **Media Standards** — MediaConfig singleton from YAML: selfie 512×768, video 640×480, audio 22050Hz
- **PromptBuilder** — 5-tier escalation for image/video prompts
- **Logging & Monitoring** — `@timed` decorator, SystemMonitor, ring buffer, structured logging
- **Resilience** — Retry with exponential backoff, circuit breaker, config validation
- **Scene Registry** — Dynamic scene discovery and registration

### Testing
- **315 tests** across 15 test files
- **18 integration tests** spanning all three pillars
- **22 live wire tests** validating real service connections
- Test command: `python -m pytest tests/ -v`

### Documentation
- `docs/THREE_PILLARS.md` — Architecture overview
- `docs/LMSTUDIO.md` — Deep integration guide, MCP setup, streaming
- `docs/TTS.md` — Qwen3-TTS voice design, casting office
- `docs/KPI.md` — Benchmarking, metrics, dashboard usage
- `docs/STRUCTURE_GUIDE.md` — Complete project structure
- `docs/SKILLS.md` — Skill system and MCP tools
- `docs/COMFYUI.md` — ComfyUI integration guide
- `docs/API.md` — API reference

---

## [1.0.0] — Initial Release

- Basic phone scene with LLM chat
- ComfyUI image generation
- SQLite database
- Character system with personalities
- RAG memory via ChromaDB
