"""
Tests for content.simulation.database.db — full CRUD coverage.

Every table (characters, personalities, roles, memories, conversations,
interactions, media, character_states) gets create/read/update/delete tests
plus count/search/pagination helpers.
"""
import json
import pytest
from content.simulation.database.db import Database


@pytest.fixture
def db(tmp_path):
    """Fresh database per test."""
    return Database(str(tmp_path / "test.db"))


# ─── helpers ───────────────────────────────────────────────────────────

def _make_personality(db: Database, name="Test Personality") -> str:
    return db.create_personality(
        name=name,
        system_prompt="You are helpful.",
        traits=["kind"],
        warmth=0.8,
    )


def _make_character(db: Database, name="Luna", personality_id=None) -> str:
    return db.create_character(
        name=name, age=22, sex="female",
        personality_id=personality_id,
    )


# ═══════════════════════════════════════════════════════════════════════
#  CHARACTER CRUD
# ═══════════════════════════════════════════════════════════════════════

class TestCharacters:
    def test_create_and_get(self, db):
        cid = _make_character(db)
        char = db.get_character(cid)
        assert char is not None
        assert char["name"] == "Luna"
        assert char["age"] == 22

    def test_get_all(self, db):
        baseline = len(db.get_all_characters())  # seeded characters
        _make_character(db, "A")
        _make_character(db, "B")
        assert len(db.get_all_characters()) == baseline + 2

    def test_update(self, db):
        cid = _make_character(db)
        assert db.update_character(cid, name="Nova")
        assert db.get_character(cid)["name"] == "Nova"

    def test_update_rejects_bad_column(self, db):
        cid = _make_character(db)
        with pytest.raises(ValueError, match="Invalid column"):
            db.update_character(cid, evil_col="x")

    def test_delete_cascades(self, db):
        cid = _make_character(db)
        db.add_memory(cid, "test memory")
        db.add_media(cid, "image", "/fake.png")
        assert db.delete_character(cid)
        assert db.get_character(cid) is None
        assert db.get_character_memories(cid) == []
        assert db.get_character_media(cid) == []

    def test_search(self, db):
        _make_character(db, "Luna Star")
        _make_character(db, "Nova Ray")
        results_luna = db.search_characters("luna")
        assert any(c["name"] == "Luna Star" for c in results_luna)
        results_a = db.search_characters("a")
        # At least the 2 we created (both contain 'a'), plus any seeded chars with 'a'
        assert len(results_a) >= 2

    def test_count(self, db):
        baseline = db.count_characters()  # seeded characters
        _make_character(db)
        assert db.count_characters() == baseline + 1

    def test_personality_seeds_state(self, db):
        pid = _make_personality(db, "Warm")
        cid = _make_character(db, personality_id=pid)
        state = db.get_character_state(cid)
        assert state is not None
        assert state["warmth"] == 0.8  # seeded from personality


# ═══════════════════════════════════════════════════════════════════════
#  PERSONALITY CRUD
# ═══════════════════════════════════════════════════════════════════════

class TestPersonalities:
    def test_create_and_get(self, db):
        pid = _make_personality(db)
        p = db.get_personality(pid)
        assert p["name"] == "Test Personality"
        assert p["traits"] == ["kind"]

    def test_get_by_name(self, db):
        _make_personality(db, "Unique Name")
        p = db.get_personality_by_name("Unique Name")
        assert p is not None

    def test_get_all(self, db):
        baseline = len(db.get_all_personalities())  # seeded personalities
        _make_personality(db, "A")
        _make_personality(db, "B")
        assert len(db.get_all_personalities()) == baseline + 2

    def test_update(self, db):
        pid = _make_personality(db)
        assert db.update_personality(pid, name="Updated")
        assert db.get_personality(pid)["name"] == "Updated"

    def test_update_json_field(self, db):
        pid = _make_personality(db)
        assert db.update_personality(pid, traits=["brave", "loyal"])
        assert db.get_personality(pid)["traits"] == ["brave", "loyal"]

    def test_update_rejects_bad_column(self, db):
        pid = _make_personality(db)
        with pytest.raises(ValueError):
            db.update_personality(pid, bad_col="x")

    def test_delete(self, db):
        pid = _make_personality(db)
        assert db.delete_personality(pid)
        assert db.get_personality(pid) is None

    def test_delete_nonexistent(self, db):
        assert not db.delete_personality("no-such-id")


