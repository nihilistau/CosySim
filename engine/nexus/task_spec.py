"""TaskSpec validation module for LMSTaskBridge.

Provides structured task specification, result validation, and quality scoring
for delegated LMStudio tasks. Designed to complement the existing LMSTaskBridge
without circular imports — all dataclasses are self-contained.

Typical usage::

    from engine.nexus.task_spec import TaskSpec, validate_result

    spec = TaskSpec(task_type="evaluate", prompt="Rate this dialog")
    vr = spec.validate()
    if vr.ok:
        kwargs = spec.to_submit_kwargs()
        task_id = bridge.submit(**kwargs)
        # ... after completion ...
        validated = validate_result(result.output, "evaluate")
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, FrozenSet, List, Optional

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ──── Constants ────────────────────────────────────────────────────────────────

VALID_TASK_TYPES: FrozenSet[str] = frozenset({
    "evaluate",
    "summarize",
    "generate",
    "classify",
    "compare",
    "code_review",
    "security_check",
    "test_generate",
    "doc_generate",
    "translate",
    "refactor",
})

VALID_FORMATS: FrozenSet[str] = frozenset({"text", "json", "code", "markdown"})

VALID_PRIORITIES: FrozenSet[str] = frozenset({
    "critical", "high", "normal", "low", "background",
})

# Maximum prompt length before we emit a warning (bytes-ish, chars).
_PROMPT_WARN_LENGTH = 100_000

# ──── ValidationResult ─────────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    """Outcome of a validation check.

    Attributes:
        valid: Whether the validated object passed all required checks.
        errors: Hard failures that block execution.
        warnings: Soft issues that should be noted but do not block.
    """

    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Alias for ``valid``."""
        return self.valid

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


# ──── TaskSpec ─────────────────────────────────────────────────────────────────


@dataclass
class TaskSpec:
    """Structured specification for a delegated task.

    Captures all parameters needed to submit a task to LMSTaskBridge with
    pre-flight validation.

    Attributes:
        task_type: One of VALID_TASK_TYPES (e.g. ``"evaluate"``).
        prompt: The user-facing prompt text.
        model: Target LMStudio model identifier (empty = auto-select).
        system_prompt: Override for the default system prompt.
        temperature: Sampling temperature (0.0–2.0).
        max_tokens: Maximum tokens to generate.
        priority: Priority name string matching LMSTaskBridge.Priority.
        timeout_s: Maximum execution time in seconds.
        max_retries: How many times to retry on failure.
        expected_format: Expected output format (text/json/code/markdown).
        expected_schema: Optional JSON Schema dict for structured output.
        context: Key-value context forwarded to the model.
        metadata: Extra metadata stored on the queued task.
        tags: Tags for filtering and tracking.
    """

    task_type: str
    prompt: str
    model: str = ""
    system_prompt: str = ""
    temperature: float = 0.7
    max_tokens: int = 1024
    priority: str = "normal"
    timeout_s: float = 120.0
    max_retries: int = 3
    expected_format: str = "text"
    expected_schema: Optional[Dict[str, Any]] = None
    context: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None

    # ── public API ──────────────────────────────────────────────────────────

    def validate(self) -> ValidationResult:
        """Run pre-flight validation on this spec.

        Returns:
            A ``ValidationResult`` with any errors or warnings.
        """
        return validate_spec(self)

    def to_submit_kwargs(self) -> Dict[str, Any]:
        """Convert this spec into keyword arguments for ``LMSTaskBridge.submit()``.

        Returns:
            A dict suitable for ``bridge.submit(**kwargs)``.
        """
        kwargs: Dict[str, Any] = {
            "prompt": self.prompt,
            "priority": self.priority,
            "model": self.model,
            "system_prompt": self.system_prompt,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "task_type": self.task_type,
        }
        # Pack extra fields into **kwargs that submit() stores as metadata
        if self.context is not None:
            kwargs["context"] = self.context
        if self.metadata is not None:
            kwargs["metadata"] = self.metadata
        if self.tags is not None:
            kwargs["tags"] = self.tags
        if self.expected_format != "text":
            kwargs["expected_format"] = self.expected_format
        if self.expected_schema is not None:
            kwargs["expected_schema"] = self.expected_schema
        if self.timeout_s != 120.0:
            kwargs["timeout_s"] = self.timeout_s
        if self.max_retries != 3:
            kwargs["max_retries"] = self.max_retries
        return kwargs


# ──── ResultSchema ─────────────────────────────────────────────────────────────


