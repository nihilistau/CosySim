# CosySim Skills System — v0.60.1

Skills are Python callables that an LLM agent invokes as **tools** during inference.
The `@skill` decorator registers them into the global `SKILL_REGISTRY`. LMStudio
calls skills via MCP tool use during `/api/v1/chat` responses. The system now
includes **195 skills across 21 packs** (13 core + 8 scene packs).

---

## Architecture

```
@skill decorator               engine/skills/skill.py
  └─► SKILL_REGISTRY           engine/skills/registry.py
        ├─ get_pack_tools(pack)  → [callable, …]
        ├─ get_pack_metas(pack)  → [SkillMeta, …]
        ├─ all_tools(tags=[…])   → [callable, …]
        └─ mcp_skill_pack(…)     → MCP integration payload

VirtualAgentManager.infer()     engine/agents/virtual_agent_manager.py
  └─► LMSClient.chat_stateful(messages, tools=[skill_callables])
        └─► LMStudio /api/v1/chat → tool_call → skill function → result
```

---

## All Skill Packs

### Core Packs (engine/skills/builtin/)

| Pack | Module | Skills |
|------|--------|--------|
| `memory` | memory_skills.py | `search_memory`, `store_memory`, `get_event_chain_summary`, `summarize_chain` |
| `character` | character_skills.py | `get_character_state`, `adjust_trait`, `set_mood`, `adjust_relationship` |
| `comfyui` | comfyui_skills.py | `generate_image`, `generate_character_portrait`, `list_comfyui_workflows` |
| `voice` | voice_skills.py | `generate_voice_message`, `list_voice_messages` |
| `tts` | tts_skills.py | `generate_voice_message`, `cast_voice`, `list_voice_presets`, `list_voicemails` |
| `social` | social_skills.py | Social interaction skills |
| `boards` | board_skills.py | Shared board game mechanics |
| `training` | training_skills.py | `trigger_finetune`, `get_training_status`, `export_training_data`, `list_trained_models` |
| `notebooklm` | notebooklm_skills.py | `notebooklm_ask`, `notebooklm_add_source`, `notebooklm_generate_audio`, `notebooklm_list_notebooks`, `notebooklm_search` |
| `nexus` | nexus_skills.py | `nexus_search`, `nexus_add`, `nexus_nlm_ask`, `nexus_status`, `nexus_log_session`, `nexus_store_prompt`, `nexus_search_prompts`, `nexus_get_rules`, `nexus_submit_idea`, `nexus_changelog`, `nexus_ask`, `nexus_research`, `nexus_converse`, `nexus_finish_research`, `nexus_youtube` |
| `coding` | coding_skills.py | `coding_store_snippet`, `coding_store_decision`, `coding_research`, `coding_store_bug`, `coding_log_session`, `coding_find_snippet`, `coding_list_decisions`, `coding_get_session` |
| `nlm_forge` | nlm_forge_skills.py | `nlm_ask`, `nlm_batch_ask`, `nlm_distill`, `nlm_decompose`, `nlm_analyze`, `nlm_solve`, `nlm_build_topic`, `nlm_status`, `nlm_cache_stats`, `nlm_guided_distill` |

### Scene Packs (content/scenes/{name}/{name}_skills.py)

| Pack | Module | Skills | Count |
|------|--------|--------|-------|
| `realm` | realm_skills.py | inventory CRUD, stat checks, director control, murder mystery, fourth-wall, desperation dice | 16 |
| `bedroom` | bedroom_skills.py | wardrobe, interactions, stats, consent, atmosphere, narrative, timed actions, furniture | 10 |
| `neoncity` | neoncity_skills.py | player status, movement, combat, hacking, storm queries, events, end turn | 9 |
| `phone` | phone_skills.py | message send/read, contacts, media, call controls | 6 |
| `casino` | casino_skills.py | game state, betting, cards, table management, jackpots, check, raise, bluff | 9 |
| `heist` | heist_skills.py | crew management, intel, planning, execute phase, escape | 7 |
| `lounge` | lounge_skills.py | jukebox, drinks, secrets, back room, atmosphere, social, trust | 10 |
| `coders` | coders_skills.py | room status, agent info, add feature, feature list, run code, tick | 6 |
| `command_center` | command_center_skills.py | system monitoring, model control, scene status, diagnostics, training | 6 |
| `warzone` | warzone_skills.py | status, attack, build, upgrade, special ops, recon, end turn | 7 |
| `gallery` | gallery_skills.py | exhibit management, art generation, critique, curation, tours, gallery walk | 8 |
| `tavern` | tavern_skills.py | order food/drink, patron info, tales, dice, brawl, cook, menu, atmosphere, secret menu, bard song | 10 |
| `games` | games_skills.py | word games, trivia, creative challenges, scores, status, hint, skip | 7 |

