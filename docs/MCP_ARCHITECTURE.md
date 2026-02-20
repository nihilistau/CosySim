# CosySim MCP Architecture Guide

> **Audience:** Developers extending or debugging the CosySim agent / governance layer.  
> **Updated:** Current session (post-polish pass)

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [IAgent Protocol](#2-iagent-protocol)
3. [AgentGovernor Lifecycle](#3-agentgovernor-lifecycle)
4. [Interceptor Pipeline](#4-interceptor-pipeline)
5. [GameState & Observer System](#5-gamestate--observer-system)
6. [AgentRouter — Inter-Agent Messaging](#6-agentrouter--inter-agent-messaging)
7. [SkillManifest & Trigger Types](#7-skillmanifest--trigger-types)
8. [Scene Integration Pattern](#8-scene-integration-pattern)
9. [Adding a Custom Interceptor](#9-adding-a-custom-interceptor)
10. [Adding a Custom Skill](#10-adding-a-custom-skill)
11. [Module Exports Quick Reference](#11-module-exports-quick-reference)

---

## 1. System Overview

```
┌──────────────────────────────────────────────────────────────┐
│  Scene Layer  (content/scenes/*)                             │
│  SceneAgent → creates AgentGovernor(CharacterAgent, ...)     │
└──────────────────────────┬───────────────────────────────────┘
                           │  governor.reply(user_message)
┌──────────────────────────▼───────────────────────────────────┐
│  AgentGovernor  (engine/mcp/comms_framework.py)              │
│                                                              │
│  1. Build ResponseContext (sys-prompt, policy, manifest …)   │
│  2. InterceptorPipeline.run_pre(ctx)  ─── PRE hooks          │
│  3. CharacterAgent.reply(user_message, skip_gov=True)  ─LLM  │
│  4. InterceptorPipeline.run_post(ctx) ─── POST hooks         │
│  5. Return ctx["reply"]                                      │
└──────────────────────────────────────────────────────────────┘
              │ reads/writes
┌─────────────▼────────────────────────────────────────────────┐
│  Shared Singletons  (engine/mcp/comms_framework.py)          │
│                                                              │
│  GameState   — game session key/value store + observer bus   │
│  AgentRouter — async inbox messaging between agents          │
│  SkillManifest — per-scene skill definitions (YAML-backed)   │
└──────────────────────────────────────────────────────────────┘
```

All three singletons are module-level and thread-safe.  
Access them via:

```python
from engine.mcp import get_game_state, get_router, get_skill_manifest
```

---

## 2. IAgent Protocol

`engine/agents/protocols.py`

```python
@runtime_checkable
class IAgent(Protocol):
    character: Any                        # character data object
    capabilities: Set[AgentCapability]    # declared capabilities

    def reply(self, user_message: str, *, chain_id=None,
              history=None, **kwargs) -> str: ...

    def quick_query(self, prompt: str, *, max_tokens: int = 200) -> str: ...

    def cancel(self) -> None: ...
```

### AgentCapability Enum

| Value | Meaning |
|-------|---------|
| `text` | Can produce natural language replies |
| `tools` | Has skill packs / tool calls enabled |
| `memory` | Has RAG / long-term memory |
| `streaming` | Supports streaming tokens |
| `tts` | Has voice synthesis wired up |
| `vision` | Can interpret image inputs |
| `image_gen` | Can call image-generation APIs |
| `governed` | Wrapped by an AgentGovernor |
| `policy` | Applies InteractionPolicy |
| `game_player` | Can act as a player in a mini-game |
| `game_host` | Can host / adjudicate a mini-game |

Both `CharacterAgent` and `AgentGovernor` implement `IAgent`. Any object satisfying
the structural protocol can be used in governor position or as a scene agent.

---

## 3. AgentGovernor Lifecycle

```
AgentGovernor(agent, scene="bedroom", pipeline=pipeline)
      │
      ▼
  governor.reply(user_message)
      │
      ├─ skip_gov=True?  ──► agent.reply(user_message) (no pipeline)
      │
      ├─ Build ResponseContext {
      │        system_prompt  = ""            (interceptors fill this)
      │        policy         = InteractionPolicy(...)
      │        skill_manifest = SkillManifest().get(scene)
      │        user_message   = user_message
      │        agent_id       = character.id
      │        scene          = scene
      │    }
      │
      ├─ pipeline.run_pre(ctx)                  (injects system prompt etc.)
      │
      ├─ agent.reply(user_message,              (single LLM call)
      │              system_prompt=ctx["system_prompt"],
      │              skip_gov=True)
      │
      ├─ ctx["reply"] = llm_response
      │
      └─ pipeline.run_post(ctx)                 (shapes / logs response)
            │
            └─► return ctx["reply"]
```

### Dry-Run Debug

```python
dump = governor.context_dump("What should I do?")
# Returns dict — no LLM call made, shows what system_prompt would look like
print(dump["system_prompt"])
```

---

## 4. Interceptor Pipeline

### Full Pipeline (priority order)

| Priority | Interceptor | Phase | What it does |
|----------|-------------|-------|--------------|
| 8  | `CharacterRegistryInterceptor` | pre | Syncs character mood/energy to sys-prompt |
| 10 | `RouterMessageInjector` | pre | Injects pending router messages into ctx |
| 12 | `DialogDirectiveInterceptor` | pre | Applies scene dialog directives |
| 15 | `BedroomSceneInterceptor` | pre | Bedroom-specific sys-prompt additions |
| 15 | `PhoneSceneInterceptor` | pre | Phone scene sys-prompt additions |
| 15 | `LoungeSceneInterceptor` | pre | Lounge scene sys-prompt additions |
| 20 | `AutoResultInjector` | pre | Injects auto-triggered skill results |
| 30 | `SkillAwarenessInterceptor` | pre | Lists REQUIRED / AVAILABLE tools |
| 35 | `GameSessionInterceptor` | pre | Injects active game session state |
| 40 | `GameRulesInterceptor` | pre | Injects game rules if game active |
| 50 | `PersonalityGuardInterceptor` | pre | Adds forbidden topics / required tone |
| 60 | `PolicyEnforcerInterceptor` | pre | Enforces max token prompt reminder |
| 70 | `MemoryEnhancerInterceptor` | pre | Injects top-k semantic memories |
| 80 | `ResponseShaperInterceptor` | post | Strips leaked skill sections, trims |
| 85 | `TTSStyleInterceptor` | post | Builds `ctx["tts_meta"]` for CosyVoice |
| 90 | `ActivityLoggerInterceptor` | post | Logs interaction to DB |
| 92 | `MoodSyncInterceptor` | post | Strips `[MOOD:xxx]` tag, syncs registry |

### Abort Flag

Any pre interceptor can set `ctx["abort"] = True` to stop the pipeline (no LLM
call will be made). The governor will return `ctx.get("reply", "")` as result.

---

## 5. GameState & Observer System

```python
from engine.mcp import get_game_state

gs = get_game_state()

# CRUD
gs.set("blackjack-001", "player_score", 17)
gs.get("blackjack-001", "player_score")         # → 17
gs.increment("blackjack-001", "player_score", 4) # → 21
gs.get_all("blackjack-001")                      # → {"player_score": 21}
gs.reset("blackjack-001")                        # clears game data

# Observer — fires on every set()/increment()/reset()
def on_score_change(game_id: str, key: str, value):
    print(f"[{game_id}] {key} = {value}")

gs.subscribe("blackjack-001", on_score_change)   # single-game observer
gs.subscribe_all(on_score_change)                # all-games observer
gs.unsubscribe("blackjack-001", on_score_change)
```

Observers are called synchronously in the same thread that called `set()` /
`increment()`. If an observer raises, it is silently swallowed to protect other
observers.

---

## 6. AgentRouter — Inter-Agent Messaging

```python
from engine.mcp import get_router

router = get_router()

# Send a message to agent "luna"
router.send("luna", "remind me of the deal we made", sender_id="player",
            meta={"priority": "high"})

# Recipient drains their inbox
messages = router.drain("luna")
# → [{"message": "...", "sender": "player", "meta": {...}, "ts": ...}]

# Non-destructive peek
messages = router.peek("luna")

if router.has_messages("luna"):
    ...
```

`RouterMessageInjector` (priority 10) automatically pipes pending messages into
the system prompt before the LLM call so agents react to them organically.

---

## 7. SkillManifest & Trigger Types

`SkillManifest` is a per-scene registry of available tool/skill calls.

```python
from engine.mcp import get_skill_manifest, TRIGGER_AUTO, TRIGGER_OPTIONAL, TRIGGER_REQUIRED

sm = get_skill_manifest()
phone_scene = sm.get("phone")

auto_skills     = phone_scene.auto_skills()      # always injected as results
optional_skills = phone_scene.optional_skills()  # shown as available
required_skills = phone_scene.required_skills()  # LLM must call these
```

| Trigger | Meaning |
|---------|---------|
| `auto` | Skill fires automatically every turn; result injected into pre-call ctx |
| `optional` | LLM is told the skill exists but chooses whether to call it |
| `required` | LLM is required to call this skill in its reply |

Manifests can be overridden via YAML at `config/default.yaml` under the
`skill_manifest:` key or hot-reloaded per scene.

---

## 8. Scene Integration Pattern

All scenes follow the same pattern: **wrap** a `CharacterAgent` with a governor,
**register interceptors**, **pass the governor** to `SceneAgent`.

```python
# content/scenes/<scene>/scene.py  (reference pattern)

from engine.agents import CharacterAgent, get_governor, AgentGovernor
from engine.mcp import (
    get_game_state, get_router, InteractionPolicy,
    InterceptorPipeline, SkillManifest,
)
from engine.agents.interceptors import _build_default_pipeline

class MyScene:
    def __init__(self, character):
        self.agent: AgentGovernor = get_governor(
            CharacterAgent(character, skill_packs=["memory"]),
            scene="my_scene",
            policy=InteractionPolicy(
                required_tone="warm",
                forbidden_topics=["real names"],
                max_reply_tokens=400,
            ),
        )

    def chat(self, user_message: str) -> str:
        return self.agent.reply(user_message)
```

`get_governor()` creates an `AgentGovernor` backed by the default 17-interceptor
pipeline.  Pass `pipeline=InterceptorPipeline()` to start with a blank pipeline.

---

## 9. Adding a Custom Interceptor

```python
from engine.mcp.comms_framework import InterceptorBase, ResponseContext

class WeatherInjector(InterceptorBase):
    """Inject current weather into system prompt before LLM call."""

    name     = "weather_injector"   # unique identifier
    priority = 45                   # slot in the pipeline (0–100+)

    def pre_call(self, ctx: ResponseContext) -> None:
        weather = fetch_weather()   # your code
        ctx["system_prompt"] += f"\n[Current weather: {weather}]"

    def post_call(self, ctx: ResponseContext) -> None:
        pass   # nothing to do after the LLM responds
```

Register it:

```python
from engine.mcp import get_governor
from my_interceptors import WeatherInjector

gov = get_governor(my_agent, scene="lounge")
gov.pipeline.add(WeatherInjector())  # sorted by priority automatically
```

Remove it later:

```python
gov.pipeline.remove("weather_injector")
```

---

## 10. Adding a Custom Skill

1. **Create the skill function** in `engine/skills/builtin/` or your own module:

```python
# engine/skills/builtin/dice.py
from engine.mcp.comms_framework import SkillResult

def roll_dice(sides: int = 6) -> SkillResult:
    import random
    roll = random.randint(1, sides)
    return SkillResult(
        skill_name="roll_dice",
        output=f"You rolled a {roll}!",
        metadata={"sides": sides, "result": roll},
    )
```

2. **Register the skill** via `SKILL_REGISTRY`:

```python
from engine.skills import SKILL_REGISTRY
from engine.skills.builtin.dice import roll_dice

SKILL_REGISTRY["roll_dice"] = roll_dice
```

3. **Declare it in the scene manifest**:

```python
from engine.mcp.comms_framework import SceneManifest, SkillEntry, TRIGGER_OPTIONAL

manifest = SceneManifest(
    scene="bedroom",
    skills=[
        SkillEntry(name="roll_dice", trigger=TRIGGER_OPTIONAL,
                   description="Roll a dice (1–N sides)"),
    ]
)
```

The `SkillAwarenessInterceptor` (priority 30) will automatically advertise this
skill to the LLM each turn.

---

## 11. Module Exports Quick Reference

### `from engine.mcp import ...`

| Symbol | Type | Purpose |
|--------|------|---------|
| `get_governor` | function | Create/get a governor for an agent |
| `AgentGovernor` | class | Governance wrapper for any IAgent |
| `InterceptorBase` | class | Base for custom interceptors |
| `InterceptorPipeline` | class | Ordered interceptor container |
| `ResponseContext` | class | Dict-like context bag for one turn |
| `InteractionPolicy` | dataclass | Per-turn policy configuration |
| `GameState` | class | Game key/value store |
| `get_game_state` | function | Get singleton GameState |
| `AgentRouter` | class | Inter-agent message inbox |
| `get_router` | function | Get singleton AgentRouter |
| `SkillManifest` | class | Scene→skill registry |
| `get_skill_manifest` | function | Get singleton SkillManifest |
| `SceneManifest` | dataclass | Skills for one scene |
| `SkillEntry` | dataclass | Single skill declaration |
| `TRIGGER_AUTO` | str `"auto"` | Auto-fire each turn |
| `TRIGGER_OPTIONAL` | str `"optional"` | Available, LLM chooses |
| `TRIGGER_REQUIRED` | str `"required"` | LLM must call this |

### `from engine.agents import ...`

| Symbol | Type | Purpose |
|--------|------|---------|
| `CharacterAgent` | class | Primary LLM conversational agent |
| `AgentLoop` | class | Multi-turn agent orchestrator |
| `SceneAgent` | class | Scene-level orchestration wrapper |
| `get_scene_agent` | function | Create scene-scoped agent |
| `AgentGovernor` | class | (re-export from mcp) |
| `get_governor` | function | (re-export from mcp) |
| `IAgent` | Protocol | Structural interface contract |
| `IInterceptor` | Protocol | Structural interceptor contract |
| `AgentCapability` | Enum | Declared agent capabilities |

---

*Generated by CosySim architecture polish pass — see `CHANGELOG.md` for commit details.*