@dataclass
class ResultSchema:
    """Expected output schema for a task type.

    Defines structural, length, and pattern requirements that a task output
    must satisfy, plus a quality rubric for heuristic scoring.

    Attributes:
        task_type: The task type this schema applies to.
        min_length: Minimum acceptable output length in characters.
        max_length: Maximum acceptable output length in characters.
        required_patterns: Regex patterns that MUST appear in the output.
        forbidden_patterns: Regex patterns that MUST NOT appear.
        expected_sections: Section headers expected in the output.
        json_schema: Optional JSON Schema for structured output validation.
        quality_rubric: ``{criterion: weight}`` for heuristic quality scoring.
    """

    task_type: str
    min_length: int = 10
    max_length: int = 50_000
    required_patterns: List[str] = field(default_factory=list)
    forbidden_patterns: List[str] = field(default_factory=list)
    expected_sections: List[str] = field(default_factory=list)
    json_schema: Optional[Dict[str, Any]] = None
    quality_rubric: Optional[Dict[str, float]] = None

    # ── validation ──────────────────────────────────────────────────────────

    def validate(self, output: str) -> ValidationResult:
        """Validate *output* against this schema.

        Args:
            output: The raw text output from the task.

        Returns:
            A ``ValidationResult`` with structural errors and warnings.
        """
        errors: List[str] = []
        warnings: List[str] = []
        stripped = output.strip()
        length = len(stripped)

        # Length checks
        if length < self.min_length:
            errors.append(
                f"Output too short ({length} chars, minimum {self.min_length})"
            )
        if length > self.max_length:
            warnings.append(
                f"Output exceeds max length ({length} chars, maximum {self.max_length})"
            )

        # Required patterns
        for pattern in self.required_patterns:
            try:
                if not re.search(pattern, stripped):
                    errors.append(f"Missing required pattern: {pattern}")
            except re.error as exc:
                warnings.append(f"Invalid required pattern '{pattern}': {exc}")

        # Forbidden patterns
        for pattern in self.forbidden_patterns:
            try:
                if re.search(pattern, stripped):
                    errors.append(f"Contains forbidden pattern: {pattern}")
            except re.error as exc:
                warnings.append(f"Invalid forbidden pattern '{pattern}': {exc}")

        # Expected sections
        if self.expected_sections:
            missing = [
                sec for sec in self.expected_sections
                if sec.lower() not in stripped.lower()
            ]
            if missing:
                warnings.append(f"Missing expected sections: {', '.join(missing)}")

        # JSON Schema (lightweight — checks parsability + top-level keys)
        if self.json_schema is not None:
            json_errors = _validate_json_schema(stripped, self.json_schema)
            errors.extend(json_errors)

        return ValidationResult(valid=not errors, errors=errors, warnings=warnings)

    # ── quality scoring ─────────────────────────────────────────────────────

    def score_quality(self, output: str) -> float:
        """Heuristic quality score for *output* based on the rubric.

        Returns a score in the range ``[0.0, 1.0]``.

        Args:
            output: The raw text output from the task.

        Returns:
            A float quality score.
        """
        if not self.quality_rubric:
            return _baseline_quality_score(output)

        total_weight = sum(self.quality_rubric.values())
        if total_weight <= 0:
            return _baseline_quality_score(output)

        weighted_sum = 0.0
        for criterion, weight in self.quality_rubric.items():
            criterion_score = _score_criterion(criterion, output, self.task_type)
            weighted_sum += criterion_score * weight

        raw = weighted_sum / total_weight
        return max(0.0, min(1.0, raw))


# ──── ValidatedTaskResult ──────────────────────────────────────────────────────


