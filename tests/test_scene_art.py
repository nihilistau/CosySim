"""Tests for engine/art/scene_art.py — SceneArtManager.

All external dependencies (requests, Nexus client, ContentGate, config) are
fully mocked.  No network calls or filesystem access occur during the suite.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# Ensure the project root is on sys.path for absolute imports.
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PLACEHOLDER_URL = "/static/img/placeholder.png"


def _iso_now(delta_hours: float = 0.0) -> str:
    """Return an ISO-8601 UTC timestamp offset by *delta_hours*."""
    return (datetime.now(timezone.utc) + timedelta(hours=delta_hours)).isoformat()


def _make_result_dict(
    request_id: str = "abc123",
    url: str = "http://localhost:8188/view?filename=out.png&subfolder=&type=output",
    cached: bool = False,
    nexus_key: str = "portrait:aria:neutral:",
    created_at: str | None = None,
) -> dict:
    """Build a minimal :class:`ArtResult` dictionary for cache entries."""
    return {
        "request_id": request_id,
        "url": url,
        "base64_data": None,
        "cached": cached,
        "generation_ms": 0,
        "nexus_key": nexus_key,
        "created_at": created_at or _iso_now(),
    }


def _mock_config(overrides: dict | None = None) -> MagicMock:
    """Return a MagicMock that mimics :class:`~engine.config.ConfigManager`."""
    defaults = {
        "art.comfyui_url": "http://localhost:8188",
        "art.enabled": True,
        "art.cache_ttl_hours": 24,
        "art.adult_enabled": True,
        "art.timeout": 30,
    }
    if overrides:
        defaults.update(overrides)

    mock = MagicMock()
    mock.get.side_effect = lambda key, default=None: defaults.get(key, default)
    return mock


def _mock_nexus(search_returns: list | None = None) -> MagicMock:
    """Return a mock Nexus client."""
    mock = MagicMock()
    mock.search.return_value = search_returns or []
    mock.add_entry.return_value = "entry-001"
    mock.ask.return_value = {"answer": "slender, silver hair, violet eyes"}
    return mock


def _mock_gate(can_show: bool = True) -> MagicMock:
    """Return a mock ContentGate."""
    mock = MagicMock()
    mock.can_show.return_value = can_show
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the module-level SceneArtManager singleton before each test."""
    import engine.art.scene_art as art_mod
    art_mod._manager_instance = None
    yield
    art_mod._manager_instance = None


@pytest.fixture()
def manager(monkeypatch):
    """Return a fresh SceneArtManager with all externals mocked."""
    nexus = _mock_nexus()
    gate = _mock_gate()
    cfg = _mock_config()

    from engine.art import scene_art as art_mod

    monkeypatch.setattr(art_mod, "_get_nexus", lambda: nexus)
    monkeypatch.setattr(art_mod, "_get_content_gate", lambda: gate)

    with patch("engine.art.scene_art.get_config", return_value=cfg):
        mgr = art_mod.SceneArtManager()

    # Expose mocks for assertions.
    mgr._nexus = nexus
    mgr._gate = gate
    return mgr


# ---------------------------------------------------------------------------
# ArtResult helper tests
# ---------------------------------------------------------------------------


class TestArtResultHelpers:
    """ArtResult serialisation round-trips."""

    def test_to_dict_contains_all_fields(self):
        from engine.art.scene_art import ArtResult

        r = ArtResult(
            request_id="req1",
            url="/img/x.png",
            base64_data=None,
            cached=False,
            generation_ms=500,
            nexus_key="k",
        )
        d = r.to_dict()
        assert d["request_id"] == "req1"
        assert d["url"] == "/img/x.png"
        assert d["cached"] is False

    def test_from_dict_round_trip(self):
        from engine.art.scene_art import ArtResult

        original = ArtResult(
            request_id="req2",
            url="/img/y.png",
            base64_data="abc==",
            cached=True,
            generation_ms=200,
            nexus_key="portrait:char:mood:scene",
        )
        recovered = ArtResult.from_dict(original.to_dict())
        assert recovered.request_id == "req2"
        assert recovered.base64_data == "abc=="
        assert recovered.cached is True


# ---------------------------------------------------------------------------
# Cache tests
# ---------------------------------------------------------------------------


