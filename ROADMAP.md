# CosySim Roadmap

> Current: **v0.55b** | Last updated: 2025-07-20

## Philosophy

CosySim is a **meta-system** — a playground for designing, testing, benchmarking, and evolving AI agent interactions. Every scene is a self-contained experiment combining agents, state, game logic, and UI. The framework exists so that agents (and humans) can methodically explore what works, feed results back into the system, and continuously improve.

---

## Completed

### v0.50a — Master Consolidation & Nexus Integration
- Unified 13 scenes on BaseScene + MCP pipeline
- 194 MCP skills across 26 packs
- 25-interceptor governance pipeline
- LMStudio v1 API with stateful conversations, branching, streaming
- Nexus knowledge system with ChromaDB, FTS5, plugin hooks
- Session logger, knowledge seeding, experiment framework
- Cross-scene agent state persistence
- Training pipeline Nexus integration

### v0.50b — Nexus Expansion & Scene Polish
- Nexus Q&A distillation cache, Research Manager, YouTube ingestion
- Plugin system with lifecycle hooks
- Scene quality uplift (22 new skills across 5 scenes)
- Experiment framework with 4 skills
- Bedroom v5→v6 (furniture overhaul, director avatar, camera views, room layout)
- Deprecation cleanup (88 warnings → 2 third-party)
- 1,839 tests passing, 263 Nexus tests

### v0.51 — Multi-Model Orchestration & Agent Intelligence ✅
- [x] InferenceOrchestrator — unified facade bridging ModelManager, InferenceRouter, ResourceManager
- [x] Big/small agent routing via tier selection (classify→router, act→gpu_primary, background→cpu_utility)
- [x] JIT model loading with TTL-based eviction (ModelManager JIT_TTL mode with reaper thread)
- [x] Concurrency controls — 6 ResourceManager strategies (SINGLE_BIG, CONCURRENT, MULTI_SMALL, JIT_SWAP, SPECULATIVE, HYBRID)
- [x] Model capability profiles (InferenceConfig + LoadConfig with from_agent_profile/from_yaml)
- [x] Nexus 4-tier query router (Q&A cache → FTS5 → NLM synthesis → deep research)
- [x] Nexus control panel (8-page Streamlit dashboard on :8702)
- [x] URL system — ingestion, chunking, heading extraction
- [x] Config validator — 22-key schema validation with enum + range checks
- [x] 10 Copilot agents (.github/agents/) + 9 instruction files (.github/instructions/)
- [x] 1,903 tests passing

### v0.51b — Sprint 6+7: URL System, llmster, Audit Hardening ✅
- [x] URL manager with heading/chunking patterns for web content ingestion
- [x] llmster CLI bridge — 5 MCP tools wrapping `lms.exe` commands
- [x] 92 MCP tools batch-hardened with try/except error handling
- [x] 3 critical bug fixes (LoadConfig import, duplicate nexus_maintain, hardcoded port)
- [x] 4 YAML sections annotated as RESERVED (stt, security, testing, observability)
- [x] `llm.custom_context` config key for agent context injection
- [x] 5 new test files: lounge (79), gallery (49), games (60), activity_bus (33), resilience (30)
- [x] All 11 scenes migrated to governance framework (build_governance_context + StateCoordinator)
- [x] 144 MCP server tools, 160 MCP skills across 25 packs
- [x] 2,613 tests passing across 75+ files

### v0.52b — Sprint 8: Knowledge Seeding, Tuning, Agent System ✅
- [x] Nexus knowledge dump — 49-model catalog, settings guide, technical findings stored
- [x] Nexus audit rules — structured audit requirements enforced

### v0.53b — Training Pipeline & Metrics ✅
- [x] Training pipeline wiring and metrics collection
- [x] Metrics backup and audit systems

### v0.54b — NLM Intelligence Layer ✅
- [x] NLM Engine, Knowledge Forge, NLM Router (4-tier: cache → FTS → synthesis → deep research)
- [x] Copilot Bridge session hooks
- [x] 10 NLM forge MCP skills
- [x] NLM CLI (16 commands)
- [x] Nexus Control Panel upgrades — 28 new routes, NLM Lab tab
- [x] HAR extractor for NotebookLM

### v0.55b — Full-Project Audit & Hardening ✅ ← CURRENT
- [x] 3,521 tests passing (was ~3,012), 0 failures
- [x] ResourceManager deadlock fix (Lock → RLock)
- [x] Router training data capture system for 270M model fine-tuning
- [x] Bedroom scene mixin refactor (2,610 → 1,300 lines) — combat, dialog, inventory, social
- [x] Frontend polish — 30s timeout, toast notifications, button guards
- [x] Config hardening — all 18 scenes in production.yaml
- [x] unittest → pytest migration
- [x] Project grade: A- (was B+)

---

## Next Up

### v0.56b — Live Wire & Streaming

- [ ] Live wire testing framework for end-to-end scene validation
- [ ] Socket.IO streaming for batch operations
- [ ] Scene template system (scaffold new scenes from archetypes)
- [ ] Agent performance metrics (engagement, coherence, creativity scores)
- [ ] Cross-scene event propagation

### v0.57+ — Advanced Features

**Multi-agent orchestration:**
- [ ] Agent teams with role specialization
- [ ] Debate/consensus protocols
- [ ] Agent-to-agent teaching (knowledge transfer)
- [ ] Emergent behavior detection and logging

**Production readiness:**
- [ ] Scene packaging (export/import scenes as packages)
- [ ] Remote agent support (agents running on different machines)
- [ ] Performance profiling and bottleneck detection
- [ ] Plugin marketplace (share skills, interceptors, scenes)

---

## Architecture Principles

1. **Everything through MCP** — Skills, state, events, and cross-system communication all go through the MCP pipeline
2. **Nexus as truth** — Prompts, rules, configurations, session history, and experiment results live in Nexus
3. **Local-first** — No cloud dependencies. LMStudio, ChromaDB, ComfyUI, TTS all run locally
4. **Test-driven** — Every feature gets tests. Current: 3,521 CosySim tests
5. **Scene independence** — Scenes are self-contained. Adding a scene shouldn't break others
6. **Agent freedom within rails** — Governance pipeline enforces consistency without killing creativity
7. **Nexus-first workflow** — Search Nexus before coding, store decisions after. Audit results always go to Nexus