@dataclass
class ValidatedTaskResult:
    """Task result enriched with validation status and quality scoring.

    Attributes:
        task_id: Unique task identifier.
        task_type: The task type that produced this result.
        status: Execution status (pending/running/completed/failed/cancelled).
        output: Raw text output.
        model: Model that produced the output.
        latency_ms: Execution latency in milliseconds.
        tokens_generated: Number of tokens produced.
        tps: Tokens per second.
        error: Error message, if any.
        metadata: Extra metadata from the task.
        validated: Whether validation has been run.
        validation_errors: List of validation error messages.
        quality_score: Heuristic quality score (0.0–1.0).
        schema_match: Whether the output matched its schema.
    """

    task_id: str = ""
    task_type: str = ""
    status: str = "pending"
    output: str = ""
    model: str = ""
    latency_ms: float = 0.0
    tokens_generated: int = 0
    tps: float = 0.0
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Validation fields
    validated: bool = False
    validation_errors: List[str] = field(default_factory=list)
    quality_score: float = 0.0
    schema_match: bool = False

    @classmethod
    def from_task_result(
        cls,
        result: Any,
        task_type: str,
    ) -> ValidatedTaskResult:
        """Create from an existing ``TaskResult`` (or duck-typed equivalent).

        Copies core fields from *result* and populates the ``task_type``.
        Does **not** run validation — call ``validate_result()`` for that.

        Args:
            result: A ``TaskResult`` instance or any object with matching attrs.
            task_type: The task type for schema lookup.

        Returns:
            A new ``ValidatedTaskResult``.
        """
        return cls(
            task_id=getattr(result, "task_id", ""),
            task_type=task_type,
            status=getattr(result, "status", "pending"),
            output=getattr(result, "output", ""),
            model=getattr(result, "model", ""),
            latency_ms=getattr(result, "latency_ms", 0.0),
            tokens_generated=getattr(result, "tokens_generated", 0),
            tps=getattr(result, "tps", 0.0),
            error=getattr(result, "error", ""),
            metadata=getattr(result, "metadata", None) or {},
        )

    @property
    def ok(self) -> bool:
        """Whether the task completed without errors."""
        return self.status == "completed" and not self.error

    @property
    def fully_valid(self) -> bool:
        """Whether the task completed, validated, and meets quality bar."""
        return self.ok and self.validated and self.quality_score >= 0.5

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status,
            "output": self.output,
            "model": self.model,
            "latency_ms": round(self.latency_ms, 2),
            "tokens_generated": self.tokens_generated,
            "tps": round(self.tps, 2),
            "error": self.error,
            "metadata": self.metadata,
            "validated": self.validated,
            "validation_errors": list(self.validation_errors),
            "quality_score": round(self.quality_score, 4),
            "schema_match": self.schema_match,
            "ok": self.ok,
            "fully_valid": self.fully_valid,
        }


# ──── Built-in Schemas ─────────────────────────────────────────────────────────

BUILTIN_SCHEMAS: Dict[str, ResultSchema] = {
    "evaluate": ResultSchema(
        task_type="evaluate",
        min_length=20,
        max_length=5000,
        required_patterns=[r"\d+"],
        quality_rubric={
            "has_rating": 0.4,
            "has_justification": 0.3,
            "coherent": 0.3,
        },
    ),
    "summarize": ResultSchema(
        task_type="summarize",
        min_length=30,
        max_length=3000,
        forbidden_patterns=[r"(?i)^I (?:cannot|can't|am unable)"],
        quality_rubric={
            "concise": 0.3,
            "complete": 0.4,
            "coherent": 0.3,
        },
    ),
    "generate": ResultSchema(
        task_type="generate",
        min_length=20,
        max_length=50_000,
        quality_rubric={
            "relevant": 0.4,
            "complete": 0.3,
            "creative": 0.3,
        },
    ),
    "classify": ResultSchema(
        task_type="classify",
        min_length=5,
        max_length=2000,
        quality_rubric={
            "has_label": 0.5,
            "has_confidence": 0.3,
            "coherent": 0.2,
        },
    ),
    "compare": ResultSchema(
        task_type="compare",
        min_length=50,
        max_length=10_000,
        quality_rubric={
            "covers_both": 0.4,
            "balanced": 0.3,
            "conclusion": 0.3,
        },
    ),
    "code_review": ResultSchema(
        task_type="code_review",
        min_length=30,
        max_length=15_000,
        quality_rubric={
            "identifies_issues": 0.4,
            "actionable": 0.3,
            "severity": 0.3,
        },
    ),
    "security_check": ResultSchema(
        task_type="security_check",
        min_length=30,
        max_length=15_000,
        required_patterns=[
            r"(?i)(vulnerab|risk|secure|safe|inject|xss|sql|auth)",
        ],
        quality_rubric={
            "identifies_risks": 0.4,
            "severity_rated": 0.3,
            "actionable": 0.3,
        },
    ),
    "test_generate": ResultSchema(
        task_type="test_generate",
        min_length=50,
        max_length=30_000,
        required_patterns=[r"(?:def test_|test |assert|expect)"],
        quality_rubric={
            "has_tests": 0.4,
            "covers_edge_cases": 0.3,
            "runnable": 0.3,
        },
    ),
    "doc_generate": ResultSchema(
        task_type="doc_generate",
        min_length=50,
        max_length=30_000,
        quality_rubric={
            "complete": 0.3,
            "clear": 0.3,
            "examples": 0.2,
            "structured": 0.2,
        },
    ),
    "translate": ResultSchema(
        task_type="translate",
        min_length=10,
        max_length=50_000,
        quality_rubric={
            "accuracy": 0.4,
            "fluency": 0.3,
            "complete": 0.3,
        },
    ),
    "refactor": ResultSchema(
        task_type="refactor",
        min_length=30,
        max_length=30_000,
        required_patterns=[
            r"(?:def |class |function |import |const |let |var )",
        ],
        quality_rubric={
            "improved": 0.4,
            "preserves_behavior": 0.3,
            "readable": 0.3,
        },
    ),
}


