"""Comprehensive tests for engine.nexus.task_spec.

Covers TaskSpec validation, ResultSchema validation and scoring,
ValidatedTaskResult lifecycle, built-in schemas, and public helpers.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from engine.nexus.task_spec import (
    BUILTIN_SCHEMAS,
    VALID_FORMATS,
    VALID_PRIORITIES,
    VALID_TASK_TYPES,
    ResultSchema,
    TaskSpec,
    ValidatedTaskResult,
    ValidationResult,
    get_schema,
    score_output,
    validate_result,
    validate_spec,
)


# ──── TaskSpec Validation ──────────────────────────────────────────────────────


class TestTaskSpecValidation:
    """TaskSpec.validate() pre-flight checks."""

    def test_valid_spec_passes(self) -> None:
        """Valid spec with all defaults passes validation."""
        spec = TaskSpec(task_type="evaluate", prompt="Rate this dialog")
        vr = spec.validate()
        assert vr.ok
        assert vr.errors == []

    def test_unknown_task_type_fails(self) -> None:
        """Unknown task_type produces validation error."""
        spec = TaskSpec(task_type="unknown_type", prompt="test")
        vr = spec.validate()
        assert not vr.ok
        assert any("task_type" in e for e in vr.errors)

    def test_empty_prompt_fails(self) -> None:
        """Empty prompt produces validation error."""
        spec = TaskSpec(task_type="evaluate", prompt="")
        vr = spec.validate()
        assert not vr.ok
        assert any("prompt" in e for e in vr.errors)

    def test_whitespace_only_prompt_fails(self) -> None:
        """Whitespace-only prompt fails validation."""
        spec = TaskSpec(task_type="evaluate", prompt="   \n  ")
        vr = spec.validate()
        assert not vr.ok
        assert any("prompt" in e for e in vr.errors)

    def test_negative_temperature_fails(self) -> None:
        """Temperature < 0 fails validation."""
        spec = TaskSpec(task_type="evaluate", prompt="test", temperature=-0.1)
        vr = spec.validate()
        assert not vr.ok
        assert any("temperature" in e for e in vr.errors)

    def test_temperature_above_2_fails(self) -> None:
        """Temperature > 2.0 fails validation."""
        spec = TaskSpec(task_type="evaluate", prompt="test", temperature=2.1)
        vr = spec.validate()
        assert not vr.ok
        assert any("temperature" in e for e in vr.errors)

    def test_zero_max_tokens_fails(self) -> None:
        """max_tokens < 1 fails validation."""
        spec = TaskSpec(task_type="evaluate", prompt="test", max_tokens=0)
        vr = spec.validate()
        assert not vr.ok
        assert any("max_tokens" in e for e in vr.errors)

    def test_negative_timeout_fails(self) -> None:
        """timeout_s <= 0 fails validation."""
        spec = TaskSpec(task_type="evaluate", prompt="test", timeout_s=-5.0)
        vr = spec.validate()
        assert not vr.ok
        assert any("timeout" in e.lower() for e in vr.errors)

    def test_negative_retries_fails(self) -> None:
        """max_retries < 0 fails validation."""
        spec = TaskSpec(task_type="evaluate", prompt="test", max_retries=-1)
        vr = spec.validate()
        assert not vr.ok
        assert any("retries" in e.lower() for e in vr.errors)

    def test_invalid_format_fails(self) -> None:
        """Unknown expected_format fails validation."""
        spec = TaskSpec(
            task_type="evaluate", prompt="test", expected_format="yaml"
        )
        vr = spec.validate()
        assert not vr.ok
        assert any("format" in e.lower() for e in vr.errors)

    def test_invalid_priority_fails(self) -> None:
        """Unknown priority fails validation."""
        spec = TaskSpec(task_type="evaluate", prompt="test", priority="urgent")
        vr = spec.validate()
        assert not vr.ok
        assert any("priority" in e.lower() for e in vr.errors)

    def test_high_temperature_warns(self) -> None:
        """Temperature > 1.5 generates warning but still valid."""
        spec = TaskSpec(task_type="evaluate", prompt="test", temperature=1.8)
        vr = spec.validate()
        assert vr.ok
        assert len(vr.warnings) > 0
        assert any("temperature" in w.lower() for w in vr.warnings)


# ──── TaskSpec.to_submit_kwargs ────────────────────────────────────────────────


class TestTaskSpecToSubmitKwargs:
    """TaskSpec.to_submit_kwargs() conversion to bridge kwargs."""

    def test_to_submit_kwargs_basic(self) -> None:
        """Basic spec converts to correct kwargs."""
        spec = TaskSpec(task_type="evaluate", prompt="Rate this")
        kwargs = spec.to_submit_kwargs()
        assert kwargs["prompt"] == "Rate this"
        assert kwargs["task_type"] == "evaluate"
        assert "priority" in kwargs
        assert kwargs["priority"] == "normal"

    def test_to_submit_kwargs_with_context(self) -> None:
        """Context and metadata included when set."""
        ctx = {"scene": "bedroom"}
        meta = {"user": "tester"}
        spec = TaskSpec(
            task_type="evaluate",
            prompt="Rate this",
            context=ctx,
            metadata=meta,
        )
        kwargs = spec.to_submit_kwargs()
        assert kwargs["context"] == ctx
        assert kwargs["metadata"] == meta

    def test_to_submit_kwargs_custom_format(self) -> None:
        """Non-default format appears in kwargs."""
        spec = TaskSpec(
            task_type="generate", prompt="Make JSON", expected_format="json"
        )
        kwargs = spec.to_submit_kwargs()
        assert kwargs["expected_format"] == "json"

    def test_to_submit_kwargs_default_values_omitted(self) -> None:
        """Default timeout/retries not in kwargs."""
        spec = TaskSpec(task_type="evaluate", prompt="test")
        kwargs = spec.to_submit_kwargs()
        # Defaults (timeout_s=120.0, max_retries=3, format=text) are omitted
        assert "timeout_s" not in kwargs
        assert "max_retries" not in kwargs
        assert "expected_format" not in kwargs


# ──── ResultSchema Validation ──────────────────────────────────────────────────


class TestResultSchemaValidation:
    """ResultSchema.validate() structural checks."""

    def test_schema_too_short(self) -> None:
        """Output shorter than min_length fails."""
        schema = ResultSchema(task_type="test", min_length=50)
        vr = schema.validate("short")
        assert not vr.ok
        assert any("too short" in e.lower() for e in vr.errors)

    def test_schema_too_long_warns(self) -> None:
        """Output exceeding max_length produces warning, not error."""
        schema = ResultSchema(task_type="test", min_length=1, max_length=10)
        vr = schema.validate("A" * 100)
        assert vr.ok  # still valid — max_length is a warning
        assert len(vr.warnings) > 0
        assert any("max length" in w.lower() for w in vr.warnings)

    def test_required_pattern_present(self) -> None:
        """Output with required pattern passes."""
        schema = ResultSchema(
            task_type="test",
            min_length=1,
            required_patterns=[r"\d+/10"],
        )
        vr = schema.validate("Rating: 7/10 — good quality.")
        assert vr.ok

    def test_required_pattern_missing(self) -> None:
        """Output without required pattern fails."""
        schema = ResultSchema(
            task_type="test",
            min_length=1,
            required_patterns=[r"\d+/10"],
        )
        vr = schema.validate("This is a long enough output with no rating.")
        assert not vr.ok
        assert any("required pattern" in e.lower() for e in vr.errors)

    def test_forbidden_pattern_detected(self) -> None:
        """Output with forbidden pattern fails."""
        schema = ResultSchema(
            task_type="test",
            min_length=1,
            forbidden_patterns=[r"(?i)TODO"],
        )
        vr = schema.validate("This has a TODO marker in it, which is bad.")
        assert not vr.ok
        assert any("forbidden" in e.lower() for e in vr.errors)

    def test_expected_sections_present(self) -> None:
        """Output containing expected section headers passes."""
        schema = ResultSchema(
            task_type="test",
            min_length=1,
            expected_sections=["Summary", "Details"],
        )
        output = "Summary\nThis is the summary.\n\nDetails\nHere are the details."
        vr = schema.validate(output)
        # Sections found — no warnings about missing sections
        missing_warnings = [w for w in vr.warnings if "missing expected" in w.lower()]
        assert len(missing_warnings) == 0

    def test_json_schema_valid(self) -> None:
        """Valid JSON matching required keys passes JSON schema check."""
        schema = ResultSchema(
            task_type="test",
            min_length=1,
            json_schema={
                "required": ["name", "score"],
                "properties": {"name": {}, "score": {}},
            },
        )
        output = json.dumps({"name": "test", "score": 95})
        vr = schema.validate(output)
        assert vr.ok

    def test_json_schema_invalid(self) -> None:
        """Non-JSON output fails JSON schema validation."""
        schema = ResultSchema(
            task_type="test",
            min_length=1,
            json_schema={
                "required": ["name"],
                "properties": {"name": {}},
            },
        )
        vr = schema.validate("This is not JSON at all, just plain text here.")
        assert not vr.ok
        assert any("json" in e.lower() for e in vr.errors)


# ──── Quality Scoring ──────────────────────────────────────────────────────────


class TestQualityScoring:
    """ResultSchema.score_quality() and score_output() heuristics."""

    def test_baseline_quality_empty(self) -> None:
        """Empty output scores 0."""
        schema = ResultSchema(task_type="test")
        assert schema.score_quality("") == 0.0

    def test_baseline_quality_short(self) -> None:
        """Very short output scores low."""
        schema = ResultSchema(task_type="test")
        score = schema.score_quality("ok")
        assert score < 0.3

    def test_baseline_quality_structured(self) -> None:
        """Well-structured output scores high."""
        schema = ResultSchema(task_type="test")
        output = (
            "## Analysis\n\n"
            "The system performs well under load. Response times are "
            "consistently below 200ms. Memory usage stays stable.\n\n"
            "- Point one is important.\n"
            "- Point two is also notable.\n\n"
            "Overall, the results look promising."
        )
        score = schema.score_quality(output)
        assert score >= 0.5

    def test_rubric_quality_evaluate(self) -> None:
        """Evaluate schema scores output with rating highly."""
        schema = BUILTIN_SCHEMAS["evaluate"]
        output = (
            "Rating: 8/10. The dialog is coherent and engaging. "
            "The character stays in role because the personality traits "
            "are well defined. The reasoning behind each response is clear "
            "and justified by the context provided."
        )
        score = schema.score_quality(output)
        assert score >= 0.5

    def test_score_output_convenience(self) -> None:
        """score_output() returns float for known task type."""
        output = (
            "Rating: 7/10. Good quality because the structure is sound. "
            "Therefore the overall assessment is positive."
        )
        score = score_output(output, "evaluate")
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_score_output_unknown_type(self) -> None:
        """score_output() for unknown type uses baseline scoring."""
        output = (
            "This is a reasonable response with multiple sentences. "
            "It has some structure. The content is relevant."
        )
        score = score_output(output, "nonexistent_type")
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0


# ──── ValidatedTaskResult ──────────────────────────────────────────────────────


class TestValidatedTaskResult:
    """ValidatedTaskResult properties and factory method."""

    def test_validated_result_ok_completed(self) -> None:
        """ok is True when status=completed and no error."""
        result = ValidatedTaskResult(
            task_id="t1", status="completed", output="done", error=""
        )
        assert result.ok

    def test_validated_result_ok_failed(self) -> None:
        """ok is False when status=failed."""
        result = ValidatedTaskResult(
            task_id="t1", status="failed", output="", error="timeout"
        )
        assert not result.ok

    def test_validated_result_ok_with_error(self) -> None:
        """ok is False when status=completed but error is set."""
        result = ValidatedTaskResult(
            task_id="t1", status="completed", error="partial failure"
        )
        assert not result.ok

    def test_validated_result_fully_valid(self) -> None:
        """fully_valid when ok + validated + quality >= 0.5."""
        result = ValidatedTaskResult(
            task_id="t1",
            status="completed",
            output="good result",
            error="",
            validated=True,
            quality_score=0.75,
        )
        assert result.fully_valid

    def test_validated_result_not_fully_valid_low_quality(self) -> None:
        """fully_valid is False when quality_score < 0.5."""
        result = ValidatedTaskResult(
            task_id="t1",
            status="completed",
            output="ok",
            error="",
            validated=True,
            quality_score=0.3,
        )
        assert not result.fully_valid

    def test_validated_result_from_task_result(self) -> None:
        """from_task_result creates result from duck-typed object."""
        fake = SimpleNamespace(
            task_id="abc-123",
            status="completed",
            output="Some output text",
            model="qwen3-0.6b",
            latency_ms=245.5,
            tokens_generated=42,
            tps=17.1,
            error="",
            metadata={"key": "val"},
        )
        vtr = ValidatedTaskResult.from_task_result(fake, "evaluate")
        assert vtr.task_id == "abc-123"
        assert vtr.task_type == "evaluate"
        assert vtr.status == "completed"
        assert vtr.output == "Some output text"
        assert vtr.model == "qwen3-0.6b"
        assert vtr.latency_ms == 245.5
        assert vtr.tokens_generated == 42
        assert vtr.error == ""
        assert vtr.metadata == {"key": "val"}

    def test_validated_result_from_task_result_missing_attrs(self) -> None:
        """from_task_result handles missing attributes gracefully."""
        fake = SimpleNamespace()
        vtr = ValidatedTaskResult.from_task_result(fake, "summarize")
        assert vtr.task_id == ""
        assert vtr.task_type == "summarize"
        assert vtr.status == "pending"

    def test_validated_result_to_dict(self) -> None:
        """to_dict() includes all fields and computed properties."""
        result = ValidatedTaskResult(
            task_id="t1",
            task_type="evaluate",
            status="completed",
            output="output text",
            model="test-model",
            latency_ms=100.123,
            tokens_generated=50,
            tps=25.456,
            error="",
            validated=True,
            quality_score=0.85,
            schema_match=True,
        )
        d = result.to_dict()
        assert d["task_id"] == "t1"
        assert d["task_type"] == "evaluate"
        assert d["status"] == "completed"
        assert d["output"] == "output text"
        assert d["model"] == "test-model"
        assert d["latency_ms"] == 100.12
        assert d["tokens_generated"] == 50
        assert d["tps"] == 25.46
        assert d["error"] == ""
        assert d["validated"] is True
        assert d["quality_score"] == 0.85
        assert d["schema_match"] is True
        assert d["ok"] is True
        assert d["fully_valid"] is True


# ──── validate_result Function ─────────────────────────────────────────────────


class TestValidateResult:
    """validate_result() top-level helper."""

    def test_validate_result_with_builtin_schema(self) -> None:
        """validate_result uses builtin schema for known type."""
        output = (
            "Rating: 8/10. The dialog is solid because it maintains "
            "character voice. The reasoning is justified and coherent."
        )
        vtr = validate_result(output, "evaluate")
        assert vtr.validated
        assert vtr.task_type == "evaluate"
        assert vtr.status == "completed"
        assert isinstance(vtr.quality_score, float)

    def test_validate_result_custom_schema(self) -> None:
        """validate_result uses custom schema when provided."""
        custom = ResultSchema(
            task_type="custom",
            min_length=5,
            max_length=100,
            required_patterns=[r"PASS"],
        )
        vtr = validate_result("Test result: PASS — all clear.", "custom", schema=custom)
        assert vtr.validated
        assert vtr.schema_match

    def test_validate_result_no_schema(self) -> None:
        """validate_result uses baseline scoring for unknown type."""
        vtr = validate_result(
            "Some output for a type that has no schema defined anywhere.",
            "totally_unknown_type_xyz",
        )
        assert vtr.validated
        assert vtr.schema_match  # no schema = auto-pass
        assert isinstance(vtr.quality_score, float)

    def test_validate_result_passing_output(self) -> None:
        """Good output for evaluate type gets positive quality score."""
        output = (
            "Rating: 9/10. Excellent work because the dialog flows naturally. "
            "The character's personality shines through. Therefore this is a "
            "strong example of in-character roleplay."
        )
        vtr = validate_result(output, "evaluate")
        assert vtr.schema_match
        assert vtr.quality_score > 0.0

    def test_validate_result_failing_output(self) -> None:
        """Bad output (too short) fails validation."""
        vtr = validate_result("no", "evaluate")
        assert vtr.validated
        assert not vtr.schema_match
        assert len(vtr.validation_errors) > 0


# ──── Built-in Schemas ─────────────────────────────────────────────────────────


class TestBuiltinSchemas:
    """BUILTIN_SCHEMAS coverage and get_schema() lookup."""

    def test_all_task_types_have_schemas(self) -> None:
        """Every VALID_TASK_TYPE has a BUILTIN_SCHEMA."""
        for task_type in VALID_TASK_TYPES:
            assert task_type in BUILTIN_SCHEMAS, (
                f"Missing builtin schema for {task_type}"
            )

    def test_builtin_schema_count(self) -> None:
        """There are exactly 11 built-in schemas matching 11 task types."""
        assert len(BUILTIN_SCHEMAS) == len(VALID_TASK_TYPES) == 11

    def test_get_schema_known(self) -> None:
        """get_schema returns schema for known type."""
        schema = get_schema("evaluate")
        assert schema is not None
        assert isinstance(schema, ResultSchema)
        assert schema.task_type == "evaluate"

    def test_get_schema_unknown(self) -> None:
        """get_schema returns None for unknown type."""
        assert get_schema("nonexistent_type") is None


# ──── ValidationResult ─────────────────────────────────────────────────────────


class TestValidationResult:
    """ValidationResult serialization and properties."""

    def test_validation_result_to_dict(self) -> None:
        """to_dict produces correct structure."""
        vr = ValidationResult(
            valid=False,
            errors=["bad input"],
            warnings=["watch out"],
        )
        d = vr.to_dict()
        assert d["valid"] is False
        assert d["errors"] == ["bad input"]
        assert d["warnings"] == ["watch out"]

    def test_validation_result_ok_alias(self) -> None:
        """ok property aliases valid."""
        vr_true = ValidationResult(valid=True)
        vr_false = ValidationResult(valid=False, errors=["err"])
        assert vr_true.ok is True
        assert vr_false.ok is False


# ──── Constants Sanity ─────────────────────────────────────────────────────────


class TestConstants:
    """Verify constant sets contain expected values."""

    def test_valid_task_types_contents(self) -> None:
        """VALID_TASK_TYPES contains core types."""
        expected = {
            "evaluate", "summarize", "generate", "classify", "compare",
            "code_review", "security_check", "test_generate",
            "doc_generate", "translate", "refactor",
        }
        assert VALID_TASK_TYPES == expected

    def test_valid_formats_contents(self) -> None:
        """VALID_FORMATS contains text, json, code, markdown."""
        assert VALID_FORMATS == frozenset({"text", "json", "code", "markdown"})

    def test_valid_priorities_contents(self) -> None:
        """VALID_PRIORITIES contains all priority levels."""
        assert VALID_PRIORITIES == frozenset({
            "critical", "high", "normal", "low", "background",
        })


# ──── Edge Cases ───────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_boundary_temperature_zero(self) -> None:
        """Temperature at exact boundary 0.0 is valid."""
        spec = TaskSpec(task_type="evaluate", prompt="test", temperature=0.0)
        assert spec.validate().ok

    def test_boundary_temperature_two(self) -> None:
        """Temperature at exact boundary 2.0 is valid."""
        spec = TaskSpec(task_type="evaluate", prompt="test", temperature=2.0)
        assert spec.validate().ok

    def test_max_tokens_one(self) -> None:
        """max_tokens=1 is the minimum valid value."""
        spec = TaskSpec(task_type="evaluate", prompt="test", max_tokens=1)
        assert spec.validate().ok

    def test_max_retries_zero(self) -> None:
        """max_retries=0 is valid (no retries)."""
        spec = TaskSpec(task_type="evaluate", prompt="test", max_retries=0)
        assert spec.validate().ok

    def test_all_valid_formats_accepted(self) -> None:
        """Every entry in VALID_FORMATS passes validation."""
        for fmt in VALID_FORMATS:
            spec = TaskSpec(
                task_type="evaluate", prompt="test", expected_format=fmt
            )
            vr = spec.validate()
            assert vr.ok, f"Format '{fmt}' should be valid"

    def test_all_valid_priorities_accepted(self) -> None:
        """Every entry in VALID_PRIORITIES passes validation."""
        for pri in VALID_PRIORITIES:
            spec = TaskSpec(
                task_type="evaluate", prompt="test", priority=pri
            )
            vr = spec.validate()
            assert vr.ok, f"Priority '{pri}' should be valid"

    def test_all_valid_task_types_accepted(self) -> None:
        """Every entry in VALID_TASK_TYPES passes validation."""
        for tt in VALID_TASK_TYPES:
            spec = TaskSpec(task_type=tt, prompt="test")
            vr = spec.validate()
            assert vr.ok, f"Task type '{tt}' should be valid"

    def test_to_submit_kwargs_with_tags(self) -> None:
        """Tags list appears in kwargs when set."""
        spec = TaskSpec(
            task_type="evaluate",
            prompt="test",
            tags=["perf", "nightly"],
        )
        kwargs = spec.to_submit_kwargs()
        assert kwargs["tags"] == ["perf", "nightly"]

    def test_to_submit_kwargs_nondefault_timeout(self) -> None:
        """Non-default timeout_s appears in kwargs."""
        spec = TaskSpec(task_type="evaluate", prompt="test", timeout_s=60.0)
        kwargs = spec.to_submit_kwargs()
        assert kwargs["timeout_s"] == 60.0

    def test_to_submit_kwargs_nondefault_retries(self) -> None:
        """Non-default max_retries appears in kwargs."""
        spec = TaskSpec(task_type="evaluate", prompt="test", max_retries=1)
        kwargs = spec.to_submit_kwargs()
        assert kwargs["max_retries"] == 1

    def test_schema_missing_expected_sections_warns(self) -> None:
        """Missing expected sections produce warnings, not errors."""
        schema = ResultSchema(
            task_type="test",
            min_length=1,
            expected_sections=["Introduction", "Conclusion"],
        )
        vr = schema.validate("Just some text without section headers here.")
        # Missing sections are warnings, not errors
        assert vr.ok
        assert any("missing expected" in w.lower() for w in vr.warnings)

    def test_validate_result_returns_completed_status(self) -> None:
        """validate_result always sets status to completed."""
        vtr = validate_result("some output", "summarize")
        assert vtr.status == "completed"
