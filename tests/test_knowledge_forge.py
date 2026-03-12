"""Tests for engine.nexus.knowledge_forge — NLM-powered knowledge operations."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.knowledge_forge import (
    KnowledgeForge,
    QAPair,
    ForgeResult,
    generate_questions,
)


# ──── Fixtures ────

@pytest.fixture
def mock_engine():
    """Mock NLMEngine."""
    engine = MagicMock()
    engine.ask.return_value = {"answer": "This is the answer to the question."}
    engine.ask_batch.return_value = [
        {"question": "Q1?", "answer": {"answer": "Answer to Q1 which is long enough to pass."}},
        {"question": "Q2?", "answer": {"answer": "Answer to Q2 which is also long enough to pass."}},
    ]
    engine.create_notebook.return_value = {"notebook_id": "nb-test-123"}
    engine.create_from_files.return_value = {"notebook_id": "nb-code-456"}
    engine.generate.return_value = {"content": "Generated study guide content."}
    engine.add_source.return_value = {"success": True}
    return engine


@pytest.fixture
def mock_nexus():
    """Mock NexusClient."""
    client = MagicMock()
    client.add_qa.return_value = "qa-123"
    client.add_entry.return_value = "entry-456"
    return client


@pytest.fixture
def forge(mock_engine, mock_nexus):
    """KnowledgeForge with mocked dependencies."""
    f = KnowledgeForge(engine=mock_engine)
    f._nexus_client = mock_nexus
    return f


# ──── QAPair Tests ────

def test_qa_pair_to_dict():
    """QAPair serializes correctly."""
    pair = QAPair(question="What is X?", answer="X is Y.", topic="testing")
    d = pair.to_dict()
    assert d["question"] == "What is X?"
    assert d["answer"] == "X is Y."
    assert d["topic"] == "testing"


def test_qa_pair_to_instruction():
    """Instruction format has instruction + output."""
    pair = QAPair(question="How?", answer="Like this.")
    fmt = pair.to_instruction()
    assert fmt["instruction"] == "How?"
    assert fmt["output"] == "Like this."


def test_qa_pair_to_chat_ml():
    """ChatML format has messages array."""
    pair = QAPair(question="Q?", answer="A.")
    fmt = pair.to_chat_ml()
    assert len(fmt["messages"]) == 2
    assert fmt["messages"][0]["role"] == "user"
    assert fmt["messages"][1]["role"] == "assistant"


# ──── ForgeResult Tests ────

def test_forge_result_success():
    """Success when has content and no errors."""
    r = ForgeResult(operation="test", qa_pairs=[QAPair(question="Q", answer="A")])
    assert r.success is True


def test_forge_result_failure():
    """Not success when has errors only."""
    r = ForgeResult(operation="test", errors=["something failed"])
    assert r.success is False


def test_forge_result_empty():
    """Not success when empty."""
    r = ForgeResult(operation="test")
    assert r.success is False


# ──── Question Generation Tests ────

def test_generate_questions_topic():
    """Generate topic questions."""
    qs = generate_questions("MCP Framework", category="topic", count=5, subject="MCP")
    assert len(qs) == 5
    assert all("MCP" in q for q in qs)


def test_generate_questions_code():
    """Generate code-specific questions."""
    qs = generate_questions("BaseScene", category="code", count=3, subject="BaseScene")
    assert len(qs) == 3
    assert any("design pattern" in q.lower() for q in qs)


def test_generate_questions_plan():
    """Generate plan-related questions."""
    qs = generate_questions("Add caching", category="plan", count=4, subject="caching")
    assert len(qs) == 4


def test_generate_questions_unknown_category():
    """Unknown category falls back to topic."""
    qs = generate_questions("test", category="unknown", count=3)
    assert len(qs) == 3


# ──── Distillation Tests ────

def test_distill_with_topics(forge, mock_engine, mock_nexus):
    """Distill generates questions from topics and stores results."""
    result = forge.distill("nb-1", topics=["MCP state"], count=2, delay=0)
    assert isinstance(result, ForgeResult)
    assert result.operation == "distill"
    assert mock_engine.ask_batch.called
    assert len(result.qa_pairs) > 0


def test_distill_with_explicit_questions(forge, mock_engine):
    """Distill with explicit questions skips generation."""
    result = forge.distill(
        "nb-1", questions=["What is X?", "How does Y work?"],
        store_in_nexus=False, delay=0,
    )
    assert mock_engine.ask_batch.called
    args = mock_engine.ask_batch.call_args
    assert args[0][1] == ["What is X?", "How does Y work?"]


def test_distill_stores_in_nexus(forge, mock_nexus):
    """Distill stores Q&A pairs in Nexus when enabled."""
    result = forge.distill("nb-1", questions=["Q?"], store_in_nexus=True, delay=0)
    assert mock_nexus.add_qa.called


def test_distill_skips_nexus(forge, mock_nexus):
    """Distill skips Nexus when disabled."""
    result = forge.distill("nb-1", questions=["Q?"], store_in_nexus=False, delay=0)
    assert not mock_nexus.add_qa.called


def test_distill_handles_errors(forge, mock_engine):
    """Distill records errors from failed answers."""
    mock_engine.ask_batch.return_value = [
        {"question": "Q1?", "answer": {"error": "backend down"}},
    ]
    result = forge.distill("nb-1", questions=["Q1?"], store_in_nexus=False, delay=0)
    assert len(result.errors) > 0


# ──── Plan Decomposition Tests ────

def test_decompose(forge, mock_engine):
    """Decompose breaks plan into steps."""
    mock_engine.ask.return_value = {
        "answer": "1. Create file.py\n2. Add imports\n3. Write tests"
    }
    result = forge.decompose("Add caching layer", notebook_id="nb-1")
    assert result.operation == "decompose"
    assert len(result.steps) == 3
    assert result.steps[0]["step"] == 1


def test_decompose_without_notebook(forge):
    """Decompose without notebook returns helpful message."""
    result = forge.decompose("Add feature")
    assert len(result.steps) == 0


def test_decompose_stores_in_nexus(forge, mock_engine, mock_nexus):
    """Decompose stores result in Nexus."""
    mock_engine.ask.return_value = {"answer": "1. Step one\n2. Step two"}
    forge.decompose("Plan", notebook_id="nb-1", store_in_nexus=True)
    assert mock_nexus.add_entry.called


# ──── Code Analysis Tests ────

def test_analyze(forge, mock_engine):
    """Analyze creates notebook from files and asks questions."""
    result = forge.analyze(
        ["src/engine/mcp.py"], questions=["What pattern?"],
        store_in_nexus=False,
    )
    assert result.operation == "analyze"
    assert mock_engine.create_from_files.called


def test_analyze_auto_generates_questions(forge, mock_engine):
    """Analyze generates questions when none provided."""
    result = forge.analyze(["src/mcp.py"], store_in_nexus=False)
    assert mock_engine.ask_batch.called


# ──── Document Generation Tests ────

def test_generate_doc(forge, mock_engine, mock_nexus):
    """Generate document from notebook."""
    result = forge.generate_doc("nb-1", doc_type="study_guide")
    assert result.operation == "generate_doc"
    assert len(result.documents) == 1
    assert result.documents[0]["type"] == "study_guide"


def test_generate_doc_error(forge, mock_engine):
    """Handle generation errors."""
    mock_engine.generate.return_value = {"error": "generation failed"}
    result = forge.generate_doc("nb-1")
    assert len(result.errors) > 0


# ──── Dialog Polish Tests ────

def test_polish(forge, mock_engine):
    """Polish dialog returns polished version."""
    mock_engine.ask.return_value = {"answer": "Polished line 1\nPolished line 2"}
    result = forge.polish(
        "Lola", ["Hey there", "What's up?"],
        style_guide="Casual, warm", notebook_id="nb-chars",
    )
    assert result.operation == "polish"
    assert len(result.documents) == 1
    assert result.documents[0]["character"] == "Lola"


def test_polish_without_notebook(forge):
    """Polish without notebook returns error."""
    result = forge.polish("Lola", ["Hi"])
    assert len(result.errors) > 0


# ──── Problem Solving Tests ────

def test_solve(forge, mock_engine, mock_nexus):
    """Solve stores solution in Nexus."""
    result = forge.solve("How do I add caching?", notebook_id="nb-arch")
    assert len(result.qa_pairs) == 1
    assert mock_nexus.add_qa.called


def test_solve_with_context_files(forge, mock_engine):
    """Solve creates notebook from context files."""
    result = forge.solve("Bug in X?", context_files=["src/x.py"], store_in_nexus=False)
    assert mock_engine.create_from_files.called


def test_solve_no_context(forge):
    """Solve without context returns error."""
    result = forge.solve("How?")
    assert len(result.errors) > 0


# ──── Training Export Tests ────

def test_export_training_instruction(forge, tmp_path):
    """Export training data in instruction format."""
    output = tmp_path / "train.jsonl"
    result = forge.export_training(
        "nb-1", format="instruction", count=2,
        output_path=str(output),
    )
    assert result.operation == "export_training"
    assert output.exists()
    lines = output.read_text().strip().split("\n")
    assert len(lines) > 0
    parsed = json.loads(lines[0])
    assert "instruction" in parsed
    assert "output" in parsed


def test_export_training_chat_ml(forge, tmp_path):
    """Export in ChatML format."""
    output = tmp_path / "train_chat.jsonl"
    result = forge.export_training(
        "nb-1", format="chat_ml", count=2,
        output_path=str(output),
    )
    assert output.exists()
    parsed = json.loads(output.read_text().strip().split("\n")[0])
    assert "messages" in parsed


def test_export_training_sharegpt(forge, tmp_path):
    """Export in ShareGPT format."""
    output = tmp_path / "train_sgpt.jsonl"
    result = forge.export_training(
        "nb-1", format="sharegpt", count=2,
        output_path=str(output),
    )
    assert output.exists()
    parsed = json.loads(output.read_text().strip().split("\n")[0])
    assert "conversations" in parsed


# ──── Build Topic Tests ────

def test_build_topic(forge, mock_engine, mock_nexus):
    """Build topic creates notebook, adds sources, distills."""
    with patch("engine.nexus.nlm_notebook_factory.get_notebook_factory") as mock_factory_fn:
        mock_factory = MagicMock()
        mock_factory.get_or_create.return_value = "nb-test-123"
        mock_factory_fn.return_value = mock_factory
        result = forge.build_topic(
            "MCP Framework", sources=["https://docs.example.com"],
            question_count=2,
        )
    assert result.operation == "build_topic"
    assert result.notebook_id == "nb-test-123"
    assert mock_factory.get_or_create.called


def test_build_topic_fail_create(forge, mock_engine):
    """Build topic handles notebook creation failure."""
    with patch("engine.nexus.nlm_notebook_factory.get_notebook_factory") as mock_factory_fn:
        mock_factory = MagicMock()
        mock_factory.get_or_create.return_value = None
        mock_factory_fn.return_value = mock_factory
        result = forge.build_topic("Topic")
    assert len(result.errors) > 0


# ──── Scoring Tests ────

def test_score(forge, mock_engine):
    """Score updates quality_score on pairs."""
    mock_engine.ask.return_value = {"answer": "0.85"}
    pairs = [QAPair(question="Q?", answer="A.")]
    scored = forge.score(pairs, notebook_id="nb-1")
    assert scored[0].quality_score == pytest.approx(0.85, abs=0.01)


def test_score_invalid_response(forge, mock_engine):
    """Score handles non-numeric response."""
    mock_engine.ask.return_value = {"answer": "This is not a number"}
    pairs = [QAPair(question="Q?", answer="A.")]
    scored = forge.score(pairs, notebook_id="nb-1")
    assert scored[0].quality_score == 0.5  # fallback


def test_score_no_notebook(forge):
    """Score without notebook returns pairs unchanged."""
    pairs = [QAPair(question="Q?", answer="A.")]
    scored = forge.score(pairs)
    assert scored[0].quality_score == 0.0  # unchanged