# ──── Public Helper Functions ──────────────────────────────────────────────────


def validate_spec(spec: TaskSpec) -> ValidationResult:
    """Validate a ``TaskSpec`` before submission.

    Checks task_type, prompt, numeric ranges, and format. Emits warnings for
    values that are technically valid but likely undesirable.

    Args:
        spec: The task specification to validate.

    Returns:
        A ``ValidationResult``.
    """
    errors: List[str] = []
    warnings: List[str] = []

    # ── hard errors ─────────────────────────────────────────────────────────
    if spec.task_type not in VALID_TASK_TYPES:
        errors.append(f"Unknown task_type: {spec.task_type}")

    if not spec.prompt or not spec.prompt.strip():
        errors.append("prompt is required")

    if spec.temperature < 0.0 or spec.temperature > 2.0:
        errors.append("temperature must be 0.0-2.0")

    if spec.max_tokens < 1:
        errors.append("max_tokens must be >= 1")

    if spec.timeout_s <= 0:
        errors.append("timeout_s must be positive")

    if spec.max_retries < 0:
        errors.append("max_retries must be >= 0")

    if spec.expected_format not in VALID_FORMATS:
        errors.append(f"Unknown expected_format: {spec.expected_format}")

    if spec.priority not in VALID_PRIORITIES:
        errors.append(f"Unknown priority: {spec.priority}")

    # Validate expected_schema is valid JSON Schema (top-level sanity)
    if spec.expected_schema is not None:
        if not isinstance(spec.expected_schema, dict):
            errors.append("expected_schema must be a dict")

    # ── soft warnings ───────────────────────────────────────────────────────
    if spec.temperature > 1.5:
        warnings.append("High temperature may produce inconsistent results")

    if spec.max_tokens > 8192:
        warnings.append("Large max_tokens may be slow for small models")

    if spec.prompt and len(spec.prompt) > _PROMPT_WARN_LENGTH:
        warnings.append("Very long prompt — consider chunking")

    if spec.timeout_s > 600:
        warnings.append("Timeout exceeds 10 minutes — may block workers")

    if spec.max_retries > 10:
        warnings.append("High retry count — consider whether failures are transient")

    return ValidationResult(valid=not errors, errors=errors, warnings=warnings)


def get_schema(task_type: str) -> Optional[ResultSchema]:
    """Get the built-in schema for a task type.

    Args:
        task_type: One of the valid task type strings.

    Returns:
        The corresponding ``ResultSchema``, or ``None`` if not found.
    """
    return BUILTIN_SCHEMAS.get(task_type)


def validate_result(
    output: str,
    task_type: str,
    schema: Optional[ResultSchema] = None,
) -> ValidatedTaskResult:
    """Validate task output against its schema and compute quality score.

    Uses ``BUILTIN_SCHEMAS`` when no custom *schema* is supplied. If the
    task_type has no built-in schema either, only baseline quality scoring
    is applied.

    Args:
        output: Raw text output from the task.
        task_type: The task type that produced the output.
        schema: Optional custom schema override.

    Returns:
        A ``ValidatedTaskResult`` with validation and scoring populated.
    """
    effective_schema = schema or BUILTIN_SCHEMAS.get(task_type)
    result = ValidatedTaskResult(
        task_type=task_type,
        status="completed",
        output=output,
    )

    if effective_schema is None:
        # No schema available — only baseline scoring
        result.validated = True
        result.schema_match = True
        result.quality_score = _baseline_quality_score(output)
        logger.debug(
            "No schema for task_type=%s, baseline score=%.2f",
            task_type,
            result.quality_score,
        )
        return result

    vr = effective_schema.validate(output)
    result.validated = True
    result.schema_match = vr.valid
    result.validation_errors = list(vr.errors)
    result.quality_score = effective_schema.score_quality(output)

    if not vr.valid:
        logger.info(
            "Validation failed for task_type=%s: %s",
            task_type,
            "; ".join(vr.errors),
        )

    return result


