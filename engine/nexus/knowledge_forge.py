"""Knowledge Forge — NLM-powered knowledge operations for CosySim.

Uses NotebookLM (free Gemini compute) to distill Q&A, decompose plans,
analyze code, polish dialog, generate training data, and build topic
knowledge bases. Every answer is stored in Nexus for compound reuse.

Version: v1.57.0 [2026-03-26]

Change Log:
    v1.57.0 [2026-03-26] — Add _extract_qa_structured() for Gemini structured output
                            extraction of Q&A pairs from raw text (preferred over regex);
                            add _extract_qa_regex() as explicit fallback method

Usage:
    from engine.nexus.knowledge_forge import get_knowledge_forge
    forge = get_knowledge_forge()
    qa_pairs = forge.distill("notebook-id", topics=["MCP state", "skills"])
    steps = forge.decompose("Implement caching layer", model_size="9b")
    training = forge.export_training("notebook-id", format="instruction")
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from engine.config import get_config
from engine.nexus.nlm_engine import NLMEngine, get_nlm_engine

logger = logging.getLogger(__name__)


# ──── Data Models ────

@dataclass
class QAPair:
    """A single question-answer pair with metadata."""

    question: str
    answer: str
    source_notebook: str = ""
    topic: str = ""
    quality_score: float = 0.0
    citations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "question": self.question,
            "answer": self.answer,
            "source_notebook": self.source_notebook,
            "topic": self.topic,
            "quality_score": self.quality_score,
            "citations": self.citations,
        }

    def to_instruction(self) -> Dict[str, str]:
        """Convert to instruction format for fine-tuning."""
        return {
            "instruction": self.question,
            "output": self.answer,
        }

    def to_chat_ml(self) -> Dict[str, Any]:
        """Convert to ChatML format for fine-tuning."""
        return {
            "messages": [
                {"role": "user", "content": self.question},
                {"role": "assistant", "content": self.answer},
            ]
        }


@dataclass
class ForgeResult:
    """Result of a forge operation."""

    operation: str
    notebook_id: str = ""
    qa_pairs: List[QAPair] = field(default_factory=list)
    documents: List[Dict[str, str]] = field(default_factory=list)
    steps: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    nexus_ids: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def success(self) -> bool:
        """Whether the operation produced results."""
        return bool(self.qa_pairs or self.documents or self.steps) and not self.errors


# ──── Question Generation ────

_CODE_QUESTIONS = [
    "What design pattern does {subject} use?",
    "What are the main responsibilities of {subject}?",
    "How does {subject} handle errors?",
    "What are the dependencies of {subject}?",
    "How is {subject} tested?",
    "What configuration does {subject} require?",
    "What are the public methods of {subject}?",
    "How does {subject} interact with the MCP framework?",
]

_TOPIC_QUESTIONS = [
    "What is {subject} and how does it work?",
    "What are the key components of {subject}?",
    "What are common pitfalls when working with {subject}?",
    "What best practices should be followed for {subject}?",
    "How do you implement {subject} step by step?",
    "What are the performance considerations for {subject}?",
    "How does {subject} relate to other parts of the system?",
    "What edge cases should be handled in {subject}?",
]

_PLAN_QUESTIONS = [
    "What are the prerequisites before starting?",
    "What files need to be modified?",
    "What new files need to be created?",
    "What tests should be written?",
    "What are the risks and how to mitigate them?",
    "What is the correct implementation order?",
]


def generate_questions(
    context: str,
    category: str = "topic",
    count: int = 10,
    subject: str = "",
) -> List[str]:
    """Auto-generate relevant questions for batch asking.

    Args:
        context: Context text (code, topic description, or plan).
        category: Question category — "code", "topic", or "plan".
        count: Number of questions to generate.
        subject: Subject to template into questions.

    Returns:
        List of generated questions.
    """
    templates = {
        "code": _CODE_QUESTIONS,
        "topic": _TOPIC_QUESTIONS,
        "plan": _PLAN_QUESTIONS,
    }
    base = templates.get(category, _TOPIC_QUESTIONS)

    questions = []
    subj = subject or context[:50].strip()
    for tmpl in base[:count]:
        questions.append(tmpl.format(subject=subj))

    # Add context-specific questions
    if len(questions) < count and context:
        questions.append(f"Explain this in detail: {context[:200]}")
    if len(questions) < count:
        questions.append(f"What are the most important things to know about {subj}?")

    return questions[:count]


# ──── Knowledge Forge ────

class KnowledgeForge:
    """Orchestrates NLM for knowledge distillation, analysis, and generation.

    The forge uses NotebookLM's free Gemini compute to:
    - Distill Q&A pairs from notebooks (batch asking)
    - Decompose complex plans into small-model-executable steps
    - Analyze source code via NLM
    - Polish dialog for characters
    - Generate training data in multiple formats
    - Build topic knowledge bases end-to-end

    Every answer is optionally stored in Nexus for compound reuse.
    """

    def __init__(self, engine: Optional[NLMEngine] = None) -> None:
        self._engine = engine or get_nlm_engine()
        self._nexus_client: Any = None

    def _get_nexus(self) -> Any:
        """Lazy-load Nexus client."""
        if self._nexus_client is None:
            from engine.nexus.client import get_nexus_client
            self._nexus_client = get_nexus_client()
        return self._nexus_client

    # ──── Q&A Distillation ────

    def distill(
        self,
        notebook_id: str,
        topics: Optional[List[str]] = None,
        questions: Optional[List[str]] = None,
        count: int = 20,
        store_in_nexus: bool = True,
        delay: float = 1.5,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> ForgeResult:
        """Distill Q&A pairs from a notebook using batch asking.

        Either provide explicit questions or topics (questions auto-generated).

        Args:
            notebook_id: Source notebook UUID.
            topics: List of topics to generate questions for.
            questions: Explicit list of questions to ask.
            count: Questions per topic (if using topics).
            store_in_nexus: Whether to store Q&A pairs in Nexus.
            delay: Seconds between questions.
            on_progress: Progress callback(current, total, question).

        Returns:
            ForgeResult with Q&A pairs.
        """
        start = time.monotonic()
        result = ForgeResult(operation="distill", notebook_id=notebook_id)

        # Build question list
        all_questions: List[str] = []
        if questions:
            all_questions = list(questions)
        elif topics:
            for topic in topics:
                all_questions.extend(
                    generate_questions(topic, category="topic", count=count, subject=topic)
                )
        else:
            all_questions = generate_questions("", count=count)

        # Batch ask
        answers = self._engine.ask_batch(
            notebook_id, all_questions, delay=delay, on_progress=on_progress,
        )

        # Build Q&A pairs
        for item in answers:
            q = item.get("question", "")
            ans_data = item.get("answer", {})
            ans_text = ans_data.get("answer", ans_data.get("response", str(ans_data)))

            if not ans_text or "error" in ans_data:
                result.errors.append(f"Failed: {q[:80]}")
                continue

            pair = QAPair(
                question=q,
                answer=ans_text if isinstance(ans_text, str) else json.dumps(ans_text),
                source_notebook=notebook_id,
                topic=topics[0] if topics else "",
            )
            result.qa_pairs.append(pair)

        # Store in Nexus
        if store_in_nexus and result.qa_pairs:
            nexus = self._get_nexus()
            for pair in result.qa_pairs:
                try:
                    qa_id = nexus.add_qa(pair.question, pair.answer, category="nlm_distilled")
                    if qa_id:
                        result.nexus_ids.append(qa_id)
                except Exception as e:
                    result.errors.append(f"Nexus store error: {e}")

        result.duration_seconds = round(time.monotonic() - start, 1)
        logger.info(
            "Distilled %d Q&A pairs from notebook %s in %.1fs",
            len(result.qa_pairs), notebook_id[:8], result.duration_seconds,
        )
        return result

    # ──── Plan Decomposition ────

    def decompose(
        self,
        plan_text: str,
        notebook_id: str = "",
        model_size: str = "9b",
        store_in_nexus: bool = True,
    ) -> ForgeResult:
        """Decompose a complex plan into small-model-executable steps.

        Asks NLM to break down the plan into numbered steps that a
        small local model (e.g., 9B) can follow without creativity.

        Args:
            plan_text: The high-level plan to decompose.
            notebook_id: Optional notebook with codebase context.
            model_size: Target model size (affects step granularity).
            store_in_nexus: Store the decomposition in Nexus.

        Returns:
            ForgeResult with steps list.
        """
        start = time.monotonic()
        result = ForgeResult(operation="decompose", notebook_id=notebook_id)

        prompt = (
            f"I need to implement the following plan. Break it down into specific, "
            f"numbered implementation steps that a {model_size} parameter language model "
            f"can follow. Each step should be concrete, unambiguous, and include:\n"
            f"- Exact file to edit/create\n"
            f"- What to add/change\n"
            f"- Any imports or dependencies needed\n\n"
            f"Plan:\n{plan_text}\n\n"
            f"Provide the steps as a numbered list. Be extremely specific — "
            f"the model following these steps has no creativity, only execution ability."
        )

        if notebook_id:
            answer = self._engine.ask(notebook_id, prompt)
        else:
            # Without a notebook, we need one with context
            answer = {"answer": "No notebook provided for decomposition. "
                      "Create a notebook with relevant source files first."}

        ans_text = answer.get("answer", answer.get("response", ""))
        if ans_text and "error" not in answer:
            # Parse numbered steps
            lines = ans_text.split("\n") if isinstance(ans_text, str) else []
            step_num = 0
            current_step = ""
            for line in lines:
                stripped = line.strip()
                if stripped and stripped[0].isdigit() and "." in stripped[:4]:
                    if current_step:
                        result.steps.append({"step": step_num, "instruction": current_step.strip()})
                    step_num += 1
                    current_step = stripped.split(".", 1)[1].strip() if "." in stripped else stripped
                elif current_step:
                    current_step += " " + stripped

            if current_step:
                result.steps.append({"step": step_num, "instruction": current_step.strip()})

            # Store in Nexus
            if store_in_nexus:
                nexus = self._get_nexus()
                try:
                    entry_id = nexus.add_entry(
                        title=f"Plan Decomposition: {plan_text[:60]}",
                        content=ans_text if isinstance(ans_text, str) else json.dumps(ans_text),
                        content_type="plan",
                        category="nlm_decomposed",
                        tags=["plan", "decomposition", model_size],
                    )
                    if entry_id:
                        result.nexus_ids.append(entry_id)
                except Exception as e:
                    result.errors.append(f"Nexus store error: {e}")

        result.duration_seconds = round(time.monotonic() - start, 1)
        return result

    # ──── Code Analysis ────

    def analyze(
        self,
        file_paths: List[str],
        questions: Optional[List[str]] = None,
        notebook_name: str = "",
        store_in_nexus: bool = True,
    ) -> ForgeResult:
        """Analyze source code by creating an NLM notebook and asking questions.

        Args:
            file_paths: Source files to analyze.
            questions: Questions to ask about the code. Auto-generated if None.
            notebook_name: Name for the temporary notebook.
            store_in_nexus: Store results in Nexus.

        Returns:
            ForgeResult with Q&A pairs about the code.
        """
        start = time.monotonic()
        name = notebook_name or f"Code Analysis: {Path(file_paths[0]).name if file_paths else 'unknown'}"
        result = ForgeResult(operation="analyze")

        # Create notebook from source files
        nb_result = self._engine.create_from_files(file_paths, name)
        notebook_id = nb_result.get("notebook_id", "")
        if not notebook_id:
            result.errors.append(f"Failed to create notebook: {nb_result}")
            return result
        result.notebook_id = notebook_id

        # Generate questions if not provided
        if not questions:
            subjects = [Path(f).stem for f in file_paths[:3]]
            questions = []
            for subj in subjects:
                questions.extend(
                    generate_questions(subj, category="code", count=5, subject=subj)
                )

        # Batch ask
        distill_result = self.distill(
            notebook_id, questions=questions,
            store_in_nexus=store_in_nexus, delay=2.0,
        )
        result.qa_pairs = distill_result.qa_pairs
        result.errors.extend(distill_result.errors)
        result.nexus_ids.extend(distill_result.nexus_ids)
        result.duration_seconds = round(time.monotonic() - start, 1)
        return result

    # ──── Document Generation ────

    def generate_doc(
        self,
        notebook_id: str,
        doc_type: str = "study_guide",
        instructions: str = "",
        store_in_nexus: bool = True,
    ) -> ForgeResult:
        """Generate a structured document from a notebook.

        Args:
            notebook_id: Source notebook UUID.
            doc_type: study_guide, faq, briefing, deep_dive, timeline.
            instructions: Custom instructions for generation.
            store_in_nexus: Store result in Nexus.

        Returns:
            ForgeResult with generated document.
        """
        start = time.monotonic()
        result = ForgeResult(operation="generate_doc", notebook_id=notebook_id)

        gen_result = self._engine.generate(notebook_id, doc_type, instructions)
        if "error" in gen_result:
            result.errors.append(str(gen_result["error"]))
        else:
            content = gen_result.get("content", gen_result.get("data", ""))
            result.documents.append({
                "type": doc_type,
                "content": content if isinstance(content, str) else json.dumps(content),
                "notebook_id": notebook_id,
            })

            if store_in_nexus and content:
                nexus = self._get_nexus()
                try:
                    entry_id = nexus.add_entry(
                        title=f"NLM {doc_type}: {notebook_id[:8]}",
                        content=content if isinstance(content, str) else json.dumps(content),
                        content_type="document",
                        category="nlm_generated",
                        tags=["notebooklm", doc_type, "generated"],
                    )
                    if entry_id:
                        result.nexus_ids.append(entry_id)
                except Exception as e:
                    result.errors.append(f"Nexus store error: {e}")

        result.duration_seconds = round(time.monotonic() - start, 1)
        return result

    # ──── Dialog Polish ────

    def polish(
        self,
        character: str,
        lines: List[str],
        style_guide: str = "",
        notebook_id: str = "",
    ) -> ForgeResult:
        """Polish character dialog using NLM.

        Args:
            character: Character name/ID.
            lines: Dialog lines to polish.
            style_guide: Style instructions (voice, tone, vocabulary).
            notebook_id: Notebook with character profile sources.

        Returns:
            ForgeResult with polished dialog in documents.
        """
        start = time.monotonic()
        result = ForgeResult(operation="polish", notebook_id=notebook_id)

        if not notebook_id:
            result.errors.append("No notebook_id provided for dialog polish")
            result.duration_seconds = round(time.monotonic() - start, 1)
            return result

        prompt = (
            f"Polish the following dialog lines for character '{character}'. "
            f"Maintain their personality and voice.\n"
        )
        if style_guide:
            prompt += f"\nStyle guide: {style_guide}\n"
        prompt += "\nOriginal lines:\n" + "\n".join(f"- {line}" for line in lines)
        prompt += "\n\nProvide the polished versions, one per line."

        answer = self._engine.ask(notebook_id, prompt)
        ans_text = answer.get("answer", answer.get("response", ""))
        if ans_text and "error" not in answer:
            result.documents.append({
                "type": "dialog_polish",
                "character": character,
                "original": lines,
                "polished": ans_text if isinstance(ans_text, str) else str(ans_text),
            })

        result.duration_seconds = round(time.monotonic() - start, 1)
        return result

    # ──── Problem Solving ────

    def solve(
        self,
        question: str,
        context_files: Optional[List[str]] = None,
        notebook_id: str = "",
        store_in_nexus: bool = True,
    ) -> ForgeResult:
        """Use NLM to solve a problem with optional code context.

        Args:
            question: The problem/question to solve.
            context_files: Optional source files for context.
            notebook_id: Existing notebook with context.
            store_in_nexus: Store the solution in Nexus.

        Returns:
            ForgeResult with the solution.
        """
        start = time.monotonic()
        result = ForgeResult(operation="solve")

        # Create notebook from context files if no notebook provided
        if not notebook_id and context_files:
            nb_result = self._engine.create_from_files(
                context_files, f"Problem: {question[:40]}"
            )
            notebook_id = nb_result.get("notebook_id", "")

        if not notebook_id:
            result.errors.append("No context available (provide notebook_id or context_files)")
            return result

        result.notebook_id = notebook_id
        answer = self._engine.ask(notebook_id, question)
        ans_text = answer.get("answer", answer.get("response", ""))

        if ans_text and "error" not in answer:
            pair = QAPair(
                question=question,
                answer=ans_text if isinstance(ans_text, str) else json.dumps(ans_text),
                source_notebook=notebook_id,
                topic="problem_solving",
            )
            result.qa_pairs.append(pair)

            if store_in_nexus:
                nexus = self._get_nexus()
                try:
                    qa_id = nexus.add_qa(question, pair.answer, category="nlm_solution")
                    if qa_id:
                        result.nexus_ids.append(qa_id)
                except Exception as e:
                    result.errors.append(f"Nexus store error: {e}")

        result.duration_seconds = round(time.monotonic() - start, 1)
        return result

    # ──── Training Data Export ────

    def export_training(
        self,
        notebook_id: str,
        format: str = "instruction",
        topics: Optional[List[str]] = None,
        count: int = 50,
        quality_threshold: float = 0.0,
        output_path: Optional[str] = None,
    ) -> ForgeResult:
        """Generate training data from a notebook via distillation.

        Pipeline: Notebook -> Distill Q&A -> Score -> Filter -> Export JSONL.

        Args:
            notebook_id: Source notebook UUID.
            format: Output format — "instruction", "chat_ml", "sharegpt".
            topics: Topics to distill (auto-generated if None).
            count: Number of Q&A pairs to generate.
            quality_threshold: Minimum quality score (0.0 = no filter).
            output_path: Optional file path for JSONL output.

        Returns:
            ForgeResult with Q&A pairs and optional file output.
        """
        start = time.monotonic()
        result = ForgeResult(operation="export_training", notebook_id=notebook_id)

        # Distill Q&A pairs
        distill_result = self.distill(
            notebook_id, topics=topics, count=count,
            store_in_nexus=True, delay=2.0,
        )
        result.qa_pairs = distill_result.qa_pairs
        result.errors.extend(distill_result.errors)
        result.nexus_ids.extend(distill_result.nexus_ids)

        # Filter by quality
        if quality_threshold > 0:
            result.qa_pairs = [p for p in result.qa_pairs if p.quality_score >= quality_threshold]

        # Format for export
        formatted = []
        for pair in result.qa_pairs:
            if format == "chat_ml":
                formatted.append(pair.to_chat_ml())
            elif format == "sharegpt":
                formatted.append({
                    "conversations": [
                        {"from": "human", "value": pair.question},
                        {"from": "gpt", "value": pair.answer},
                    ]
                })
            else:
                formatted.append(pair.to_instruction())

        # Write JSONL if output path given
        if output_path and formatted:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                for item in formatted:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
            result.documents.append({
                "type": "training_export",
                "format": format,
                "path": str(out),
                "count": len(formatted),
            })
            logger.info("Exported %d training examples to %s", len(formatted), out)

        result.duration_seconds = round(time.monotonic() - start, 1)
        return result

    # ──── End-to-End Pipeline ────

    def build_topic(
        self,
        topic: str,
        sources: Optional[List[str]] = None,
        question_count: int = 30,
        store_in_nexus: bool = True,
        on_progress: Optional[Callable[[str, int, int], None]] = None,
    ) -> ForgeResult:
        """End-to-end knowledge building: create notebook -> add sources -> distill.

        Args:
            topic: Topic name for the notebook.
            sources: URLs or file paths to add as sources.
            question_count: Number of Q&A pairs to generate.
            store_in_nexus: Store everything in Nexus.
            on_progress: Callback(phase, current, total).

        Returns:
            ForgeResult with all generated knowledge.
        """
        start = time.monotonic()
        result = ForgeResult(operation="build_topic")

        if on_progress:
            on_progress("creating_notebook", 0, 3)

        # 1. Create notebook via factory
        from engine.nexus.nlm_notebook_factory import get_notebook_factory

        factory = get_notebook_factory()
        notebook_id = factory.get_or_create(
            f"Knowledge: {topic}",
            category="knowledge",
            dedup_key=f"knowledge:{topic}",
        )
        if not notebook_id:
            result.errors.append("Failed to create notebook via factory")
            return result
        result.notebook_id = notebook_id

        if on_progress:
            on_progress("adding_sources", 1, 3)

        # 2. Add file-based sources (non-URL sources)
        if sources:
            for src in sources:
                if Path(src).exists():
                    try:
                        content = Path(src).read_text(encoding="utf-8", errors="replace")
                        self._engine.add_source(notebook_id, "text", content[:50000])
                    except Exception as e:
                        result.errors.append(f"Source add error: {e}")

        if on_progress:
            on_progress("distilling", 2, 3)

        # 3. Distill Q&A
        distill_result = self.distill(
            notebook_id, topics=[topic], count=question_count,
            store_in_nexus=store_in_nexus,
        )
        result.qa_pairs = distill_result.qa_pairs
        result.errors.extend(distill_result.errors)
        result.nexus_ids.extend(distill_result.nexus_ids)

        result.duration_seconds = round(time.monotonic() - start, 1)
        logger.info(
            "Built topic '%s': notebook=%s, %d Q&A pairs in %.1fs",
            topic, notebook_id[:8], len(result.qa_pairs), result.duration_seconds,
        )
        return result

    # ──── Structured Q&A Extraction ────

    # v1.57.0 [2026-03-26] — Gemini structured output for Q&A extraction
    # CONNECTS: engine.integrations.aistudio_client.generate_structured, engine.nexus.schemas
    # CALLED BY: External callers needing structured Q&A from raw text (e.g. bulk ingestion)
    def _extract_qa_structured(self, text: str, topic: str) -> List[Dict]:
        """Extract Q&A pairs from raw text using Gemini structured output.

        Uses Gemini's JSON schema enforcement to produce guaranteed well-formed
        Q&A pairs, eliminating regex-based parsing of fenced JSON blocks.
        Falls back to _extract_qa_regex() if the structured API is unavailable.

        Args:
            text: Raw text to extract Q&A pairs from.
            topic: Topic context for the extraction prompt.

        Returns:
            List of dicts with 'question', 'answer', and optional 'confidence'/'category'.
        """
        try:
            from engine.integrations.aistudio_client import generate_structured
            from engine.nexus.schemas import QA_BATCH_SCHEMA

            # Truncate to avoid exceeding model context limits
            prompt = (
                f"Extract question-and-answer pairs from this text about '{topic}'. "
                f"Each pair should have a clear, self-contained question and a "
                f"comprehensive answer. Include a confidence score (0.0-1.0) and "
                f"category for each pair.\n\n"
                f"Text:\n{text[:5000]}"
            )
            result = generate_structured(prompt, QA_BATCH_SCHEMA)
            if isinstance(result, list):
                logger.debug(
                    "[KnowledgeForge] Structured Q&A extraction succeeded "
                    "(operation=extract_qa_structured, topic=%s, pairs=%d)",
                    topic,
                    len(result),
                )
                return result
            return []
        except Exception as exc:
            logger.debug(
                "[KnowledgeForge] Structured extraction failed, using regex fallback "
                "(operation=extract_qa_structured, topic=%s): %s",
                topic,
                exc,
            )
            return self._extract_qa_regex(text)

    def _extract_qa_regex(self, text: str) -> List[Dict]:
        """Extract Q&A pairs from text using regex patterns (fallback).

        Looks for common Q&A patterns in the text:
          - "Q: ... A: ..." style pairs
          - Numbered question-answer blocks
          - Markdown-formatted Q&A sections

        Args:
            text: Raw text to parse for Q&A patterns.

        Returns:
            List of dicts with 'question' and 'answer' keys.
        """
        import re

        pairs: List[Dict] = []

        # Pattern 1: "Q: question\nA: answer" style
        qa_pattern = re.compile(
            r"(?:Q|Question)\s*[:.]?\s*(.+?)\n\s*(?:A|Answer)\s*[:.]?\s*(.+?)(?=\n\s*(?:Q|Question)\s*[:.]?|\Z)",
            re.DOTALL | re.IGNORECASE,
        )
        for match in qa_pattern.finditer(text):
            q = match.group(1).strip()
            a = match.group(2).strip()
            if q and a:
                pairs.append({"question": q, "answer": a})

        # Pattern 2: numbered "1. question\nanswer" style
        if not pairs:
            numbered_pattern = re.compile(
                r"\d+\.\s*\*?\*?(.+?)\*?\*?\n((?:(?!\d+\.).)+)",
                re.DOTALL,
            )
            for match in numbered_pattern.finditer(text):
                q = match.group(1).strip()
                a = match.group(2).strip()
                if q and a and len(a) > 20:
                    pairs.append({"question": q, "answer": a})

        logger.debug(
            "[KnowledgeForge] Regex Q&A extraction (operation=extract_qa_regex, pairs=%d)",
            len(pairs),
        )
        return pairs

    # ──── Scoring ────

    def score(
        self,
        qa_pairs: List[QAPair],
        notebook_id: str = "",
    ) -> List[QAPair]:
        """Score Q&A pairs for quality using NLM.

        Args:
            qa_pairs: Pairs to score.
            notebook_id: Optional notebook for context-aware scoring.

        Returns:
            Same pairs with quality_score updated.
        """
        if not notebook_id or not qa_pairs:
            return qa_pairs

        # Batch score by asking NLM to rate answers
        for pair in qa_pairs:
            prompt = (
                f"Rate the quality of this Q&A pair on a scale of 0.0 to 1.0. "
                f"Consider accuracy, completeness, and usefulness.\n\n"
                f"Q: {pair.question}\nA: {pair.answer[:500]}\n\n"
                f"Reply with ONLY a number between 0.0 and 1.0."
            )
            result = self._engine.ask(notebook_id, prompt)
            ans = result.get("answer", result.get("response", ""))
            try:
                score = float(str(ans).strip().split()[0])
                pair.quality_score = max(0.0, min(1.0, score))
            except (ValueError, IndexError):
                pair.quality_score = 0.5

        return qa_pairs


# ──── Singleton ────

_forge: Optional[KnowledgeForge] = None


def get_knowledge_forge() -> KnowledgeForge:
    """Return the global KnowledgeForge singleton."""
    global _forge
    if _forge is None:
        _forge = KnowledgeForge()
    return _forge
