import datetime

def update_history():
    history_file = "REFACTORING_HISTORY.md"
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    
    entry = f"""
### Phase 4 Update ({date_str})
- Replaced inline logic with `_impl` function calls for the remaining major interactive and scene-based tools in `cosysim_server.py`, including:
  - `enforce_behavior`
  - `mood_contagion`
  - `schedule_consequence`
  - `dream_whisper`
  - `mirror_soul`
  - `time_echo`
  - `serve_lounge_drink`
- Added a `helpers/` directory containing python scripts for string replacement and AST parsing (`find_remaining_try_except.py`, `replace_tool_pattern.py`) to systematically track and fix the remaining `try...except` blocks in the core MCP server.
"""

    with open(history_file, 'a', encoding='utf-8') as f:
        f.write(entry)
    
    print(f"Appended latest updates to {history_file}")

if __name__ == '__main__':
    update_history()
