# AGENT_NOTES — CosySim System Architecture

> Generated: 2025-07-16 | Version: v0.51b | Tests: 1,927 passing

## System Overview

CosySim is a multi-scene AI simulation framework built on a custom MCP pipeline
with LMStudio v1 API integration and Nexus knowledge management. It provides
a playground for designing, testing, and evolving AI agent interactions.

## MCP Server Access

### For Copilot CLI (you)
The CosySim MCP server is configured in `.vscode/mcp.json`:
```json
{
  "servers": {
    "cosysim": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "engine.mcp.cosysim_server"]
    },
    "nexus": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "nexus.mcp.server"],
      "cwd": "C:\\Files\\Nexus"
    }
  }
}
```

### 124 MCP Tools Available
- **14 Nexus bridge tools** — nexus_search, nexus_ask, nexus_add, nexus_add_qa,
  nexus_get_rules, nexus_store_prompt, nexus_get_prompts, nexus_research,
  nexus_converse, nexus_finish_research, nexus_import_youtube, nexus_log_session,
  nexus_status, nexus_list_plugins
- **3 Discovery tools** — list_all_skills, get_skill_info, system_status
- **107 CosySim tools** — memory, characters, games, narrative, dialog, wardrobe,
  mood, image generation, conversation management, framework status

## Nexus-First Workflow

1. **Before coding**: `nexus_search("topic")`, `nexus_get_rules("scope")`
2. **During work**: `list_all_skills()`, `system_status()`
3. **After completing**: `nexus_add("Decision: ...", content, "decision")`

## CLI Access

```bash
# Nexus CLI
python -m engine.nexus.cli search "query"
python -m engine.nexus.cli ask "question"
python -m engine.nexus.cli add "Title" "Content" --type decision
python -m engine.nexus.cli status

# Launch scenes
python launcher.py --scene bedroom
python launcher.py --list

# Run tests
python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py
```

## Architecture Layers

```
┌─────────────────────────────────────────────┐
│  Copilot CLI / VS Code / Terminal           │
│  └─ .vscode/mcp.json → MCP Server (stdio)  │
├─────────────────────────────────────────────┤
│  CosySim MCP Server (124 tools)             │
│  ├─ Nexus Bridge (14 tools)                 │
│  ├─ Skill Discovery (3 tools)               │
│  └─ Scene/Character/Media tools (107)       │
├─────────────────────────────────────────────┤
│  Engine Layer                               │
│  ├─ MCPFramework (state tree)               │
│  ├─ DialogSystem (conversations)            │
│  ├─ InterceptorPipeline (25 interceptors)   │
│  ├─ InferenceOrchestrator (model routing)   │
│  ├─ SkillRegistry (194 skills, 26 packs)    │
│  └─ NexusClient (25+ methods → :8700)       │
├─────────────────────────────────────────────┤
│  Scene Layer (18 scenes)                    │
│  ├─ BaseScene (registration, lifecycle)     │
│  ├─ Scene-specific skills & game logic      │
│  └─ Flask blueprints + Three.js frontends   │
├─────────────────────────────────────────────┤
│  External Services                          │
│  ├─ LMStudio (:1234) — LLM inference       │
│  ├─ Nexus KMS (:8700) — Knowledge          │
│  ├─ ComfyUI (:8188) — Image generation     │
│  ├─ TTS Server (:8600) — Voice synthesis    │
│  └─ Web Bridge (:8601) — Socket.IO          │
└─────────────────────────────────────────────┘
```

## Key Singletons

```python
from engine.config import get_config              # ConfigManager
from engine.mcp import get_framework              # MCPFramework
from engine.mcp import get_character_registry      # CharacterRegistry
from engine.mcp import get_dialog_system           # DialogSystem
from engine.mcp import get_rules_engine            # SceneRulesEngine
from engine.mcp import get_scene_state_manager     # SceneStateManager
from engine.mcp import get_governor                # AgentGovernor
from engine.mcp import get_router                  # AgentRouter
from engine.scenes.base_scene import BaseScene     # Scene base class
from engine.skills.skill import skill              # @skill decorator
from engine.nexus.client import get_nexus_client   # Nexus KMS client
from engine.lmstudio.orchestrator import get_orchestrator  # Multi-model orchestrator
```

## Custom Agents (.github/agents/)

| Agent | File | Purpose |
|-------|------|---------|
| Copilot Workflow | copilot-workflow.agent.md | Master agent, Nexus-first, all tools |
| Scene Builder | scene-builder.agent.md | Scaffold new scenes |
| Scene Debugger | scene-debugger.agent.md | Diagnose scene issues |
| Scene Auditor | scene-auditor.agent.md | Rate scene quality |
| Skill Developer | skill-developer.agent.md | Create skill packs |
| Test Writer | test-writer.agent.md | Generate tests |
| Doc Writer | doc-writer.agent.md | Maintain docs |
| Codebase Navigator | codebase-navigator.agent.md | Explain architecture |
| System Architect | system-architect.agent.md | Cross-project design |
| Nexus Researcher | nexus-researcher.agent.md | Research + store knowledge |

## File Dependencies (Key Files)

### Core Framework
1. `engine/config.py` — ConfigManager (loads YAML, dot-notation)
2. `engine/paths.py` — ROOT, project path constants
3. `engine/mcp/framework.py` — MCPFramework state tree
4. `engine/mcp/dialog_system.py` — Conversation threading
5. `engine/mcp/scene_rules_engine.py` — Rules + ConversationHeat
6. `engine/mcp/comms_framework.py` — AgentGovernor, routing
7. `engine/agents/interceptors.py` — 25-interceptor pipeline
8. `engine/agents/virtual_agent.py` — VirtualAgent base
9. `engine/agents/stream_processor.py` — Tag extraction [MOOD:x], [IMAGE:y]
10. `engine/skills/skill.py` — @skill decorator
11. `engine/skills/registry.py` — SkillRegistry
12. `engine/lmstudio/lms_client.py` — LMStudio v1 API client
13. `engine/lmstudio/orchestrator.py` — Multi-model routing
14. `engine/nexus/client.py` — Nexus HTTP client
15. `engine/nexus/cli.py` — Nexus CLI tool
16. `engine/mcp/cosysim_server.py` — FastMCP server (124 tools)

### Scene System
17. `engine/scenes/base_scene.py` — BaseScene with registration
18. `content/scenes/{name}/{name}_scene.py` — Scene implementation
19. `content/scenes/{name}/{name}_skills.py` — Scene-specific skills
20. `content/scenes/{name}/templates/` — HTML/Three.js frontend
