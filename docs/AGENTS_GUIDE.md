# 🤖 CosySim — Agent Handoff Guide

> Everything an AI agent needs to take over this codebase and keep building.

---

## 1. Project Identity

**CosySim** is a **framework for building AI agent simulation scenes**.  
Think of it as a game engine where the NPCs are real LLM-powered agents.

| Layer | Directory | Purpose |
|-------|-----------|---------|
| **Engine** | `engine/` | Reusable platform — assets, agents, skills, scenes, config, LMStudio |
| **Content** | `content/` | Example scenes (phone, bedroom, hub) that demonstrate the framework |
| **Config** | `config/` | YAML config files, env-var overridable |

---

## 2. The Most Important Concept: EventChain

**If it's not in EventChain, it didn't happen.**

Every interaction gets a `chain_id` (UUID). Events within a chain link via `parent_id`,
forming a causal tree. This is the audit trail, the debugger, the replay system.

```
message_in → rag_query → rag_result → llm_request → tool_call → tool_result → llm_response → message_out
```

**Key file:** `content/simulation/database/events.py`  
**16 event types:** message_in/out, llm_request/response/cancelled, rag_query/result,
memory_stored, skill_called/result, tool_call/result, media_generated,
autonomous_trigger, scene_state_change, error

---

## 3. How Agents Work

```
User message → PhoneScene.handle_send_message()
  → set_chain_context(chain_id, scene_id)
  → CharacterAgent._act()
    → query RAG for relevant memories
    → build system prompt (personality + memories + context)
    → call LMStudio LLM (via lmstudio SDK)
    → LLM may invoke skills as tools
    → skills read chain context from thread-local
    → response returned
  → clear_chain_context()
  → emit response to client
```

**Critical pattern:** Skills can't receive `chain_id` as kwargs because the LMStudio
SDK invokes them. Solution: `engine/skills/chain_context.py` stores chain context
in thread-local storage. `CharacterAgent._act()` sets it before calling the LLM and
clears it after.

---

## 4. Running the Project

```bash
# Install
pip install -e .

# Run tests (75 tests, should all pass)
python -m pytest tests/ -v --tb=short

# Launch specific scenes
python launcher.py --mode phone      # Port 5555
python launcher.py --mode bedroom    # Port 5556
python launcher.py --mode hub        # Port 8500 (Streamlit)
python launcher.py --mode dashboard  # Port 8501 (Streamlit)
python launcher.py --mode admin      # Port 8502 (Streamlit)

# Quick health checks
python launcher.py --status
python launcher.py --init-db
```

**Hardware:** RTX 2060 12GB, VRAM cap 11.5GB.  
**Environment:** Windows, Python 3.10.19, conda env "cosyvoice".

---

## 5. Key Files Map

| What | File | Notes |
|------|------|-------|
| Database CRUD | `content/simulation/database/db.py` | 9 tables, full CRUD, parameterised queries |
| EventChain | `content/simulation/database/events.py` | Ground truth — never bypass this |
| RAG Memory | `content/simulation/database/rag.py` | ChromaDB vector store, logs to EventChain |
| Character Agent | `engine/agents/character_agent.py` | Core agent loop — reply(), _act() |
| Chain Context | `engine/skills/chain_context.py` | Thread-local context for skills |
| Skill Registry | `engine/skills/registry.py` | @skill decorator, pack system |
| BaseScene | `engine/scenes/base_scene.py` | Abstract base for all scenes |
| Phone Scene | `content/scenes/phone/phone_scene.py` | Largest scene, 52+ Flask routes |
| Bedroom Scene | `content/scenes/bedroom/bedroom_scene.py` | 3D Three.js scene |
| Config | `engine/config.py` | Dot-notation, env-var override |
| Launcher | `launcher.py` | Unified entry point |

---

## 6. Database Schema

9 tables in SQLite (`simulation/simulation.db`):

| Table | Key Columns | Full CRUD? |
|-------|-------------|:----------:|
| characters | id, name, age, sex, personality_id, tags, metadata | ✅ |
| personalities | id, name, system_prompt, traits, warmth..creativity | ✅ |
| roles | id, name, description, required_traits | ✅ |
| memories | id, character_id, content, importance, emotion | ✅ |
| conversations | id, character_id, chain_id, messages, started_at | ✅ |
| interactions | id, type, character_id, content, chain_id | ✅ |
| media | id, character_id, type, filepath, metadata | ✅ |
| character_states | character_id, mood, energy, relationship_level, warmth..creativity | ✅ |
| events | id, chain_id, parent_id, event_type, actor, payload | ✅ (EventChain) |

---

## 7. Skill System

Skills are Python functions decorated with `@skill()` and grouped into packs.

```python
from engine.skills.registry import skill, SkillPack

@skill(name="search_memories", description="Search character memories")
def search_memories(query: str, character_id: str = "", top_k: int = 5) -> str:
    ctx = get_chain_context()  # Read thread-local chain context
    ...
    return "Found 3 relevant memories..."
```