class TestCheckCache:
    """_check_cache logic."""

    def test_cache_hit_returns_result(self, manager):
        cache_key = "portrait:aria:neutral:"
        data = _make_result_dict(nexus_key=cache_key)
        manager._nexus.search.return_value = [
            {"title": f"art:{cache_key}", "content": json.dumps(data)}
        ]

        result = manager._check_cache(cache_key)

        assert result is not None
        assert result.cached is True
        assert result.url == data["url"]

    def test_cache_miss_returns_none(self, manager):
        manager._nexus.search.return_value = []
        assert manager._check_cache("portrait:nobody:sad:") is None

    def test_cache_title_mismatch_returns_none(self, manager):
        """Search may return a fuzzy match with a different title — must be rejected."""
        cache_key = "portrait:aria:neutral:"
        data = _make_result_dict(nexus_key=cache_key)
        # Return an entry with a *different* title.
        manager._nexus.search.return_value = [
            {"title": "art:portrait:other:key", "content": json.dumps(data)}
        ]
        assert manager._check_cache(cache_key) is None

    def test_cache_expiry(self, manager):
        """Entries older than TTL are treated as a miss."""
        cache_key = "portrait:aria:neutral:"
        old_ts = _iso_now(delta_hours=-(manager._cache_ttl_hours + 1))
        data = _make_result_dict(nexus_key=cache_key, created_at=old_ts)
        manager._nexus.search.return_value = [
            {"title": f"art:{cache_key}", "content": json.dumps(data)}
        ]
        assert manager._check_cache(cache_key) is None

    def test_cache_within_ttl_not_expired(self, manager):
        """Entries younger than TTL should be returned."""
        cache_key = "bg:bedroom:night:neutral"
        fresh_ts = _iso_now(delta_hours=-(manager._cache_ttl_hours - 1))
        data = _make_result_dict(nexus_key=cache_key, created_at=fresh_ts)
        manager._nexus.search.return_value = [
            {"title": f"art:{cache_key}", "content": json.dumps(data)}
        ]
        result = manager._check_cache(cache_key)
        assert result is not None

    def test_malformed_json_returns_none(self, manager):
        cache_key = "portrait:broken:neutral:"
        manager._nexus.search.return_value = [
            {"title": f"art:{cache_key}", "content": "not-json{{"}
        ]
        assert manager._check_cache(cache_key) is None

    def test_nexus_exception_returns_none(self, manager):
        manager._nexus.search.side_effect = ConnectionError("Nexus down")
        # Should not raise; silently returns None.
        assert manager._check_cache("any:key") is None


class TestStoreCache:
    """_store_cache persists correctly to Nexus."""

    def test_store_calls_add_entry(self, manager):
        from engine.art.scene_art import ArtResult

        result = ArtResult(
            request_id="r1",
            url="/img/x.png",
            base64_data=None,
            cached=False,
            generation_ms=123,
            nexus_key="",
        )
        manager._store_cache("portrait:aria:neutral:", result)

        manager._nexus.add_entry.assert_called_once()
        kwargs = manager._nexus.add_entry.call_args
        assert kwargs[1]["title"] == "art:portrait:aria:neutral:" or \
               kwargs[0][0] == "art:portrait:aria:neutral:"

    def test_store_nexus_exception_does_not_propagate(self, manager):
        from engine.art.scene_art import ArtResult

        manager._nexus.add_entry.side_effect = RuntimeError("DB full")
        result = ArtResult(
            request_id="r2", url="/img/x.png", base64_data=None,
            cached=False, generation_ms=0, nexus_key="",
        )
        # Must not raise.
        manager._store_cache("some:key", result)


# ---------------------------------------------------------------------------
# _generate tests
# ---------------------------------------------------------------------------


