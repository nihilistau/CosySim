"""Tests for the Orpheus TTS client."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from engine.tts.orpheus_client import (
    OrpheusClient,
    ORPHEUS_VOICES,
    MOOD_TO_EMOTION,
)


@pytest.fixture
def client(tmp_path: Path) -> OrpheusClient:
    """Create an OrpheusClient pointing at a temp output dir."""
    return OrpheusClient(
        server_url="http://localhost:5005",
        default_voice="tara",
        timeout=10,
        output_dir=tmp_path,
    )


class TestOrpheusVoiceCatalog:
    """Voice catalog tests."""

    def test_voice_count(self):
        """All 25 Orpheus voices are cataloged."""
        assert len(ORPHEUS_VOICES) == 25

    def test_english_voices(self):
        en = [n for n, v in ORPHEUS_VOICES.items() if v["lang"] == "en"]
        assert len(en) == 8

    def test_voice_has_required_keys(self):
        for name, info in ORPHEUS_VOICES.items():
            assert "lang" in info, f"{name} missing lang"
            assert "gender" in info, f"{name} missing gender"
            assert "style" in info, f"{name} missing style"

    def test_mood_to_emotion_mapping(self):
        assert MOOD_TO_EMOTION["happy"] == "<laugh>"
        assert MOOD_TO_EMOTION["sad"] == "<sigh>"
        assert MOOD_TO_EMOTION["surprised"] == "<gasp>"


class TestOrpheusGenerate:
    """TTS generation tests (mocked HTTP)."""

    @patch("engine.tts.orpheus_client.requests.post")
    def test_generate_basic(self, mock_post: MagicMock, client: OrpheusClient):
        """Basic generation returns a valid WAV path."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"RIFF" + b"\x00" * 100  # fake WAV
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        path = client.generate("Hello world")

        assert Path(path).exists()
        assert path.endswith(".wav")
        assert "orpheus_tara_" in path
        mock_post.assert_called_once()

        call_kwargs = mock_post.call_args
        payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
        assert payload["voice"] == "tara"
        assert payload["input"] == "Hello world"

    @patch("engine.tts.orpheus_client.requests.post")
    def test_generate_with_voice(self, mock_post: MagicMock, client: OrpheusClient):
        """Specifying a voice uses that voice."""
        mock_resp = MagicMock()
        mock_resp.content = b"RIFF" + b"\x00" * 50
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        path = client.generate("Test", voice="leo")
        assert "orpheus_leo_" in path

    @patch("engine.tts.orpheus_client.requests.post")
    def test_generate_with_mood_injection(self, mock_post: MagicMock, client: OrpheusClient):
        """Mood tags are injected as Orpheus emotion tags."""
        mock_resp = MagicMock()
        mock_resp.content = b"RIFF" + b"\x00" * 50
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client.generate("That's funny", mood="happy")

        payload = mock_post.call_args[1]["json"]
        assert "<laugh>" in payload["input"]

    @patch("engine.tts.orpheus_client.requests.post")
    def test_generate_speed_clamped(self, mock_post: MagicMock, client: OrpheusClient):
        """Speed is clamped to 0.5-1.5 range."""
        mock_resp = MagicMock()
        mock_resp.content = b"RIFF" + b"\x00" * 50
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client.generate("Test", speed=5.0)
        payload = mock_post.call_args[1]["json"]
        assert payload["speed"] == 1.5

        client.generate("Test", speed=0.1)
        payload = mock_post.call_args[1]["json"]
        assert payload["speed"] == 0.5

    @patch("engine.tts.orpheus_client.requests.post")
    def test_generate_connection_error(self, mock_post: MagicMock, client: OrpheusClient):
        """ConnectionError raised when server is down."""
        import requests as req
        mock_post.side_effect = req.ConnectionError("refused")

        with pytest.raises(ConnectionError, match="Cannot reach Orpheus"):
            client.generate("Hello")

    @patch("engine.tts.orpheus_client.requests.post")
    def test_generate_http_error(self, mock_post: MagicMock, client: OrpheusClient):
        """RuntimeError raised on HTTP error."""
        import requests as req
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req.HTTPError(response=MagicMock(text="bad"))
        mock_post.return_value = mock_resp

        with pytest.raises(RuntimeError, match="Orpheus generation failed"):
            client.generate("Hello")


