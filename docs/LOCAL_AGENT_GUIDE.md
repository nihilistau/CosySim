# Local Agent Guide — CosySim Task Execution

> Safety rails and operational guide for local LMStudio-hosted agents
> executing tasks from the CosySim task scheduler.

## Who This Is For

You are a local LLM model (running on LMStudio) that has been assigned a task
from the CosySim task scheduler. This guide defines what you can do, how to do
it safely, and how to report your work.

## Ground Rules

### You CAN
- Read any file in the CosySim codebase
- Edit files specified in your task ticket
- Create new files specified in your task ticket
- Run the test suite
- Search and add entries to Nexus
- Create git commits (with conventional commit format)

### You CANNOT
- Delete files (ever)
- Modify `engine/mcp/` core framework files (unless explicitly authorized)
- Modify `config/default.yaml` without backup
- Make real HTTP calls to external services in tests
- Push to remote repositories
- Install new packages without authorization
- Modify other agents' active tasks
- Skip running tests before committing

### You MUST
- Read the task ticket completely before starting
- Search Nexus for context before writing code
- Run the full test suite before AND after changes
- Use absolute imports only
- Add type hints to all function signatures
- Use `logging.getLogger(__name__)` instead of `print()`
- Store your findings/decisions in Nexus
- Create a conventional commit with Co-authored-by trailer
- Mark your task as complete when done

## Task Ticket Format

Tasks from the scheduler follow this structure:

```json
{
    "id": "task-uuid",
    "title": "Short task description",
    "description": "Detailed requirements and acceptance criteria",
    "priority": 1,
    "complexity": "low|medium|high",
    "status": "claimed",
    "assigned_agent": "agent-name",
    "allowed_operations": ["read", "edit", "create", "test"],
    "target_files": ["engine/skills/builtin/my_skills.py"],
    "parent_task": "parent-uuid-if-subtask",
    "acceptance_criteria": [
        "Tests pass",
        "No regressions",
        "Nexus entry created"
    ]
}
```

## Execution Workflow

### 1. Claim the Task
```python
# The scheduler assigns you a task — acknowledge it
from engine.nexus.client import get_nexus_client
client = get_nexus_client()
```

### 2. Research
```python
# Always search Nexus first
results = client.search("topic related to your task")
# Check existing patterns in the codebase
# Read relevant test files for expected behavior
```

### 3. Run Baseline Tests
```bash
python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py
# Record: X tests passed, 0 failures
```

### 4. Implement
- Make minimal, surgical changes
- Follow the Python conventions (see docs/AGENT_ONBOARDING.md)
- One logical change per commit
- If unsure about approach, check Nexus or stop and report

### 5. Test Your Changes
```bash
# Run full suite again
python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py
# Verify: same or more tests pass, 0 failures
```

### 6. Store Results
```python
# Store what you learned
client.add_entry(
    title="Task Complete: your-task-title",
    content="What was done, decisions made, files changed",
    content_type="note",
    category="dev"
)
```

### 7. Commit
```bash
git add -A
git commit -m "feat: description of change" -m "Task: task-uuid" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### 8. Report Completion
Mark the task as done in the scheduler and include:
- Files changed
- Tests added/modified
- Nexus entries created
- Any issues or follow-up tasks needed

## Safety Checks

Before every commit, verify:

| Check | How |
|-------|-----|
| Tests pass | `python -m pytest tests/ -q --tb=line` |
| No syntax errors | `python -m py_compile changed_file.py` |
| Imports are absolute | grep for `from .` in changed files |
| No print statements | grep for `print(` in changed files |
| Type hints present | Review function signatures |
| No hardcoded values | grep for port numbers, file paths in changed files |

## Complexity Guidelines

### Low Complexity Tasks
- Add a test case
- Fix a typo in docs
- Update a config value
- Add a Nexus entry

### Medium Complexity Tasks
- Add a new skill function
- Fix a bug with known root cause
- Refactor a module (no behavior change)
- Update documentation

### High Complexity Tasks
- Add a new scene
- Modify the interceptor pipeline
- Change inference routing logic
- Multi-file refactoring

**Rule**: If a task feels higher complexity than labeled, STOP and report.
Don't attempt high-complexity work without explicit authorization.

## Error Recovery

If something goes wrong:

1. **Test failures after your change**: `git checkout -- .` to revert all changes
2. **Can't understand the task**: Mark as "blocked" with explanation
3. **Unexpected behavior**: Don't try to fix cascading issues — revert and report
4. **Nexus unreachable**: Continue work but note that Nexus storage is pending

## Communication

Local agents communicate through:
- **Task status updates** in the scheduler
- **Nexus entries** for knowledge/decisions
- **Git commits** for code changes
- **Task comments** for questions or blockers

You do NOT:
- Send emails or notifications
- Interact with external services
- Modify the scheduler itself
- Communicate with other agents directly
