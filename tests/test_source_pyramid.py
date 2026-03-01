"""Tests for engine.nexus.source_pyramid."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import pytest

from engine.nexus.source_pyramid import (
    SourcePyramid,
    get_source_pyramid,
    LAYER_NAMES,
)


class TestLayerNames:
    def test_six_layers_defined(self):
        assert len(LAYER_NAMES) == 6

    def test_layers_zero_through_five(self):
        for i in range(6):
            assert i in LAYER_NAMES, f"Missing layer {i}"

    def test_layer_names_have_numeric_prefix(self):
        for idx, name in LAYER_NAMES.items():
            prefix = f"_{idx:02d}_"
            assert name.startswith(prefix), f"Layer {idx} name missing prefix: {name}"

    def test_layer_names_are_descriptive(self):
        all_names = " ".join(LAYER_NAMES.values()).upper()
        assert "CONSUMER" in all_names
        assert "SCHEMA" in all_names or "OUTPUT" in all_names
        assert "EXAMPLE" in all_names or "GOOD" in all_names


class TestBuildAll:
    def test_build_all_returns_dict(self):
        pyramid = SourcePyramid()
        docs = pyramid.build_all()
        assert isinstance(docs, dict)

    def test_build_all_without_existing_questions_returns_five(self):
        """Layer 4 (coverage) is skipped when existing_questions is None."""
        pyramid = SourcePyramid()
        docs = pyramid.build_all()
        assert len(docs) == 5

    def test_build_all_with_existing_questions_returns_six(self):
        """Layer 4 is included when existing_questions is provided."""
        pyramid = SourcePyramid()
        docs = pyramid.build_all(existing_questions=["What is X?"])
        assert len(docs) == 6

    def test_build_all_keys_match_layer_names(self):
        pyramid = SourcePyramid()
        docs = pyramid.build_all(existing_questions=["Q?"])
        for key in docs:
            assert key in LAYER_NAMES.values(), f"Unexpected key: {key}"

    def test_build_all_values_are_non_empty_strings(self):
        pyramid = SourcePyramid()
        docs = pyramid.build_all()
        for key, content in docs.items():
            assert isinstance(content, str), f"Layer {key} not a string"
            assert len(content) > 20, f"Layer {key} content too short"

    def test_build_all_layer0_contains_consumer(self):
        pyramid = SourcePyramid()
        docs = pyramid.build_all()
        layer0 = docs[LAYER_NAMES[0]]
        assert "consumer" in layer0.lower() or "Consumer" in layer0

    def test_build_all_with_existing_questions_adds_coverage_layer(self):
        pyramid = SourcePyramid()
        questions = ["What is CosySim?", "How do I run tests?"]
        docs = pyramid.build_all(existing_questions=questions)
        # Layer 4 (coverage) should include existing questions
        layer4 = docs[LAYER_NAMES[4]]
        assert "CosySim" in layer4 or "tests" in layer4.lower()

    def test_build_all_without_existing_questions_still_returns_five_keys(self):
        pyramid = SourcePyramid()
        docs = pyramid.build_all(existing_questions=[])
        # Empty list is not None, so layer 4 is included
        assert len(docs) == 6


class TestUploadPyramid:
    def test_upload_pyramid_calls_add_source_per_layer(self):
        pyramid = SourcePyramid()
        mock_nlm = MagicMock()
        mock_nlm.add_text_source.return_value = {"status": "ok"}

        with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=mock_nlm):
            # Pass existing_questions to include layer 4 (all 6 layers)
            count = pyramid.upload_pyramid(
                "nb-test-123",
                skip_layer_4=False,
                existing_questions=["What is X?"],
            )

        assert mock_nlm.add_text_source.call_count == 6
        assert count == 6

    def test_upload_pyramid_returns_count(self):
        pyramid = SourcePyramid()
        mock_nlm = MagicMock()
        mock_nlm.add_text_source.return_value = {"status": "ok"}

        with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=mock_nlm):
            count = pyramid.upload_pyramid("nb-test-123")

        assert isinstance(count, int)
        assert count >= 0

    def test_upload_pyramid_passes_notebook_id(self):
        pyramid = SourcePyramid()
        mock_nlm = MagicMock()
        mock_nlm.add_text_source.return_value = {"status": "ok"}

        with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=mock_nlm):
            pyramid.upload_pyramid("nb-specific-id")

        for c in mock_nlm.add_text_source.call_args_list:
            args, kwargs = c
            notebook_id = kwargs.get("notebook_id") or (args[0] if args else None)
            assert notebook_id == "nb-specific-id"

    def test_upload_pyramid_handles_nlm_failure(self):
        pyramid = SourcePyramid()
        mock_nlm = MagicMock()
        mock_nlm.add_text_source.side_effect = Exception("NLM offline")

        with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=mock_nlm):
            # Should not raise, returns 0
            count = pyramid.upload_pyramid("nb-test-fail")

        assert isinstance(count, int)
        assert count == 0


class TestUploadContent:
    def test_upload_content_calls_add_source_per_doc(self):
        pyramid = SourcePyramid()
        mock_nlm = MagicMock()
        mock_nlm.add_text_source.return_value = {"status": "ok"}

        from engine.nexus.history_miner import SourceDocument
        docs = [
            SourceDocument(title="Theme A", content="content a", theme="architecture"),
            SourceDocument(title="Theme B", content="content b", theme="nexus-core"),
        ]

        with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=mock_nlm):
            count = pyramid.upload_content("nb-test-123", docs)

        assert mock_nlm.add_text_source.call_count == 2
        assert count == 2

    def test_upload_content_empty_list(self):
        pyramid = SourcePyramid()
        mock_nlm = MagicMock()

        with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=mock_nlm):
            count = pyramid.upload_content("nb-test-123", [])

        assert count == 0
        assert mock_nlm.add_text_source.call_count == 0


class TestRefreshCoverage:
    def test_refresh_coverage_calls_add_source(self):
        pyramid = SourcePyramid()
        mock_nlm = MagicMock()
        mock_nlm.add_text_source.return_value = {"status": "ok"}
        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.list_entries.return_value = [
            {"question": "What is X?"},
            {"question": "How does Y work?"},
        ]

        with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=mock_nlm):
            pyramid.refresh_coverage("nb-test-123", mock_client)

        assert mock_nlm.add_text_source.called

    def test_refresh_coverage_skips_if_client_unavailable(self):
        pyramid = SourcePyramid()
        mock_nlm = MagicMock()
        mock_client = MagicMock()
        mock_client.is_available.return_value = False

        with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=mock_nlm):
            pyramid.refresh_coverage("nb-test-123", mock_client)

        assert not mock_nlm.add_text_source.called


class TestSingleton:
    def test_singleton_returns_same_instance(self):
        p1 = get_source_pyramid()
        p2 = get_source_pyramid()
        assert p1 is p2
