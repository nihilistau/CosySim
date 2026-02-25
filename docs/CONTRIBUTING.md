# Contributing to CosySim

Guidelines for humans and AI agents working on this codebase.

---

## Quick Reference

```bash
# Setup
pip install -e .

# Run tests (must pass before committing)
python -m pytest tests/ -v --tb=short

# Launch for manual testing
python launcher.py --mode phone      # :5555
python launcher.py --mode bedroom    # :5556
python launcher.py --mode hub        # :8500
python launcher.py --mode admin      # :8502

# Check health
python launcher.py --status
```

---

## Project Structure

```
engine/          Reusable framework (DO NOT put scene-specific logic here)
  mcp/tools/     MCP tool modules (8 domain files, 67 functions)
content/         Example scenes + simulation services
  scenes/        Phone, bedroom, hub, casino, realm, neoncity, coders, heist, warzone, gallery, lounge
  simulation/    Database, RAG, character system, services
  shared/        Shared CSS/themes used by all scenes
config/          YAML settings (ports, URLs, thresholds)
training/        Training pipeline (merge_adapters, dataset generation)
tests/           Pytest test suite (1,756 tests)
docs/            Documentation
```

---

## Code Style

- **Python 3.10+**, type hints on all public methods
- **Docstrings:** Module-level + class-level + public methods
- **Imports:** Standard library → third-party → project (grouped with blank lines)
- **SQL:** Always parameterised queries (`?` placeholders). Column names validated against whitelists.
- **Config:** Never hardcode ports/URLs. Use `get_config().get("section.key", default)`.
- **EventChain:** Every service interaction must be logged. If it's not in EventChain, it didn't happen.

---

## Testing

All tests live in `tests/`. Run with `python -m pytest tests/ -v --tb=short`.

**1,756 tests** across 40+ test files.

### Test Requirements

- **Every new module needs tests.** No exceptions — skills, interceptors, tools, scenes.
- **Mock external dependencies** (LMStudio, ComfyUI, TTS) — never call live services in tests.
- Use `tmp_path` fixture for temp databases
- Use `conftest.py` fixtures (`temp_db`, `event_chain`, `mock_config`)
- Test the happy path + at least one error case
- DB tests should test create → read → update → delete

---

## Adding a New Scene

Each scene lives in its own directory with a standard structure:

```
content/scenes/<name>/
├── <name>_scene.py      # Flask app inheriting BaseScene + MCPSceneMixin
├── <name>_skills.py     # @skill functions grouped into a SkillPack
├── <name>_rules.py      # SceneRulesEngine config (permissions, thresholds)
├── __init__.py           # Exports scene class
├── templates/            # Jinja2 templates
└── static/               # Scene-specific CSS/JS
```

1. Create the directory and files above
2. Inherit from `BaseScene` and mix in `MCPSceneMixin`
3. Implement: `start()`, `stop()`, `get_plugin_info()`
4. Wire `build_governance_context()` + `StateCoordinator` in scene init
5. Add route to `launcher.py` mode_map
6. Add tests in `tests/` (see Test Requirements below)
7. Document in `docs/`

---

## Adding a New Skill

1. Decorate with `@skill(name="...", description="...", pack="<pack_name>")`
   - The `pack` parameter groups skills for registration (e.g. `"realm"`, `"casino"`)
2. Read chain context: `from engine.skills.chain_context import get_chain_context`
3. Log to EventChain: both `skill_called` and `skill_result`
4. Return a string (LLM reads this)
5. Register the pack in the scene's `__init__` or `start()` method:
   ```python
   from engine.skills import SkillPack
   pack = SkillPack("my_scene", [my_skill_func, ...])
   pack.register(self.skill_registry)
   ```

---

## Writing an Interceptor

Interceptors modify prompts before inference (pre-call) or process responses after (post-call).

1. Extend `InterceptorBase` from `engine/mcp/comms_framework.py`
2. Override `pre_call()` and/or `post_call()`
3. Set `priority` (lower runs first — e.g. content filter at 10, mood sync at 50)
4. Register in the interceptor pipeline via `comms_framework.py`:
   ```python
   from engine.mcp.comms_framework import InterceptorBase
   
   class MyInterceptor(InterceptorBase):
       priority = 20
       def pre_call(self, context): ...
       def post_call(self, context, response): ...
   ```

---

## Adding an MCP Tool

MCP tools are split across domain modules in `engine/mcp/tools/`:

| Module | Domain |
|--------|--------|
| `character_tools.py` | Character state, relationships |
| `dialog_tools.py` | Dialog trees, conversation state |
| `game_tools.py` | Game sessions, turns |
| `media_tools.py` | Image/voice generation |
| `memory_tools.py` | RAG memory search/store |
| `scene_tools.py` | Scene state, lifecycle |
| `utility_tools.py` | Config, benchmarks, misc |
| `wardrobe_tools.py` | Wardrobe/appearance |

1. Add the function logic in the appropriate `engine/mcp/tools/<domain>_tools.py`
2. Add the MCP wrapper in `engine/mcp/cosysim_server.py` to expose it as an MCP tool
3. Add tests for the tool logic

---

## Key Architectural Rules

1. **EventChain is ground truth.** Every interaction must be logged with chain_id.
2. **Skills use thread-local context** (`engine/skills/chain_context.py`). Never pass chain_id as a skill parameter — set it before `llm.act()`, read it inside the skill.
3. **Framework ≠ Content.** `engine/` is reusable. `content/` is examples. Don't put scene-specific code in engine.
4. **Graceful degradation.** If ComfyUI/LMStudio/TTS is offline, return a placeholder.
5. **Config over code.** All ports, URLs, model names, timeouts go in `config/settings.yaml`.

---

## Database

SQLite at `simulation/simulation.db`. 9 tables with full CRUD.

### Schema Changes

- Add columns via `_migrate_schema()` in `db.py` (add-only migrations)
- Column names in dynamic SQL must be validated against whitelists (see `ALLOWED_COLUMNS`)
- Always use `with self.get_connection() as conn:` context manager

---

## Commit Guidelines

- Write clear commit messages describing what changed and why
- Run tests before committing: `python -m pytest tests/ -v --tb=short`
- Always include the Co-authored-by trailer for AI-assisted commits:
  ```
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
  ```

---

## Known Limitations

- Voice/video call UI buttons are disabled (placeholder — "coming soon")
- Scene export/import raises `NotImplementedError`
- Migration system is add-only (no rollback, no version table)