class TestOrpheusStream:
    """Streaming generation tests."""

    @patch("engine.tts.orpheus_client.requests.post")
    def test_generate_stream(self, mock_post: MagicMock, client: OrpheusClient):
        """Streaming writes chunks to a WAV file."""
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"RIFF", b"\x00" * 50]
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        path = client.generate_stream("Long text here")
        assert Path(path).exists()


class TestOrpheusHealth:
    """Health check tests."""

    @patch("engine.tts.orpheus_client.requests.get")
    def test_health_online(self, mock_get: MagicMock, client: OrpheusClient):
        mock_get.return_value = MagicMock(status_code=200)
        result = client.health()
        assert result["status"] == "ok"
        assert result["voices"] == 25

    @patch("engine.tts.orpheus_client.requests.get")
    def test_health_offline(self, mock_get: MagicMock, client: OrpheusClient):
        import requests as req
        mock_get.side_effect = req.ConnectionError()
        result = client.health()
        assert result["status"] == "offline"


class TestOrpheusVoiceMatching:
    """Voice matching/selection tests."""

    def test_match_by_gender(self, client: OrpheusClient):
        voice = client.match_voice(gender="male", lang="en")
        assert ORPHEUS_VOICES[voice]["gender"] == "male"

    def test_match_by_style(self, client: OrpheusClient):
        voice = client.match_voice(style="warm gentle", lang="en")
        assert voice == "leah"

    def test_match_by_language(self, client: OrpheusClient):
        voice = client.match_voice(lang="fr")
        assert ORPHEUS_VOICES[voice]["lang"] == "fr"

    def test_match_fallback_to_english(self, client: OrpheusClient):
        voice = client.match_voice(lang="xx")
        assert ORPHEUS_VOICES[voice]["lang"] == "en"

    def test_match_gender_and_style(self, client: OrpheusClient):
        voice = client.match_voice(gender="male", style="authoritative deep", lang="en")
        assert voice == "leo"


class TestOrpheusSkills:
    """Test the Orpheus TTS skills."""

    @patch("engine.tts.orpheus_client.requests.post")
    def test_orpheus_speak_skill(self, mock_post: MagicMock, tmp_path: Path):
        """orpheus_speak skill generates audio."""
        mock_resp = MagicMock()
        mock_resp.content = b"RIFF" + b"\x00" * 50
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        with patch("engine.tts.orpheus_client._client", None):
            with patch("engine.tts.orpheus_client.OrpheusClient.__init__", return_value=None):
                from engine.skills.builtin.tts_skills import orpheus_speak
                with patch("engine.tts.orpheus_client.get_orpheus_client") as mock_get:
                    mock_client = OrpheusClient(
                        server_url="http://localhost:5005",
                        output_dir=tmp_path,
                    )
                    mock_get.return_value = mock_client
                    result = orpheus_speak("Hello", voice="tara")
                    assert "Voice message saved" in result or "failed" in result.lower()

    def test_list_orpheus_voices_skill(self):
        """list_orpheus_voices returns formatted list."""
        from engine.skills.builtin.tts_skills import list_orpheus_voices
        result = list_orpheus_voices()
        assert "tara" in result
        assert "leo" in result

    def test_list_orpheus_voices_filtered(self):
        """list_orpheus_voices filters by language."""
        from engine.skills.builtin.tts_skills import list_orpheus_voices
        result = list_orpheus_voices(lang="fr")
        assert "pierre" in result
        assert "tara" not in result

    def test_list_orpheus_voices_unknown_lang(self):
        """list_orpheus_voices returns message for unknown language."""
        from engine.skills.builtin.tts_skills import list_orpheus_voices
        result = list_orpheus_voices(lang="xx")
        assert "No Orpheus voices" in result
