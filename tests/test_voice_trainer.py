"""Tests for training/voice_trainer.py."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from training.voice_trainer import VoiceTrainer, VoiceTrainResult


def test_collect_sample_writes_to_samples_jsonl(tmp_path: Path) -> None:
    """collect_sample writes metadata to samples.jsonl."""
    trainer = VoiceTrainer(base_dir=tmp_path)
    trainer.collect_sample("aria", "Hello world", str(tmp_path / "test.wav"), 0.9, "piper")

    samples_path = tmp_path / "aria" / "piper" / "samples.jsonl"
    assert samples_path.exists()
    records = [json.loads(l) for l in samples_path.read_text().splitlines() if l.strip()]
    assert len(records) == 1
    assert records[0]["character_id"] == "aria"
    assert records[0]["backend"] == "piper"


def test_collect_sample_all_backends(tmp_path: Path) -> None:
    """collect_sample works for all supported backends."""
    trainer = VoiceTrainer(base_dir=tmp_path)
    for backend in ("piper", "qwen3", "orpheus"):
        trainer.collect_sample("lola", f"test {backend}", f"audio_{backend}.wav", 0.8, backend)

    for backend in ("piper", "qwen3", "orpheus"):
        samples_path = tmp_path / "lola" / backend / "samples.jsonl"
        assert samples_path.exists()


def test_collect_sample_unknown_backend_ignored(tmp_path: Path) -> None:
    """collect_sample with unknown backend is ignored without crashing."""
    trainer = VoiceTrainer(base_dir=tmp_path)
    trainer.collect_sample("aria", "test", "audio.wav", 0.9, "unknown_backend")
    # No file should be created for unknown backend
    unknown_path = tmp_path / "aria" / "unknown_backend" / "samples.jsonl"
    assert not unknown_path.exists()


def test_get_character_stats(tmp_path: Path) -> None:
    """get_character_stats returns sample counts per backend."""
    trainer = VoiceTrainer(base_dir=tmp_path)
    trainer.collect_sample("lola", "text1", "audio1.wav", 0.8, "piper")
    trainer.collect_sample("lola", "text2", "audio2.wav", 0.9, "qwen3")
    trainer.collect_sample("lola", "text3", "audio3.wav", 0.7, "piper")

    stats = trainer.get_character_stats("lola")
    assert stats["piper"] == 2
    assert stats["qwen3"] == 1
    assert stats.get("orpheus", 0) == 0


def test_get_all_stats(tmp_path: Path) -> None:
    """get_all_stats returns stats for all characters."""
    trainer = VoiceTrainer(base_dir=tmp_path)
    trainer.collect_sample("aria", "hello", "a.wav", 1.0, "piper")
    trainer.collect_sample("viktor", "world", "b.wav", 0.9, "orpheus")

    stats = trainer.get_all_stats()
    assert "aria" in stats
    assert "viktor" in stats
    assert stats["aria"]["piper"] == 1


def test_train_piper_missing_data_returns_error(tmp_path: Path) -> None:
    """train_piper returns error result when no data available."""
    trainer = VoiceTrainer(base_dir=tmp_path)
    result = trainer.train_piper("unknown_character", force=False)
    assert isinstance(result, VoiceTrainResult)
    assert result.success is False
    assert result.character_id == "unknown_character"
    assert result.backend == "piper"
    assert result.error is not None


def test_train_below_threshold_returns_error(tmp_path: Path) -> None:
    """Training below threshold returns error unless force=True."""
    trainer = VoiceTrainer(base_dir=tmp_path)
    trainer.collect_sample("aria", "hello", "a.wav", 1.0, "piper")

    result = trainer.train_piper("aria", force=False, min_samples=5)
    assert result.success is False
    assert "Insufficient" in result.error


def test_auto_train_all_skips_below_threshold(tmp_path: Path) -> None:
    """auto_train_all skips characters below min_samples threshold."""
    trainer = VoiceTrainer(base_dir=tmp_path)
    # Only 1 sample — below default threshold of 30
    trainer.collect_sample("aria", "hello", "a.wav", 1.0, "piper")

    results = trainer.auto_train_all(min_samples=30)
    # No training should happen
    assert len(results) == 0


def test_voice_train_result_to_dict() -> None:
    """VoiceTrainResult.to_dict() returns correct structure."""
    result = VoiceTrainResult(
        character_id="aria",
        backend="piper",
        success=True,
        samples_used=50,
        output_path="/some/path",
    )
    d = result.to_dict()
    assert d["character_id"] == "aria"
    assert d["backend"] == "piper"
    assert d["success"] is True
    assert d["samples_used"] == 50


def test_get_voice_trainer_returns_singleton() -> None:
    """get_voice_trainer() returns the same instance on repeated calls."""
    import training.voice_trainer as vt_module
    original = vt_module._instance
    vt_module._instance = None
    try:
        from training.voice_trainer import get_voice_trainer
        t1 = get_voice_trainer()
        t2 = get_voice_trainer()
        assert t1 is t2
    finally:
        vt_module._instance = original