def score_output(output: str, task_type: str) -> float:
    """Score the quality of a task output.

    Convenience wrapper that returns just the float score.

    Args:
        output: Raw text output from the task.
        task_type: The task type for schema lookup.

    Returns:
        A quality score in ``[0.0, 1.0]``.
    """
    schema = BUILTIN_SCHEMAS.get(task_type)
    if schema is not None:
        return schema.score_quality(output)
    return _baseline_quality_score(output)


# ──── Private Helpers ──────────────────────────────────────────────────────────

# Compiled patterns reused across criterion scoring.
_RE_NUMERIC = re.compile(r"\d+(?:\.\d+)?")
_RE_SENTENCE_END = re.compile(r"[.!?]\s")
_RE_HEADING = re.compile(r"(?m)^#{1,6}\s|^[A-Z][A-Za-z ]{2,}:\s")
_RE_BULLET = re.compile(r"(?m)^[\-\*\•]\s|^\d+[.)]\s")
_RE_CODE_BLOCK = re.compile(r"```[\s\S]*?```|`[^`]+`")
_RE_CODE_CONSTRUCT = re.compile(
    r"(?:def |class |function |import |const |let |var |return |if |for |while )"
)
_RE_EXAMPLE = re.compile(r"(?i)(example|e\.g\.|for instance|such as|>>>)")
_RE_COMPARISON = re.compile(
    r"(?i)(however|whereas|on the other hand|in contrast|compared to|unlike|while)"
)
_RE_CONCLUSION = re.compile(
    r"(?i)(in conclusion|overall|therefore|thus|in summary|to summarize|"
    r"the winner|recommended|verdict|final)"
)
_RE_SEVERITY = re.compile(
    r"(?i)(critical|high|medium|low|info|warning|error|severe|minor|major)"
)
_RE_CONFIDENCE = re.compile(
    r"(?i)(confidence|probability|likelihood|certainty|score|%|\blikely\b|\bunlikely\b)"
)
_RE_EDGE_CASE = re.compile(
    r"(?i)(edge case|boundary|corner case|empty|null|none|zero|negative|overflow|"
    r"invalid|error handling|exception)"
)
_RE_REFUSAL = re.compile(r"(?i)^I (?:cannot|can't|am unable|don't)")
_RE_JUSTIFICATION = re.compile(
    r"(?i)(because|reason|due to|since|as a result|rationale|justification|therefore)"
)
_RE_ISSUE = re.compile(
    r"(?i)(issue|bug|problem|flaw|concern|smell|warning|error|risk|suggestion|"
    r"recommend|should|could be improved)"
)
_RE_ACTIONABLE = re.compile(
    r"(?i)(fix|change|replace|update|refactor|remove|add|consider|use|avoid|"
    r"instead|should|must|recommend)"
)


def _baseline_quality_score(output: str) -> float:
    """Fallback quality score when no rubric is available.

    Uses simple heuristics: non-empty, reasonable length, sentence structure.

    Args:
        output: Raw text output.

    Returns:
        A score in ``[0.0, 1.0]``.
    """
    stripped = output.strip()
    if not stripped:
        return 0.0

    score = 0.3  # Base score for non-empty output
    length = len(stripped)

    # Length bonus (sweet spot 50–5000 chars)
    if length >= 50:
        score += 0.15
    if length >= 200:
        score += 0.1

    # Sentence structure
    sentences = _RE_SENTENCE_END.findall(stripped)
    if len(sentences) >= 2:
        score += 0.15

    # Structure (headings or bullets)
    if _RE_HEADING.search(stripped) or _RE_BULLET.search(stripped):
        score += 0.15

    # Not a refusal
    if _RE_REFUSAL.search(stripped):
        score -= 0.3

    # Penalty for extremely short output
    if length < 10:
        score -= 0.2

    return max(0.0, min(1.0, score))


def _score_criterion(criterion: str, output: str, task_type: str) -> float:
    """Score a single quality criterion for *output*.

    Uses heuristic pattern matching and structural analysis rather than
    LLM-based evaluation. Each criterion returns a score in ``[0.0, 1.0]``.

    Args:
        criterion: The rubric criterion name (e.g. ``"has_rating"``).
        output: Raw text output.
        task_type: The task type for context-aware scoring.

    Returns:
        A float score for this criterion.
    """
    stripped = output.strip()
    if not stripped:
        return 0.0

    length = len(stripped)
    scorer = _CRITERION_SCORERS.get(criterion)
    if scorer is not None:
        return scorer(stripped, length, task_type)

    # Unknown criterion — give a neutral-positive score based on length
    return min(1.0, length / 200)


# ── individual criterion scorers ────────────────────────────────────────────


