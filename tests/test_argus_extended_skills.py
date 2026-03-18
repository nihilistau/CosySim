"""Tests for engine.skills.builtin.argus_extended_skills — ARGUS extended MCP skills.

All network calls are mocked — no real HTTP calls are made.

Coverage (30+ tests):
  - All 10 skills return valid JSON
  - Skills use correct underlying client methods
  - Error handling: exceptions produce error JSON, never raise
  - Return field validation (status, content, model, etc.)
  - Parameter forwarding (model, temperature, category, page_size)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ──── Helpers ─────────────────────────────────────────────────────────────────


def _parse_result(result: str) -> dict:
    """Parse the JSON string returned by a skill."""
    return json.loads(result)


def _ok(result: str) -> dict:
    """Assert status is 'ok' and return parsed dict."""
    parsed = _parse_result(result)
    assert parsed["status"] == "ok", f"Expected ok, got: {parsed}"
    return parsed


def _error(result: str) -> dict:
    """Assert status is 'error' and return parsed dict."""
    parsed = _parse_result(result)
    assert parsed["status"] == "error", f"Expected error, got: {parsed}"
    return parsed


# ──── opal_generate ───────────────────────────────────────────────────────────


class TestOpalGenerateSkill:
    """opal_generate skill."""

    def test_opal_generate_returns_ok_json(self) -> None:
        """opal_generate returns valid JSON with status='ok'."""
        mock_client = MagicMock()
        mock_client.generate_content.return_value = {
            "content": "creative output",
            "rpcid": "ug7pge",
        }
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_opal_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import opal_generate
            result = _ok(opal_generate("write a poem"))
        assert result["content"] == "creative output"

    def test_opal_generate_passes_style(self) -> None:
        """opal_generate forwards style parameter to client."""
        mock_client = MagicMock()
        mock_client.generate_content.return_value = {"content": "", "rpcid": "ug7pge"}
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_opal_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import opal_generate
            opal_generate("prompt", style="formal")
        mock_client.generate_content.assert_called_once_with(
            prompt="prompt", style="formal"
        )

    def test_opal_generate_error_json_on_exception(self) -> None:
        """opal_generate returns error JSON when client raises."""
        mock_client = MagicMock()
        mock_client.generate_content.side_effect = RuntimeError("network fail")
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_opal_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import opal_generate
            result = _error(opal_generate("prompt"))
        assert "network fail" in result["error"]

    def test_opal_generate_never_raises(self) -> None:
        """opal_generate never propagates exceptions."""
        mock_client = MagicMock()
        mock_client.generate_content.side_effect = Exception("boom")
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_opal_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import opal_generate
            result = opal_generate("any")
        assert json.loads(result)["status"] == "error"


# ──── opal_gallery_list ───────────────────────────────────────────────────────


class TestOpalGalleryListSkill:
    """opal_gallery_list skill."""

    def test_opal_gallery_list_returns_items(self) -> None:
        """opal_gallery_list returns items list from client."""
        mock_client = MagicMock()
        mock_client.gallery_list.return_value = [{"id": "i1"}, {"id": "i2"}]
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_opal_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import opal_gallery_list
            result = _ok(opal_gallery_list(category="art", page_size=5))
        assert result["count"] == 2
        assert len(result["items"]) == 2

    def test_opal_gallery_list_passes_params(self) -> None:
        """opal_gallery_list forwards category and page_size."""
        mock_client = MagicMock()
        mock_client.gallery_list.return_value = []
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_opal_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import opal_gallery_list
            opal_gallery_list(category="templates", page_size=10)
        mock_client.gallery_list.assert_called_once_with(
            category="templates", page_size=10
        )

    def test_opal_gallery_list_error_on_exception(self) -> None:
        """opal_gallery_list returns error JSON on failure."""
        mock_client = MagicMock()
        mock_client.gallery_list.side_effect = ConnectionError("timeout")
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_opal_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import opal_gallery_list
            result = _error(opal_gallery_list())
        assert "timeout" in result["error"]


# ──── opal_drive_list ─────────────────────────────────────────────────────────


class TestOpalDriveListSkill:
    """opal_drive_list skill."""

    def test_opal_drive_list_returns_files(self) -> None:
        """opal_drive_list returns file list from client."""
        mock_client = MagicMock()
        mock_client.drive_proxy_list.return_value = [{"id": "f1"}]
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_opal_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import opal_drive_list
            result = _ok(opal_drive_list(page_size=3))
        assert result["count"] == 1

    def test_opal_drive_list_passes_page_size(self) -> None:
        """opal_drive_list forwards page_size."""
        mock_client = MagicMock()
        mock_client.drive_proxy_list.return_value = []
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_opal_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import opal_drive_list
            opal_drive_list(page_size=7)
        mock_client.drive_proxy_list.assert_called_once_with(page_size=7)

    def test_opal_drive_list_error_on_exception(self) -> None:
        """opal_drive_list returns error JSON on failure."""
        mock_client = MagicMock()
        mock_client.drive_proxy_list.side_effect = Exception("err")
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_opal_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import opal_drive_list
            result = _error(opal_drive_list())
        assert "err" in result["error"]


# ──── appcatalyst_generate ────────────────────────────────────────────────────


class TestAppCatalystGenerateSkill:
    """appcatalyst_generate skill."""

    def test_appcatalyst_generate_returns_text(self) -> None:
        """appcatalyst_generate returns generated text."""
        mock_client = MagicMock()
        mock_client.generate.return_value = {
            "text": "Gemini 3 response",
            "model": "gemini-3-flash-preview",
        }
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_appcatalyst_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import appcatalyst_generate
            result = _ok(appcatalyst_generate("hello"))
        assert result["text"] == "Gemini 3 response"
        assert result["model"] == "gemini-3-flash-preview"

    def test_appcatalyst_generate_passes_model_and_temperature(self) -> None:
        """appcatalyst_generate forwards model and temperature."""
        mock_client = MagicMock()
        mock_client.generate.return_value = {"text": "", "model": "m"}
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_appcatalyst_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import appcatalyst_generate
            appcatalyst_generate(
                "prompt",
                model="gemini-2.5-flash",
                temperature=0.2,
                system_prompt="be precise",
            )
        call_kwargs = mock_client.generate.call_args[1]
        assert call_kwargs["model"] == "gemini-2.5-flash"
        assert call_kwargs["temperature"] == 0.2
        assert call_kwargs["system_prompt"] == "be precise"

    def test_appcatalyst_generate_error_on_exception(self) -> None:
        """appcatalyst_generate returns error JSON on failure."""
        mock_client = MagicMock()
        mock_client.generate.side_effect = Exception("API error")
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_appcatalyst_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import appcatalyst_generate
            result = _error(appcatalyst_generate("prompt"))
        assert "API error" in result["error"]


# ──── appcatalyst_generate_vision ─────────────────────────────────────────────


class TestAppCatalystGenerateVisionSkill:
    """appcatalyst_generate_vision skill."""

    def test_generate_vision_returns_text(self, tmp_path) -> None:
        """appcatalyst_generate_vision returns vision response text."""
        img_file = tmp_path / "test.jpg"
        img_file.write_bytes(b"fake_image_bytes")

        mock_client = MagicMock()
        mock_client.generate_vision.return_value = {
            "text": "I see a cat",
            "model": "gemini-3-flash-preview",
        }
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_appcatalyst_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import appcatalyst_generate_vision
            result = _ok(appcatalyst_generate_vision("describe", str(img_file)))
        assert result["text"] == "I see a cat"

    def test_generate_vision_error_when_image_not_found(self) -> None:
        """appcatalyst_generate_vision returns error when image path doesn't exist."""
        from engine.skills.builtin.argus_extended_skills import appcatalyst_generate_vision
        result = _error(appcatalyst_generate_vision("describe", "/nonexistent/image.jpg"))
        assert "not found" in result["error"].lower() or "nonexistent" in result["error"]

    def test_generate_vision_error_on_exception(self, tmp_path) -> None:
        """appcatalyst_generate_vision returns error JSON on client failure."""
        img_file = tmp_path / "img.png"
        img_file.write_bytes(b"data")
        mock_client = MagicMock()
        mock_client.generate_vision.side_effect = Exception("vision error")
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_appcatalyst_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import appcatalyst_generate_vision
            result = _error(appcatalyst_generate_vision("desc", str(img_file)))
        assert "vision error" in result["error"]


