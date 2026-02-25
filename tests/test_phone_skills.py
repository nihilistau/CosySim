"""Tests for phone scene MCP skills — wired implementations."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, PropertyMock


# ── Helpers ────────────────────────────────────────────────────

def _make_mock_scene():
    scene = MagicMock()
    scene._autotxt_muted = False
    scene.sio = MagicMock()
    scene._comfy = None
    return scene


def _make_mock_db():
    db = MagicMock()
    db.get_or_create_dm.return_value = {"id": "thread-123"}
    db.save_message.return_value = {
        "id": "msg-1", "thread_id": "thread-123",
        "sender_id": "system", "content": "test",
    }
    db.list_threads.return_value = [
        {"character_id": "aria", "unread": 3, "last_message": "Hey there!"},
        {"character_id": "lola", "unread": 0, "last_message": "See you later"},
    ]
    db.total_unread.return_value = 3
    db.create_game_session.return_value = "game-001"
    db.get_game_session.return_value = {
        "id": "game-001", "session_type": "truth_or_dare",
        "state": {"round": 2, "history": []},
    }
    db.update_game_state.return_value = None
    return db


# ── Send message ───────────────────────────────────────────────


class TestPhoneSendMessage:
    @patch("content.scenes.phone.phone_skills._get_phone_db")
    @patch("content.scenes.phone.phone_skills._get_phone_scene")
    def test_send_message_success(self, mock_scene_fn, mock_db_fn):
        from content.scenes.phone.phone_skills import phone_send_message
        mock_scene_fn.return_value = _make_mock_scene()
        mock_db_fn.return_value = _make_mock_db()

        result = phone_send_message(character_id="aria", message="Hello!")
        assert "Message sent to aria" in result
        assert "Hello!" in result

    @patch("content.scenes.phone.phone_skills._get_phone_scene")
    def test_send_message_missing_args(self, mock_scene_fn):
        from content.scenes.phone.phone_skills import phone_send_message
        result = phone_send_message()
        assert "Specify" in result

    @patch("content.scenes.phone.phone_skills._get_phone_scene")
    def test_send_message_no_scene(self, mock_scene_fn):
        from content.scenes.phone.phone_skills import phone_send_message
        mock_scene_fn.return_value = None
        result = phone_send_message(character_id="aria", message="hi")
        assert "not active" in result

    @patch("content.scenes.phone.phone_skills._get_phone_db")
    @patch("content.scenes.phone.phone_skills._get_phone_scene")
    def test_send_message_long_preview(self, mock_scene_fn, mock_db_fn):
        from content.scenes.phone.phone_skills import phone_send_message
        mock_scene_fn.return_value = _make_mock_scene()
        mock_db_fn.return_value = _make_mock_db()

        long_msg = "x" * 100
        result = phone_send_message(character_id="aria", message=long_msg)
        assert "..." in result

    @patch("content.scenes.phone.phone_skills._get_phone_db")
    @patch("content.scenes.phone.phone_skills._get_phone_scene")
    def test_send_message_emits_socket(self, mock_scene_fn, mock_db_fn):
        from content.scenes.phone.phone_skills import phone_send_message
        scene = _make_mock_scene()
        mock_scene_fn.return_value = scene
        mock_db_fn.return_value = _make_mock_db()

        phone_send_message(character_id="lola", message="test")
        scene.sio.emit.assert_called_once()
        call_args = scene.sio.emit.call_args
        assert call_args[0][0] == "message_new"


# ── Check messages ─────────────────────────────────────────────


class TestPhoneCheckMessages:
    @patch("content.scenes.phone.phone_skills._get_phone_db")
    def test_check_messages_success(self, mock_db_fn):
        from content.scenes.phone.phone_skills import phone_check_messages
        mock_db_fn.return_value = _make_mock_db()

        result = phone_check_messages()
        assert "2 threads" in result
        assert "aria" in result
        assert "🔴" in result  # unread marker

    @patch("content.scenes.phone.phone_skills._get_phone_db")
    def test_check_messages_empty(self, mock_db_fn):
        from content.scenes.phone.phone_skills import phone_check_messages
        db = _make_mock_db()
        db.list_threads.return_value = []
        mock_db_fn.return_value = db

        result = phone_check_messages()
        assert "No message threads" in result

    @patch("content.scenes.phone.phone_skills._get_phone_db")
    def test_check_messages_no_scene(self, mock_db_fn):
        from content.scenes.phone.phone_skills import phone_check_messages
        mock_db_fn.return_value = None

        result = phone_check_messages()
        assert "not active" in result


# ── Start game ─────────────────────────────────────────────────


class TestPhoneStartGame:
    @patch("content.scenes.phone.phone_skills._get_phone_db")
    @patch("content.scenes.phone.phone_skills._get_phone_scene")
    def test_start_game_success(self, mock_scene_fn, mock_db_fn):
        from content.scenes.phone.phone_skills import phone_start_game
        mock_scene_fn.return_value = _make_mock_scene()
        mock_db_fn.return_value = _make_mock_db()

        result = phone_start_game(game_type="truth_or_dare", character_id="aria")
        assert "Truth Or Dare" in result
        assert "game-001" in result

    def test_start_game_invalid_type(self):
        from content.scenes.phone.phone_skills import phone_start_game
        result = phone_start_game(game_type="invalid")
        assert "Unknown game" in result

    @patch("content.scenes.phone.phone_skills._get_phone_db")
    @patch("content.scenes.phone.phone_skills._get_phone_scene")
    def test_start_game_emits_event(self, mock_scene_fn, mock_db_fn):
        from content.scenes.phone.phone_skills import phone_start_game
        scene = _make_mock_scene()
        mock_scene_fn.return_value = scene
        mock_db_fn.return_value = _make_mock_db()

        phone_start_game(game_type="trivia", character_id="lola")
        scene.sio.emit.assert_called()
        event_name = scene.sio.emit.call_args[0][0]
        assert event_name == "game_event"


# ── Game action ────────────────────────────────────────────────


class TestPhoneGameAction:
    @patch("content.scenes.phone.phone_skills._get_phone_db")
    def test_game_action_success(self, mock_db_fn):
        from content.scenes.phone.phone_skills import phone_game_action
        mock_db_fn.return_value = _make_mock_db()

        result = phone_game_action(action="truth", thread_id="thread-123")
        assert "Action recorded" in result
        assert "round 3" in result  # was round 2, incremented

    @patch("content.scenes.phone.phone_skills._get_phone_db")
    def test_game_action_no_session(self, mock_db_fn):
        from content.scenes.phone.phone_skills import phone_game_action
        db = _make_mock_db()
        db.get_game_session.return_value = None
        mock_db_fn.return_value = db

        result = phone_game_action(action="dare", thread_id="t-1")
        assert "No active game" in result

    def test_game_action_no_action(self):
        from content.scenes.phone.phone_skills import phone_game_action
        result = phone_game_action()
        assert "What's your move" in result


# ── Generate image ─────────────────────────────────────────────


class TestPhoneGenerateImage:
    def test_generate_image_no_prompt(self):
        from content.scenes.phone.phone_skills import phone_generate_image
        result = phone_generate_image()
        assert "Describe" in result

    @patch("content.scenes.phone.phone_skills._get_phone_scene")
    def test_generate_image_no_comfyui(self, mock_scene_fn):
        from content.scenes.phone.phone_skills import phone_generate_image
        scene = _make_mock_scene()
        scene._comfy = None
        scene.comfy = None
        mock_scene_fn.return_value = scene

        result = phone_generate_image(prompt="cat on a beach")
        assert "not connected" in result

    @patch("content.scenes.phone.phone_skills._get_phone_db")
    @patch("content.scenes.phone.phone_skills._get_phone_scene")
    def test_generate_image_with_comfyui(self, mock_scene_fn, mock_db_fn):
        from content.scenes.phone.phone_skills import phone_generate_image
        scene = _make_mock_scene()
        comfy = MagicMock()
        comfy.generate_image.return_value = "/images/cat.png"
        scene._comfy = comfy
        mock_scene_fn.return_value = scene
        mock_db_fn.return_value = _make_mock_db()

        result = phone_generate_image(prompt="cat on beach")
        assert "Image generated" in result
        assert "/images/cat.png" in result


# ── Toggle autotxt ─────────────────────────────────────────────


class TestPhoneToggleAutotxt:
    @patch("content.scenes.phone.phone_skills._get_phone_scene")
    def test_toggle_mute(self, mock_scene_fn):
        from content.scenes.phone.phone_skills import phone_toggle_autotxt
        scene = _make_mock_scene()
        mock_scene_fn.return_value = scene

        result = phone_toggle_autotxt(mute=True)
        assert "muted" in result
        assert scene._autotxt_muted is True

    @patch("content.scenes.phone.phone_skills._get_phone_scene")
    def test_toggle_unmute(self, mock_scene_fn):
        from content.scenes.phone.phone_skills import phone_toggle_autotxt
        scene = _make_mock_scene()
        mock_scene_fn.return_value = scene

        result = phone_toggle_autotxt(mute=False)
        assert "unmuted" in result
        assert scene._autotxt_muted is False

    @patch("content.scenes.phone.phone_skills._get_phone_scene")
    def test_toggle_no_scene(self, mock_scene_fn):
        from content.scenes.phone.phone_skills import phone_toggle_autotxt
        mock_scene_fn.return_value = None

        result = phone_toggle_autotxt(mute=True)
        assert "not active" in result
