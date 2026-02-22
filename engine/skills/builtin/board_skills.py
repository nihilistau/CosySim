"""
Board skills — MCP skills for highscores and system-wide message boards.

Skills:
    view_highscores  — Read a highscore table
    submit_highscore — Post a score
    post_to_board    — Post a message to a shared board
    read_board       — Read messages from a shared board
"""
from engine.skills.skill import skill


@skill(pack="boards", tags=["social", "data"],
       description="View a highscore table. Returns ranked list.")
def view_highscores(board_id: str = "global", limit: int = 10) -> str:
    from engine.mcp.shared_boards import get_shared_boards
    scores = get_shared_boards().get_highscores(board_id, int(limit))
    if not scores:
        return f"No scores on '{board_id}' yet."
    lines = [f"🏆 Highscores — {board_id}"]
    for s in scores:
        lines.append(f"  #{s['rank']} {s['player_name']}: {s['score']}")
    return "\n".join(lines)


@skill(pack="boards", tags=["social", "data"],
       description="Submit a highscore to a board.")
def submit_highscore(board_id: str, player_name: str, score: int) -> str:
    from engine.mcp.shared_boards import get_shared_boards
    result = get_shared_boards().submit_score(board_id, player_name, int(score))
    return f"Score submitted! {player_name}: {result['score']} (Rank #{result['rank']})"


@skill(pack="boards", tags=["social", "communication"],
       description="Post a message to a shared message board.")
def post_to_board(board_id: str = "cosysim_global", message: str = "",
                  author_name: str = "Agent") -> str:
    from engine.mcp.shared_boards import get_shared_boards
    from engine.skills.chain_context import get_chain_context
    ctx = get_chain_context()
    author_id = ctx.get("character_id", "unknown") if ctx else "unknown"
    result = get_shared_boards().post_message(
        board_id, author_id, message, author_name)
    return f"Message posted to '{board_id}' (#{result['id']})"


@skill(pack="boards", tags=["social", "communication"],
       description="Read messages from a shared message board.")
def read_board(board_id: str = "cosysim_global", limit: int = 20) -> str:
    from engine.mcp.shared_boards import get_shared_boards
    messages = get_shared_boards().get_messages(board_id, int(limit))
    if not messages:
        return f"No messages on '{board_id}' yet."
    lines = [f"📋 Board — {board_id} ({len(messages)} messages)"]
    for m in messages:
        lines.append(f"  [{m['author_name']}]: {m['content']}")
    return "\n".join(lines)
