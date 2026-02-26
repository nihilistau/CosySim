"""
Tests for engine.lmstudio.conversation — ConversationMessage, Conversation,
ConversationManager, singleton, and edge cases.

Covers:
- ConversationMessage serialisation (to_dict)
- Conversation init, system prompt, turn counting
- Conversation.send() — stateful fast-path and full-replay fallback
- Conversation.send_stateless() — store=False, no state mutation
- Conversation.branch_at() — response_id lookup + fork with server branching
- Conversation.fork() — deep copy, at_turn slicing, branch_response_id
- Conversation.edit_message() / truncate() — server invalidation
- Conversation.update_system_if_changed() — idempotent guard
- Conversation.add_system_message / add_assistant_message — injections
- ConversationManager CRUD — create, get, get_or_create, delete, list
- ConversationManager invalidation — invalidate_all, invalidate_model, callbacks
- ConversationManager stats
- Thread-safety — concurrent sends
- Edge cases — empty conversations, bad branch indices, zero-turn fork
- Singleton — get_conversation_manager
"""
import copy
import threading
import time
from unittest.mock import MagicMock, patch, call

import pytest

from engine.lmstudio.conversation import (
    Conversation,
    ConversationManager,
    ConversationMessage,
    get_conversation_manager,
)


# ── Helpers ───────────────────────────────────────────────────────────

def _make_lms_response(content="ok", response_id="resp_abc123"):
    """Build a lightweight mock LMSResponse."""
    resp = MagicMock()
    resp.content = content
    resp.response_id = response_id
    return resp


def _populated_conversation(n_turns=3, system="You are a helper."):
    """Create a Conversation with *n_turns* user/assistant pairs pre-loaded."""
    conv = Conversation("pop_conv", system=system, model="test-model")
    for i in range(1, n_turns + 1):
        rid = f"resp_{i:04d}"
        conv.messages.append(ConversationMessage(
            role="user", content=f"user msg {i}", timestamp=float(i),
        ))
        conv.messages.append(ConversationMessage(
            role="assistant", content=f"asst msg {i}", timestamp=float(i) + 0.5,
            metadata={"response_id": rid},
        ))
        conv._response_id_history.append(rid)
    conv.response_id = f"resp_{n_turns:04d}"
    conv._server_synced = True
    return conv


# ── ConversationMessage ───────────────────────────────────────────────

class TestConversationMessage:
    """Serialisation and metadata handling for ConversationMessage."""

    def test_to_dict_basic(self):
        msg = ConversationMessage(role="user", content="hello")
        d = msg.to_dict()
        assert d == {"role": "user", "content": "hello"}

    def test_to_dict_includes_tool_calls(self):
        tc = [{"id": "tc1", "type": "function", "function": {"name": "f"}}]
        msg = ConversationMessage(
            role="assistant", content="", metadata={"tool_calls": tc}
        )
        d = msg.to_dict()
        assert d["tool_calls"] is tc

    def test_to_dict_tool_role_includes_tool_call_id(self):
        msg = ConversationMessage(
            role="tool", content="result",
            metadata={"tool_call_id": "tc1"},
        )
        d = msg.to_dict()
        assert d["tool_call_id"] == "tc1"

    def test_to_dict_no_tool_metadata_omits_keys(self):
        msg = ConversationMessage(role="system", content="sys")
        d = msg.to_dict()
        assert "tool_calls" not in d
        assert "tool_call_id" not in d

    def test_default_timestamp_is_zero(self):
        msg = ConversationMessage(role="user", content="x")
        assert msg.timestamp == 0.0

    def test_metadata_default_is_empty_dict(self):
        msg = ConversationMessage(role="user", content="x")
        assert msg.metadata == {}


# ── Conversation init & properties ────────────────────────────────────

