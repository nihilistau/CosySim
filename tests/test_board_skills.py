"""Tests for board_skills — MCP skills for highscores and message boards."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# Patch paths — local imports inside each skill read from the source module,
# so we patch the source rather than the consuming module.
_PATCH_BOARDS = "engine.mcp.shared_boards.get_shared_boards"
_PATCH_CTX = "engine.skills.chain_context.get_chain_context"


# ── Helpers ────────────────────────────────────────────────────


def _make_highscores(*entries):
    """Build a list of highscore dicts matching SharedBoardManager format."""
    return [
        {"rank": i + 1, "player_name": name, "score": score}
        for i, (name, score) in enumerate(entries)
    ]


def _make_messages(*entries):
    """Build a list of message dicts matching SharedBoardManager format."""
    return [
        {"id": i + 1, "author_id": f"char-{i}", "author_name": author, "content": text}
        for i, (author, text) in enumerate(entries)
    ]


# ══════════════════════════════════════════════════════════════════
#  view_highscores
# ══════════════════════════════════════════════════════════════════


class TestViewHighscores:
    """Tests for the view_highscores skill."""

    @patch(_PATCH_BOARDS)
    def test_returns_formatted_scores(self, mock_get_boards):
        """Scores should render as a ranked list with the trophy header."""
        from engine.skills.builtin.board_skills import view_highscores

        boards = MagicMock()
        boards.get_highscores.return_value = _make_highscores(
            ("Alice", 9000), ("Bob", 7500), ("Carol", 5000),
        )
        mock_get_boards.return_value = boards

        result = view_highscores()

        assert "🏆 Highscores" in result
        assert "global" in result
        assert "#1 Alice: 9000" in result
        assert "#2 Bob: 7500" in result
        assert "#3 Carol: 5000" in result
        boards.get_highscores.assert_called_once_with("global", 10)

    @patch(_PATCH_BOARDS)
    def test_empty_scores_returns_friendly_message(self, mock_get_boards):
        """An empty board should return a 'no scores' message, not a crash."""
        from engine.skills.builtin.board_skills import view_highscores

        boards = MagicMock()
        boards.get_highscores.return_value = []
        mock_get_boards.return_value = boards

        result = view_highscores()

        assert "No scores" in result
        assert "global" in result

    @patch(_PATCH_BOARDS)
    def test_custom_board_id(self, mock_get_boards):
        """A custom board_id should be forwarded to the manager."""
        from engine.skills.builtin.board_skills import view_highscores

        boards = MagicMock()
        boards.get_highscores.return_value = _make_highscores(("Zara", 42))
        mock_get_boards.return_value = boards

        result = view_highscores(board_id="trivia_night")

        assert "trivia_night" in result
        boards.get_highscores.assert_called_once_with("trivia_night", 10)

    @patch(_PATCH_BOARDS)
    def test_custom_limit(self, mock_get_boards):
        """The limit parameter should be cast to int and forwarded."""
        from engine.skills.builtin.board_skills import view_highscores

        boards = MagicMock()
        boards.get_highscores.return_value = []
        mock_get_boards.return_value = boards

        view_highscores(limit=5)

        boards.get_highscores.assert_called_once_with("global", 5)

    @patch(_PATCH_BOARDS)
    def test_limit_string_coerced_to_int(self, mock_get_boards):
        """LMStudio may pass limit as a string; it should be coerced to int."""
        from engine.skills.builtin.board_skills import view_highscores

        boards = MagicMock()
        boards.get_highscores.return_value = []
        mock_get_boards.return_value = boards

        view_highscores(limit="3")

        boards.get_highscores.assert_called_once_with("global", 3)

    @patch(_PATCH_BOARDS)
    def test_single_score_formatting(self, mock_get_boards):
        """A board with exactly one score should still render correctly."""
        from engine.skills.builtin.board_skills import view_highscores

        boards = MagicMock()
        boards.get_highscores.return_value = _make_highscores(("Solo", 100))
        mock_get_boards.return_value = boards

        result = view_highscores()

        assert "#1 Solo: 100" in result
        assert result.count("#") == 1  # only one rank line


# ══════════════════════════════════════════════════════════════════
#  submit_highscore
# ══════════════════════════════════════════════════════════════════


class TestSubmitHighscore:
    """Tests for the submit_highscore skill."""

    @patch(_PATCH_BOARDS)
    def test_submit_success_with_rank(self, mock_get_boards):
        """Successful submission should return confirmation with rank."""
        from engine.skills.builtin.board_skills import submit_highscore

        boards = MagicMock()
        boards.submit_score.return_value = {"score": 9001, "rank": 1}
        mock_get_boards.return_value = boards

        result = submit_highscore(board_id="arcade", player_name="Neo", score=9001)

        assert "Score submitted" in result
        assert "Neo" in result
        assert "9001" in result
        assert "Rank #1" in result
        boards.submit_score.assert_called_once_with("arcade", "Neo", 9001)

    @patch(_PATCH_BOARDS)
    def test_submit_low_rank(self, mock_get_boards):
        """A low-ranking score should still show the correct rank number."""
        from engine.skills.builtin.board_skills import submit_highscore

        boards = MagicMock()
        boards.submit_score.return_value = {"score": 10, "rank": 99}
        mock_get_boards.return_value = boards

        result = submit_highscore(board_id="global", player_name="Newbie", score=10)

        assert "Rank #99" in result

    @patch(_PATCH_BOARDS)
    def test_submit_score_coerced_to_int(self, mock_get_boards):
        """Score passed as string should be coerced to int before submission."""
        from engine.skills.builtin.board_skills import submit_highscore

        boards = MagicMock()
        boards.submit_score.return_value = {"score": 500, "rank": 5}
        mock_get_boards.return_value = boards

        submit_highscore(board_id="quiz", player_name="Bot", score="500")

        boards.submit_score.assert_called_once_with("quiz", "Bot", 500)


# ══════════════════════════════════════════════════════════════════
#  post_to_board
# ══════════════════════════════════════════════════════════════════


class TestPostToBoard:
    """Tests for the post_to_board skill."""

    @patch(_PATCH_CTX)
    @patch(_PATCH_BOARDS)
    def test_post_success_with_chain_context(self, mock_get_boards, mock_ctx):
        """When chain context has a character_id, it should be used as author_id."""
        from engine.skills.builtin.board_skills import post_to_board

        mock_ctx.return_value = {"character_id": "aria", "scene_id": "lounge"}
        boards = MagicMock()
        boards.post_message.return_value = {"id": 42}
        mock_get_boards.return_value = boards

        result = post_to_board(
            board_id="cosysim_global", message="Hello world!", author_name="Aria",
        )

        assert "Message posted" in result
        assert "cosysim_global" in result
        assert "#42" in result
        boards.post_message.assert_called_once_with(
            "cosysim_global", "aria", "Hello world!", "Aria",
        )

    @patch(_PATCH_CTX)
    @patch(_PATCH_BOARDS)
    def test_post_without_chain_context(self, mock_get_boards, mock_ctx):
        """When chain context is empty, author_id should fall back to 'unknown'."""
        from engine.skills.builtin.board_skills import post_to_board

        mock_ctx.return_value = {}
        boards = MagicMock()
        boards.post_message.return_value = {"id": 7}
        mock_get_boards.return_value = boards

        result = post_to_board(message="Anon post")

        boards.post_message.assert_called_once_with(
            "cosysim_global", "unknown", "Anon post", "Agent",
        )
        assert "#7" in result

    @patch(_PATCH_CTX)
    @patch(_PATCH_BOARDS)
    def test_post_with_none_context(self, mock_get_boards, mock_ctx):
        """When get_chain_context() returns None, author_id should be 'unknown'."""
        from engine.skills.builtin.board_skills import post_to_board

        mock_ctx.return_value = None
        boards = MagicMock()
        boards.post_message.return_value = {"id": 1}
        mock_get_boards.return_value = boards

        post_to_board(message="Null context")

        boards.post_message.assert_called_once_with(
            "cosysim_global", "unknown", "Null context", "Agent",
        )

    @patch(_PATCH_CTX)
    @patch(_PATCH_BOARDS)
    def test_post_custom_board_id(self, mock_get_boards, mock_ctx):
        """A custom board_id should be forwarded to post_message."""
        from engine.skills.builtin.board_skills import post_to_board

        mock_ctx.return_value = {"character_id": "lola"}
        boards = MagicMock()
        boards.post_message.return_value = {"id": 99}
        mock_get_boards.return_value = boards

        result = post_to_board(board_id="vip_lounge", message="VIP only")

        assert "vip_lounge" in result
        boards.post_message.assert_called_once_with(
            "vip_lounge", "lola", "VIP only", "Agent",
        )

    @patch(_PATCH_CTX)
    @patch(_PATCH_BOARDS)
    def test_post_custom_author_name(self, mock_get_boards, mock_ctx):
        """The author_name argument should be passed through to post_message."""
        from engine.skills.builtin.board_skills import post_to_board

        mock_ctx.return_value = {"character_id": "rex"}
        boards = MagicMock()
        boards.post_message.return_value = {"id": 5}
        mock_get_boards.return_value = boards

        post_to_board(message="Woof", author_name="Rex the Dog")

        boards.post_message.assert_called_once_with(
            "cosysim_global", "rex", "Woof", "Rex the Dog",
        )

    @patch(_PATCH_CTX)
    @patch(_PATCH_BOARDS)
    def test_post_default_parameters(self, mock_get_boards, mock_ctx):
        """Calling with no args should use all defaults."""
        from engine.skills.builtin.board_skills import post_to_board

        mock_ctx.return_value = {}
        boards = MagicMock()
        boards.post_message.return_value = {"id": 0}
        mock_get_boards.return_value = boards

        post_to_board()

        boards.post_message.assert_called_once_with(
            "cosysim_global", "unknown", "", "Agent",
        )


# ══════════════════════════════════════════════════════════════════
#  read_board
# ══════════════════════════════════════════════════════════════════


class TestReadBoard:
    """Tests for the read_board skill."""

    @patch(_PATCH_BOARDS)
    def test_returns_formatted_messages(self, mock_get_boards):
        """Messages should render with author names and content."""
        from engine.skills.builtin.board_skills import read_board

        boards = MagicMock()
        boards.get_messages.return_value = _make_messages(
            ("Alice", "Good morning!"),
            ("Bob", "Hey Alice!"),
        )
        mock_get_boards.return_value = boards

        result = read_board()

        assert "📋 Board" in result
        assert "cosysim_global" in result
        assert "2 messages" in result
        assert "[Alice]: Good morning!" in result
        assert "[Bob]: Hey Alice!" in result
        boards.get_messages.assert_called_once_with("cosysim_global", 20)

    @patch(_PATCH_BOARDS)
    def test_empty_board_returns_friendly_message(self, mock_get_boards):
        """An empty board should return a 'no messages' string, not a crash."""
        from engine.skills.builtin.board_skills import read_board

        boards = MagicMock()
        boards.get_messages.return_value = []
        mock_get_boards.return_value = boards

        result = read_board()

        assert "No messages" in result
        assert "cosysim_global" in result

    @patch(_PATCH_BOARDS)
    def test_custom_board_id(self, mock_get_boards):
        """A custom board_id should be forwarded to get_messages."""
        from engine.skills.builtin.board_skills import read_board

        boards = MagicMock()
        boards.get_messages.return_value = _make_messages(("Mod", "Welcome!"))
        mock_get_boards.return_value = boards

        result = read_board(board_id="announcements")

        assert "announcements" in result
        boards.get_messages.assert_called_once_with("announcements", 20)

    @patch(_PATCH_BOARDS)
    def test_custom_limit(self, mock_get_boards):
        """The limit parameter should be forwarded to get_messages."""
        from engine.skills.builtin.board_skills import read_board

        boards = MagicMock()
        boards.get_messages.return_value = []
        mock_get_boards.return_value = boards

        read_board(limit=5)

        boards.get_messages.assert_called_once_with("cosysim_global", 5)

    @patch(_PATCH_BOARDS)
    def test_limit_string_coerced_to_int(self, mock_get_boards):
        """Limit passed as string should be coerced to int."""
        from engine.skills.builtin.board_skills import read_board

        boards = MagicMock()
        boards.get_messages.return_value = []
        mock_get_boards.return_value = boards

        read_board(limit="10")

        boards.get_messages.assert_called_once_with("cosysim_global", 10)

    @patch(_PATCH_BOARDS)
    def test_single_message_count_label(self, mock_get_boards):
        """Board with one message should show '1 messages' in header."""
        from engine.skills.builtin.board_skills import read_board

        boards = MagicMock()
        boards.get_messages.return_value = _make_messages(("Solo", "Only me here"))
        mock_get_boards.return_value = boards

        result = read_board()

        assert "1 messages" in result
        assert "[Solo]: Only me here" in result
