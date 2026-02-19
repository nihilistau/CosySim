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
content/         Example scenes + simulation services
  scenes/        Phone, bedroom, hub, dashboard, admin
  simulation/    Database, RAG, character system, services
  shared/        Shared CSS/themes used by all scenes
config/          YAML settings (ports, URLs, thresholds)
tests/           Pytest test suite (75 tests)
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

| File | Tests | Coverage |
|------|:-----:|----------|
| test_event_chain.py | 12 | Chain creation, logging, tree view |
| test_config.py | 5 | Dot-notation, env override |
| test_skills.py | 6 | Decorator, packs, chain context |
| test_database.py | 52 | Full CRUD for all 8 data tables |

### Writing Tests

- Use `tmp_path` fixture for temp databases
- Use `conftest.py` fixtures (`temp_db`, `event_chain`, `mock_config`)
- Test the happy path + at least one error case
- DB tests should test create → read → update → delete

---

## Adding a New Scene

1. Create `content/scenes/<name>/<name>_scene.py`
2. Inherit from `BaseScene`
3. Implement: `start()`, `stop()`, `get_plugin_info()`
4. Add route to `launcher.py` mode_map
5. Add tests in `tests/`
6. Document in `docs/`

---

## Adding a New Skill

1. Decorate with `@skill(name="...", description="...")`
2. Read chain context: `from engine.skills.chain_context import get_chain_context`
3. Log to EventChain: both `skill_called` and `skill_result`
4. Return a string (LLM reads this)
5. Add to a `SkillPack`, register in scene init

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
- Include `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>` trailer if AI-assisted

---

## Known Limitations

- Voice/video call UI buttons are disabled (placeholder — "coming soon")
- Scene export/import raises `NotImplementedError`
- No inter-scene messaging (pub/sub)
- Migration system is add-only (no rollback, no version table)
- Qwen3-TTS not yet integrated (user wants this as next feature)
