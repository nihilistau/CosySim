---
description: 'CosySim test conventions — pytest fixtures, mocking external services, assertion patterns'
applyTo: 'tests/**/*.py'
---

# Testing Conventions

## Framework
- pytest 9.0+ with plain `assert` statements
- No `unittest.TestCase` classes — use pytest fixtures
- Mock all external services (LMStudio, ComfyUI, TTS, Nexus)

## Fixtures (from conftest.py)
- `temp_db(tmp_path)` — temporary SQLite Database instance
- `event_chain(temp_db)` — EventChain with temp DB backing
- `mock_config()` — MagicMock dict-like with `.get(key, default)`

## File Naming
- Test files: `test_{module_name}.py`
- Test functions: `test_{behavior_being_tested}()`
- Group related tests in the same file

## Test Structure
```python
def test_feature_does_expected_thing(temp_db, mock_config):
    """What behavior is being verified."""
    # Arrange
    scene = MyScene(config=mock_config)

    # Act
    result = scene.do_thing("input")

    # Assert
    assert result["status"] == "ok"
    assert "expected_key" in result
```

## Mocking
- Use `unittest.mock.MagicMock`, `patch`, `AsyncMock`
- Never make real HTTP calls to LMStudio, ComfyUI, or TTS
- Mock at the client boundary, not deep internals
- Use `tmp_path` for any file I/O tests

## Running Tests

### Smart runner (preferred — git-diff aware)
```bash
# Quick sanity check (~53s, ~15 files, one per domain)
python scripts/smart_test.py --smoke
python -m pytest tests/ --smoke-only

# Only tests for uncommitted changes (auto-caps at 80 files)
python scripts/smart_test.py
python -m pytest tests/ --affected

# Only tests for staged files (pre-commit)
python -m pytest tests/ --staged

# Tests for a specific domain
python scripts/smart_test.py --domain scene_hub
python scripts/smart_test.py --domain engine_core,shared

# Tests since a git ref
python -m pytest tests/ --since HEAD~3

# Dry-run: show what would run
python scripts/smart_test.py --list

# Auto-fallback to smoke if too many files affected
python -m pytest tests/ --affected --cap 40
```

### Direct pytest (single files, markers, full suite)
```bash
python -m pytest tests/test_bedroom_game.py -v    # Single file
python -m pytest tests/ -m unit                    # By marker
python -m pytest tests/ -m "not slow"              # Skip slow
python -m pytest -n auto tests/                    # Parallel (xdist)
```

## Coverage
- Every scene should have a test file
- Every skill pack should have tests
- Test both happy path and edge cases
- Database-seeded characters (lola, viktor, aria, frankie, mira) are always present
