# CosySim Skills System

Skills are Python callables that an LLM agent can invoke as **tools** during a
conversation turn.  The `@skill` decorator registers them into the global
`SKILL_REGISTRY`.  The agent pulls the relevant skills out of the registry and
passes them to `llm.act()` (LMStudio SDK) or uses them for direct invocation.

---

## Architecture Overview

```
@skill                            engine/skills/skill.py
  └─► SKILL_REGISTRY              engine/skills/registry.py
        ├─ get_pack_tools(pack)   → [callable, …]
        ├─ all_tools(tags=[…])    → [callable, …]
        └─ mcp_skill_pack(…)      → MCP integration payload dict

CharacterAgent.reply()            engine/agents/character_agent.py
  └─► _get_tools()                reads SKILL_REGISTRY for character's packs
        └─► llm.act(chat, tools)  LMStudio SDK agentic call
```

---

## Built-in Skill Packs

| Pack | Module | Skills |
|---|---|---|
| `memory` | `engine/skills/builtin/memory_skills.py` | `search_memory`, `store_memory`, `get_event_chain_summary`, `summarize_chain` |
| `character` | `engine/skills/builtin/character_skills.py` | `get_character_state`, `adjust_trait`, `set_mood`, `adjust_relationship` |
| `comfyui` | `engine/skills/builtin/comfyui_skills.py` | `generate_image`, `generate_character_portrait`, `list_comfyui_workflows` |
| `voice` | `engine/skills/builtin/voice_skills.py` | `generate_voice_message`, `list_voice_messages` |

---

## Writing a Custom Skill

### Minimal example

```python
# my_extension/skills.py
from engine.skills import skill

@skill
def greet_user(name: str) -> str:
    """
    Say hello to a user by name.

    Args:
        name: The user's display name.

    Returns:
        A greeting string.
    """
    return f"Hello, {name}! 👋"
```

The `@skill` decorator with no arguments:
- Sets `name` = function name (`"greet_user"`)
- Sets `pack` = `"default"`
- Sets `description` = first line of docstring

---

### Full decorator syntax

```python
@skill(
    name="send_email",          # override registry key
    pack="notifications",       # group skills into packs
    description="Send an e-mail to the user via SMTP.",
    tags=["email", "notify"],   # used for filtering in SKILL_REGISTRY.all_tools(tags=[…])
)
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email and return a confirmation string."""
    ...
    return f"Email sent to {to}"
```

---

### Type annotations matter

The LMStudio SDK infers the JSON schema for the tool from Python type hints.
Always annotate every parameter and the return type.

Supported parameter types:

| Python type | JSON schema |
|---|---|
| `str` | `string` |
| `int` | `integer` |
| `float` | `number` |
| `bool` | `boolean` |
| `List[str]` | `array` of `string` |
| `Optional[str]` | `string` with `nullable: true` |

---

## Registering Skills

Skills are auto-registered when the decorated function is **imported**.  Load
all built-in packs from your `__init__` or module setup:

```python
import engine.skills.builtin  # triggers all @skill decorators
```

Or import a specific pack:

```python
from engine.skills.builtin import memory_skills  # only memory pack
```

---

## Querying the Registry

```python
from engine.skills import SKILL_REGISTRY

# List all skill packs
for pack in SKILL_REGISTRY.all_packs():
    print(pack)

# Get callables for one pack (pass to llm.act)
tools = SKILL_REGISTRY.get_pack_tools("memory")

# Get all skills tagged "image"
image_tools = SKILL_REGISTRY.all_tools(tags=["image"])

# Human-readable summary
print(SKILL_REGISTRY.describe())
```

---

## MCP Integration

`mcp_skill_pack()` produces a payload dict for the MCP (Model Context Protocol)
tools API so skills can be exposed to any MCP-compatible client:

```python
from engine.skills import mcp_skill_pack

payload = mcp_skill_pack(
    server_url="http://localhost:9000",
    allowed_tools=["generate_image", "search_memory"],
    name="cosysim-tools",
)
# pass payload to your MCP server registration code
```

---

## HTTP API (Phone Scene)

| Endpoint | Method | Description |
|---|---|---|
| `/api/skills/list` | GET | List all registered skills.  Optional `?pack=memory` or `?tag=image` filter. |
| `/api/skills/run` | POST | Execute a skill.  Body: `{"skill": "search_memory", "kwargs": {"query": "beach"}}` |

Example:

```bash
curl http://localhost:5555/api/skills/list?pack=memory
curl -X POST http://localhost:5555/api/skills/run \
     -H "Content-Type: application/json" \
     -d '{"skill": "search_memory", "kwargs": {"query": "birthday"}}'
```

---

## Tips & Best Practices

1. **Keep skills small and single-purpose** — the LLM reasons about what to
   call based on the function name and docstring.  Vague names lead to hallucination.

2. **Return human-readable strings** — skills return `str` in CosySim.  The
   SDK wraps the result as a `tool_result` message.

3. **Avoid side-effects in parameter defaults** — defaults are evaluated at
   import time; use `None` guards for mutable defaults.

4. **Use the `tags` field** — tags make filtering cheap.  Tag image skills with
   `"image"`, memory skills with `"memory"`, etc.

5. **Test skills in isolation** first — a skill is just a Python function.
   Call it directly before wiring it to an agent.

```python
from engine.skills.builtin.memory_skills import search_memory

# Direct call — no LLM involved
result = search_memory("coffee", character_id="abc123", top_k=3)
print(result)
```
