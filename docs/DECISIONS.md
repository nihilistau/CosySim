# Architecture Decision Records

> CosySim Documentation — v1.50 [2026-03-22]
>
> Key design decisions and their rationale. New decisions go at the top.

---

## ADR-014: Documentation Overhaul — Unified Versioning (2026-03-22)
**Context:** 39 doc files with version stamps ranging from v0.73b to v1.50. Skill count claims (178) were 5x off from actual (1,000). Scene count said "20" when 32 targets existed. Three separate docs covered the Nexus/NLM system.
**Decision:** Complete rewrite of all documentation at v1.50. Merge overlapping docs (3 Nexus → 1, DEPLOYMENT+OPERATIONS → 1). Archive stale meta-docs. Fix all numbers from codebase audit.
**Consequences:** 25 active docs (down from 31). All docs at v1.50. Numbers verified against code. Archive preserves historical narrative.

## ADR-013: Three-Pillar Architecture (2026-03-21)
**Context:** Flat launcher with 20+ targets and no organization. Hard to understand what runs where and why.
**Decision:** Organize all 32 targets into three pillars — GAME (15 scenes), SERVICE (11 infrastructure), CREATION (6 authoring tools). Defined in `engine/control_plane_registry.py`.
**Consequences:** Launcher flags: `--game`, `--services`, `--creation`, `--core`, `--all`. Clear separation of concerns. Each pillar can start independently. TUI organizes by pillar.

## ADR-012: Codespace as Remote Execution Environment (2026-02-26)
**Context:** Tests take 3.5+ min locally. Need cloud-based test/eval capability for LLM agents.
**Decision:** Wrap `gh codespace` CLI in `engine/codespace/manager.py`. Expose as 6 MCP skills.
**Consequences:** Agents can run tests remotely. Requires `codespace` scope on gh auth. Usage costs GitHub minutes.

## ADR-011: Triple-Layer Knowledge Architecture (2026-02-25)
**Context:** Knowledge lives in local Nexus but needs to be accessible to GitHub Copilot agents.
**Decision:** Nexus (local, authoritative) → Copilot Spaces (cloud, synced) → Copilot Memory (auto-generated).
**Consequences:** Knowledge flows one-way up. space_exporter.py bridges Nexus→Space. Manual sync for now, automated later.

## ADR-010: Copilot Coding Agent for Knowledge Pipeline (2026-02-25)
**Context:** Need automated research and knowledge curation at scale.
**Decision:** GitHub Issues → Copilot coding agent → PRs → merge → pull results to Nexus.
**Consequences:** Requires `copilot-setup-steps.yml` on default branch. Agent creates `copilot/*` branches.

## ADR-009: InferenceOrchestrator as Unified API (2026-02-20)
**Context:** ModelManager, InferenceRouter, ResourceManager were separate with inconsistent interfaces.
**Decision:** Single `get_orchestrator().infer()` call bridges all three. Auto tier selection, model loading, perf tracking.
**Consequences:** Simplified calling code. Single point of failure but with fallback logic.

## ADR-008: MCP Framework State Tree (2025-12)
**Context:** Game state was scattered across Python locals, globals, and database.
**Decision:** All mutable state syncs to MCPFramework tree. MCPSceneNode per scene, MCPCharacterNode per character.
**Consequences:** State is inspectable, serializable, and consistent. Slight overhead for tree operations.

## ADR-007: @skill Decorator for Tool Calling (2025-11)
**Context:** LLM tool functions were ad-hoc with inconsistent registration.
**Decision:** `@skill(pack=..., description=..., category=...)` decorator auto-registers into SKILL_REGISTRY.
**Consequences:** Uniform skill interface. ~1,000 skills across 95 packs (as of v1.50). 8 categories enable filtering. AgentGovernor filters to ~50-80 relevant skills per call.

## ADR-006: Interceptor Pipeline for Agent Governance (2025-11)
**Context:** Need to inject context, enforce rules, shape responses without modifying agent code.
**Decision:** Priority-ordered interceptor chain. pre_call modifies request, post_call modifies response.
**Consequences:** 24 interceptors (as of v1.50). Composable but ordering matters. Lower priority = runs first.

## ADR-005: LMStudio v1 API with SSE Streaming (2025-10)
**Context:** Need local LLM inference with streaming and conversation state.
**Decision:** LMStudio v1 API at localhost:1234. SSE event-based streaming. Stateful conversations via store+previous_response_id.
**Consequences:** Tied to LMStudio. Custom SSE parser needed (not OpenAI-compatible). Works well with GGUF models.

## ADR-004: Nexus as Central Knowledge System (2025-10)
**Context:** Need persistent knowledge that survives sessions and can be queried by agents.
**Decision:** Nexus KMS at localhost:8700. REST API + CLI + MCP integration. FTS5 search.
**Consequences:** External dependency (auto-managed since v1.42). 47 client methods. Dual integration: skill-based (for agents) + direct HTTP (for scripts).

## ADR-003: BaseScene Pattern for Scene Development (2025-09)
**Context:** Each scene was a standalone Flask app with no shared infrastructure.
**Decision:** BaseScene class with required overrides (start, stop, get_plugin_info). MCPSceneMixin for state. NexusSceneMixin for knowledge.
**Consequences:** Consistent scene structure. 19 Flask scenes follow pattern (as of v1.50). 4 Streamlit apps are utility-only.

## ADR-002: Flask + Socket.IO for Scene Web Apps (2025-09)
**Context:** Need real-time interactive web interfaces for each scene.
**Decision:** Flask with Jinja2 templates. Socket.IO for real-time updates. Vanilla JS (no build step).
**Consequences:** Simple deployment. No frontend framework complexity. Each scene is self-contained.

## ADR-001: Python-First Local Architecture (2025-08)
**Context:** Building an AI simulation framework for local development and experimentation.
**Decision:** Python 3.11+, local-first (no cloud dependencies), LMStudio for inference, all state on local filesystem.
**Consequences:** Full control. No API costs for inference. Limited by local hardware (12GB VRAM). Requires manual deployment for remote access.

---

## Change Log

| Version | Date | Changes |
|---------|------|---------|
| v1.50 | 2026-03-22 | Doc overhaul — added ADR-013 (three-pillar) and ADR-014 (doc overhaul), fixed stale numbers in ADR-003/006/007 |
| v1.42 | 2026-03-21 | ADR-012 added (Codespace remote execution) |
