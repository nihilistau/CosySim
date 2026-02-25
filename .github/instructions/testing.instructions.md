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
```bash
# Full suite
python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py

# Single file
python -m pytest tests/test_bedroom_game.py -v

# By marker
python -m pytest tests/ -m unit
python -m pytest tests/ -m "not slow"
```

## Coverage
- Every scene should have a test file
- Every skill pack should have tests
- Test both happy path and edge cases
- Database-seeded characters (lola, viktor, aria, frankie, mira) are always present