def _score_has_rating(text: str, length: int, task_type: str) -> float:
    """Check for numeric ratings (1-10, percentages, stars)."""
    numbers = _RE_NUMERIC.findall(text)
    if not numbers:
        return 0.0
    # Prefer numbers that look like ratings (1–10, 0–100)
    for n in numbers:
        val = float(n)
        if 1 <= val <= 10 or 0 <= val <= 100:
            return 1.0
    return 0.5


def _score_has_justification(text: str, length: int, task_type: str) -> float:
    """Check for reasoning/justification language."""
    matches = _RE_JUSTIFICATION.findall(text)
    if not matches:
        return 0.1
    if len(matches) >= 3:
        return 1.0
    return 0.4 + 0.2 * len(matches)


def _score_coherent(text: str, length: int, task_type: str) -> float:
    """Estimate coherence from sentence structure and length."""
    sentences = _RE_SENTENCE_END.findall(text)
    sentence_count = len(sentences) + (1 if not text.endswith((".", "!", "?")) else 0)
    if sentence_count < 1:
        return 0.2
    # Reasonable sentence count for the length
    avg_sentence_len = length / max(sentence_count, 1)
    if 30 <= avg_sentence_len <= 300:
        return 1.0
    if 15 <= avg_sentence_len <= 500:
        return 0.7
    return 0.3


def _score_concise(text: str, length: int, task_type: str) -> float:
    """Reward conciseness — shorter (but substantive) is better for summaries."""
    if length < 30:
        return 0.2  # Too short to be useful
    if length <= 500:
        return 1.0
    if length <= 1500:
        return 0.7
    if length <= 3000:
        return 0.4
    return 0.2  # Very long for a summary


def _score_complete(text: str, length: int, task_type: str) -> float:
    """Estimate completeness from structure and length."""
    score = 0.0
    # Minimum substance
    if length >= 50:
        score += 0.3
    if length >= 200:
        score += 0.2
    # Sentence endings (complete thoughts)
    if text.rstrip().endswith((".", "!", "?", "```")):
        score += 0.2
    # Has structure
    if _RE_HEADING.search(text) or _RE_BULLET.search(text):
        score += 0.15
    # Multiple paragraphs
    if text.count("\n\n") >= 1:
        score += 0.15
    return min(1.0, score)


def _score_creative(text: str, length: int, task_type: str) -> float:
    """Estimate creativity from vocabulary diversity and length."""
    words = text.lower().split()
    if len(words) < 5:
        return 0.1
    unique_ratio = len(set(words)) / len(words)
    # Higher unique word ratio suggests more creative vocabulary
    if unique_ratio >= 0.7:
        return 1.0
    if unique_ratio >= 0.5:
        return 0.7
    return 0.4


def _score_relevant(text: str, length: int, task_type: str) -> float:
    """Estimate relevance (non-refusal, substantial content)."""
    if _RE_REFUSAL.search(text):
        return 0.0
    if length < 20:
        return 0.2
    if length >= 100:
        return 0.8
    return 0.5


def _score_has_label(text: str, length: int, task_type: str) -> float:
    """Check for classification label presence."""
    # Look for common label patterns: "Label:", "Category:", quoted labels, etc.
    patterns = [
        r"(?i)(?:label|class|category|type|group|tag)\s*[:=]\s*\S+",
        r"(?i)^[A-Z][A-Za-z_\-]+$",
        r'(?i)"[A-Za-z_\-]+"',
    ]
    for pat in patterns:
        if re.search(pat, text, re.MULTILINE):
            return 1.0
    # Fallback: first line is short and looks like a label
    first_line = text.strip().split("\n")[0].strip()
    if len(first_line) < 50 and not first_line.endswith((".", "!")):
        return 0.6
    return 0.2


def _score_has_confidence(text: str, length: int, task_type: str) -> float:
    """Check for confidence/probability indicators."""
    if _RE_CONFIDENCE.search(text):
        return 1.0
    if _RE_NUMERIC.search(text):
        return 0.5
    return 0.1


def _score_covers_both(text: str, length: int, task_type: str) -> float:
    """Check that a comparison covers both sides."""
    comparisons = _RE_COMPARISON.findall(text)
    if len(comparisons) >= 2:
        return 1.0
    if len(comparisons) >= 1:
        return 0.6
    # At least has multiple sections or paragraphs
    if text.count("\n\n") >= 2:
        return 0.5
    return 0.2