**4 skill packs:** character (4 skills), comfyui (3), memory (4), voice (2) = 13 total.

---

## 8. Config System

```yaml
# config/settings.yaml
services:
  lmstudio:
    host: localhost
    port: 1234
  comfyui:
    host: localhost
    port: 8188
```

Access: `get_config().get("services.lmstudio.port", 1234)`  
Override: `COSYSIM_SERVICES__LMSTUDIO__PORT=5678` env var

---

## 9. Architecture Principles

1. **If it's not in EventChain, it didn't happen.** Every service must propagate chain_id.
2. **Skills are the interface.** Agents talk to services through skills. Skills return strings.
3. **Graceful degradation.** Every external service has a placeholder/offline mode.
4. **Config over code.** Ports, URLs, models, thresholds — all in YAML.
5. **Framework ≠ content.** Engine is reusable. Scenes are examples.
6. **Test the ground truth.** EventChain tests are the most important tests.

---

## 10. Test Suite

```bash
python -m pytest tests/ -v --tb=short
```

| Test File | Count | What It Tests |
|-----------|:-----:|---------------|
| test_event_chain.py | 12 | Chain creation, event logging, tree reconstruction |
| test_config.py | 5 | Dot-notation, env override, set/get |
| test_skills.py | 6 | @skill decorator, SkillPack, chain context |
| test_database.py | 52 | Full CRUD for all 8 data tables |
| **Total** | **75** | |

---

## 11. Known State & Next Steps

### ✅ Working
- All Python files compile cleanly
- 75/75 tests passing
- EventChain wired as ground truth through RAG, skills, media, agent loop
- Dark mode UI across all Streamlit scenes
- Phone scene: messaging, gallery, voice/video messages, autonomous messaging
- Phone scene: dynamic mood/relationship system, read receipts, typing indicator
- Bedroom scene: 3D environment, character animations, chat
- Full DB CRUD with count/search/pagination helpers
- Lifecycle hooks in BaseScene now fire correctly

### 🔲 Ready to Build
- **Qwen3-TTS integration** — voice message generation (see user's original request)
- **Call UI** — voice/video call buttons are disabled ("coming soon")
- **Scene scaffolding** — `cosysim new-scene <name>` CLI tool
- **More skill packs** — vision, web search, calendar, etc.
- **Scene discovery** — auto-detect scenes from directory structure
- **Pub/sub messaging** — inter-scene communication

---

## 12. Adding a New Scene (Step by Step)

1. Create `content/scenes/<name>/` with `__init__.py`
2. Create `<name>_scene.py` inheriting `BaseScene`
3. Implement `start()`, `stop()`, `get_plugin_info()`
4. Add template in `templates/` and static files in `static/`
5. Register skill packs in `__init__` via `SKILL_REGISTRY.register_pack()`
6. Add to `launcher.py` mode_map
7. Add config in `config/settings.yaml`
8. Write tests in `tests/`

---

## 13. Adding a New Skill

1. Create function with `@skill()` decorator
2. Add to a `SkillPack` in `engine/skills/builtin/` or `content/` skills
3. Read chain context: `ctx = get_chain_context()`
4. Log events: `ec.log(chain_id, "skill_called", ...)`
5. Return a string (LLM-friendly description of result)
6. Register pack in scene's `__init__`

---

*Last updated after Phase 8. 75 tests passing. 4 commits on master.*

---

## 10. VirtualAgent Framework

**Phase 5** introduced a decoupled agent architecture.

### Agent vs LLM Execution

| Component | Role |
|-----------|------|
| **VirtualAgent** | Agent identity, state, prompt building, RAG. Implements `IAgent`. |
| **VirtualAgentManager** | Centralized LLM call router. Controls concurrency, model lifecycle, hooks. |
| **InferenceRequest** | Typed request from agent to manager |
| **InferenceResponse** | Typed response from manager to agent |

### Quick Start

```python
from engine.agents.virtual_agent_manager import get_virtual_agent_manager

mgr = get_virtual_agent_manager()
agent = mgr.create_agent(character, scene="bedroom")
reply = agent.reply("Hello!")
```

### CharacterAgent Backward Compat

```python
# Legacy mode (default) — direct LMSClient calls
agent = CharacterAgent(character, scene="bedroom")

# v2.5: CharacterAgent always creates a VirtualAgent internally
agent = CharacterAgent(character, scene="bedroom")
```

### Key Files

| File | Purpose |
|------|---------|
| `engine/agents/virtual_agent.py` | VirtualAgent + InferenceRequest/Response + state persistence |
| `engine/agents/virtual_agent_manager.py` | VirtualAgentManager singleton (inference router) |
| `engine/agents/character_agent.py` | Thin adapter — always delegates to VirtualAgent |
| `engine/agents/agent_loop.py` | 3-phase tick: perceive → batch-decide → execute |
| `engine/agents/scene_agent.py` | One-shot utility agent via VirtualAgentManager |