# ═══════════════════════════════════════════════════════════════════════
#  ROLE CRUD
# ═══════════════════════════════════════════════════════════════════════

class TestRoles:
    def test_create_and_get(self, db):
        rid = db.create_role("Nurse", "A caring nurse", required_traits=["kind"])
        r = db.get_role(rid)
        assert r["name"] == "Nurse"
        assert r["required_traits"] == ["kind"]

    def test_get_all(self, db):
        db.create_role("A", "desc")
        db.create_role("B", "desc")
        assert len(db.get_all_roles()) == 2

    def test_update(self, db):
        rid = db.create_role("Old", "desc")
        assert db.update_role(rid, name="New", description="updated")
        r = db.get_role(rid)
        assert r["name"] == "New"
        assert r["description"] == "updated"

    def test_update_rejects_bad_column(self, db):
        rid = db.create_role("R", "d")
        with pytest.raises(ValueError):
            db.update_role(rid, evil="x")

    def test_delete(self, db):
        rid = db.create_role("R", "d")
        assert db.delete_role(rid)
        assert db.get_role(rid) is None


# ═══════════════════════════════════════════════════════════════════════
#  MEMORY CRUD
# ═══════════════════════════════════════════════════════════════════════

class TestMemories:
    def test_create_and_get(self, db):
        cid = _make_character(db)
        mid = db.add_memory(cid, "She likes cats", importance=0.9)
        mems = db.get_character_memories(cid)
        assert len(mems) == 1
        assert mems[0]["content"] == "She likes cats"
        assert mems[0]["importance"] == 0.9

    def test_update(self, db):
        cid = _make_character(db)
        mid = db.add_memory(cid, "old content")
        assert db.update_memory(mid, content="new content", importance=1.0)
        mems = db.get_character_memories(cid)
        assert mems[0]["content"] == "new content"

    def test_delete(self, db):
        cid = _make_character(db)
        mid = db.add_memory(cid, "temp")
        assert db.delete_memory(mid)
        assert db.get_character_memories(cid) == []

    def test_count(self, db):
        cid = _make_character(db)
        assert db.count_memories(cid) == 0
        db.add_memory(cid, "a")
        db.add_memory(cid, "b")
        assert db.count_memories(cid) == 2
        assert db.count_memories() >= 2  # global count


# ═══════════════════════════════════════════════════════════════════════
#  CONVERSATION CRUD
# ═══════════════════════════════════════════════════════════════════════

class TestConversations:
    def test_create_and_get(self, db):
        cid = _make_character(db)
        cvid = db.create_conversation(cid, "chain-1", messages=[{"role": "user", "text": "hi"}])
        conv = db.get_conversation(cvid)
        assert conv is not None
        assert conv["chain_id"] == "chain-1"
        assert len(conv["messages"]) == 1

    def test_update_messages(self, db):
        cid = _make_character(db)
        cvid = db.create_conversation(cid, "c1")
        msgs = [{"role": "user", "text": "hello"}, {"role": "assistant", "text": "hi"}]
        assert db.update_conversation(cvid, msgs)
        assert len(db.get_conversation(cvid)["messages"]) == 2

    def test_update_ended(self, db):
        cid = _make_character(db)
        cvid = db.create_conversation(cid, "c1")
        db.update_conversation(cvid, [], ended=True)
        conv = db.get_conversation(cvid)
        assert conv["ended_at"] is not None

    def test_get_character_conversations(self, db):
        cid = _make_character(db)
        db.create_conversation(cid, "c1")
        db.create_conversation(cid, "c2")
        assert len(db.get_character_conversations(cid)) == 2

    def test_delete(self, db):
        cid = _make_character(db)
        cvid = db.create_conversation(cid, "c1")
        assert db.delete_conversation(cvid)
        assert db.get_conversation(cvid) is None

    def test_delete_character_conversations(self, db):
        cid = _make_character(db)
        db.create_conversation(cid, "c1")
        db.create_conversation(cid, "c2")
        assert db.delete_character_conversations(cid) == 2

    def test_count(self, db):
        cid = _make_character(db)
        db.create_conversation(cid, "c1")
        assert db.count_conversations(cid) == 1
        assert db.count_conversations() >= 1

    def test_pagination(self, db):
        cid = _make_character(db)
        for i in range(5):
            db.create_conversation(cid, f"c{i}")
        page, total = db.get_conversations_paginated(cid, offset=0, limit=2)
        assert len(page) == 2
        assert total == 5
        page2, _ = db.get_conversations_paginated(cid, offset=2, limit=2)
        assert len(page2) == 2