def _score_balanced(text: str, length: int, task_type: str) -> float:
    """Check that a comparison is balanced (not one-sided)."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(paragraphs) < 2:
        return 0.3
    lengths = [len(p) for p in paragraphs]
    if not lengths:
        return 0.3
    max_len = max(lengths)
    min_len = min(lengths)
    if max_len == 0:
        return 0.3
    ratio = min_len / max_len
    if ratio >= 0.3:
        return 1.0
    if ratio >= 0.1:
        return 0.6
    return 0.3


def _score_conclusion(text: str, length: int, task_type: str) -> float:
    """Check for concluding statements."""
    if _RE_CONCLUSION.search(text):
        return 1.0
    # Last paragraph pattern
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if paragraphs and len(paragraphs[-1]) > 20:
        return 0.4
    return 0.1


def _score_identifies_issues(text: str, length: int, task_type: str) -> float:
    """Check for issue identification in reviews."""
    matches = _RE_ISSUE.findall(text)
    if len(matches) >= 3:
        return 1.0
    if len(matches) >= 1:
        return 0.5 + 0.15 * len(matches)
    return 0.1


def _score_actionable(text: str, length: int, task_type: str) -> float:
    """Check for actionable suggestions."""
    matches = _RE_ACTIONABLE.findall(text)
    if len(matches) >= 3:
        return 1.0
    if len(matches) >= 1:
        return 0.4 + 0.2 * len(matches)
    return 0.1


def _score_severity(text: str, length: int, task_type: str) -> float:
    """Check for severity ratings."""
    return 1.0 if _RE_SEVERITY.search(text) else 0.1


def _score_identifies_risks(text: str, length: int, task_type: str) -> float:
    """Check for security risk identification."""
    risk_terms = re.findall(
        r"(?i)(vulnerab|risk|threat|exploit|attack|injection|xss|csrf|"
        r"sql.?inject|auth.?bypass|overflow|privilege|escalat)",
        text,
    )
    if len(risk_terms) >= 3:
        return 1.0
    if len(risk_terms) >= 1:
        return 0.4 + 0.2 * len(risk_terms)
    return 0.1


def _score_severity_rated(text: str, length: int, task_type: str) -> float:
    """Check for severity ratings in security context."""
    return _score_severity(text, length, task_type)


def _score_has_tests(text: str, length: int, task_type: str) -> float:
    """Check for test function presence."""
    test_funcs = re.findall(r"(?:def test_\w+|it\(['\"]|describe\(['\"])", text)
    asserts = re.findall(r"(?:assert |expect\(|should\b)", text)
    count = len(test_funcs) + len(asserts)
    if count >= 5:
        return 1.0
    if count >= 2:
        return 0.6 + 0.1 * count
    if count >= 1:
        return 0.4
    return 0.1


def _score_covers_edge_cases(text: str, length: int, task_type: str) -> float:
    """Check for edge case coverage in tests."""
    matches = _RE_EDGE_CASE.findall(text)
    if len(matches) >= 3:
        return 1.0
    if len(matches) >= 1:
        return 0.4 + 0.2 * len(matches)
    return 0.1


def _score_runnable(text: str, length: int, task_type: str) -> float:
    """Check if generated code/tests look syntactically runnable."""
    has_code = bool(_RE_CODE_CONSTRUCT.search(text))
    has_blocks = bool(_RE_CODE_BLOCK.search(text))
    if has_code:
        return 1.0
    if has_blocks:
        return 0.7
    return 0.2


def _score_clear(text: str, length: int, task_type: str) -> float:
    """Estimate clarity from sentence structure."""
    return _score_coherent(text, length, task_type)


def _score_examples(text: str, length: int, task_type: str) -> float:
    """Check for examples in documentation."""
    if _RE_EXAMPLE.search(text):
        score = 0.6
        if _RE_CODE_BLOCK.search(text):
            score += 0.4
        return min(1.0, score)
    if _RE_CODE_BLOCK.search(text):
        return 0.5
    return 0.1


def _score_structured(text: str, length: int, task_type: str) -> float:
    """Check for structural elements (headings, bullets, sections)."""
    score = 0.0
    if _RE_HEADING.search(text):
        score += 0.4
    if _RE_BULLET.search(text):
        score += 0.3
    if text.count("\n\n") >= 2:
        score += 0.15
    if _RE_CODE_BLOCK.search(text):
        score += 0.15
    return min(1.0, max(0.1, score))


def _score_accuracy(text: str, length: int, task_type: str) -> float:
    """Estimate translation accuracy (heuristic: not a refusal, has substance)."""
    if _RE_REFUSAL.search(text):
        return 0.0
    if length < 10:
        return 0.2
    return 0.7  # Cannot truly judge accuracy without reference


def _score_fluency(text: str, length: int, task_type: str) -> float:
    """Estimate fluency from sentence endings and structure."""
    return _score_coherent(text, length, task_type)


def _score_improved(text: str, length: int, task_type: str) -> float:
    """Check if refactored code looks like an improvement."""
    improvement_signals = re.findall(
        r"(?i)(extract|simplif|clean|rename|reorganiz|split|consolidat|"
        r"type.?hint|docstring|refactor|improve)",
        text,
    )
    has_code = bool(_RE_CODE_CONSTRUCT.search(text))
    score = 0.2
    if has_code:
        score += 0.4
    if improvement_signals:
        score += min(0.4, 0.1 * len(improvement_signals))
    return min(1.0, score)


def _score_preserves_behavior(text: str, length: int, task_type: str) -> float:
    """Check for behaviour-preserving indicators in refactored code."""
    # Look for comments/notes about preserving functionality
    if re.search(r"(?i)(same behavior|functionally equivalent|no change in|preserv)", text):
        return 1.0
    if bool(_RE_CODE_CONSTRUCT.search(text)):
        return 0.6  # Has code, assume reasonable
    return 0.3


def _score_readable(text: str, length: int, task_type: str) -> float:
    """Estimate code readability."""
    score = 0.3
    # Docstrings / comments
    if re.search(r'(?:"""|\'\'\'|//|#\s)', text):
        score += 0.3
    # Reasonable line lengths
    lines = text.split("\n")
    long_lines = sum(1 for line in lines if len(line) > 120)
    if long_lines == 0:
        score += 0.2
    elif long_lines < len(lines) * 0.1:
        score += 0.1
    # Has structure
    if _RE_CODE_CONSTRUCT.search(text):
        score += 0.2
    return min(1.0, score)


