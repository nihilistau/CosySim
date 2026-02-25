# .github/ — Copilot Customization System

This directory contains a layered GitHub Copilot customization system
designed for the CosySim AI simulation framework.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1: Global (Personal)                             │
│  ~/.copilot/copilot-instructions.md    CLI persona      │
│  ~/.github/copilot-instructions.md     IDE persona      │
├─────────────────────────────────────────────────────────┤
│  Layer 2: Shared Rules (Cross-Project)                  │
│  ~/.config/copilot/shared-rules/                        │
│  ├── system-architecture.instructions.md                │
│  ├── git-workflow.instructions.md                       │
│  └── security.instructions.md                           │
│  (Loaded via COPILOT_CUSTOM_INSTRUCTIONS_DIRS env var)  │
├─────────────────────────────────────────────────────────┤
│  Layer 3: Repository (This Project)                     │
│  .github/copilot-instructions.md       Master context   │
│  .github/instructions/*.instructions.md  Path-specific  │
│  .github/agents/*.agent.md             Custom agents    │
│  .github/hooks/                        Session hooks    │
└─────────────────────────────────────────────────────────┘
```

## Priority Order (highest → lowest)

1. **Personal** — `~/.copilot/copilot-instructions.md`
2. **Path-Specific** — `.github/instructions/*.instructions.md` (with `applyTo` globs)
3. **Repository-Wide** — `.github/copilot-instructions.md`
4. **Shared Rules** — `~/.config/copilot/shared-rules/` (via env var)
5. **Organization** — (if applicable)

Rules merge additively when there's no conflict. Higher priority wins on conflicts.

## Instructions (8 files)

| File | Applies To | Purpose |
|------|-----------|---------|
| `python.instructions.md` | `**/*.py` | Import style, type hints, docstrings, naming |
| `scenes.instructions.md` | `content/scenes/**/*.py` | BaseScene lifecycle, MCP wiring |
| `mcp-framework.instructions.md` | `engine/mcp/**`, `engine/skills/**`, `engine/agents/**` | Skills, interceptors, state |
| `testing.instructions.md` | `tests/**/*.py` | pytest fixtures, mocking, assertions |
| `lmstudio.instructions.md` | `engine/lmstudio/**/*.py` | v1 API, streaming, conversations |
| `config.instructions.md` | `config/**/*.yaml` | Dot-notation access, file hierarchy |
| `frontend.instructions.md` | `content/scenes/**/templates/**`, `**/static/**` | Jinja2, JS, CSS, Socket.IO |
| `deployment.instructions.md` | Startup scripts, deployment files | Service ordering, health checks |

## Agents (8 agents)

| Agent | Description |
|-------|-------------|
| `scene-builder` | Scaffold new scenes from scratch |
| `scene-debugger` | Diagnose and fix scene/agent issues |
| `scene-auditor` | Rate scenes against AAA quality standard |
| `skill-developer` | Create and register MCP skill packs |
| `test-writer` | Generate pytest test suites |
| `doc-writer` | Maintain documentation system |
| `codebase-navigator` | Explain architecture, trace call chains |
| `system-architect` | Cross-project architecture decisions |

### Using Agents

In VS Code Copilot Chat, reference an agent with `@agent-name`:
```
@scene-builder Create a new "tavern" scene with NPC bartering mechanics
@scene-auditor Audit the casino scene against AAA standard
@test-writer Generate tests for engine/mcp/dialog_system.py
```

In Copilot CLI, agents are available as context when working in this repo.

## Hooks

### Session Logger (`hooks/session-logger/`)
Logs session start/end and prompt submissions to `.github/hooks/logs/session.log`.
Uses PowerShell commands compatible with Windows.

## Environment Setup

The `COPILOT_CUSTOM_INSTRUCTIONS_DIRS` user environment variable points to
`~/.config/copilot/shared-rules/` for cross-project rules that apply to
CosySim, Nexus, and any future projects.

## Maintenance

- **Adding a new instruction:** Create `.instructions.md` in `instructions/`,
  set `applyTo` glob in YAML frontmatter, update this README
- **Adding a new agent:** Create `.agent.md` in `agents/`, set `description`
  and `name` in YAML frontmatter, update this README
- **Updating rules:** Edit the relevant file. CLI sessions need `/resume` to
  reload; IDE sessions reload automatically
- **Verification:** Use `/session` command in Copilot CLI to see active files