# ═══════════════════════════════════════════════════════════════════════
#  INTERACTION CRUD
# ═══════════════════════════════════════════════════════════════════════

class TestInteractions:
    def test_log_and_get_chain(self, db):
        cid = _make_character(db)
        db.log_interaction("message", cid, "hello", chain_id="ch1")
        db.log_interaction("response", cid, "hi there", chain_id="ch1")
        chain = db.get_interaction_chain("ch1")
        assert len(chain) == 2

    def test_get_character_interactions(self, db):
        cid = _make_character(db)
        db.log_interaction("msg", cid, "a")
        db.log_interaction("media", cid, "b")
        assert len(db.get_character_interactions(cid)) == 2
        assert len(db.get_character_interactions(cid, interaction_type="msg")) == 1

    def test_delete_single(self, db):
        cid = _make_character(db)
        iid = db.log_interaction("msg", cid, "temp")
        assert db.delete_interaction(iid)
        assert db.get_character_interactions(cid) == []

    def test_delete_chain(self, db):
        cid = _make_character(db)
        db.log_interaction("a", cid, "1", chain_id="ch")
        db.log_interaction("b", cid, "2", chain_id="ch")
        assert db.delete_interaction_chain("ch") == 2

    def test_count(self, db):
        cid = _make_character(db)
        db.log_interaction("a", cid, "x")
        assert db.count_interactions(cid) == 1
        assert db.count_interactions() >= 1


# ═══════════════════════════════════════════════════════════════════════
#  MEDIA CRUD
# ═══════════════════════════════════════════════════════════════════════

class TestMedia:
    def test_add_and_get(self, db):
        cid = _make_character(db)
        mid = db.add_media(cid, "image", "/img.png", metadata={"prompt": "test"})
        media = db.get_character_media(cid)
        assert len(media) == 1
        assert media[0]["filepath"] == "/img.png"
        assert media[0]["metadata"]["prompt"] == "test"

    def test_get_single(self, db):
        cid = _make_character(db)
        mid = db.add_media(cid, "image", "/img.png")
        m = db.get_media(mid)
        assert m is not None
        assert m["type"] == "image"

    def test_filter_by_type(self, db):
        cid = _make_character(db)
        db.add_media(cid, "image", "/a.png")
        db.add_media(cid, "video", "/b.mp4")
        assert len(db.get_character_media(cid, "image")) == 1

    def test_update(self, db):
        cid = _make_character(db)
        mid = db.add_media(cid, "image", "/old.png")
        assert db.update_media(mid, filepath="/new.png", metadata={"edited": True})
        m = db.get_media(mid)
        assert m["filepath"] == "/new.png"
        assert m["metadata"]["edited"] is True

    def test_update_rejects_bad_column(self, db):
        cid = _make_character(db)
        mid = db.add_media(cid, "image", "/x.png")
        with pytest.raises(ValueError):
            db.update_media(mid, evil="x")

    def test_delete_single(self, db):
        cid = _make_character(db)
        mid = db.add_media(cid, "image", "/x.png")
        assert db.delete_media(mid)
        assert db.get_media(mid) is None

    def test_delete_character_media(self, db):
        cid = _make_character(db)
        db.add_media(cid, "image", "/a.png")
        db.add_media(cid, "video", "/b.mp4")
        assert db.delete_character_media(cid, "image") == 1
        assert len(db.get_character_media(cid)) == 1  # video remains

    def test_delete_all_character_media(self, db):
        cid = _make_character(db)
        db.add_media(cid, "image", "/a.png")
        db.add_media(cid, "video", "/b.mp4")
        assert db.delete_character_media(cid) == 2

    def test_count(self, db):
        cid = _make_character(db)
        db.add_media(cid, "image", "/a.png")
        db.add_media(cid, "video", "/b.mp4")
        assert db.count_media(cid) == 2
        assert db.count_media(cid, "image") == 1
        assert db.count_media() >= 2

    def test_pagination(self, db):
        cid = _make_character(db)
        for i in range(5):
            db.add_media(cid, "image", f"/{i}.png")
        page, total = db.get_media_paginated(cid, offset=0, limit=2)
        assert len(page) == 2
        assert total == 5


