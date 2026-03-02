# Helper Scripts

This directory contains useful scripts for identifying and replacing patterns in `cosysim_server.py` and other modules during refactoring.

1. **find_remaining_try_except.py**: 
   - Usage: `python helpers/find_remaining_try_except.py [filepath]`
   - Parses the AST of the target file and prints the names of all functions containing a bare `try...except Exception:` block.

2. **replace_tool_pattern.py**:
   - Usage: This is a template for performing regex replacements to strip `try...except` blocks and import Pydantic models from extracted tools. Modify the `pattern` and `replacement` strings within the file for the specific tool you're targeting.