class TestGenerate:
    """_generate posts to ComfyUI and polls history."""

    def _comfy_post_mock(self, prompt_id: str = "pid-001"):
        """Return a mock for requests.post that returns a prompt_id."""
        post_mock = MagicMock()
        post_mock.return_value.json.return_value = {"prompt_id": prompt_id}
        post_mock.return_value.raise_for_status = MagicMock()
        return post_mock

    def _comfy_history_mock(self, prompt_id: str, filename: str = "out.png"):
        """Return a mock for requests.get that returns a completed history."""
        get_mock = MagicMock()
        get_mock.return_value.raise_for_status = MagicMock()
        get_mock.return_value.json.return_value = {
            prompt_id: {
                "outputs": {
                    "9": {"images": [{"filename": filename, "subfolder": ""}]}
                },
                "status": {"status_str": "success"},
            }
        }
        return get_mock

    def test_generate_disabled_returns_placeholder(self, manager):
        manager._enabled = False
        from engine.art.scene_art import ArtRequest, ArtStyle

        req = ArtRequest(id="r1", style=ArtStyle.PORTRAIT, prompt="test")
        result = manager._generate(req)

        assert result.url == _PLACEHOLDER_URL
        assert result.cached is False
        assert result.generation_ms == 0

    def test_generate_posts_to_comfyui(self, manager):
        from engine.art.scene_art import ArtRequest, ArtStyle

        pid = "pid-test-001"
        post_mock = self._comfy_post_mock(pid)
        get_mock = self._comfy_history_mock(pid)

        with patch("engine.art.scene_art.requests.post", post_mock), \
             patch("engine.art.scene_art.requests.get", get_mock):
            req = ArtRequest(id="r1", style=ArtStyle.PORTRAIT, prompt="test portrait")
            manager._generate(req)

        post_mock.assert_called_once()
        call_args = post_mock.call_args
        url_called = call_args[0][0]
        assert url_called == "http://localhost:8188/prompt"
        payload = call_args[1]["json"]
        assert "prompt" in payload
        assert payload["client_id"] == "cosysim"

    def test_generate_polls_history(self, manager):
        from engine.art.scene_art import ArtRequest, ArtStyle

        pid = "pid-hist-001"
        post_mock = self._comfy_post_mock(pid)
        get_mock = self._comfy_history_mock(pid)

        with patch("engine.art.scene_art.requests.post", post_mock), \
             patch("engine.art.scene_art.requests.get", get_mock):
            req = ArtRequest(id="r2", style=ArtStyle.SCENE_BG, prompt="bedroom")
            result = manager._generate(req)

        # history endpoint must have been polled
        get_mock.assert_called()
        history_url = get_mock.call_args[0][0]
        assert pid in history_url
        assert result.url.endswith("out.png&subfolder=&type=output")

    def test_generate_workflow_contains_prompt(self, manager):
        """Verify the positive CLIP node carries the request prompt text."""
        from engine.art.scene_art import ArtRequest, ArtStyle

        pid = "pid-wf-001"
        captured = {}

        def capture_post(url, json=None, timeout=None):
            captured["payload"] = json
            m = MagicMock()
            m.json.return_value = {"prompt_id": pid}
            m.raise_for_status = MagicMock()
            return m

        get_mock = self._comfy_history_mock(pid)
        with patch("engine.art.scene_art.requests.post", side_effect=capture_post), \
             patch("engine.art.scene_art.requests.get", get_mock):
            req = ArtRequest(id="r3", style=ArtStyle.PORTRAIT, prompt="violet eyes")
            manager._generate(req)

        workflow = captured["payload"]["prompt"]
        assert workflow["6"]["inputs"]["text"] == "violet eyes"

    def test_generate_uses_random_seed_when_minus_one(self, manager):
        """seed=-1 must produce a random seed in the workflow."""
        from engine.art.scene_art import ArtRequest, ArtStyle

        pid = "pid-seed-001"
        captured = {}

        def capture_post(url, json=None, timeout=None):
            captured["payload"] = json
            m = MagicMock()
            m.json.return_value = {"prompt_id": pid}
            m.raise_for_status = MagicMock()
            return m

        get_mock = self._comfy_history_mock(pid)
        with patch("engine.art.scene_art.requests.post", side_effect=capture_post), \
             patch("engine.art.scene_art.requests.get", get_mock):
            req = ArtRequest(id="r4", style=ArtStyle.PORTRAIT, prompt="test", seed=-1)
            manager._generate(req)

        seed_used = captured["payload"]["prompt"]["3"]["inputs"]["seed"]
        assert isinstance(seed_used, int)
        assert seed_used >= 0

    def test_generate_timeout_raises(self, manager):
        """_poll_history must raise TimeoutError if job never completes."""
        from engine.art.scene_art import ArtRequest, ArtStyle

        pid = "pid-timeout"
        post_mock = self._comfy_post_mock(pid)

        # History always returns an empty object (job not finished).
        get_mock = MagicMock()
        get_mock.return_value.raise_for_status = MagicMock()
        get_mock.return_value.json.return_value = {}

        with patch("engine.art.scene_art.requests.post", post_mock), \
             patch("engine.art.scene_art.requests.get", get_mock), \
             patch("engine.art.scene_art.time.sleep"):  # skip real sleeps
            req = ArtRequest(id="r5", style=ArtStyle.PORTRAIT, prompt="test")
            with pytest.raises(TimeoutError):
                manager._poll_history(pid, req.id, max_wait=0.01)