# ═══════════════════════════════════════════════════════════════════════
#  CHARACTER STATE CRUD
# ═══════════════════════════════════════════════════════════════════════

class TestCharacterState:
    def test_created_with_character(self, db):
        cid = _make_character(db)
        state = db.get_character_state(cid)
        assert state is not None
        assert state["warmth"] == 0.5  # default

    def test_update(self, db):
        cid = _make_character(db)
        assert db.update_character_state(cid, mood="happy", energy=0.9)
        state = db.get_character_state(cid)
        assert state["mood"] == "happy"
        assert state["energy"] == 0.9

    def test_update_rejects_bad_column(self, db):
        cid = _make_character(db)
        with pytest.raises(ValueError):
            db.update_character_state(cid, evil="x")

    def test_delete(self, db):
        cid = _make_character(db)
        assert db.delete_character_state(cid)
        assert db.get_character_state(cid) is None


# ═══════════════════════════════════════════════════════════════════════
#  CHARACTER RELATIONSHIPS
# ═══════════════════════════════════════════════════════════════════════

class TestRelationships:
    def _pair(self, db):
        a = _make_character(db, "Alice")
        b = _make_character(db, "Bob")
        return a, b

    def test_create_and_get(self, db):
        a, b = self._pair(db)
        rid = db.create_relationship(a, b, trust=0.7)
        assert rid
        rel = db.get_relationship(a, b)
        assert rel is not None
        assert rel["trust"] == 0.7

    def test_order_independent(self, db):
        a, b = self._pair(db)
        db.create_relationship(a, b, attraction=0.9)
        assert db.get_relationship(b, a)["attraction"] == 0.9

    def test_defaults(self, db):
        a, b = self._pair(db)
        db.create_relationship(a, b)
        rel = db.get_relationship(a, b)
        assert rel["relationship_level"] == 0.5
        assert rel["arousal_a"] == 0.0

    def test_update(self, db):
        a, b = self._pair(db)
        db.create_relationship(a, b)
        assert db.update_relationship(a, b, trust=0.9, arousal_a=0.3)
        rel = db.get_relationship(a, b)
        assert rel["trust"] == 0.9
        assert rel["arousal_a"] == 0.3

    def test_update_nonexistent_returns_false(self, db):
        assert not db.update_relationship("x", "y", trust=0.5)

    def test_update_bad_field_ignored(self, db):
        a, b = self._pair(db)
        db.create_relationship(a, b)
        assert not db.update_relationship(a, b, badfield=1)

    def test_get_or_create(self, db):
        a, b = self._pair(db)
        rel = db.get_or_create_relationship(a, b, trust=0.8)
        assert rel["trust"] == 0.8
        rel2 = db.get_or_create_relationship(a, b, trust=0.1)
        assert rel2["trust"] == 0.8  # not overwritten

    def test_list_relationships(self, db):
        a, b = self._pair(db)
        c = _make_character(db, "Charlie")
        db.create_relationship(a, b)
        db.create_relationship(a, c)
        rels = db.list_relationships(a)
        assert len(rels) == 2

    def test_list_empty(self, db):
        a = _make_character(db, "Alice")
        assert db.list_relationships(a) == []

    def test_delete_relationship(self, db):
        a, b = self._pair(db)
        db.create_relationship(a, b)
        assert db.delete_relationship(a, b)
        assert db.get_relationship(a, b) is None

    def test_delete_nonexistent(self, db):
        assert not db.delete_relationship("x", "y")

    def test_metadata_roundtrip(self, db):
        a, b = self._pair(db)
        db.create_relationship(a, b, metadata={"history": ["met at bar"]})
        rel = db.get_relationship(a, b)
        assert rel["metadata"]["history"] == ["met at bar"]

    def test_update_metadata(self, db):
        a, b = self._pair(db)
        db.create_relationship(a, b)
        db.update_relationship(a, b, metadata={"note": "close"})
        rel = db.get_relationship(a, b)
        assert rel["metadata"]["note"] == "close"

    def test_duplicate_create_ignored(self, db):
        a, b = self._pair(db)
        db.create_relationship(a, b, trust=0.3)
        db.create_relationship(a, b, trust=0.9)  # INSERT OR IGNORE
        rel = db.get_relationship(a, b)
        assert rel["trust"] == 0.3  # first wins
