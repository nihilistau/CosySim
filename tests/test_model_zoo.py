"""Tests for training/model_zoo.py."""
import pytest
from training.model_zoo import (
    MODEL_ZOO,
    ModelSpec,
    get_spec,
    get_conversation_specs,
    get_nlp_specs,
    get_voice_specs,
    list_specs,
)


def test_model_zoo_has_all_types() -> None:
    """All 14 model types must be present."""
    expected = {
        "qa_evaluator", "conversation_analyzer", "syntax_fixer",
        "router_v2", "router_v3", "knowledge_synthesizer",
        "tool_dispatch", "grammar_scanner", "output_evaluator",
        "conversational", "coder",
        "voice_piper", "voice_qwen3", "voice_orpheus",
    }
    for key in expected:
        assert key in MODEL_ZOO, f"Missing model type: {key}"


def test_get_spec_returns_correct() -> None:
    """get_spec returns correct spec with proper fields."""
    spec = get_spec("tool_dispatch")
    assert spec.id == "tool_dispatch"
    assert spec.base_model_alias == "qwen-270m"
    assert spec.task_type == "structured_output"
    assert spec.train_threshold == 200
    assert "skill_calls" in spec.collect_from


def test_get_spec_missing_raises_key_error() -> None:
    """get_spec raises KeyError for unknown model type."""
    with pytest.raises(KeyError):
        get_spec("nonexistent_model_type")


def test_list_specs_filter_by_task_type() -> None:
    """list_specs filters by task_type correctly."""
    classification = list_specs(task_type="classification")
    assert all(s.task_type == "classification" for s in classification)
    assert len(classification) >= 2


def test_list_specs_sorted_by_priority() -> None:
    """list_specs returns specs sorted by priority."""
    specs = list_specs()
    priorities = [s.priority for s in specs]
    assert priorities == sorted(priorities)


def test_get_nlp_specs_excludes_voice() -> None:
    """get_nlp_specs excludes voice model types."""
    nlp = get_nlp_specs()
    voice_types = {"voice_piper", "voice_qwen3", "voice_orpheus"}
    for spec in nlp:
        assert spec.task_type not in voice_types


def test_get_voice_specs() -> None:
    """get_voice_specs returns only voice types."""
    voice = get_voice_specs()
    assert len(voice) == 3
    backends = {s.voice_backend for s in voice}
    assert backends == {"piper", "qwen3", "orpheus"}


def test_get_conversation_specs() -> None:
    """get_conversation_specs returns only conversation types."""
    conv = get_conversation_specs()
    assert len(conv) >= 1
    assert all(s.task_type == "conversation" for s in conv)


def test_all_specs_have_required_fields() -> None:
    """All ModelSpec entries have non-empty required fields."""
    for spec_id, spec in MODEL_ZOO.items():
        assert spec.id == spec_id, f"ID mismatch for {spec_id}"
        assert spec.display_name, f"Missing display_name for {spec_id}"
        assert spec.base_model_alias, f"Missing base_model_alias for {spec_id}"
        assert spec.task_type, f"Missing task_type for {spec_id}"
        assert spec.dataset_key, f"Missing dataset_key for {spec_id}"
        assert spec.train_threshold > 0, f"Invalid train_threshold for {spec_id}"


def test_voice_specs_have_character_ids() -> None:
    """Voice specs have character_ids populated."""
    for spec in get_voice_specs():
        assert len(spec.character_ids) > 0, f"Voice spec {spec.id} missing character_ids"
        assert spec.voice_backend is not None, f"Voice spec {spec.id} missing voice_backend"
