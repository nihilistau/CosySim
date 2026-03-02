import re

with open("engine/mcp/cosysim_server.py", "r", encoding="utf-8") as f:
    content = f.read()

import_block = """from engine.mcp.tools.conversation_tools import (
    query_stateless_impl,
    get_conversation_info_impl,
    fork_conversation_impl,
    get_conversation_heat_level_impl,
    bump_conversation_heat_impl,
    check_conversation_history_impl,
)
"""

if "from engine.mcp.tools.conversation_tools import" not in content:
    content = content.replace(
        "from engine.mcp.tools.lounge_tools import (",
        import_block + "from engine.mcp.tools.lounge_tools import ("
    )

replacement_block = """@mcp.tool()
def query_stateless(prompt: str, system: str = "") -> str:
    \"\"\"
    Make a disposable one-off LLM query (store=false).
    Use this for quick decisions, classifications, or utility tasks
    that shouldn't affect the conversation state.
    Returns the raw response text.
    \"\"\"
    return query_stateless_impl(prompt, system)


@mcp.tool()
def get_conversation_info(conversation_id: str) -> str:
    \"\"\"
    Get information about a conversation including response history
    and available branch points.
    Returns JSON with conversation state and forkable response IDs.
    \"\"\"
    return get_conversation_info_impl(conversation_id)


@mcp.tool()
def fork_conversation(conversation_id: str, turn: int = -1) -> str:
    \"\"\"
    Create a conversation branch from a specific turn.
    Use this to try alternative approaches or undo to a previous point.
    Turn -1 means branch from the latest point.
    Returns the new forked conversation ID.
    \"\"\"
    return fork_conversation_impl(conversation_id, turn)


@mcp.tool()
def get_conversation_heat_level(conversation_id: str) -> str:
    \"\"\"
    Get the current heat level (0-100) for a conversation.
    Heat increases with flirty/intimate content and decays over time.
    Returns JSON with the heat level and current directive.
    \"\"\"
    return get_conversation_heat_level_impl(conversation_id)


@mcp.tool()
def bump_conversation_heat(
    conversation_id: str,
    amount: float = 10,
    reason: str = "",
) -> str:
    \"\"\"
    Manually increase conversation heat level.
    Use during flirty, intimate, or emotionally charged exchanges.
    Returns the new heat level.
    \"\"\"
    return bump_conversation_heat_impl(conversation_id, amount, reason)


@mcp.tool()
def check_conversation_history(
    conversation_id: str,
    last_n: int = 5,
) -> str:
    \"\"\"
    Review recent conversation messages for a thread.
    Useful for the agent to check context before responding.
    Returns the last N messages with metadata.
    \"\"\"
    return check_conversation_history_impl(conversation_id, last_n)"""

pattern = re.compile(r'@mcp\.tool\(\)\ndef query_stateless\(.*?def check_conversation_history\(.*?return json\.dumps\(\{"error": str\(e\)\}\)', re.DOTALL | re.MULTILINE)

content = pattern.sub(replacement_block, content)

with open("engine/mcp/cosysim_server.py", "w", encoding="utf-8") as f:
    f.write(content)