# ---------------------------------------------------------------------------
# Adult gating tests
# ---------------------------------------------------------------------------


class TestAdultGating:
    """ContentGate integration in prompt building."""

    def _generate_stub(self, manager, request):
        """Replace _generate with a no-op that returns a dummy ArtResult."""
        from engine.art.scene_art import ArtResult
        return ArtResult(
            request_id=request.id,
            url="/img/gen.png",
            base64_data=None,
            cached=False,
            generation_ms=10,
            nexus_key="",
        )

    def test_adult_gating_adds_prompt_when_enabled(self, manager):
        """Adult-allowed + adult_enabled should append adult additions to portrait prompt."""
        manager._gate.can_show.return_value = True
        manager._adult_enabled = True

        captured_req = {}

        def fake_generate(req):
            captured_req["req"] = req
            return self._generate_stub(manager, req)

        manager._nexus.search.return_value = []  # cache miss
        manager._generate = fake_generate

        manager.get_character_portrait("aria", mood="seductive")

        prompt = captured_req["req"].prompt
        assert any(kw in prompt for kw in ("sensual", "alluring", "elegant"))

    def test_adult_gating_skips_when_gate_disabled(self, manager):
        """When ContentGate blocks adult content, additions must not appear."""
        manager._gate.can_show.return_value = False
        manager._adult_enabled = True

        captured_req = {}

        def fake_generate(req):
            captured_req["req"] = req
            return self._generate_stub(manager, req)

        manager._nexus.search.return_value = []
        manager._generate = fake_generate

        manager.get_character_portrait("aria", mood="seductive")

        prompt = captured_req["req"].prompt
        negative = captured_req["req"].negative_prompt
        # Adult keywords must NOT be present.
        assert "sensual" not in prompt
        # Default negative must be retained.
        assert "nsfw" in negative

    def test_adult_gating_skips_when_config_disabled(self, manager):
        """art.adult_enabled=False prevents adult additions regardless of ContentGate."""
        manager._gate.can_show.return_value = True
        manager._adult_enabled = False  # config override

        captured_req = {}

        def fake_generate(req):
            captured_req["req"] = req
            return self._generate_stub(manager, req)

        manager._nexus.search.return_value = []
        manager._generate = fake_generate

        manager.get_character_portrait("aria", mood="seductive")
        prompt = captured_req["req"].prompt
        assert "sensual" not in prompt

    def test_action_card_adult_gate_intensity_two(self, manager):
        """Action card intensity >= 2 + adult allowed adds explicit additions."""
        manager._gate.can_show.return_value = True
        manager._adult_enabled = True

        captured_req = {}

        def fake_generate(req):
            captured_req["req"] = req
            return self._generate_stub(manager, req)

        manager._generate = fake_generate
        manager.get_action_card("two lovers embrace", intensity=2)

        assert "explicit" in captured_req["req"].prompt or \
               "uncensored" in captured_req["req"].prompt

    def test_action_card_adult_gate_intensity_one_no_additions(self, manager):
        """Action card intensity=1 must not add explicit content."""
        manager._gate.can_show.return_value = True
        manager._adult_enabled = True

        captured_req = {}

        def fake_generate(req):
            captured_req["req"] = req
            return self._generate_stub(manager, req)

        manager._generate = fake_generate
        manager.get_action_card("sword fight", intensity=1)

        assert "explicit" not in captured_req["req"].prompt
        assert "uncensored" not in captured_req["req"].prompt


# ---------------------------------------------------------------------------
# get_character_portrait tests
# ---------------------------------------------------------------------------


