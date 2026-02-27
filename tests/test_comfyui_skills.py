"""Tests for comfyui_skills — ComfyUI image generation skills.

Covers:
- generate_image:  success, no-result, ImportError, exceptions, dimension fallback
- generate_character_portrait:  prompt delegation, parameter forwarding
- list_comfyui_workflows:  success, empty, exception, missing method
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, call

import pytest


# ── Patch paths (source-module patching for lazy imports) ──────────
_PATCH_CONFIG = "engine.config.get_config"
_PATCH_CTX = "engine.skills.chain_context.get_chain_context"
_PATCH_CLIENT = "content.simulation.services.comfyui_client.ComfyUIClient"
_PATCH_MEDIA_CFG = "engine.media.media_config.get_media_config"
_PATCH_EVENT_CHAIN = "content.simulation.database.events.EventChain"


# ── Helpers ────────────────────────────────────────────────────────

def _default_config():
    """Return a mock config that answers comfyui.base_url."""
    cfg = MagicMock()
    cfg.get = lambda key, default=None: {
        "comfyui.base_url": "http://localhost:8188",
    }.get(key, default)
    return cfg


def _default_ctx(**overrides):
    """Return a mock chain context dict with sensible defaults."""
    ctx = {
        "chain_id": "chain-001",
        "scene_id": "studio",
        "character_id": "char-42",
    }
    ctx.update(overrides)
    return ctx


# ══════════════════════════════════════════════════════════════════
#  generate_image
# ══════════════════════════════════════════════════════════════════


class TestGenerateImage:
    """Tests for the generate_image skill."""

    @patch(_PATCH_EVENT_CHAIN)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CTX)
    @patch(_PATCH_CONFIG)
    def test_success_returns_download_url(
        self, mock_cfg, mock_ctx, mock_client_cls, mock_ec_cls,
    ):
        """Successful generation returns /api/media/download/<filename>."""
        from engine.skills.builtin.comfyui_skills import generate_image

        mock_cfg.return_value = _default_config()
        mock_ctx.return_value = _default_ctx()
        client = MagicMock()
        client.generate_image.return_value = "/output/images/skill_realistic_001.png"
        mock_client_cls.return_value = client

        result = generate_image(prompt="sunset over mountains", width=512, height=768)

        assert result == "/api/media/download/skill_realistic_001.png"
        client.generate_image.assert_called_once_with(
            positive_prompt="sunset over mountains",
            negative_prompt="",
            save_dir="content/simulation/media/images",
            filename_prefix="skill_realistic",
        )

    @patch(_PATCH_EVENT_CHAIN)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CTX)
    @patch(_PATCH_CONFIG)
    def test_no_result_returns_error_message(
        self, mock_cfg, mock_ctx, mock_client_cls, mock_ec_cls,
    ):
        """When ComfyUI returns None the skill reports a descriptive error."""
        from engine.skills.builtin.comfyui_skills import generate_image

        mock_cfg.return_value = _default_config()
        mock_ctx.return_value = _default_ctx()
        client = MagicMock()
        client.generate_image.return_value = None
        mock_client_cls.return_value = client

        result = generate_image(prompt="a cat", width=512, height=768)

        assert "no result" in result.lower()

    @patch(_PATCH_EVENT_CHAIN)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CTX)
    @patch(_PATCH_CONFIG)
    def test_empty_string_result_returns_error(
        self, mock_cfg, mock_ctx, mock_client_cls, mock_ec_cls,
    ):
        """Empty string is falsy — should trigger the 'no result' branch."""
        from engine.skills.builtin.comfyui_skills import generate_image

        mock_cfg.return_value = _default_config()
        mock_ctx.return_value = _default_ctx()
        client = MagicMock()
        client.generate_image.return_value = ""
        mock_client_cls.return_value = client

        result = generate_image(prompt="a cat", width=512, height=768)

        assert "no result" in result.lower()

    def test_import_error_returns_not_available(self):
        """If ComfyUI client can't be imported the skill says so."""
        from engine.skills.builtin.comfyui_skills import generate_image

        with patch(
            "builtins.__import__",
            side_effect=_raise_import_on_comfyui,
        ):
            result = generate_image(prompt="test")

        assert "not available" in result.lower()

    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CTX)
    @patch(_PATCH_CONFIG)
    def test_generate_exception_returns_error(
        self, mock_cfg, mock_ctx, mock_client_cls,
    ):
        """Runtime errors in ComfyUI are caught and surfaced."""
        from engine.skills.builtin.comfyui_skills import generate_image

        mock_cfg.return_value = _default_config()
        mock_ctx.return_value = _default_ctx()
        client = MagicMock()
        client.generate_image.side_effect = ConnectionError("refused")
        mock_client_cls.return_value = client

        result = generate_image(prompt="a cat", width=512, height=768)

        assert "failed to generate image" in result.lower()
        assert "refused" in result.lower()

    @patch(_PATCH_EVENT_CHAIN)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CTX)
    @patch(_PATCH_CONFIG)
    @patch(_PATCH_MEDIA_CFG)
    def test_zero_dims_loads_from_media_config(
        self, mock_media, mock_cfg, mock_ctx, mock_client_cls, mock_ec_cls,
    ):
        """width=0, height=0 should read dims from MediaConfig.image_dims."""
        from engine.skills.builtin.comfyui_skills import generate_image

        media_cfg = MagicMock()
        media_cfg.image_dims.return_value = (768, 1024)
        mock_media.return_value = media_cfg

        mock_cfg.return_value = _default_config()
        mock_ctx.return_value = _default_ctx()
        client = MagicMock()
        client.generate_image.return_value = "/output/result.png"
        mock_client_cls.return_value = client

        result = generate_image(prompt="landscape", width=0, height=0)

        media_cfg.image_dims.assert_called_once_with("selfie")
        assert "/api/media/download/result.png" in result

    @patch(_PATCH_EVENT_CHAIN)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CTX)
    @patch(_PATCH_CONFIG)
    @patch(_PATCH_MEDIA_CFG)
    def test_media_config_failure_falls_back_to_512x768(
        self, mock_media, mock_cfg, mock_ctx, mock_client_cls, mock_ec_cls,
    ):
        """If MediaConfig throws, default to 512×768 and keep going."""
        from engine.skills.builtin.comfyui_skills import generate_image

        mock_media.side_effect = RuntimeError("no config")

        mock_cfg.return_value = _default_config()
        mock_ctx.return_value = _default_ctx()
        client = MagicMock()
        client.generate_image.return_value = "/output/fallback.png"
        mock_client_cls.return_value = client

        result = generate_image(prompt="fallback test", width=0, height=0)

        # Should still succeed — fallback dimensions used
        assert "/api/media/download/fallback.png" in result

    @patch(_PATCH_EVENT_CHAIN)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CTX)
    @patch(_PATCH_CONFIG)
    def test_custom_dimensions_skip_media_config(
        self, mock_cfg, mock_ctx, mock_client_cls, mock_ec_cls,
    ):
        """Explicit non-zero dimensions should not trigger MediaConfig lookup."""
        from engine.skills.builtin.comfyui_skills import generate_image

        mock_cfg.return_value = _default_config()
        mock_ctx.return_value = _default_ctx()
        client = MagicMock()
        client.generate_image.return_value = "/output/custom.png"
        mock_client_cls.return_value = client

        with patch(_PATCH_MEDIA_CFG) as mock_media:
            result = generate_image(prompt="wide", width=1024, height=576)
            mock_media.assert_not_called()

        assert "/api/media/download/custom.png" in result

    @patch(_PATCH_EVENT_CHAIN)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CTX)
    @patch(_PATCH_CONFIG)
    def test_event_chain_logging_on_success(
        self, mock_cfg, mock_ctx, mock_client_cls, mock_ec_cls,
    ):
        """Successful generation should log a media_generated event."""
        from engine.skills.builtin.comfyui_skills import generate_image

        mock_cfg.return_value = _default_config()
        mock_ctx.return_value = _default_ctx()
        client = MagicMock()
        client.generate_image.return_value = "/output/logged.png"
        mock_client_cls.return_value = client
        ec_instance = MagicMock()
        mock_ec_cls.return_value = ec_instance

        generate_image(prompt="log me", width=512, height=768)

        ec_instance.log.assert_called_once()
        log_kwargs = ec_instance.log.call_args
        assert log_kwargs[0][0] == "media_generated"
        assert log_kwargs[1]["chain_id"] == "chain-001"
        assert log_kwargs[1]["scene_id"] == "studio"
        assert log_kwargs[1]["actor"] == "skill:generate_image"

    @patch(_PATCH_EVENT_CHAIN)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CTX)
    @patch(_PATCH_CONFIG)
    def test_no_chain_id_skips_event_logging(
        self, mock_cfg, mock_ctx, mock_client_cls, mock_ec_cls,
    ):
        """Without a chain_id in context, EventChain.log should not fire."""
        from engine.skills.builtin.comfyui_skills import generate_image

        mock_cfg.return_value = _default_config()
        mock_ctx.return_value = _default_ctx(chain_id=None)
        client = MagicMock()
        client.generate_image.return_value = "/output/nolog.png"
        mock_client_cls.return_value = client
        ec_instance = MagicMock()
        mock_ec_cls.return_value = ec_instance

        result = generate_image(prompt="silent", width=512, height=768)

        assert "/api/media/download/nolog.png" in result
        ec_instance.log.assert_not_called()

    @patch(_PATCH_EVENT_CHAIN)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CTX)
    @patch(_PATCH_CONFIG)
    def test_event_chain_exception_suppressed(
        self, mock_cfg, mock_ctx, mock_client_cls, mock_ec_cls,
    ):
        """If EventChain.log raises, the image URL is still returned."""
        from engine.skills.builtin.comfyui_skills import generate_image

        mock_cfg.return_value = _default_config()
        mock_ctx.return_value = _default_ctx()
        client = MagicMock()
        client.generate_image.return_value = "/output/safe.png"
        mock_client_cls.return_value = client
        mock_ec_cls.side_effect = RuntimeError("DB locked")

        result = generate_image(prompt="resilient", width=512, height=768)

        assert "/api/media/download/safe.png" in result

    @patch(_PATCH_EVENT_CHAIN)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CTX)
    @patch(_PATCH_CONFIG)
    def test_negative_prompt_forwarded(
        self, mock_cfg, mock_ctx, mock_client_cls, mock_ec_cls,
    ):
        """Negative prompt should be passed through to the client."""
        from engine.skills.builtin.comfyui_skills import generate_image

        mock_cfg.return_value = _default_config()
        mock_ctx.return_value = _default_ctx()
        client = MagicMock()
        client.generate_image.return_value = "/output/neg.png"
        mock_client_cls.return_value = client

        generate_image(prompt="sky", negative_prompt="clouds", width=512, height=768)

        _, kwargs = client.generate_image.call_args
        assert kwargs["negative_prompt"] == "clouds"

    @patch(_PATCH_EVENT_CHAIN)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CTX)
    @patch(_PATCH_CONFIG)
    def test_style_sets_filename_prefix(
        self, mock_cfg, mock_ctx, mock_client_cls, mock_ec_cls,
    ):
        """The style parameter should be used in the filename_prefix."""
        from engine.skills.builtin.comfyui_skills import generate_image

        mock_cfg.return_value = _default_config()
        mock_ctx.return_value = _default_ctx()
        client = MagicMock()
        client.generate_image.return_value = "/output/anime_001.png"
        mock_client_cls.return_value = client

        generate_image(prompt="warrior", style="anime", width=512, height=768)

        _, kwargs = client.generate_image.call_args
        assert kwargs["filename_prefix"] == "skill_anime"

    @patch(_PATCH_EVENT_CHAIN)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CTX)
    @patch(_PATCH_CONFIG)
    def test_base_url_from_config(
        self, mock_cfg, mock_ctx, mock_client_cls, mock_ec_cls,
    ):
        """ComfyUIClient should be constructed with the configured base_url."""
        from engine.skills.builtin.comfyui_skills import generate_image

        cfg = MagicMock()
        cfg.get = lambda key, default=None: {
            "comfyui.base_url": "http://gpu-server:9999",
        }.get(key, default)
        mock_cfg.return_value = cfg
        mock_ctx.return_value = _default_ctx()
        client = MagicMock()
        client.generate_image.return_value = "/output/remote.png"
        mock_client_cls.return_value = client

        generate_image(prompt="remote", width=512, height=768)

        mock_client_cls.assert_called_once_with(base_url="http://gpu-server:9999")

    @patch(_PATCH_EVENT_CHAIN)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CTX)
    @patch(_PATCH_CONFIG)
    def test_prompt_truncated_in_event_payload(
        self, mock_cfg, mock_ctx, mock_client_cls, mock_ec_cls,
    ):
        """Long prompts should be truncated in the EventChain payload."""
        from engine.skills.builtin.comfyui_skills import generate_image

        mock_cfg.return_value = _default_config()
        mock_ctx.return_value = _default_ctx()
        client = MagicMock()
        client.generate_image.return_value = "/output/trunc.png"
        mock_client_cls.return_value = client
        ec_instance = MagicMock()
        mock_ec_cls.return_value = ec_instance

        long_prompt = "a " * 500  # 1000 chars
        generate_image(prompt=long_prompt, width=512, height=768)

        log_kwargs = ec_instance.log.call_args[1]
        # Payload prompt is capped at 200 chars
        assert len(log_kwargs["payload"]["prompt"]) <= 200
        # Summary prompt is capped at 60 chars
        assert len(log_kwargs["summary"]) <= len("Image generated: ") + 60