---

## Writing a Skill

### Minimal

```python
from engine.skills import skill

@skill
def greet_user(name: str) -> str:
    """Say hello to a user by name."""
    return f"Hello, {name}! 👋"
```

### Full Decorator

```python
from engine.skills import skill, SkillCategory

@skill(
    name="send_alert",
    pack="notifications",
    description="Send an alert notification.",
    tags=["notify", "urgent"],
    category=SkillCategory.SYSTEM,
    cooldown=10.0,          # seconds between calls
)
def send_alert(message: str, priority: int = 1) -> str:
    """Send a system alert with priority level."""
    return f"Alert sent: {message} (priority={priority})"
```

### Decorator Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | str | function name | Registry key |
| `pack` | str | `"default"` | Group name for filtering |
| `description` | str | docstring first line | Tool description for LLM |
| `tags` | list[str] | `[]` | Filtering tags |
| `category` | SkillCategory | `GENERAL` | Category enum |
| `cooldown` | float | `0.0` | Min seconds between invocations |

### SkillCategory Values

```python
from engine.skills import SkillCategory

SkillCategory.GENERAL      # Default
SkillCategory.GAME         # Game mechanics
SkillCategory.NARRATIVE    # Story/dialog
SkillCategory.SYSTEM       # System operations
SkillCategory.ENVIRONMENT  # Environment queries
SkillCategory.SOCIAL       # Social interactions
SkillCategory.MEDIA        # Media generation
```

---

## Scene-Specific Skills

Scene skills live in `content/scenes/{name}/{name}_skills.py` and use
`get_active_scene()` to access the running scene instance:

```python
from engine.skills import skill, SkillCategory
from engine.scenes.base_scene import get_active_scene

@skill(pack="my_scene", tags=["game"], category=SkillCategory.GAME)
def get_score(player_id: str) -> str:
    """Get a player's current score."""
    scene = get_active_scene("my_scene")
    if not scene or not hasattr(scene, "state"):
        return "Scene not running"
    return str(scene.state.get_score(player_id))
```

**Registration:** Import the skills module in the scene's `__init__.py`:
```python
# content/scenes/my_scene/__init__.py
from . import my_scene_skills  # triggers @skill decorators
```

---

## Querying the Registry

```python
from engine.skills import SKILL_REGISTRY

# List all packs
SKILL_REGISTRY.all_packs()           # → ["memory", "realm", ...]

# Get callables for a pack (pass to LMSClient tools=[...])
tools = SKILL_REGISTRY.get_pack_tools("memory")

# Get metadata for a pack
metas = SKILL_REGISTRY.get_pack_metas("realm")
for m in metas:
    print(f"{m.name}: {m.description} (cooldown={m.cooldown_secs}s)")

# Filter by tags
image_tools = SKILL_REGISTRY.all_tools(tags=["image"])

# Human-readable summary
print(SKILL_REGISTRY.describe())
```

---

## MCP Integration

Skills are exposed to LMStudio as MCP tools via the skills server:

```python
from engine.skills import mcp_skill_pack

payload = mcp_skill_pack(
    server_url="http://localhost:9000",
    allowed_tools=["generate_image", "search_memory"],
    name="cosysim-tools",
)
```

The `engine/mcp/skills_server.py` runs a FastMCP server that
automatically exposes all registered skill packs as MCP tools.

---

## Governance Integration

Skills participate in the AgentGovernor pipeline:

1. **Pre-call interceptors** can modify the tool list before inference
2. **The LLM** calls skills via MCP tool_call during SSE streaming
3. **StreamProcessor** tracks tool call lifecycle (start → args → result)
4. **Post-call interceptors** see tool_calls in the ResponseContext

```python
# In a custom interceptor
class MyInterceptor(InterceptorBase):
    def post_call(self, context):
        for tc in context.get("tool_calls", []):
            print(f"Agent called: {tc.name}({tc.arguments})")
```

---

## Tips

1. **Keep skills small and single-purpose** — the LLM picks tools by name + docstring
2. **Return human-readable strings** — results are fed back to the LLM as tool_result
3. **Type-annotate everything** — LMStudio infers JSON schema from Python type hints
4. **Use cooldown for expensive ops** — prevents rapid repeated image generation
5. **Test skills directly** — they're just Python functions:

```python
from engine.skills.builtin.memory_skills import search_memory
result = search_memory("coffee", character_id="abc123", top_k=3)
```