# ── criterion scorer registry ──────────────────────────────────────────────

_CRITERION_SCORERS: Dict[
    str,
    Any,  # Callable[[str, int, str], float] — avoid Callable import overhead
] = {
    "has_rating": _score_has_rating,
    "has_justification": _score_has_justification,
    "coherent": _score_coherent,
    "concise": _score_concise,
    "complete": _score_complete,
    "creative": _score_creative,
    "relevant": _score_relevant,
    "has_label": _score_has_label,
    "has_confidence": _score_has_confidence,
    "covers_both": _score_covers_both,
    "balanced": _score_balanced,
    "conclusion": _score_conclusion,
    "identifies_issues": _score_identifies_issues,
    "actionable": _score_actionable,
    "severity": _score_severity,
    "identifies_risks": _score_identifies_risks,
    "severity_rated": _score_severity_rated,
    "has_tests": _score_has_tests,
    "covers_edge_cases": _score_covers_edge_cases,
    "runnable": _score_runnable,
    "clear": _score_clear,
    "examples": _score_examples,
    "structured": _score_structured,
    "accuracy": _score_accuracy,
    "fluency": _score_fluency,
    "improved": _score_improved,
    "preserves_behavior": _score_preserves_behavior,
    "readable": _score_readable,
}


def _validate_json_schema(
    text: str,
    schema: Dict[str, Any],
) -> List[str]:
    """Lightweight JSON schema validation (no jsonschema dependency).

    Checks that *text* is valid JSON and that required top-level keys from
    the schema's ``properties`` and ``required`` lists are present.

    Args:
        text: Raw output text that should be JSON.
        schema: A JSON Schema-like dict with optional ``properties`` and
            ``required`` keys.

    Returns:
        A list of error strings (empty if valid).
    """
    errors: List[str] = []

    # Try to extract JSON from fenced code blocks first
    json_str = text.strip()
    block_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", json_str)
    if block_match:
        json_str = block_match.group(1).strip()

    try:
        parsed = json.loads(json_str)
    except (json.JSONDecodeError, ValueError) as exc:
        errors.append(f"Output is not valid JSON: {exc}")
        return errors

    # Check required keys
    required = schema.get("required", [])
    if isinstance(parsed, dict):
        for key in required:
            if key not in parsed:
                errors.append(f"Missing required JSON key: {key}")
    elif required:
        errors.append("Expected a JSON object but got a non-object type")

    # Check declared properties exist (as warnings → we use errors lightly)
    properties = schema.get("properties", {})
    if isinstance(parsed, dict) and properties:
        missing_props = [k for k in properties if k not in parsed]
        if missing_props and not required:
            # Only note if none are required — otherwise required check covers it
            pass  # Soft miss, not an error

    return errors