# ──── appcatalyst_list_models ─────────────────────────────────────────────────


class TestAppCatalystListModelsSkill:
    """appcatalyst_list_models skill."""

    def test_list_models_returns_model_list(self) -> None:
        """appcatalyst_list_models returns list of models."""
        mock_client = MagicMock()
        mock_client.list_models.return_value = [
            {"name": "gemini-3-flash-preview"},
            {"name": "gemini-2.5-flash"},
        ]
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_appcatalyst_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import appcatalyst_list_models
            result = _ok(appcatalyst_list_models())
        assert result["count"] == 2

    def test_list_models_error_on_exception(self) -> None:
        """appcatalyst_list_models returns error JSON on failure."""
        mock_client = MagicMock()
        mock_client.list_models.side_effect = Exception("fail")
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_appcatalyst_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import appcatalyst_list_models
            result = _error(appcatalyst_list_models())
        assert "fail" in result["error"]


# ──── appcatalyst_embed ───────────────────────────────────────────────────────


class TestAppCatalystEmbedSkill:
    """appcatalyst_embed skill."""

    def test_embed_returns_embedding(self) -> None:
        """appcatalyst_embed returns embedding vector."""
        mock_client = MagicMock()
        mock_client.embed.return_value = [0.1, 0.2, 0.3]
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_appcatalyst_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import appcatalyst_embed
            result = _ok(appcatalyst_embed("hello"))
        assert result["dim"] == 3
        assert result["embedding"] == [0.1, 0.2, 0.3]

    def test_embed_passes_text_and_model(self) -> None:
        """appcatalyst_embed forwards text and model to client."""
        mock_client = MagicMock()
        mock_client.embed.return_value = []
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_appcatalyst_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import appcatalyst_embed
            appcatalyst_embed("my text", model="custom-embed")
        mock_client.embed.assert_called_once_with(
            text="my text", model="custom-embed"
        )

    def test_embed_error_on_exception(self) -> None:
        """appcatalyst_embed returns error JSON on failure."""
        mock_client = MagicMock()
        mock_client.embed.side_effect = Exception("embed fail")
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_appcatalyst_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import appcatalyst_embed
            result = _error(appcatalyst_embed("text"))
        assert "embed fail" in result["error"]


