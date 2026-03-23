# Bug Fix Workflow

Enforced bug-fix sprint. Follow these rules exactly.

## Process

1. **Read the user's bug list** — work items in the EXACT order given. Do NOT reorder priorities.
2. **Fix ONE bug at a time.** Do not batch fixes or work on multiple bugs simultaneously.
3. **For each bug:**
   a. Read the relevant code and understand the root cause before writing any fix.
   b. If existing working code solves part of the problem, reuse it — do NOT rewrite from scratch.
   c. Implement the minimal fix. Do NOT refactor surrounding code.
   d. Run tests: `python -m pytest tests/ --affected -x -q`
   e. For UI bugs, also run: `python scripts/browser_test.py`
   f. Show the user the passing test output as proof.
4. **Commit each fix separately** with a descriptive message tied to the specific bug.
5. **Do NOT:**
   - Refactor unrelated code
   - Add features not in the bug list
   - Edit files outside the scope of the current bug
   - Declare "fixed" without showing passing test output
   - Move to the next bug until the current one is fully verified
6. **After all bugs are fixed**, run the full smoke suite: `python scripts/smart_test.py --smoke`