class TestConversationInit:
    """Construction, system prompt injection, and basic property tests."""

    def test_init_with_system(self):
        conv = Conversation("c1", system="Be nice.", model="m1")
        assert conv.conversation_id == "c1"
        assert conv.system == "Be nice."
        assert conv.model == "m1"
        assert len(conv.messages) == 1
        assert conv.messages[0].role == "system"
        assert conv.messages[0].content == "Be nice."

    def test_init_without_system(self):
        conv = Conversation("c2")
        assert conv.messages == []
        assert conv.system == ""

    def test_turn_count_excludes_system(self):
        conv = Conversation("c3", system="sys")
        assert conv.turn_count == 0
        conv.messages.append(ConversationMessage(role="user", content="hi"))
        assert conv.turn_count == 1
        conv.messages.append(ConversationMessage(role="assistant", content="hey"))
        assert conv.turn_count == 2

    def test_is_synced_requires_both(self):
        conv = Conversation("c4")
        assert conv.is_synced is False
        conv._server_synced = True
        assert conv.is_synced is False  # no response_id yet
        conv.response_id = "resp_001"
        assert conv.is_synced is True

    def test_created_at_and_last_active_set(self):
        before = time.time()
        conv = Conversation("c5")
        after = time.time()
        assert before <= conv.created_at <= after
        assert before <= conv.last_active <= after


# ── Conversation.send() ──────────────────────────────────────────────

class TestConversationSend:
    """send() path selection — stateful fast-path vs full replay."""

    @patch("engine.lmstudio.lms_client.get_lms_client")
    @patch("engine.lmstudio.inference_config.InferenceConfig")
    def test_send_full_replay_when_not_synced(self, MockCfg, mock_get_client):
        """First send (not synced) replays entire history via client.chat()."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        MockCfg.return_value = MagicMock()
        MockCfg.merge = MagicMock(side_effect=lambda b, o: b)

        resp = _make_lms_response("hello back", "resp_001")
        mock_client.chat.return_value = resp

        conv = Conversation("s1", system="sys", model="test-model")
        result = conv.send("hi there")

        # Should call chat() (full replay) not chat_stateful()
        mock_client.chat.assert_called_once()
        mock_client.chat_stateful.assert_not_called()

        # State updated
        assert result.content == "hello back"
        assert conv.response_id == "resp_001"
        assert conv._server_synced is True
        assert conv._response_id_history == ["resp_001"]

    @patch("engine.lmstudio.lms_client.get_lms_client")
    @patch("engine.lmstudio.inference_config.InferenceConfig")
    def test_send_stateful_when_synced(self, MockCfg, mock_get_client):
        """Second send (synced) uses chat_stateful() with previous_response_id."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        MockCfg.return_value = MagicMock()
        MockCfg.merge = MagicMock(side_effect=lambda b, o: b)

        conv = Conversation("s2", system="sys")
        conv.response_id = "resp_001"
        conv._server_synced = True

        resp = _make_lms_response("follow-up", "resp_002")
        mock_client.chat_stateful.return_value = resp

        result = conv.send("what next?")

        mock_client.chat_stateful.assert_called_once()
        args, kwargs = mock_client.chat_stateful.call_args
        assert args[0] == "what next?"
        assert kwargs["previous_response_id"] == "resp_001"
        assert conv.response_id == "resp_002"
        assert "resp_002" in conv._response_id_history

    @patch("engine.lmstudio.lms_client.get_lms_client")
    @patch("engine.lmstudio.inference_config.InferenceConfig")
    def test_send_records_messages(self, MockCfg, mock_get_client):
        """send() appends both user and assistant messages to history."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        MockCfg.return_value = MagicMock()
        MockCfg.merge = MagicMock(side_effect=lambda b, o: b)

        resp = _make_lms_response("reply", "resp_x")
        mock_client.chat.return_value = resp

        conv = Conversation("s3")
        conv.send("question")

        assert len(conv.messages) == 2
        assert conv.messages[0].role == "user"
        assert conv.messages[0].content == "question"
        assert conv.messages[1].role == "assistant"
        assert conv.messages[1].content == "reply"
        assert conv.messages[1].metadata["response_id"] == "resp_x"

    @patch("engine.lmstudio.lms_client.get_lms_client")
    @patch("engine.lmstudio.inference_config.InferenceConfig")
    def test_send_with_previous_response_id_override(self, MockCfg, mock_get_client):
        """Override forces chat_stateful even when not synced."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        MockCfg.return_value = MagicMock()
        MockCfg.merge = MagicMock(side_effect=lambda b, o: b)

        resp = _make_lms_response("overridden", "resp_ovr")
        mock_client.chat_stateful.return_value = resp

        conv = Conversation("s4")
        conv._server_synced = False
        result = conv.send("msg", previous_response_id_override="resp_external")

        mock_client.chat_stateful.assert_called_once()
        _, kwargs = mock_client.chat_stateful.call_args
        assert kwargs["previous_response_id"] == "resp_external"

    @patch("engine.lmstudio.lms_client.get_lms_client")
    @patch("engine.lmstudio.inference_config.InferenceConfig")
    def test_send_updates_last_active(self, MockCfg, mock_get_client):
        """last_active timestamp moves forward after send."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        MockCfg.return_value = MagicMock()
        MockCfg.merge = MagicMock(side_effect=lambda b, o: b)
        mock_client.chat.return_value = _make_lms_response()

        conv = Conversation("s5")
        old_active = conv.last_active
        time.sleep(0.01)
        conv.send("ping")
        assert conv.last_active > old_active

    @patch("engine.lmstudio.lms_client.get_lms_client")
    @patch("engine.lmstudio.inference_config.InferenceConfig")
    def test_send_handles_empty_response_id(self, MockCfg, mock_get_client):
        """If response has no response_id the server_synced stays False."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        MockCfg.return_value = MagicMock()
        MockCfg.merge = MagicMock(side_effect=lambda b, o: b)

        resp = _make_lms_response("noid", "")
        mock_client.chat.return_value = resp

        conv = Conversation("s6")
        conv.send("test")
        assert conv.response_id is None  # unchanged from init
        assert conv._server_synced is False