# ──── gemini_list_storybooks ──────────────────────────────────────────────────


class TestGeminiListStorybooksSkill:
    """gemini_list_storybooks skill."""

    def test_gemini_list_storybooks_returns_storybooks(self) -> None:
        """gemini_list_storybooks returns storybooks list."""
        mock_client = MagicMock()
        mock_client.list_storybooks.return_value = [{"id": "s1"}, {"id": "s2"}]
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_gemini_extended_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import gemini_list_storybooks
            result = _ok(gemini_list_storybooks(page_size=5))
        assert result["count"] == 2

    def test_gemini_list_storybooks_passes_params(self) -> None:
        """gemini_list_storybooks forwards page_size and locale."""
        mock_client = MagicMock()
        mock_client.list_storybooks.return_value = []
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_gemini_extended_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import gemini_list_storybooks
            gemini_list_storybooks(page_size=10, locale="en-US")
        mock_client.list_storybooks.assert_called_once_with(
            page_size=10, locale="en-US"
        )

    def test_gemini_list_storybooks_error_on_exception(self) -> None:
        """gemini_list_storybooks returns error JSON on failure."""
        mock_client = MagicMock()
        mock_client.list_storybooks.side_effect = Exception("storybook fail")
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_gemini_extended_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import gemini_list_storybooks
            result = _error(gemini_list_storybooks())
        assert "storybook fail" in result["error"]


# ──── gemini_list_saved_info ──────────────────────────────────────────────────


class TestGeminiListSavedInfoSkill:
    """gemini_list_saved_info skill."""

    def test_gemini_list_saved_info_returns_items(self) -> None:
        """gemini_list_saved_info returns saved items."""
        mock_client = MagicMock()
        mock_client.list_saved_info.return_value = [{"id": "si1"}]
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_gemini_extended_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import gemini_list_saved_info
            result = _ok(gemini_list_saved_info())
        assert result["count"] == 1

    def test_gemini_list_saved_info_passes_params(self) -> None:
        """gemini_list_saved_info forwards category and page_size."""
        mock_client = MagicMock()
        mock_client.list_saved_info.return_value = []
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_gemini_extended_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import gemini_list_saved_info
            gemini_list_saved_info(category="recipes", page_size=50)
        mock_client.list_saved_info.assert_called_once_with(
            category="recipes", page_size=50
        )

    def test_gemini_list_saved_info_error_on_exception(self) -> None:
        """gemini_list_saved_info returns error JSON on failure."""
        mock_client = MagicMock()
        mock_client.list_saved_info.side_effect = Exception("saved fail")
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_gemini_extended_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import gemini_list_saved_info
            result = _error(gemini_list_saved_info())
        assert "saved fail" in result["error"]


# ──── gemini_get_subscription_tiers ──────────────────────────────────────────


class TestGeminiGetSubscriptionTiersSkill:
    """gemini_get_subscription_tiers skill."""

    def test_returns_tier_info(self) -> None:
        """gemini_get_subscription_tiers returns tier information."""
        mock_client = MagicMock()
        mock_client.get_subscription_tiers.return_value = {
            "current_tier": "pro",
            "available_tiers": ["free", "pro"],
        }
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_gemini_extended_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import (
                gemini_get_subscription_tiers,
            )
            result = _ok(gemini_get_subscription_tiers())
        assert result["current_tier"] == "pro"
        assert "free" in result["available_tiers"]

    def test_uses_gemini_extended_client(self) -> None:
        """gemini_get_subscription_tiers calls get_gemini_extended_client."""
        mock_client = MagicMock()
        mock_client.get_subscription_tiers.return_value = {
            "current_tier": None,
            "available_tiers": [],
        }
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_gemini_extended_client",
            return_value=mock_client,
        ) as mock_get:
            from engine.skills.builtin.argus_extended_skills import (
                gemini_get_subscription_tiers,
            )
            gemini_get_subscription_tiers()
        mock_get.assert_called_once()

    def test_error_on_exception(self) -> None:
        """gemini_get_subscription_tiers returns error JSON on failure."""
        mock_client = MagicMock()
        mock_client.get_subscription_tiers.side_effect = Exception("sub fail")
        with patch(
            "engine.skills.builtin.argus_extended_skills.get_gemini_extended_client",
            return_value=mock_client,
        ):
            from engine.skills.builtin.argus_extended_skills import (
                gemini_get_subscription_tiers,
            )
            result = _error(gemini_get_subscription_tiers())
        assert "sub fail" in result["error"]