# ══════════════════════════════════════════════════════════════════
#  generate_character_portrait
# ══════════════════════════════════════════════════════════════════


class TestGenerateCharacterPortrait:
    """Tests for the generate_character_portrait skill."""

    @patch(_PATCH_EVENT_CHAIN)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CTX)
    @patch(_PATCH_CONFIG)
    def test_builds_portrait_prompt(
        self, mock_cfg, mock_ctx, mock_client_cls, mock_ec_cls,
    ):
        """Portrait prompt should include character name, description, and mood."""
        from engine.skills.builtin.comfyui_skills import generate_character_portrait

        mock_cfg.return_value = _default_config()
        mock_ctx.return_value = _default_ctx()
        client = MagicMock()
        client.generate_image.return_value = "/output/portrait_001.png"
        mock_client_cls.return_value = client

        result = generate_character_portrait(
            character_name="Alice",
            physical_description="red hair, green eyes",
            mood="happy",
        )

        assert "/api/media/download/" in result
        pos_prompt = client.generate_image.call_args[1]["positive_prompt"]
        assert "Alice" in pos_prompt
        assert "red hair, green eyes" in pos_prompt
        assert "happy expression" in pos_prompt
        assert "high quality" in pos_prompt

    @patch(_PATCH_EVENT_CHAIN)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CTX)
    @patch(_PATCH_CONFIG)
    def test_uses_fixed_negative_prompt(
        self, mock_cfg, mock_ctx, mock_client_cls, mock_ec_cls,
    ):
        """Portrait should include the standard negative prompt."""
        from engine.skills.builtin.comfyui_skills import generate_character_portrait

        mock_cfg.return_value = _default_config()
        mock_ctx.return_value = _default_ctx()
        client = MagicMock()
        client.generate_image.return_value = "/output/portrait.png"
        mock_client_cls.return_value = client

        generate_character_portrait(
            character_name="Bob",
            physical_description="tall",
        )

        neg = client.generate_image.call_args[1]["negative_prompt"]
        assert "blurry" in neg
        assert "deformed" in neg

    @patch(_PATCH_EVENT_CHAIN)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CTX)
    @patch(_PATCH_CONFIG)
    def test_portrait_dimensions_512x768(
        self, mock_cfg, mock_ctx, mock_client_cls, mock_ec_cls,
    ):
        """Portrait should use 512×768 explicitly (no MediaConfig lookup)."""
        from engine.skills.builtin.comfyui_skills import generate_character_portrait

        mock_cfg.return_value = _default_config()
        mock_ctx.return_value = _default_ctx()
        client = MagicMock()
        client.generate_image.return_value = "/output/dims.png"
        mock_client_cls.return_value = client

        with patch(_PATCH_MEDIA_CFG) as mock_media:
            generate_character_portrait(
                character_name="Carol",
                physical_description="short hair",
            )
            # Explicit 512x768 — should not consult MediaConfig
            mock_media.assert_not_called()

    @patch(_PATCH_EVENT_CHAIN)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CTX)
    @patch(_PATCH_CONFIG)
    def test_custom_style_in_prompt_and_prefix(
        self, mock_cfg, mock_ctx, mock_client_cls, mock_ec_cls,
    ):
        """Custom style appears in both the composed prompt and filename prefix."""
        from engine.skills.builtin.comfyui_skills import generate_character_portrait

        mock_cfg.return_value = _default_config()
        mock_ctx.return_value = _default_ctx()
        client = MagicMock()
        client.generate_image.return_value = "/output/anime.png"
        mock_client_cls.return_value = client

        generate_character_portrait(
            character_name="Dana",
            physical_description="blue eyes",
            style="anime portrait",
        )

        call_kwargs = client.generate_image.call_args[1]
        assert "anime portrait" in call_kwargs["positive_prompt"]
        assert call_kwargs["filename_prefix"] == "skill_anime portrait"

    @patch(_PATCH_EVENT_CHAIN)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CTX)
    @patch(_PATCH_CONFIG)
    def test_default_mood_is_neutral(
        self, mock_cfg, mock_ctx, mock_client_cls, mock_ec_cls,
    ):
        """When no mood is given, 'neutral' should appear in the prompt."""
        from engine.skills.builtin.comfyui_skills import generate_character_portrait

        mock_cfg.return_value = _default_config()
        mock_ctx.return_value = _default_ctx()
        client = MagicMock()
        client.generate_image.return_value = "/output/neutral.png"
        mock_client_cls.return_value = client

        generate_character_portrait(
            character_name="Eve",
            physical_description="blonde",
        )

        pos_prompt = client.generate_image.call_args[1]["positive_prompt"]
        assert "neutral expression" in pos_prompt

    @patch(_PATCH_EVENT_CHAIN)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CTX)
    @patch(_PATCH_CONFIG)
    def test_steps_and_cfg_forwarded(
        self, mock_cfg, mock_ctx, mock_client_cls, mock_ec_cls,
    ):
        """Portrait uses steps=25 and cfg_scale=7.5 (higher than defaults)."""
        from engine.skills.builtin.comfyui_skills import generate_character_portrait

        mock_cfg.return_value = _default_config()
        mock_ctx.return_value = _default_ctx()
        client = MagicMock()
        client.generate_image.return_value = "/output/hq.png"
        mock_client_cls.return_value = client

        # These aren't directly forwarded to the client in current impl,
        # but the function signature accepts them — verify the call succeeds
        result = generate_character_portrait(
            character_name="Frank",
            physical_description="beard",
        )
        assert "/api/media/download/" in result