class TestGetCharacterPortrait:
    """Cache-hit / cache-miss flow for character portraits."""

    def test_cache_hit_skips_generation(self, manager):
        """Cache hit must not trigger a Nexus ask or _generate call."""
        cache_key = "portrait:aria:neutral:"
        cached_data = _make_result_dict(nexus_key=cache_key)
        manager._nexus.search.return_value = [
            {"title": f"art:{cache_key}", "content": json.dumps(cached_data)}
        ]

        generate_mock = MagicMock()
        manager._generate = generate_mock

        result = manager.get_character_portrait("aria")

        generate_mock.assert_not_called()
        manager._nexus.ask.assert_not_called()
        assert result.cached is True

    def test_cache_miss_calls_nexus_ask(self, manager):
        """Cache miss must query Nexus for character appearance."""
        manager._nexus.search.return_value = []  # miss

        pid = "pid-portrait"
        post_mock = MagicMock()
        post_mock.return_value.json.return_value = {"prompt_id": pid}
        post_mock.return_value.raise_for_status = MagicMock()
        get_mock = MagicMock()
        get_mock.return_value.raise_for_status = MagicMock()
        get_mock.return_value.json.return_value = {
            pid: {"outputs": {"9": {"images": [{"filename": "p.png", "subfolder": ""}]}}}
        }

        with patch("engine.art.scene_art.requests.post", post_mock), \
             patch("engine.art.scene_art.requests.get", get_mock):
            manager.get_character_portrait("aria", mood="shy")

        manager._nexus.ask.assert_called_once()
        question = manager._nexus.ask.call_args[0][0]
        assert "aria" in question
        assert "shy" in question

    def test_cache_miss_stores_result(self, manager):
        """After generation the result must be persisted to Nexus."""
        manager._nexus.search.return_value = []

        pid = "pid-store"
        post_mock = MagicMock()
        post_mock.return_value.json.return_value = {"prompt_id": pid}
        post_mock.return_value.raise_for_status = MagicMock()
        get_mock = MagicMock()
        get_mock.return_value.raise_for_status = MagicMock()
        get_mock.return_value.json.return_value = {
            pid: {"outputs": {"9": {"images": [{"filename": "p.png", "subfolder": ""}]}}}
        }

        with patch("engine.art.scene_art.requests.post", post_mock), \
             patch("engine.art.scene_art.requests.get", get_mock):
            manager.get_character_portrait("aria")

        manager._nexus.add_entry.assert_called_once()

    def test_portrait_includes_scene_context(self, manager):
        """Portrait prompt should include scene-specific background keywords when scene is given."""
        manager._nexus.search.return_value = []

        captured = {}
        def fake_gen(req):
            captured["req"] = req
            from engine.art.scene_art import ArtResult
            return ArtResult(request_id=req.id, url="/img/x.png",
                             base64_data=None, cached=False,
                             generation_ms=0, nexus_key="")

        manager._generate = fake_gen
        manager.get_character_portrait("aria", scene="bedroom")

        assert "bedroom" in captured["req"].prompt or "penthouse" in captured["req"].prompt


# ---------------------------------------------------------------------------
# get_scene_bg tests
# ---------------------------------------------------------------------------


class TestGetSceneBg:
    """Scene background art generation."""

    def _make_gen_stub(self, manager):
        captured = {}

        from engine.art.scene_art import ArtResult

        def fake_gen(req):
            captured["req"] = req
            return ArtResult(request_id=req.id, url="/img/bg.png",
                             base64_data=None, cached=False,
                             generation_ms=0, nexus_key="")

        manager._generate = fake_gen
        return captured

    def test_get_scene_bg_known_scene(self, manager):
        """Known scene slug should produce a prompt with scene-specific keywords."""
        manager._nexus.search.return_value = []
        captured = self._make_gen_stub(manager)

        manager.get_scene_bg("bedroom", time_of_day="night", mood="romantic")

        prompt = captured["req"].prompt
        assert "penthouse" in prompt or "bedroom" in prompt

    def test_get_scene_bg_unknown_scene_fallback(self, manager):
        """Unknown scene slug must use the default prompt without raising."""
        manager._nexus.search.return_value = []
        captured = self._make_gen_stub(manager)

        manager.get_scene_bg("dungeon", time_of_day="midnight", mood="dangerous")

        prompt = captured["req"].prompt
        # Fallback default phrase
        assert "dark atmospheric" in prompt

    def test_get_scene_bg_uses_wide_resolution(self, manager):
        """Scene backgrounds must use 1024×576."""
        manager._nexus.search.return_value = []
        captured = self._make_gen_stub(manager)

        manager.get_scene_bg("casino")

        assert captured["req"].width == 1024
        assert captured["req"].height == 576

    def test_get_scene_bg_cache_hit(self, manager):
        """Cache hit must skip generation."""
        cache_key = "bg:tavern:night:tense"
        data = _make_result_dict(nexus_key=cache_key)
        manager._nexus.search.return_value = [
            {"title": f"art:{cache_key}", "content": json.dumps(data)}
        ]
        gen_mock = MagicMock()
        manager._generate = gen_mock

        result = manager.get_scene_bg("tavern", time_of_day="night", mood="tense")

        gen_mock.assert_not_called()
        assert result.cached is True

    def test_get_scene_bg_time_modifier_in_prompt(self, manager):
        """time_of_day modifier must be blended into the prompt."""
        manager._nexus.search.return_value = []
        captured = self._make_gen_stub(manager)

        manager.get_scene_bg("arena", time_of_day="dawn")

        assert "golden" in captured["req"].prompt or "dawn" in captured["req"].prompt


