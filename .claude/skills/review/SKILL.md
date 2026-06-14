# Pre-Commit Review

Run this before committing to catch accidental reverts, unintended changes, and broken tests.

## Process

1. **Show all changes:** Run `git diff --stat` to list every changed file.
2. **Verify intent:** For each changed file, confirm it was intentionally modified for the current task. Flag any files that look like they were changed accidentally or are outside scope.
3. **Check for reverts:** Run `git diff` on critical files and look for accidentally removed code, reverted features, or lost work.
4. **Run tests:** Execute `python -m pytest tests/ --affected -x -q` and show the results.
5. **For UI changes:** Also run `python scripts/browser_test.py` and confirm it passes.
6. **Report:**
   - List files that are safe to commit
   - Flag any files that should NOT be committed (accidental changes, secrets, debug code)
   - Show test results
7. **Only proceed with commit if all checks pass.** If any test fails or any file looks wrong, stop and fix before committing.