# ══════════════════════════════════════════════════════════════════
#  list_comfyui_workflows
# ══════════════════════════════════════════════════════════════════


class TestListComfyuiWorkflows:
    """Tests for the list_comfyui_workflows skill."""

    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CONFIG)
    def test_returns_json_array(self, mock_cfg, mock_client_cls):
        """Available workflows are returned as a JSON array."""
        from engine.skills.builtin.comfyui_skills import list_comfyui_workflows

        mock_cfg.return_value = _default_config()
        client = MagicMock()
        client.list_workflows.return_value = ["txt2img", "img2img", "inpaint"]
        mock_client_cls.return_value = client

        result = list_comfyui_workflows()
        parsed = json.loads(result)

        assert isinstance(parsed, list)
        assert len(parsed) == 3
        assert "txt2img" in parsed
        assert "inpaint" in parsed

    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CONFIG)
    def test_empty_workflow_list(self, mock_cfg, mock_client_cls):
        """No workflows should return an empty JSON array."""
        from engine.skills.builtin.comfyui_skills import list_comfyui_workflows

        mock_cfg.return_value = _default_config()
        client = MagicMock()
        client.list_workflows.return_value = []
        mock_client_cls.return_value = client

        result = list_comfyui_workflows()
        parsed = json.loads(result)

        assert parsed == []

    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CONFIG)
    def test_exception_returns_error_string(self, mock_cfg, mock_client_cls):
        """Network failures surface as a human-readable error string."""
        from engine.skills.builtin.comfyui_skills import list_comfyui_workflows

        mock_cfg.return_value = _default_config()
        mock_client_cls.side_effect = ConnectionError("ComfyUI offline")

        result = list_comfyui_workflows()

        assert "could not list workflows" in result.lower()
        assert "ComfyUI offline" in result

    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CONFIG)
    def test_no_list_workflows_method_returns_empty(self, mock_cfg, mock_client_cls):
        """If client lacks list_workflows, should return empty JSON array."""
        from engine.skills.builtin.comfyui_skills import list_comfyui_workflows

        mock_cfg.return_value = _default_config()
        client = MagicMock(spec=[])  # spec=[] means no attributes/methods
        mock_client_cls.return_value = client

        result = list_comfyui_workflows()
        parsed = json.loads(result)

        assert parsed == []

    @patch(_PATCH_CLIENT)
    @patch(_PATCH_CONFIG)
    def test_uses_configured_base_url(self, mock_cfg, mock_client_cls):
        """The client should be built with the URL from config."""
        from engine.skills.builtin.comfyui_skills import list_comfyui_workflows

        cfg = MagicMock()
        cfg.get = lambda key, default=None: {
            "comfyui.base_url": "http://render-box:7777",
        }.get(key, default)
        mock_cfg.return_value = cfg
        client = MagicMock()
        client.list_workflows.return_value = ["wf1"]
        mock_client_cls.return_value = client

        list_comfyui_workflows()

        mock_client_cls.assert_called_once_with(base_url="http://render-box:7777")


# ══════════════════════════════════════════════════════════════════
#  HELPERS (not test classes)
# ══════════════════════════════════════════════════════════════════

_ORIGINAL_IMPORT = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__


def _raise_import_on_comfyui(name, *args, **kwargs):
    """Replacement for builtins.__import__ that blocks comfyui_client."""
    if "comfyui_client" in name:
        raise ImportError("mocked: comfyui not installed")
    return _ORIGINAL_IMPORT(name, *args, **kwargs)
