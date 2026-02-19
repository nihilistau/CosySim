"""Tests for engine.media.media_config — MediaConfig singleton."""
import pytest
from engine.media.media_config import MediaConfig


class TestMediaConfigDefaults:
    """MediaConfig with no YAML input should use hardcoded defaults."""

    def setup_method(self):
        self.mc = MediaConfig()  # no args → uses _DEFAULTS

    def test_image_selfie_dims(self):
        assert self.mc.image_dims("selfie") == (512, 768)

    def test_image_thumbnail_dims(self):
        assert self.mc.image_dims("thumbnail") == (200, 200)

    def test_image_unknown_kind_falls_back(self):
        w, h = self.mc.image_dims("nonexistent")
        assert (w, h) == (512, 768)  # falls back to selfie default

    def test_image_format(self):
        assert self.mc.image_format("selfie") == "png"
        assert self.mc.image_format("thumbnail") == "jpg"

    def test_video_spec_message(self):
        spec = self.mc.video_spec("message")
        assert spec["width"] == 640
        assert spec["height"] == 480
        assert spec["fps"] == 24
        assert spec["codec"] == "h264"

    def test_video_dims(self):
        assert self.mc.video_dims("message") == (640, 480)

    def test_video_fps(self):
        assert self.mc.video_fps("message") == 24
        assert self.mc.video_fps("call") == 15

    def test_video_max_duration(self):
        assert self.mc.video_max_duration("message") == 15

    def test_audio_sample_rate(self):
        assert self.mc.audio_sample_rate("voice_message") == 22050

    def test_audio_channels(self):
        assert self.mc.audio_channels("voice_message") == 1

    def test_audio_format(self):
        assert self.mc.audio_format("voice_message") == "wav"

    def test_audio_max_duration(self):
        assert self.mc.audio_max_duration("voice_message") == 3600

    def test_raw_returns_dict(self):
        raw = self.mc.raw()
        assert "image" in raw
        assert "video" in raw
        assert "audio" in raw


class TestMediaConfigCustom:
    """MediaConfig with overridden values."""

    def test_custom_image_dims(self):
        mc = MediaConfig({"image": {"selfie": {"width": 1024, "height": 1024, "format": "jpg"}}})
        assert mc.image_dims("selfie") == (1024, 1024)
        assert mc.image_format("selfie") == "jpg"

    def test_custom_video(self):
        mc = MediaConfig({"video": {"message": {"width": 1920, "height": 1080, "fps": 30, "codec": "h265"}}})
        assert mc.video_dims("message") == (1920, 1080)
        assert mc.video_fps("message") == 30

    def test_missing_section_uses_defaults(self):
        mc = MediaConfig({"image": {}})
        # video is missing from custom, should fall back
        assert mc.video_dims("message") == (640, 480)

    def test_partial_override(self):
        mc = MediaConfig({
            "image": {"selfie": {"width": 768, "height": 1024, "format": "png"}},
            "video": {"message": {"width": 640, "height": 480, "fps": 24, "codec": "h264", "max_duration": 15}},
            "audio": {"voice_message": {"sample_rate": 44100, "channels": 2, "format": "mp3", "max_duration": 7200}},
        })
        assert mc.audio_sample_rate("voice_message") == 44100
        assert mc.audio_channels("voice_message") == 2
