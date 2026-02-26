# CosySim Roadmap

> Current: **v0.52b** | Last updated: 2025-07-16

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

### v0.52b — Sprint 8: Knowledge Seeding, Tuning, Agent System ✅ (in progress)
- [x] Nexus knowledge dump — 49-model catalog, settings guide, technical findings stored
- [x] Nexus audit rules — structured audit requirements enforced
- [ ] Automated inference benchmarking framework
- [ ] Auto-tuner for LMStudio settings optimization
- [ ] Inference transaction monitor
- [ ] Agent onboarding documentation
- [ ] Agent task scheduler for overnight automation
- [ ] 8 new coding agent templates
- [ ] QoL automations (Chrome extension, PowerShell scripts, AutoHotkey, Logitech profiles)
- [ ] Documentation overhaul and rating systems

---

## Next Up

### v0.53 — Inference Intelligence & Benchmarking

**Automated tuning** — Find optimal model configurations:
- [ ] Benchmark framework (TPS, TTFT, latency per config matrix)
- [ ] Auto-tuner (iterative settings optimizer, stores optimal configs in Nexus)
- [ ] CPU overflow hypothesis testing (route simple tasks to CPU-only models)
- [ ] Smart routing validation (measure GPU+CPU split vs GPU-only performance)
- [ ] Live inference monitoring (queue depth, utilization, bottleneck detection)

**Agent self-improvement** — Close the feedback loop:
- [ ] A/B testing framework for prompts and configurations
- [ ] Agent performance metrics (engagement, coherence, creativity scores)
- [ ] Automatic prompt refinement based on evaluation results
- [ ] Experiment result storage in Nexus with analysis

### v0.54 — Canvas Interface System

**Dynamic UI generation** — Agents create their own interfaces:
- [ ] Canvas component library (charts, forms, grids, media viewers)
- [ ] Agent-driven layout generation (describe UI → get working interface)
- [ ] Real-time data binding between agent state and UI components
- [ ] Template system for common patterns (dashboard, chat, game board)

**Scene creator upgrade** — Visual scene building:
- [ ] Drag-and-drop scene layout
- [ ] Visual skill/interceptor wiring
- [ ] Live preview with hot-reload

### v0.55 — Training & Fine-tuning Platform

**Training environment** — Systematic model improvement:
- [ ] Conversation quality scoring pipeline
- [ ] Automated training data generation from scenes
- [ ] Fine-tune experiment tracking in Nexus
- [ ] Model comparison dashboards
- [ ] Regression detection (model quality alerts)

### v0.56+ — Advanced Features

**Multi-agent orchestration:**
- [ ] Agent teams with role specialization
- [ ] Debate/consensus protocols
- [ ] Agent-to-agent teaching (knowledge transfer)
- [ ] Emergent behavior detection and logging

**Scene intelligence:**
- [ ] Scene auto-scaling (adjust tick rate, agent count based on activity)
- [ ] Cross-scene event propagation (events in one scene affect others)
- [ ] Agent migration between scenes with state preservation

**Production readiness:**
- [ ] Scene packaging (export/import scenes as packages)
- [ ] Plugin marketplace (share skills, interceptors, scenes)
- [ ] Remote agent support (agents running on different machines)
- [ ] Performance profiling and bottleneck detection

---

## Scene Quality Targets

| Scene | Current | Target | Priority |
|-------|---------|--------|----------|
| Bedroom | A+ (78) | A+ | Maintain |
| Casino | B+ (65) | A (70+) | v0.53 |
| Lounge | B (62) | A- (68+) | v0.53 |
| Tavern | B (60) | B+ (65+) | v0.54 |
| Heist | B (59) | B+ (65+) | v0.54 |
| Phone | B (59) | A- (68+) | v0.53 |
| Command Center | B (58) | B+ (65+) | v0.54 |
| Games | B- (55) | B (60+) | v0.54 |
| Warzone | C+ (54) | B (60+) | v0.53 |
| Gallery | C+ (53) | B (60+) | v0.53 |
| Coders | C (45) | B- (55+) | v0.54 |
| NeonCity | C (43) | B- (55+) | v0.54 |
| Realm | C- (41) | C+ (50+) | v0.55 |

---

## Architecture Principles

1. **Everything through MCP** — Skills, state, events, and cross-system communication all go through the MCP pipeline
2. **Nexus as truth** — Prompts, rules, configurations, session history, and experiment results live in Nexus
3. **Local-first** — No cloud dependencies. LMStudio, ChromaDB, ComfyUI, TTS all run locally
4. **Test-driven** — Every feature gets tests. Current: 2,613 CosySim + 253 Nexus
5. **Scene independence** — Scenes are self-contained. Adding a scene shouldn't break others
6. **Agent freedom within rails** — Governance pipeline enforces consistency without killing creativity
7. **Nexus-first workflow** — Search Nexus before coding, store decisions after. Audit results always go to Nexus
