# CosySim Roadmap

> Current: **v0.50b** | Last updated: 2025-02-25

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

---

## Next Up

### v0.51 — Multi-Model Orchestration & Agent Intelligence

**Multi-model routing** — Route tasks to the right model size:
- [ ] Big/small agent routing (complex reasoning → large model, simple replies → small model)
- [ ] JIT model loading — load models on demand, evict when idle
- [ ] Concurrency controls — parallel inference with queue management
- [ ] Model capability profiles (context window, speed, strengths)
- [ ] Cost/latency budget per scene

**Agent self-improvement** — Close the feedback loop:
- [ ] A/B testing framework for prompts and configurations
- [ ] Agent performance metrics (engagement, coherence, creativity scores)
- [ ] Automatic prompt refinement based on evaluation results
- [ ] Experiment result storage in Nexus with analysis

**Scene intelligence** — Smarter scene management:
- [ ] Scene auto-scaling (adjust tick rate, agent count based on activity)
- [ ] Cross-scene event propagation (events in one scene affect others)
- [ ] Agent migration between scenes with state preservation

---

### v0.52 — Canvas Interface System

**Dynamic UI generation** — Agents create their own interfaces:
- [ ] Canvas component library (charts, forms, grids, media viewers)
- [ ] Agent-driven layout generation (describe UI → get working interface)
- [ ] Real-time data binding between agent state and UI components
- [ ] Template system for common patterns (dashboard, chat, game board)

**Scene creator upgrade** — Visual scene building:
- [ ] Drag-and-drop scene layout
- [ ] Visual skill/interceptor wiring
- [ ] Live preview with hot-reload

---

### v0.53 — NotebookLM Integration & Knowledge Automation

**Full NLM backend** — Research at scale:
- [ ] Live NotebookLM API integration (create, query, converse)
- [ ] Multi-notebook research sessions (4+ notebooks per topic)
- [ ] Automatic knowledge distillation (NLM → Nexus entries)
- [ ] Agent-driven research workflows (plan → research → synthesize)

**Knowledge pipeline** — Continuous learning:
- [ ] Session history auto-ingestion into Nexus
- [ ] Change log tracking with semantic analysis
- [ ] Dependency graph visualization
- [ ] Rule system for knowledge validation before ingestion

---

### v0.54 — Training & Fine-tuning Platform

**Training environment** — Systematic model improvement:
- [ ] Conversation quality scoring pipeline
- [ ] Automated training data generation from scenes
- [ ] Fine-tune experiment tracking in Nexus
- [ ] Model comparison dashboards
- [ ] Regression detection (model quality alerts)

---

### v0.55+ — Advanced Features

**Multi-agent orchestration:**
- [ ] Agent teams with role specialization
- [ ] Debate/consensus protocols
- [ ] Agent-to-agent teaching (knowledge transfer)
- [ ] Emergent behavior detection and logging

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
| Casino | B+ (65) | A (70+) | v0.51 |
| Lounge | B (62) | A- (68+) | v0.51 |
| Tavern | B (60) | B+ (65+) | v0.52 |
| Heist | B (59) | B+ (65+) | v0.52 |
| Phone | B (59) | A- (68+) | v0.51 |
| Command Center | B (58) | B+ (65+) | v0.52 |
| Games | B- (55) | B (60+) | v0.52 |
| Warzone | C+ (54) | B (60+) | v0.51 |
| Gallery | C+ (53) | B (60+) | v0.51 |
| Coders | C (45) | B- (55+) | v0.52 |
| NeonCity | C (43) | B- (55+) | v0.52 |
| Realm | C- (41) | C+ (50+) | v0.53 |

---

## Architecture Principles

1. **Everything through MCP** — Skills, state, events, and cross-system communication all go through the MCP pipeline
2. **Nexus as truth** — Prompts, rules, configurations, session history, and experiment results live in Nexus
3. **Local-first** — No cloud dependencies. LMStudio, ChromaDB, ComfyUI, TTS all run locally
4. **Test-driven** — Every feature gets tests. Current: 1,839 CosySim + 263 Nexus
5. **Scene independence** — Scenes are self-contained. Adding a scene shouldn't break others
6. **Agent freedom within rails** — Governance pipeline enforces consistency without killing creativity
