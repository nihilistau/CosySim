"""
Tests for the EventChain system — the ground truth of CosySim.

If these tests fail, nothing else matters.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestStartChain:
    """Starting a chain creates a root event."""

    def test_returns_uuid_string(self, event_chain):
        chain_id = event_chain.start_chain("phone")
        assert isinstance(chain_id, str)
        assert len(chain_id) == 36  # UUID format

    def test_chain_has_root_event(self, event_chain):
        chain_id = event_chain.start_chain("phone", summary="Test chain")
        events = event_chain.get_chain(chain_id)
        assert len(events) == 1
        assert events[0]["event_type"] == "scene_state_change"
        assert events[0]["summary"] == "Test chain"


class TestLog:
    """Logging events into an existing chain."""

    def test_log_returns_event_id(self, event_chain):
        chain_id = event_chain.start_chain("phone")
        ev_id = event_chain.log(
            "message_in", actor="user",
            payload={"content": "hello"},
            chain_id=chain_id, scene_id="phone",
        )
        assert isinstance(ev_id, str)
        assert len(ev_id) == 36

    def test_events_in_chain_order(self, event_chain):
        chain_id = event_chain.start_chain("phone")
        event_chain.log("message_in", actor="user",
                        payload={"text": "hi"}, chain_id=chain_id)
        event_chain.log("llm_request", actor="llm",
                        payload={"model": "test"}, chain_id=chain_id)
        event_chain.log("llm_response", actor="agent",
                        payload={"text": "hey"}, chain_id=chain_id)

        events = event_chain.get_chain(chain_id)
        types = [e["event_type"] for e in events]
        assert types == [
            "scene_state_change",  # root from start_chain
            "message_in",
            "llm_request",
            "llm_response",
        ]

    def test_parent_id_stored(self, event_chain):
        chain_id = event_chain.start_chain("phone")
        parent = event_chain.log("message_in", actor="user",
                                 payload={}, chain_id=chain_id)
        child = event_chain.log("llm_request", actor="llm",
                                payload={}, chain_id=chain_id,
                                parent_id=parent)

        ev = event_chain.get_event(child)
        assert ev["parent_id"] == parent

    def test_orphan_chain_auto_generated(self, event_chain):
        """Logging without chain_id auto-generates one."""
        ev_id = event_chain.log("error", actor="system", payload={"msg": "oops"})
        ev = event_chain.get_event(ev_id)
        assert ev["chain_id"] is not None

    def test_payload_serialized_as_json(self, event_chain):
        chain_id = event_chain.start_chain("test")
        event_chain.log("message_in", actor="user",
                        payload={"nested": {"key": [1, 2, 3]}},
                        chain_id=chain_id)
        events = event_chain.get_chain(chain_id)
        # payload should be deserialized back to dict
        msg_ev = [e for e in events if e["event_type"] == "message_in"][0]
        assert msg_ev["payload"]["nested"]["key"] == [1, 2, 3]


class TestLogError:
    """Convenience error logging."""

    def test_captures_exception_type(self, event_chain):
        chain_id = event_chain.start_chain("test")
        try:
            raise ValueError("test error")
        except ValueError as e:
            ev_id = event_chain.log_error(e, chain_id=chain_id)

        ev = event_chain.get_event(ev_id)
        assert ev["event_type"] == "error"
        assert ev["payload"]["error_type"] == "ValueError"
        assert "test error" in ev["payload"]["message"]


class TestGetChainAsTree:
    """Tree reconstruction from parent_id edges."""

    def test_single_root(self, event_chain):
        chain_id = event_chain.start_chain("phone")
        tree = event_chain.get_chain_as_tree(chain_id)
        assert tree["chain_id"] == chain_id
        assert len(tree["events"]) == 1  # root only

    def test_nested_children(self, event_chain):
        chain_id = event_chain.start_chain("phone")
        root_events = event_chain.get_chain(chain_id)
        root_id = root_events[0]["id"]

        msg_in = event_chain.log("message_in", actor="user",
                                 payload={}, chain_id=chain_id,
                                 parent_id=root_id)
        llm_req = event_chain.log("llm_request", actor="llm",
                                  payload={}, chain_id=chain_id,
                                  parent_id=msg_in)
        event_chain.log("llm_response", actor="agent",
                        payload={}, chain_id=chain_id,
                        parent_id=llm_req)

        tree = event_chain.get_chain_as_tree(chain_id)
        root = tree["events"][0]
        assert root["event_type"] == "scene_state_change"
        assert len(root["children"]) == 1

        msg_node = root["children"][0]
        assert msg_node["event_type"] == "message_in"
        assert len(msg_node["children"]) == 1

        llm_node = msg_node["children"][0]
        assert llm_node["event_type"] == "llm_request"
        assert len(llm_node["children"]) == 1
        assert llm_node["children"][0]["event_type"] == "llm_response"


class TestGetRecentChains:
    """Recent chains summary query."""

    def test_returns_chains(self, event_chain):
        event_chain.start_chain("phone", summary="Chain A")
        event_chain.start_chain("phone", summary="Chain B")

        chains = event_chain.get_recent_chains(limit=10)
        assert len(chains) >= 2

    def test_scene_filter(self, event_chain):
        event_chain.start_chain("phone", summary="Phone chain")
        event_chain.start_chain("penthouse", summary="Bedroom chain")

        phone_chains = event_chain.get_recent_chains(scene_id="phone")
        for c in phone_chains:
            assert c["scene_id"] == "phone"