# ---------------------------------------------------------------------------
# get_action_card tests
# ---------------------------------------------------------------------------


class TestGetActionCard:
    """Action card generation — never cached."""

    def test_get_action_card_no_cache(self, manager):
        """Action cards must never read from or write to cache."""
        pid = "pid-ac-001"
        post_mock = MagicMock()
        post_mock.return_value.json.return_value = {"prompt_id": pid}
        post_mock.return_value.raise_for_status = MagicMock()
        get_mock = MagicMock()
        get_mock.return_value.raise_for_status = MagicMock()
        get_mock.return_value.json.return_value = {
            pid: {"outputs": {"9": {"images": [{"filename": "ac.png", "subfolder": ""}]}}}
        }

        with patch("engine.art.scene_art.requests.post", post_mock), \
             patch("engine.art.scene_art.requests.get", get_mock):
            manager.get_action_card("hero leaps over the chasm")

        # No cache reads or writes.
        manager._nexus.search.assert_not_called()
        manager._nexus.add_entry.assert_not_called()

    def test_get_action_card_uses_512x512(self, manager):
        """Action cards must use 512×512 dimensions."""
        captured = {}

        from engine.art.scene_art import ArtResult

        def fake_gen(req):
            captured["req"] = req
            return ArtResult(request_id=req.id, url="/img/ac.png",
                             base64_data=None, cached=False,
                             generation_ms=0, nexus_key="")

        manager._generate = fake_gen
        manager.get_action_card("a duel at dusk")

        assert captured["req"].width == 512
        assert captured["req"].height == 512

    def test_get_action_card_description_in_prompt(self, manager):
        """The user-supplied description must appear in the generated prompt."""
        captured = {}

        from engine.art.scene_art import ArtResult

        def fake_gen(req):
            captured["req"] = req
            return ArtResult(request_id=req.id, url="/img/ac.png",
                             base64_data=None, cached=False,
                             generation_ms=0, nexus_key="")

        manager._generate = fake_gen
        manager.get_action_card("villain reveals the mask")

        assert "villain reveals the mask" in captured["req"].prompt


# ---------------------------------------------------------------------------
# Singleton test
# ---------------------------------------------------------------------------


class TestSingleton:
    """get_scene_art_manager returns the same instance across calls."""

    def test_singleton(self, monkeypatch):
        from engine.art import scene_art as art_mod

        cfg = _mock_config()
        nexus = _mock_nexus()
        gate = _mock_gate()

        monkeypatch.setattr(art_mod, "_get_nexus", lambda: nexus)
        monkeypatch.setattr(art_mod, "_get_content_gate", lambda: gate)

        with patch("engine.art.scene_art.get_config", return_value=cfg):
            a = art_mod.get_scene_art_manager()
            b = art_mod.get_scene_art_manager()

        assert a is b

    def test_singleton_thread_safety(self, monkeypatch):
        """Concurrent calls to get_scene_art_manager must return the same instance."""
        import threading

        from engine.art import scene_art as art_mod

        cfg = _mock_config()
        nexus = _mock_nexus()
        gate = _mock_gate()

        monkeypatch.setattr(art_mod, "_get_nexus", lambda: nexus)
        monkeypatch.setattr(art_mod, "_get_content_gate", lambda: gate)

        results = []

        def _get():
            with patch("engine.art.scene_art.get_config", return_value=cfg):
                results.append(art_mod.get_scene_art_manager())

        threads = [threading.Thread(target=_get) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(set(id(r) for r in results)) == 1
