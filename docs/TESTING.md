# Testing

> CosySim Documentation — v1.51.0 [2026-03-25]
>
> Smart test system, pytest conventions, and fixtures.

---

## Smart Test System

The full test suite (404 test files) is large. Use the smart runner — it's git-diff-aware and runs only relevant tests.

### Smart Runner (Preferred)

```bash
# Tests for uncommitted changes
python scripts/smart_test.py

# Smoke tests (~15 files, ~53s)
python scripts/smart_test.py --smoke

# Tests for a specific domain
python scripts/smart_test.py --domain scene_hub

# Tests for last 3 commits
python scripts/smart_test.py --since HEAD~3

# Dry-run — show what would run
python scripts/smart_test.py --list
```

### Pytest Flags (Same Engine)

The smart test system is also a pytest plugin, integrated via `conftest.py`:

```bash
# Only tests for uncommitted changes
python -m pytest tests/ --affected

# Only tests for staged files
python -m pytest tests/ --staged

# Smoke tests (~15 files)
python -m pytest tests/ --smoke-only

# Tests since last commit
python -m pytest tests/ --since HEAD~1

# Cap: fall back to smoke if affected files exceed threshold
python -m pytest tests/ --affected --cap 40
```

### Direct Pytest (Full Suite)

```bash
python -m pytest tests/test_hub_flask.py -v   # Single file
python -m pytest -m "unit" tests/              # By marker
python -m pytest -n auto tests/                # Parallel (xdist)
```

### Domain Mapping

The smart runner maps source files to test domains. Key mappings in `scripts/smart_test.py`:

| Source Path | Domain | Test Files |
|-------------|--------|------------|
| `engine/mcp/` | `mcp_framework` | test_mcp_server, test_governance, ... |
| `engine/nexus/` | `nexus` | test_nexus_*, test_scheduler, ... |
| `engine/lmstudio/` | `lmstudio` | test_lmstudio_*, test_inference, ... |
| `content/scenes/hub/` | `scene_hub` | test_hub_flask, test_hub_scene |
| `engine/skills/` | `skills` | test_skills_*, test_governance, ... |
| `engine/agents/` | `agents` | test_agent_*, test_interceptor_*, ... |
| `engine/world/` | `world` | test_world_*, test_economy, ... |
| `config/` | `config` | test_config, test_integration |
| `launcher.py` | `launcher` | test_integration |

---

## Browser Testing

After **any** JS/CSS/HTML change, run browser tests before committing:

```bash
python scripts/browser_test.py             # Full Playwright run
python scripts/browser_test.py --report    # Read telemetry report
```

`cosysim-telemetry.js` captures all browser clicks, errors, and hotkeys → `POST /api/telemetry` → `data/structured_logs.jsonl`. Always check telemetry after user-reported issues.

---

## Conventions

- **Framework:** pytest with plain `assert`. No `unittest.TestCase`.
- **Mock:** All external services (LMStudio, ComfyUI, TTS, Nexus). Mock at the client boundary.
- **File naming:** `test_{module_name}.py` → `test_{behavior}()`
- **Seeded characters:** lola, viktor, aria, frankie, mira — always present in DB fixtures.
- **Excluded:** `tests/test_agent_loop.py` and `tests/live_wire_test.py` (require live services).

### Fixtures (from `conftest.py`)

| Fixture | Scope | Purpose |
|---------|-------|---------|
| `temp_db` | function | Fresh SQLite database |
| `event_chain` | function | EventChain for testing cascades |
| `mock_config` | function | Isolated config with test defaults |

### Markers

| Marker | Purpose |
|--------|---------|
| `@pytest.mark.unit` | Fast unit tests (no I/O) |
| `@pytest.mark.integration` | Integration tests (may hit services) |
| `@pytest.mark.slow` | Tests that take >5s |

### Test Configuration

Defined in `pyproject.toml` under `[tool.pytest.ini_options]`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py"
```

---

## Writing Tests

### Scene Test Template

```python
import pytest
from unittest.mock import patch

class TestMyScene:
    @pytest.fixture(autouse=True)
    def setup(self, mock_config):
        with patch("engine.lmstudio.lms_client.LMSClient"):
            from content.scenes.my_scene.my_scene_scene import MyScene
            self.scene = MyScene()
            self.app = self.scene.app
            self.client = self.app.test_client()

    def test_health_returns_200(self):
        resp = self.client.get("/api/health")
        assert resp.status_code == 200

    def test_scene_registry_returns_pillars(self):
        resp = self.client.get("/api/scene-registry")
        data = resp.get_json()
        assert "pillars" in data
        assert set(data["pillars"].keys()) == {"game", "service", "creation"}
```

### Skill Test Template

```python
from engine.skills.skill import skill

def test_my_skill_returns_result():
    @skill(pack="test", description="test skill")
    def my_skill(target: str) -> str:
        return f"did {target}"

    assert my_skill("thing") == "did thing"
```

---

## See Also

- [Contributing](CONTRIBUTING.md) — development conventions
- [Architecture](ARCHITECTURE.md) — system design
- [MCP Framework](MCP_FRAMEWORK.md) — skill and interceptor pipeline

---

## Change Log

| Version | Date | Changes |
|---------|------|---------|
| v1.50 | 2026-03-22 | Doc overhaul — accurate test file count (404), added browser testing section, unified versioning |
| v1.42 | 2026-03-21 | Initial testing guide with smart runner and pytest integration |