# ── Conversation.send_stateless() ─────────────────────────────────────

class TestConversationSendStateless:
    """send_stateless() must use store=False and NOT mutate state."""

    @patch("engine.lmstudio.lms_client.get_lms_client")
    @patch("engine.lmstudio.inference_config.InferenceConfig")
    def test_stateless_sends_store_false(self, MockCfg, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        MockCfg.return_value = MagicMock()
        MockCfg.merge = MagicMock(side_effect=lambda b, o: b)

        resp = _make_lms_response("summary", "resp_ign")
        mock_client.chat.return_value = resp

        conv = Conversation("sl1", system="sys")
        result = conv.send_stateless("summarise")

        mock_client.chat.assert_called_once()
        _, kwargs = mock_client.chat.call_args
        assert kwargs["store"] is False

    @patch("engine.lmstudio.lms_client.get_lms_client")
    @patch("engine.lmstudio.inference_config.InferenceConfig")
    def test_stateless_does_not_mutate_history(self, MockCfg, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        MockCfg.return_value = MagicMock()
        MockCfg.merge = MagicMock(side_effect=lambda b, o: b)
        mock_client.chat.return_value = _make_lms_response()

        conv = _populated_conversation(n_turns=2)
        msg_count_before = len(conv.messages)
        rid_before = conv.response_id

        conv.send_stateless("sidebar question")

        assert len(conv.messages) == msg_count_before
        assert conv.response_id == rid_before

    @patch("engine.lmstudio.lms_client.get_lms_client")
    @patch("engine.lmstudio.inference_config.InferenceConfig")
    def test_stateless_uses_system_override(self, MockCfg, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        MockCfg.return_value = MagicMock()
        MockCfg.merge = MagicMock(side_effect=lambda b, o: b)
        mock_client.chat.return_value = _make_lms_response()

        conv = Conversation("sl3", system="original sys")
        conv.send_stateless("q", system_override="custom sys")

        messages_sent = mock_client.chat.call_args[0][0]
        assert messages_sent[0]["content"] == "custom sys"

    @patch("engine.lmstudio.lms_client.get_lms_client")
    @patch("engine.lmstudio.inference_config.InferenceConfig")
    def test_stateless_uses_default_system(self, MockCfg, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        MockCfg.return_value = MagicMock()
        MockCfg.merge = MagicMock(side_effect=lambda b, o: b)
        mock_client.chat.return_value = _make_lms_response()

        conv = Conversation("sl4", system="fallback sys")
        conv.send_stateless("q")

        messages_sent = mock_client.chat.call_args[0][0]
        assert messages_sent[0]["content"] == "fallback sys"

    @patch("engine.lmstudio.lms_client.get_lms_client")
    @patch("engine.lmstudio.inference_config.InferenceConfig")
    def test_stateless_no_system_omits_system_msg(self, MockCfg, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        MockCfg.return_value = MagicMock()
        MockCfg.merge = MagicMock(side_effect=lambda b, o: b)
        mock_client.chat.return_value = _make_lms_response()

        conv = Conversation("sl5")  # no system
        conv.send_stateless("q")

        messages_sent = mock_client.chat.call_args[0][0]
        assert len(messages_sent) == 1
        assert messages_sent[0]["role"] == "user"


# ── Conversation.fork() ──────────────────────────────────────────────

class TestConversationFork:
    """fork() deep-copies messages and optionally truncates / branches."""

    def test_fork_full_copy(self):
        conv = _populated_conversation(n_turns=3)
        forked = conv.fork(new_id="fork1")

        assert forked.conversation_id == "fork1"
        assert len(forked.messages) == len(conv.messages)
        assert forked.messages is not conv.messages
        # Deep copy — mutating original doesn't affect fork
        conv.messages[1].content = "MUTATED"
        assert forked.messages[1].content != "MUTATED"

    def test_fork_at_turn(self):
        conv = _populated_conversation(n_turns=3)
        # fork counts each user/assistant individually, so at_turn=4
        # keeps messages while turn_count <= 4 → system + user1+asst1+user2+asst2
        forked = conv.fork(at_turn=4, new_id="fork2")
        assert len(forked.messages) == 5  # 1 system + 4 msgs
        assert forked.messages[0].role == "system"
        assert forked.messages[-1].role == "assistant"
        assert forked.messages[-1].content == "asst msg 2"

    def test_fork_at_turn_zero_keeps_system_only(self):
        conv = _populated_conversation(n_turns=2)
        forked = conv.fork(at_turn=0, new_id="fork0")
        assert len(forked.messages) == 1  # system only
        assert forked.messages[0].role == "system"

    def test_fork_with_branch_response_id(self):
        conv = _populated_conversation(n_turns=2)
        forked = conv.fork(
            at_turn=1,
            new_id="fork_branch",
            branch_response_id="resp_0001",
        )
        assert forked.response_id == "resp_0001"
        assert forked._server_synced is True

    def test_fork_without_branch_response_id_not_synced(self):
        conv = _populated_conversation(n_turns=2)
        forked = conv.fork(at_turn=1, new_id="fork_nosync")
        assert forked.response_id is None
        assert forked._server_synced is False

    def test_fork_invalid_branch_response_id_not_synced(self):
        """Non-resp_ prefix is treated as invalid — not synced."""
        conv = _populated_conversation(n_turns=2)
        forked = conv.fork(
            at_turn=1,
            new_id="fork_bad",
            branch_response_id="bad_prefix",
        )
        assert forked._server_synced is False
        assert forked.response_id is None

    def test_fork_preserves_model_and_config(self):
        cfg = MagicMock()
        conv = Conversation("c_cfg", model="my-model", config=cfg)
        forked = conv.fork(new_id="fork_cfg")
        assert forked.model == "my-model"

    def test_fork_auto_generates_id(self):
        conv = Conversation("base_conv")
        forked = conv.fork()
        assert forked.conversation_id.startswith("base_conv_fork_")


# ── Conversation.branch_at() ─────────────────────────────────────────

class TestConversationBranchAt:
    """branch_at() looks up the response_id at a given turn and forks."""

    def test_branch_at_valid_turn(self):
        conv = _populated_conversation(n_turns=3)
        branch = conv.branch_at(2, new_id="b2")

        # branch_at(2) → fork(at_turn=2): keeps msgs while turn_count <= 2
        # user1 (tc=1), asst1 (tc=2), user2 (tc=3 → break)
        # = system + user1 + asst1 = 3 messages
        assert len(branch.messages) == 3
        assert branch.response_id == "resp_0002"
        assert branch._server_synced is True

    def test_branch_at_turn_1(self):
        conv = _populated_conversation(n_turns=3)
        branch = conv.branch_at(1, new_id="b1")

        # branch_at(1) → fork(at_turn=1): keeps msgs while turn_count <= 1
        # user1 (tc=1, kept), asst1 (tc=2 → break)
        # = system + user1 = 2 messages
        assert len(branch.messages) == 2
        assert branch.response_id == "resp_0001"

    def test_branch_at_invalid_turn_no_response_id(self):
        """Turn beyond range → no matching response_id → fork without sync."""
        conv = _populated_conversation(n_turns=2)
        branch = conv.branch_at(99, new_id="b_oob")
        assert branch._server_synced is False
        assert branch.response_id is None

    def test_branch_at_turn_zero_no_assistant(self):
        """Turn 0 has no assistant message → no response_id."""
        conv = _populated_conversation(n_turns=2)
        branch = conv.branch_at(0, new_id="b0")
        assert branch._server_synced is False

    def test_branch_at_auto_id(self):
        conv = _populated_conversation(n_turns=1)
        branch = conv.branch_at(1)
        assert branch.conversation_id.startswith("pop_conv_fork_")


# ── Conversation history mutation ─────────────────────────────────────

class TestConversationMutation:
    """edit_message, truncate, add_*, and system update."""

    def test_edit_message_changes_content(self):
        conv = _populated_conversation(n_turns=2)
        conv.edit_message(1, "EDITED")
        assert conv.messages[1].content == "EDITED"

    def test_edit_message_invalidates_server(self):
        conv = _populated_conversation(n_turns=2)
        assert conv._server_synced is True
        conv.edit_message(1, "EDITED")
        assert conv._server_synced is False
        assert conv.response_id is None

    def test_edit_message_out_of_range_raises(self):
        conv = _populated_conversation(n_turns=1)
        with pytest.raises(IndexError, match="out of range"):
            conv.edit_message(999, "bad")

    def test_edit_message_negative_out_of_range(self):
        conv = _populated_conversation(n_turns=1)
        with pytest.raises(IndexError, match="out of range"):
            conv.edit_message(-1, "bad")

    def test_truncate_keeps_last_n_turns(self):
        conv = _populated_conversation(n_turns=4)
        conv.truncate(keep_turns=2)
        # system + last 2 turns (4 msgs) = 5
        assert conv.messages[0].role == "system"
        non_sys = [m for m in conv.messages if m.role != "system"]
        assert len(non_sys) == 4  # 2 user + 2 assistant
        assert conv._server_synced is False

    def test_truncate_more_than_available(self):
        conv = _populated_conversation(n_turns=2)
        conv.truncate(keep_turns=10)
        # All messages kept: system + 2*2 = 5
        assert len(conv.messages) == 5

    def test_add_system_message_invalidates(self):
        conv = _populated_conversation(n_turns=1)
        conv.add_system_message("new instruction")
        assert conv.messages[-1].role == "system"
        assert conv.messages[-1].content == "new instruction"
        assert conv._server_synced is False

    def test_add_assistant_message_invalidates(self):
        conv = _populated_conversation(n_turns=1)
        conv.add_assistant_message("seeded response")
        assert conv.messages[-1].role == "assistant"
        assert conv._server_synced is False

    def test_update_system_if_changed_true(self):
        conv = Conversation("us1", system="old prompt")
        changed = conv.update_system_if_changed("new prompt")
        assert changed is True
        assert conv.system == "new prompt"
        assert conv.messages[0].content == "new prompt"
        assert conv._server_synced is False

    def test_update_system_if_changed_same_noop(self):
        conv = Conversation("us2", system="same prompt")
        conv._server_synced = True
        conv.response_id = "resp_keep"
        changed = conv.update_system_if_changed("same prompt")
        assert changed is False
        assert conv._server_synced is True  # untouched
        assert conv.response_id == "resp_keep"

    def test_update_system_inserts_if_no_system_msg(self):
        conv = Conversation("us3")  # no system
        assert len(conv.messages) == 0
        conv.update_system_if_changed("injected")
        assert conv.messages[0].role == "system"
        assert conv.messages[0].content == "injected"

    def test_invalidate_public_method(self):
        conv = _populated_conversation(n_turns=1)
        assert conv._server_synced is True
        conv.invalidate()
        assert conv._server_synced is False
        assert conv.response_id is None


# ── Conversation.get_history / get_summary ────────────────────────────

class TestConversationHistory:
    """Serialisation helpers."""

    def test_get_history_returns_dicts(self):
        conv = _populated_conversation(n_turns=2)
        history = conv.get_history()
        assert isinstance(history, list)
        assert all(isinstance(d, dict) for d in history)
        assert history[0]["role"] == "system"

    def test_get_summary_keys(self):
        conv = _populated_conversation(n_turns=2)
        s = conv.get_summary()
        expected_keys = {
            "id", "turn_count", "model", "synced",
            "response_id", "response_id_count",
            "created_at", "last_active", "message_count",
        }
        assert set(s.keys()) == expected_keys
        assert s["turn_count"] == 4  # 2 user + 2 asst
        assert s["synced"] is True
        assert s["response_id_count"] == 2


# ── ConversationManager CRUD ─────────────────────────────────────────

class TestConversationManagerCRUD:
    """Create, get, get_or_create, delete, list."""

    def test_create_and_get(self):
        mgr = ConversationManager()
        conv = mgr.create("c1", system="sys", model="m1")
        assert conv.conversation_id == "c1"
        assert mgr.get("c1") is conv

    def test_get_nonexistent_returns_none(self):
        mgr = ConversationManager()
        assert mgr.get("missing") is None

    def test_create_replaces_existing(self):
        mgr = ConversationManager()
        old = mgr.create("dup")
        new = mgr.create("dup", system="replaced")
        assert mgr.get("dup") is new
        assert mgr.get("dup") is not old
        assert mgr.get("dup").system == "replaced"

    def test_get_or_create_returns_existing(self):
        mgr = ConversationManager()
        first = mgr.create("existing", system="original")
        second = mgr.get_or_create("existing", system="ignored")
        assert second is first
        assert second.system == "original"

    def test_get_or_create_creates_new(self):
        mgr = ConversationManager()
        conv = mgr.get_or_create("new1", system="fresh")
        assert conv.conversation_id == "new1"
        assert conv.system == "fresh"

    def test_delete_existing(self):
        mgr = ConversationManager()
        mgr.create("d1")
        assert mgr.delete("d1") is True
        assert mgr.get("d1") is None

    def test_delete_nonexistent(self):
        mgr = ConversationManager()
        assert mgr.delete("ghost") is False

    def test_list_conversations(self):
        mgr = ConversationManager()
        mgr.create("a", system="sa")
        mgr.create("b", system="sb")
        summaries = mgr.list_conversations()
        assert len(summaries) == 2
        ids = {s["id"] for s in summaries}
        assert ids == {"a", "b"}

    def test_list_empty(self):
        mgr = ConversationManager()
        assert mgr.list_conversations() == []


# ── ConversationManager invalidation ─────────────────────────────────

class TestConversationManagerInvalidation:
    """invalidate_all, invalidate_model, callbacks."""

    def test_invalidate_all_resets_synced(self):
        mgr = ConversationManager()
        c1 = mgr.create("i1")
        c1.response_id = "resp_1"
        c1._server_synced = True
        c2 = mgr.create("i2")
        c2.response_id = "resp_2"
        c2._server_synced = True

        count = mgr.invalidate_all("test")
        assert count == 2
        assert c1._server_synced is False
        assert c2._server_synced is False

    def test_invalidate_all_skips_already_unsynced(self):
        mgr = ConversationManager()
        c1 = mgr.create("ia1")  # not synced by default
        count = mgr.invalidate_all()
        assert count == 0

    def test_invalidate_model_selective(self):
        mgr = ConversationManager()
        c1 = mgr.create("im1", model="model-a")
        c1._server_synced = True
        c1.response_id = "resp_a"
        c2 = mgr.create("im2", model="model-b")
        c2._server_synced = True
        c2.response_id = "resp_b"

        count = mgr.invalidate_model("model-a")
        assert count == 1
        assert c1._server_synced is False
        # model-b conversation untouched
        assert c2._server_synced is True

    def test_invalidate_model_includes_none_model(self):
        """Conversations with model=None are invalidated for any model."""
        mgr = ConversationManager()
        c = mgr.create("im_none")  # model=None
        c._server_synced = True
        c.response_id = "resp_none"
        count = mgr.invalidate_model("any-model")
        assert count == 1

    def test_on_invalidate_callback_fires(self):
        mgr = ConversationManager()
        callback = MagicMock()
        mgr.on_invalidate(callback)

        c = mgr.create("cb1")
        c._server_synced = True
        c.response_id = "resp_cb"
        mgr.invalidate_all("model_swap")

        callback.assert_called_once_with("model_swap", 1)

    def test_on_invalidate_callback_exception_suppressed(self):
        mgr = ConversationManager()
        bad_callback = MagicMock(side_effect=RuntimeError("boom"))
        mgr.on_invalidate(bad_callback)

        c = mgr.create("cb2")
        c._server_synced = True
        c.response_id = "resp_cb2"
        # Should not raise even though callback explodes
        count = mgr.invalidate_all("crash_test")
        assert count == 1


# ── ConversationManager stats ────────────────────────────────────────

class TestConversationManagerStats:
    """get_stats() aggregation."""

    def test_stats_empty(self):
        mgr = ConversationManager()
        s = mgr.get_stats()
        assert s == {"total": 0, "synced": 0, "total_messages": 0, "total_turns": 0}

    def test_stats_populated(self):
        mgr = ConversationManager()
        c1 = mgr.create("st1", system="sys")
        c1.messages.append(ConversationMessage(role="user", content="u"))
        c1.messages.append(ConversationMessage(role="assistant", content="a"))
        c1._server_synced = True
        c1.response_id = "resp_st"

        c2 = mgr.create("st2", system="sys")

        s = mgr.get_stats()
        assert s["total"] == 2
        assert s["synced"] == 1
        assert s["total_messages"] == 4  # c1: sys+u+a=3, c2: sys=1
        assert s["total_turns"] == 2     # c1 has 1 user + 1 asst


# ── Thread safety ─────────────────────────────────────────────────────

class TestThreadSafety:
    """Concurrent access must not corrupt state."""

    @patch("engine.lmstudio.lms_client.get_lms_client")
    @patch("engine.lmstudio.inference_config.InferenceConfig")
    def test_concurrent_sends(self, MockCfg, mock_get_client):
        """Multiple threads sending to the same conversation."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        MockCfg.return_value = MagicMock()
        MockCfg.merge = MagicMock(side_effect=lambda b, o: b)

        counter = {"n": 0}

        def make_resp(*a, **kw):
            counter["n"] += 1
            return _make_lms_response(f"r{counter['n']}", f"resp_{counter['n']:04d}")

        mock_client.chat.side_effect = make_resp
        mock_client.chat_stateful.side_effect = make_resp

        conv = Conversation("thread_conv")
        errors = []

        def send_msg(i):
            try:
                conv.send(f"msg {i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=send_msg, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == []
        # Should have 20 messages (10 user + 10 assistant)
        assert len(conv.messages) == 20

    def test_concurrent_manager_create(self):
        """Multiple threads creating conversations in the same manager."""
        mgr = ConversationManager()
        errors = []

        def create_conv(i):
            try:
                mgr.create(f"conv_{i}", system=f"sys_{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create_conv, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == []
        assert len(mgr.list_conversations()) == 20


# ── Edge cases ────────────────────────────────────────────────────────

class TestEdgeCases:
    """Empty conversations, boundary conditions, unusual inputs."""

    def test_empty_conversation_history(self):
        conv = Conversation("empty")
        assert conv.get_history() == []
        assert conv.turn_count == 0

    def test_empty_conversation_summary(self):
        conv = Conversation("empty_sum")
        s = conv.get_summary()
        assert s["turn_count"] == 0
        assert s["message_count"] == 0
        assert s["synced"] is False

    def test_fork_empty_conversation(self):
        conv = Conversation("empty_fork")
        forked = conv.fork(new_id="forked_empty")
        assert len(forked.messages) == 0

    def test_branch_at_empty_conversation(self):
        conv = Conversation("empty_branch")
        branch = conv.branch_at(1, new_id="b_empty")
        assert branch._server_synced is False

    def test_response_id_history_accumulates(self):
        conv = Conversation("hist")
        conv._response_id_history.append("resp_a")
        conv._response_id_history.append("resp_b")
        conv._response_id_history.append("resp_c")
        assert len(conv._response_id_history) == 3
        assert conv._response_id_history[1] == "resp_b"

    def test_conversation_message_with_empty_content(self):
        msg = ConversationMessage(role="assistant", content="")
        d = msg.to_dict()
        assert d["content"] == ""

    def test_multiple_invalidations_idempotent(self):
        conv = _populated_conversation(n_turns=1)
        conv.invalidate()
        conv.invalidate()
        conv.invalidate()
        assert conv._server_synced is False
        assert conv.response_id is None

    def test_fork_preserves_deep_metadata(self):
        conv = Conversation("meta_conv", system="sys")
        conv.messages.append(ConversationMessage(
            role="assistant", content="hi",
            metadata={"response_id": "resp_deep", "nested": {"a": 1}},
        ))
        forked = conv.fork(new_id="meta_fork")
        # Mutate original metadata
        conv.messages[1].metadata["nested"]["a"] = 999
        # Fork should be independent
        assert forked.messages[1].metadata["nested"]["a"] == 1


# ── Singleton ─────────────────────────────────────────────────────────

class TestSingleton:
    """get_conversation_manager() singleton behaviour."""

    def test_singleton_returns_same_instance(self):
        import engine.lmstudio.conversation as conv_mod
        # Reset singleton for test isolation
        conv_mod._manager_instance = None
        m1 = get_conversation_manager()
        m2 = get_conversation_manager()
        assert m1 is m2
        # Clean up
        conv_mod._manager_instance = None

    def test_singleton_is_conversation_manager(self):
        import engine.lmstudio.conversation as conv_mod
        conv_mod._manager_instance = None
        mgr = get_conversation_manager()
        assert isinstance(mgr, ConversationManager)
        conv_mod._manager_instance = None
