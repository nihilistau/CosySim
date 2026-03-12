"""Cache Pipeline — orchestrates the full NLM-driven Q&A cache generation cycle.

This module implements the 10-stage pipeline that generates, evaluates, and
stores high-quality Q&A pairs in the Nexus cache using Gemini 3.0 (via NLM)
as both the generator and the evaluator.

Stages:
  A — Direct seed: high-quality turns from session history → Nexus (no NLM)
  B — Source upload: pyramid layers + themed history chunks → NLM Notebook A
  C — Raw generation: flashcards + quiz + data_tables on Notebook A
  D — Structured generation: CSV mode + code-gen mode on Notebook B
  E — Parse + deduplicate candidates from stages C + D
  F — NLM self-evaluation: ESSENTIAL / USEFUL / SKIP on Notebook C
  G — Store approved pairs in Nexus Q&A cache
  H — Generate Excel review sheet (openpyxl) for human review
  I — Upload approved pairs back as source for compounding (next cycle)
  J — Gap analysis → gap list → scheduler tasks

Usage::

    from engine.nexus.cache_pipeline import get_cache_pipeline
    pipeline = get_cache_pipeline()
    result = pipeline.run_full_cycle()
    print(f"Stored {result.stored} new Q&A pairs")
    print(f"Gaps identified: {result.gaps}")

    # Or run specific stages
    n = pipeline.ensure_notebooks()
    seeds = pipeline.run_stage_a()
    pipeline.run_stage_b(n["seed"])
    candidates = pipeline.run_stage_c(n["seed"])

CLI::

    python -m engine.nexus.cache_pipeline              # full cycle
    python -m engine.nexus.cache_pipeline --stage a    # seed only
    python -m engine.nexus.cache_pipeline --stage g    # store pending approved
    python -m engine.nexus.cache_pipeline --stats      # last cycle result
"""
from __future__ import annotations

import ast
import csv
import io
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ──── Constants ───────────────────────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parent.parent.parent
_STATE_FILE = _ROOT / ".github" / "hooks" / "logs" / "cache_pipeline_state.json"

# Minimum priority to store a pair from Stage D (code/csv mode)
_MIN_STORE_PRIORITY = 3

# Maximum candidates to send to NLM evaluator per batch (keep prompt size sane)
_EVAL_BATCH_SIZE = 50

# Ratings that get stored in Nexus
_STORE_RATINGS = {"ESSENTIAL", "USEFUL"}

# Minimum answer length for a direct-seed turn
_MIN_TURN_ANSWER_LEN = 400


# ──── Data Classes ────────────────────────────────────────────────────────────

@dataclass
class CandidatePair:
    """A Q&A pair candidate generated during pipeline stages C or D."""

    q: str
    a: str
    consumer: str = "developer"
    priority: int = 3
    category: str = "general"
    source: str = ""          # e.g. "flashcard", "quiz", "csv", "code"
    rating: str = ""          # filled by Stage F: ESSENTIAL / USEFUL / SKIP
    reason: str = ""          # NLM evaluation reason


@dataclass
class EvalResult:
    """Result of Stage F NLM self-evaluation."""

    essential: List[CandidatePair] = field(default_factory=list)
    useful: List[CandidatePair] = field(default_factory=list)
    skipped: List[CandidatePair] = field(default_factory=list)
    parse_errors: int = 0

    @property
    def approved(self) -> List[CandidatePair]:
        return self.essential + self.useful


@dataclass
class CycleResult:
    """Full pipeline cycle result — returned by run_full_cycle()."""

    direct_seeded: int = 0          # Stage A: pairs from turns
    sources_uploaded: int = 0       # Stage B: pyramid + content sources
    raw_candidates: int = 0         # Stage C: flashcards + quiz + data_tables
    structured_candidates: int = 0  # Stage D: CSV + code mode
    after_dedup: int = 0            # Stage E: after deduplication
    essential: int = 0              # Stage F: ESSENTIAL rated
    useful: int = 0                 # Stage F: USEFUL rated
    skipped: int = 0                # Stage F: SKIP rated
    stored: int = 0                 # Stage G: written to Nexus
    review_sheet_path: str = ""     # Stage H: xlsx path
    gaps: List[str] = field(default_factory=list)  # Stage J: gap topics
    duration_s: float = 0.0
    errors: List[str] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ──── Cache Pipeline ──────────────────────────────────────────────────────────

class CachePipeline:
    """Orchestrates the 10-stage NLM-driven Q&A cache generation cycle.

    The pipeline uses Gemini 3.0 (via NotebookLM) as both the generator
    and the evaluator, driven by a Source Pyramid that shapes all quota-free
    Studio tile output.

    Args:
        dry_run: If True, log what would happen but don't write to Nexus.
    """

    def __init__(self, dry_run: bool = False) -> None:
        self._dry_run = dry_run
        self._state: Dict[str, Any] = self._load_state()
        self._lock = threading.Lock()

    # ── Notebooks ───────────────────────────────────────────────────────────

    def ensure_notebooks(self) -> Dict[str, str]:
        """Ensure the four pipeline notebooks exist, creating if needed.

        Returns:
            Dict with keys: seed, builder, evaluator — notebook IDs.
        """
        from engine.nexus.nlm_notebook_manager import get_notebook_manager
        mgr = get_notebook_manager()
        week = datetime.now(timezone.utc).strftime("%Y-W%V")
        notebooks: Dict[str, str] = {}
        for role in ("seed", "builder", "evaluator"):
            slot = f"nlm-cache-{role}-{week}"
            nb = mgr.ensure_notebook(slot)
            if nb and isinstance(nb, dict):
                notebooks[role] = nb.get("id", nb.get("notebook_id", ""))
            else:
                notebooks[role] = str(nb) if nb else ""
        logger.info("Pipeline notebooks: %s", notebooks)
        return notebooks

    # ── Full Cycle ──────────────────────────────────────────────────────────

    def run_full_cycle(
        self,
        notebook_ids: Optional[Dict[str, str]] = None,
    ) -> CycleResult:
        """Run the complete 10-stage pipeline.

        Args:
            notebook_ids: Pre-created notebook IDs dict with keys seed, builder,
                evaluator.  If None, notebooks are created automatically.

        Returns:
            CycleResult with counts and metadata for the full run.
        """
        result = CycleResult()
        start = time.time()
        logger.info("=== Cache Pipeline: starting full cycle ===")

        try:
            # Get/create notebooks
            if not notebook_ids:
                notebook_ids = self.ensure_notebooks()
            seed_nb = notebook_ids.get("seed", "")
            builder_nb = notebook_ids.get("builder", "")
            evaluator_nb = notebook_ids.get("evaluator", "")

            # Stage A: direct seed
            result.direct_seeded = self.run_stage_a()

            # Stage B: upload pyramid + content to seed notebook
            if seed_nb:
                result.sources_uploaded = self.run_stage_b(seed_nb)
            else:
                result.errors.append("No seed notebook — skipped stages B/C")

            # Stage C: raw generation
            raw_candidates: List[CandidatePair] = []
            if seed_nb:
                raw_candidates = self.run_stage_c(seed_nb)
                result.raw_candidates = len(raw_candidates)

            # Stage D: structured generation (builder notebook uses seed output)
            structured_candidates: List[CandidatePair] = []
            if builder_nb:
                # Upload seed output as source for builder
                self._upload_candidates_as_source(builder_nb, raw_candidates, "raw-candidates")
                # Upload pyramid to builder too
                self._upload_pyramid_to_notebook(builder_nb)
                structured_candidates = self.run_stage_d(builder_nb)
                result.structured_candidates = len(structured_candidates)

            # Stage E: deduplicate
            all_candidates = raw_candidates + structured_candidates
            deduped = self.run_stage_e(all_candidates)
            result.after_dedup = len(deduped)

            # Stage F: NLM self-evaluation
            eval_result = EvalResult()
            if evaluator_nb and deduped:
                self._upload_candidates_as_source(evaluator_nb, deduped, "candidates")
                self._upload_pyramid_to_notebook(evaluator_nb, layers=[0, 5])  # briefing + rubric
                eval_result = self.run_stage_f(evaluator_nb, deduped)
            else:
                # If no evaluator notebook, treat all candidates as USEFUL
                eval_result.useful = [p for p in deduped if p.priority >= _MIN_STORE_PRIORITY]
                eval_result.skipped = [p for p in deduped if p.priority < _MIN_STORE_PRIORITY]

            result.essential = len(eval_result.essential)
            result.useful = len(eval_result.useful)
            result.skipped = len(eval_result.skipped)

            # Stage G: store approved
            approved = eval_result.approved
            result.stored = self.run_stage_g(approved)

            # Stage H: Excel review sheet
            if approved:
                result.review_sheet_path = self.run_stage_h(approved)

            # Stage I: upload approved as source for next cycle
            if seed_nb and approved:
                self.run_stage_i(seed_nb, approved)

            # Stage J: gap analysis
            if evaluator_nb:
                stored_questions = [p.q for p in approved]
                result.gaps = self.run_stage_j(evaluator_nb, stored_questions)

            # Persist state
            result.duration_s = round(time.time() - start, 1)
            self._save_cycle_result(result)
            logger.info("=== Cache Pipeline: complete in %.1fs | stored=%d gaps=%d ===",
                        result.duration_s, result.stored, len(result.gaps))

        except Exception as exc:
            result.errors.append(str(exc))
            result.duration_s = round(time.time() - start, 1)
            logger.error("Cache pipeline error: %s", exc, exc_info=True)

        return result

    # ── Stage A: Direct Seed ─────────────────────────────────────────────────

    def run_stage_a(self) -> int:
        """Direct seed from high-quality session turns — no NLM needed.

        Returns:
            Number of pairs stored directly in Nexus.
        """
        logger.info("Stage A: direct seed from session turns")
        try:
            from engine.nexus.history_miner import get_history_miner
            from engine.nexus.client import get_nexus_client

            miner = get_history_miner()
            pairs = miner.mine_turns(min_answer_len=_MIN_TURN_ANSWER_LEN)
            if not pairs:
                logger.info("Stage A: no qualifying turns found")
                return 0

            if self._dry_run:
                logger.info("Stage A (dry-run): would seed %d pairs", len(pairs))
                return len(pairs)

            client = get_nexus_client()
            if not client or not client.is_available():
                logger.warning("Stage A: Nexus unavailable — skipping direct seed")
                return 0

            stored = 0
            for pair in pairs:
                # Skip if already in cache
                if self._question_exists(client, pair.question):
                    continue
                try:
                    client.add_qa(
                        question=pair.question[:500],
                        answer=pair.answer[:2000],
                        category="session-history",
                        tags=["direct-seed", "session-turn"],
                    )
                    stored += 1
                except Exception as exc:
                    logger.debug("Stage A: failed to store pair: %s", exc)

            logger.info("Stage A: seeded %d/%d pairs directly", stored, len(pairs))
            return stored

        except Exception as exc:
            logger.error("Stage A failed: %s", exc)
            return 0

    # ── Stage B: Source Upload ────────────────────────────────────────────────

    def run_stage_b(self, notebook_id: str) -> int:
        """Upload source pyramid + themed history chunks to seed notebook.

        Args:
            notebook_id: NLM notebook ID for the seed notebook.

        Returns:
            Total number of sources uploaded.
        """
        logger.info("Stage B: uploading sources to notebook %s", notebook_id[:8])
        try:
            from engine.nexus.source_pyramid import get_source_pyramid
            from engine.nexus.history_miner import get_history_miner
            from engine.nexus.client import get_nexus_client

            pyramid = get_source_pyramid()
            miner = get_history_miner()

            # Get existing questions for coverage layer
            existing: List[str] = []
            try:
                client = get_nexus_client()
                if client and client.is_available():
                    qa_list = client.find_qa("", limit=1000) or []
                    existing = [
                        item.get("question", item.get("q", ""))
                        for item in qa_list
                        if isinstance(item, dict)
                    ]
            except Exception:
                logger.warning("Failed to load existing Q&A for dedup check", exc_info=True)

            # Upload pyramid layers 0-5
            uploaded = pyramid.upload_pyramid(
                notebook_id,
                existing_questions=existing if existing else None,
                skip_layer_4=len(existing) == 0,
            )

            # Upload themed history chunks
            docs = miner.mine_all_themes()
            uploaded += pyramid.upload_content(notebook_id, docs)

            logger.info("Stage B: uploaded %d sources total", uploaded)
            return uploaded

        except Exception as exc:
            logger.error("Stage B failed: %s", exc)
            return 0

    # ── Stage C: Raw Generation ───────────────────────────────────────────────

    def run_stage_c(self, notebook_id: str) -> List[CandidatePair]:
        """Run quota-free generators: flashcards + quiz + data_tables.

        Args:
            notebook_id: NLM seed notebook ID.

        Returns:
            List of raw candidate pairs.
        """
        logger.info("Stage C: raw generation on notebook %s", notebook_id[:8])
        candidates: List[CandidatePair] = []
        try:
            from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
            bridge = get_nlm_node_bridge()

            # Flashcards
            fc_result = bridge.extract_flashcards(notebook_id)
            if fc_result and not fc_result.get("error"):
                for card in fc_result.get("flashcards", []):
                    front = card.get("front", "")
                    back = card.get("back", "")
                    if front and back:
                        candidates.append(CandidatePair(
                            q=front, a=back, source="flashcard",
                        ))
            logger.debug("Stage C: flashcards → %d", len(candidates))

            # Quiz
            quiz_result = bridge.extract_quiz(notebook_id)
            if quiz_result and not quiz_result.get("error"):
                for item in quiz_result.get("questions", []):
                    q = item.get("question", "")
                    a = item.get("answer", "")
                    if not a:
                        # Quiz items may have options — use correct option
                        options = item.get("options", [])
                        correct_idx = item.get("correct_index", 0)
                        if options and correct_idx < len(options):
                            a = options[correct_idx]
                    if q and a:
                        candidates.append(CandidatePair(
                            q=q, a=a, source="quiz",
                        ))
            pre_dt = len(candidates)
            logger.debug("Stage C: quiz added %d", len(candidates) - pre_dt)

            # Data Tables
            dt_result = bridge.extract_data_tables(
                notebook_id,
                query="Q&A pairs for CosySim knowledge cache",
            )
            if dt_result and not dt_result.get("error"):
                for table in dt_result.get("tables", []):
                    rows = table.get("rows", [])
                    for row in rows:
                        # Tables may be [{key: val}, ...] or [[col1, col2], ...]
                        pair = self._extract_pair_from_table_row(row)
                        if pair:
                            candidates.append(pair)
            logger.debug("Stage C: data_tables added %d", len(candidates) - pre_dt)

        except Exception as exc:
            logger.error("Stage C failed: %s", exc)

        logger.info("Stage C: %d raw candidates", len(candidates))
        return candidates

    # ── Stage D: Structured Generation ───────────────────────────────────────

    def run_stage_d(self, notebook_id: str) -> List[CandidatePair]:
        """Structured generation: CSV mode + code-generation mode.

        Args:
            notebook_id: NLM builder notebook ID.

        Returns:
            List of structured candidate pairs with consumer/priority/category.
        """
        logger.info("Stage D: structured generation on notebook %s", notebook_id[:8])
        from engine.nexus.consumer_briefing import get_consumer_briefing
        briefing = get_consumer_briefing()
        candidates: List[CandidatePair] = []

        try:
            from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
            bridge = get_nlm_node_bridge()

            # CSV mode — run once per consumer focus for targeted batches
            for focus in ["all", "agent-task", "copilot-startup"]:
                prompt = briefing.build_csv_prompt(consumer_focus=focus, count=60)
                report = bridge.generate_report_with_prompt(notebook_id, prompt)
                if report and not report.get("error"):
                    csv_text = report.get("content", "")
                    parsed = self._parse_csv_output(csv_text)
                    candidates.extend(parsed)
                    logger.debug("Stage D CSV (%s): +%d candidates", focus, len(parsed))

            # Code-generation mode
            code_prompt = briefing.build_code_gen_prompt(count=80)
            code_report = bridge.generate_report_with_prompt(notebook_id, code_prompt)
            if code_report and not code_report.get("error"):
                code_text = code_report.get("content", "")
                code_pairs = self._exec_code_mode(code_text)
                candidates.extend(code_pairs)
                logger.debug("Stage D code-gen: +%d candidates", len(code_pairs))

        except Exception as exc:
            logger.error("Stage D failed: %s", exc)

        logger.info("Stage D: %d structured candidates", len(candidates))
        return candidates

    # ── Stage E: Deduplicate ──────────────────────────────────────────────────

    def run_stage_e(self, candidates: List[CandidatePair]) -> List[CandidatePair]:
        """Deduplicate candidates against each other and existing Nexus cache.

        Args:
            candidates: All raw + structured candidates.

        Returns:
            Deduplicated list.
        """
        logger.info("Stage E: deduplicating %d candidates", len(candidates))
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
        except Exception:
            logger.debug("Could not init NexusClient for dedup", exc_info=True)
            client = None

        seen_questions: set = set()
        deduped: List[CandidatePair] = []

        for pair in candidates:
            norm = self._normalise_question(pair.q)
            if not norm or len(norm) < 10:
                continue
            if norm in seen_questions:
                continue
            # Check Nexus cache for existing pair
            if client and client.is_available():
                if self._question_exists(client, pair.q):
                    continue
            seen_questions.add(norm)
            deduped.append(pair)

        removed = len(candidates) - len(deduped)
        logger.info("Stage E: %d candidates after dedup (removed %d)", len(deduped), removed)
        return deduped

    # ── Stage F: NLM Self-Evaluation ─────────────────────────────────────────

    def run_stage_f(
        self,
        notebook_id: str,
        candidates: List[CandidatePair],
    ) -> EvalResult:
        """NLM self-evaluation: rate each candidate ESSENTIAL / USEFUL / SKIP.

        Tries the fine-tuned qa_evaluator model first (fast, free), then falls
        back to NLM/Gemini batch evaluation if unavailable.

        Args:
            notebook_id: NLM evaluator notebook ID.
            candidates: Deduplicated candidate pairs.

        Returns:
            EvalResult with essential, useful, skipped lists.
        """
        logger.info("Stage F: evaluating %d candidates", len(candidates))

        # ── Try fine-tuned QA evaluator first ────────────────────────────────
        try:
            from engine.lmstudio.finetuned_router import get_finetuned_router
            ft_router = get_finetuned_router()
            if ft_router.is_available("qa_evaluator"):
                logger.info("Stage F: using fine-tuned qa_evaluator model")
                return self._run_stage_f_finetuned(ft_router, candidates)
        except Exception as exc:
            logger.debug("Fine-tuned evaluator unavailable, falling back to NLM: %s", exc)

        # ── Fall back to NLM/Gemini evaluation ───────────────────────────────
        from engine.nexus.consumer_briefing import get_consumer_briefing
        briefing = get_consumer_briefing()
        result = EvalResult()

        try:
            from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
            bridge = get_nlm_node_bridge()

            # Process in batches
            for i in range(0, len(candidates), _EVAL_BATCH_SIZE):
                batch = candidates[i:i + _EVAL_BATCH_SIZE]
                pairs_csv = self._candidates_to_csv(batch)
                eval_prompt = briefing.build_evaluation_prompt(pairs_csv)
                report = bridge.generate_report_with_prompt(notebook_id, eval_prompt)
                if not report or report.get("error"):
                    logger.warning("Stage F: evaluation batch %d failed", i)
                    result.useful.extend(batch)  # default to USEFUL if eval fails
                    continue

                rated = self._parse_evaluation_output(report.get("content", ""), batch)
                result.essential.extend(rated.essential)
                result.useful.extend(rated.useful)
                result.skipped.extend(rated.skipped)
                result.parse_errors += rated.parse_errors
                logger.debug(
                    "Stage F batch %d: E=%d U=%d S=%d",
                    i, len(rated.essential), len(rated.useful), len(rated.skipped),
                )

        except Exception as exc:
            logger.error("Stage F failed: %s", exc)
            result.useful.extend(candidates)  # fall back to storing all

        logger.info("Stage F: E=%d U=%d S=%d errors=%d",
                    len(result.essential), len(result.useful),
                    len(result.skipped), result.parse_errors)
        return result

    def _run_stage_f_finetuned(
        self,
        router: Any,
        candidates: List[CandidatePair],
    ) -> "EvalResult":
        """Stage F variant using a local fine-tuned qa_evaluator model."""
        result = EvalResult()
        for candidate in candidates:
            try:
                label = router.route_qa_evaluation(candidate.question, candidate.answer)
                if label is None:
                    result.useful.append(candidate)
                    continue
                label = label.strip().upper().split()[0] if label.strip() else "USEFUL"
                candidate.rating = label
                if label == "ESSENTIAL":
                    result.essential.append(candidate)
                elif label == "SKIP":
                    result.skipped.append(candidate)
                else:
                    result.useful.append(candidate)
            except Exception:
                result.useful.append(candidate)
        logger.info(
            "Stage F (fine-tuned): E=%d U=%d S=%d",
            len(result.essential), len(result.useful), len(result.skipped),
        )
        return result

    # ── Stage G: Store ────────────────────────────────────────────────────────

    def run_stage_g(self, approved: List[CandidatePair]) -> int:
        """Store approved pairs in the Nexus Q&A cache.

        Args:
            approved: ESSENTIAL + USEFUL rated pairs.

        Returns:
            Number of pairs successfully stored.
        """
        logger.info("Stage G: storing %d approved pairs", len(approved))
        if self._dry_run:
            logger.info("Stage G (dry-run): would store %d pairs", len(approved))
            return len(approved)
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            if not client or not client.is_available():
                logger.warning("Stage G: Nexus unavailable")
                return 0

            stored = 0
            for pair in approved:
                try:
                    client.add_qa(
                        question=pair.q[:500],
                        answer=pair.a[:2000],
                        category=pair.category or "general",
                        tags=[
                            "nlm-generated",
                            f"consumer-{pair.consumer}",
                            f"priority-{pair.priority}",
                            pair.rating.lower() if pair.rating else "useful",
                        ],
                    )
                    stored += 1
                except Exception as exc:
                    logger.debug("Stage G: failed to store pair '%s': %s",
                                 pair.q[:50], exc)

            logger.info("Stage G: stored %d/%d pairs", stored, len(approved))
            return stored

        except Exception as exc:
            logger.error("Stage G failed: %s", exc)
            return 0

    # ── Stage H: Excel Review Sheet ───────────────────────────────────────────

    def run_stage_h(self, approved: List[CandidatePair]) -> str:
        """Generate an Excel review sheet for the approved pairs.

        Args:
            approved: Approved pairs to include in the sheet.

        Returns:
            Path to the generated xlsx file, or empty string on failure.
        """
        logger.info("Stage H: generating review sheet for %d pairs", len(approved))
        try:
            from engine.nexus.review_sheet import get_review_sheet
            rs = get_review_sheet()
            date_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path = str(_ROOT / "data" / f"qa_review_{date_str}.xlsx")
            saved = rs.generate(approved, path)
            logger.info("Stage H: review sheet saved to %s", saved)
            return saved
        except Exception as exc:
            logger.warning("Stage H: review sheet generation failed: %s", exc)
            return ""

    # ── Stage I: Compound Upload ──────────────────────────────────────────────

    def run_stage_i(
        self,
        notebook_id: str,
        approved: List[CandidatePair],
    ) -> None:
        """Upload approved pairs as source for the next cycle (compounding).

        Args:
            notebook_id: Seed notebook ID.
            approved: Approved pairs to upload as a source document.
        """
        logger.info("Stage I: uploading %d approved pairs as compound source", len(approved))
        try:
            from engine.mcp.nlm_hybrid import get_nlm_hybrid
            hybrid = get_nlm_hybrid()
            content = self._candidates_to_markdown(approved)
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            title = f"Approved QA Pairs — {date_str}"
            result = hybrid.add_text_source(notebook_id, title=title, content=content)
            if result and result.get("error"):
                logger.warning("Stage I: upload failed: %s", result)
        except Exception as exc:
            logger.error("Stage I failed: %s", exc)

    # ── Stage J: Gap Analysis ─────────────────────────────────────────────────

    def run_stage_j(
        self,
        notebook_id: str,
        stored_questions: List[str],
    ) -> List[str]:
        """Identify coverage gaps and create scheduler tasks for each.

        Args:
            notebook_id: Evaluator notebook ID.
            stored_questions: Questions stored in this cycle.

        Returns:
            List of gap topics/questions identified by Gemini.
        """
        logger.info("Stage J: gap analysis")
        gaps: List[str] = []
        try:
            from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
            from engine.nexus.consumer_briefing import get_consumer_briefing
            bridge = get_nlm_node_bridge()
            briefing = get_consumer_briefing()

            # Fetch all current questions for a full coverage picture
            all_questions = stored_questions.copy()
            try:
                from engine.nexus.client import get_nexus_client
                client = get_nexus_client()
                if client and client.is_available():
                    qa_list = client.find_qa("", limit=1000) or []
                    all_questions += [
                        item.get("question", item.get("q", ""))
                        for item in qa_list
                        if isinstance(item, dict)
                    ]
            except Exception:
                logger.warning("Failed to load existing Q&A for gap analysis", exc_info=True)

            gap_prompt = briefing.build_gap_prompt(all_questions)
            report = bridge.generate_report_with_prompt(notebook_id, gap_prompt)
            if report and not report.get("error"):
                gaps = self._parse_gap_output(report.get("content", ""))

            # Create scheduler tasks for each gap
            if gaps and not self._dry_run:
                self._create_gap_tasks(gaps)

        except Exception as exc:
            logger.error("Stage J failed: %s", exc)

        logger.info("Stage J: identified %d gaps", len(gaps))
        return gaps

    # ── Parsing Helpers ───────────────────────────────────────────────────────

    def _parse_csv_output(self, text: str) -> List[CandidatePair]:
        """Parse CSV-format Gemini output into candidate pairs."""
        pairs: List[CandidatePair] = []
        if not text:
            return pairs
        try:
            # Find the CSV block — look for header row
            lines = text.strip().split("\n")
            start = 0
            for i, line in enumerate(lines):
                if "Question" in line and "Answer" in line:
                    start = i
                    break
            csv_text = "\n".join(lines[start:])
            reader = csv.DictReader(io.StringIO(csv_text))
            for row in reader:
                q = row.get("Question", row.get("question", "")).strip()
                a = row.get("Answer", row.get("answer", "")).strip()
                if not q or not a:
                    continue
                consumer = row.get("Consumer", row.get("consumer", "developer")).strip().lower()
                try:
                    priority = int(row.get("Priority", row.get("priority", "3")))
                    priority = max(1, min(5, priority))
                except (ValueError, TypeError):
                    priority = 3
                category = row.get("Category", row.get("category", "general")).strip().lower()
                pairs.append(CandidatePair(
                    q=q, a=a, consumer=consumer, priority=priority,
                    category=category, source="csv",
                ))
        except Exception as exc:
            logger.warning("CSV parse error: %s", exc)
        return pairs

    def _exec_code_mode(self, code: str) -> List[CandidatePair]:
        """Sandbox-execute Gemini-generated build_qa_pairs() function.

        Extracts the function definition from the generated code and executes
        it in a restricted namespace.  Gracefully handles code that includes
        extra boilerplate, comments, or docstrings.

        Args:
            code: Raw code text from Gemini.

        Returns:
            List of CandidatePair objects from the function's return value.
        """
        if not code:
            return []
        pairs: List[CandidatePair] = []
        try:
            # Extract only the function definition
            func_code = self._extract_function(code, "build_qa_pairs")
            if not func_code:
                logger.debug("Code mode: no build_qa_pairs function found")
                return []

            # Execute in a restricted namespace (no builtins)
            namespace: Dict[str, Any] = {"__builtins__": {}}
            exec(func_code, namespace)  # noqa: S102

            if "build_qa_pairs" not in namespace:
                logger.debug("Code mode: function not in namespace after exec")
                return []

            raw_pairs = namespace["build_qa_pairs"]()
            if not isinstance(raw_pairs, list):
                logger.debug("Code mode: function returned non-list")
                return []

            for item in raw_pairs:
                if not isinstance(item, dict):
                    continue
                q = str(item.get("q", "")).strip()
                a = str(item.get("a", "")).strip()
                if not q or not a:
                    continue
                consumer = str(item.get("consumer", "developer")).lower()
                try:
                    priority = int(item.get("priority", 3))
                    priority = max(1, min(5, priority))
                except (ValueError, TypeError):
                    priority = 3
                category = str(item.get("category", "general")).lower()
                pairs.append(CandidatePair(
                    q=q, a=a, consumer=consumer, priority=priority,
                    category=category, source="code",
                ))

        except SyntaxError as exc:
            logger.warning("Code mode: syntax error: %s", exc)
        except Exception as exc:
            logger.warning("Code mode: execution error: %s", exc)

        logger.debug("Code mode: extracted %d pairs", len(pairs))
        return pairs

    def _extract_function(self, code: str, func_name: str) -> str:
        """Extract a named function definition from code text."""
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == func_name:
                    return ast.unparse(node)
        except SyntaxError:
            # Try extracting with string search as fallback
            marker = f"def {func_name}"
            idx = code.find(marker)
            if idx >= 0:
                return code[idx:]
        return ""

    def _parse_evaluation_output(
        self,
        text: str,
        originals: List[CandidatePair],
    ) -> EvalResult:
        """Parse Stage F evaluation JSON output."""
        result = EvalResult()
        if not text:
            result.useful.extend(originals)
            return result
        try:
            # Find JSON array in output
            start = text.find("[")
            end = text.rfind("]") + 1
            if start < 0 or end <= start:
                raise ValueError("No JSON array found")
            rated_list = json.loads(text[start:end])
            # Build lookup by normalised question
            orig_by_q = {self._normalise_question(p.q): p for p in originals}
            seen = set()
            for item in rated_list:
                if not isinstance(item, dict):
                    continue
                q = item.get("q", item.get("question", ""))
                a = item.get("a", item.get("answer", ""))
                rating = str(item.get("rating", "USEFUL")).upper()
                reason = str(item.get("reason", ""))
                norm = self._normalise_question(q)
                # Match to original or create new
                orig = orig_by_q.get(norm)
                if orig is None:
                    # Try fuzzy match — if question is mostly the same
                    orig = next(
                        (p for key, p in orig_by_q.items()
                         if key and norm and (key in norm or norm in key)),
                        None,
                    )
                if orig:
                    orig.rating = rating
                    orig.reason = reason
                    candidate = orig
                else:
                    # New pair from evaluation response
                    if not q or not a:
                        continue
                    candidate = CandidatePair(q=q, a=a, rating=rating, reason=reason)

                if norm in seen:
                    continue
                seen.add(norm)

                if rating == "ESSENTIAL":
                    result.essential.append(candidate)
                elif rating == "USEFUL":
                    result.useful.append(candidate)
                else:
                    result.skipped.append(candidate)

            # Any originals not matched → default USEFUL
            for norm, orig in orig_by_q.items():
                if norm not in seen:
                    result.useful.append(orig)

        except Exception as exc:
            logger.warning("Evaluation parse error: %s", exc)
            result.parse_errors += 1
            result.useful.extend(originals)

        return result

    def _parse_gap_output(self, text: str) -> List[str]:
        """Parse Stage J gap analysis JSON output."""
        if not text:
            return []
        try:
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                gaps = json.loads(text[start:end])
                return [str(g) for g in gaps if g]
        except Exception as exc:
            logger.warning("Gap parse error: %s", exc)
        return []

    def _extract_pair_from_table_row(self, row: Any) -> Optional[CandidatePair]:
        """Try to extract a Q&A pair from a data table row."""
        if isinstance(row, dict):
            q = row.get("Question", row.get("question", row.get("q", "")))
            a = row.get("Answer", row.get("answer", row.get("a", "")))
            if q and a:
                return CandidatePair(q=str(q), a=str(a), source="data_table")
        elif isinstance(row, list) and len(row) >= 2:
            return CandidatePair(q=str(row[0]), a=str(row[1]), source="data_table")
        return None

    def _candidates_to_csv(self, pairs: List[CandidatePair]) -> str:
        """Serialise candidates as CSV text for the evaluation prompt."""
        buf = io.StringIO()
        writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(["q", "a", "consumer", "priority", "category"])
        for p in pairs:
            writer.writerow([p.q[:300], p.a[:500], p.consumer, p.priority, p.category])
        return buf.getvalue()

    def _candidates_to_markdown(self, pairs: List[CandidatePair]) -> str:
        """Serialise approved pairs as markdown for NLM source upload."""
        lines = ["# Approved Q&A Pairs\n"]
        for i, p in enumerate(pairs, 1):
            lines.append(f"## Pair {i}")
            lines.append(f"**Q:** {p.q}")
            lines.append(f"**A:** {p.a}")
            lines.append(f"Consumer: {p.consumer} | Priority: {p.priority} | Category: {p.category}")
            lines.append("")
        return "\n".join(lines)

    # ── Utility ───────────────────────────────────────────────────────────────

    def _normalise_question(self, q: str) -> str:
        """Normalise a question for dedup comparison."""
        return q.lower().strip().rstrip("?").strip()[:200]

    def _question_exists(self, client: Any, question: str) -> bool:
        """Check if a question is already in the Nexus Q&A cache."""
        try:
            results = client.find_qa(question, limit=1)
            if results and isinstance(results, list) and results:
                existing_q = results[0].get("question", results[0].get("q", ""))
                if self._normalise_question(existing_q) == self._normalise_question(question):
                    return True
        except Exception:
            logger.debug("Dedup check failed for question: %.60s", question, exc_info=True)
        return False

    def _upload_candidates_as_source(
        self,
        notebook_id: str,
        candidates: List[CandidatePair],
        label: str,
    ) -> None:
        """Upload a list of candidates as a source document."""
        if not candidates:
            return
        try:
            from engine.mcp.nlm_hybrid import get_nlm_hybrid
            hybrid = get_nlm_hybrid()
            content = self._candidates_to_markdown(candidates)
            hybrid.add_text_source(notebook_id, title=f"_CANDIDATES_{label.upper()}", content=content)
        except Exception as exc:
            logger.warning("Could not upload candidates as source: %s", exc)

    def _upload_pyramid_to_notebook(
        self,
        notebook_id: str,
        layers: Optional[List[int]] = None,
    ) -> None:
        """Upload specific pyramid layers to a notebook."""
        try:
            from engine.nexus.source_pyramid import get_source_pyramid
            pyramid = get_source_pyramid()
            if layers is None:
                pyramid.upload_pyramid(notebook_id, skip_layer_4=True)
            else:
                from engine.mcp.nlm_hybrid import get_nlm_hybrid
                hybrid = get_nlm_hybrid()
                from engine.nexus.source_pyramid import _LAYER_NAMES
                for layer_num in layers:
                    content = pyramid.build_layer(layer_num)
                    hybrid.add_text_source(
                        notebook_id,
                        title=_LAYER_NAMES[layer_num],
                        content=content,
                    )
        except Exception as exc:
            logger.warning("Could not upload pyramid: %s", exc)

    def _create_gap_tasks(self, gaps: List[str]) -> None:
        """Create one-off scheduler tasks for each identified gap."""
        try:
            from engine.nexus.scheduler_daemon import get_scheduler_daemon
            daemon = get_scheduler_daemon()
            for gap in gaps[:20]:  # cap at 20 gap tasks per cycle
                safe_id = "qa-gap-" + gap[:40].lower().replace(" ", "-").replace("?", "")
                safe_id = "".join(c for c in safe_id if c.isalnum() or c == "-")
                try:
                    daemon.register(
                        safe_id,
                        f"QA Gap Fill: {gap[:60]}",
                        "once",
                        lambda g=gap: self._run_gap_fill(g),
                    )
                    logger.debug("Created gap task: %s", safe_id)
                except Exception:
                    pass  # Task may already exist
        except Exception as exc:
            logger.warning("Could not create gap tasks: %s", exc)

    def _run_gap_fill(self, gap_topic: str) -> Dict[str, Any]:
        """Run a targeted generation cycle for a specific gap topic."""
        logger.info("Gap fill: %s", gap_topic)
        # This is a simplified cycle — just stage D with focused prompt
        # In a full implementation this would spin up a dedicated notebook
        return {"gap": gap_topic, "status": "scheduled"}

    # ── State ──────────────────────────────────────────────────────────────────

    def _load_state(self) -> Dict[str, Any]:
        """Load persisted pipeline state."""
        if _STATE_FILE.exists():
            try:
                return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"last_cycle": None, "total_stored": 0}

    def _save_cycle_result(self, result: CycleResult) -> None:
        """Persist cycle result to state file."""
        try:
            _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            self._state["last_cycle"] = {
                "timestamp": result.timestamp,
                "stored": result.stored,
                "essential": result.essential,
                "useful": result.useful,
                "skipped": result.skipped,
                "gaps": result.gaps,
                "duration_s": result.duration_s,
                "errors": result.errors,
            }
            self._state["total_stored"] = (
                self._state.get("total_stored", 0) + result.stored
            )
            _STATE_FILE.write_text(
                json.dumps(self._state, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Could not save cycle state: %s", exc)

    def get_last_result(self) -> Optional[Dict[str, Any]]:
        """Return the last cycle result from state."""
        return self._state.get("last_cycle")


# ──── Singleton ───────────────────────────────────────────────────────────────

_pipeline_instance: Optional[CachePipeline] = None
_pipeline_lock = threading.Lock()


def get_cache_pipeline(dry_run: bool = False) -> CachePipeline:
    """Get the singleton CachePipeline instance."""
    global _pipeline_instance
    if _pipeline_instance is None:
        with _pipeline_lock:
            if _pipeline_instance is None:
                _pipeline_instance = CachePipeline(dry_run=dry_run)
    return _pipeline_instance


# ──── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="NLM-driven Q&A cache pipeline")
    parser.add_argument("--stage", choices=list("abcdefghij"),
                        help="Run a single stage only")
    parser.add_argument("--dry-run", action="store_true",
                        help="Log but don't write to Nexus")
    parser.add_argument("--stats", action="store_true",
                        help="Show last cycle result")
    args = parser.parse_args()

    pipeline = CachePipeline(dry_run=args.dry_run)

    if args.stats:
        result = pipeline.get_last_result()
        print(json.dumps(result, indent=2, default=str) if result else "No prior cycle found")
    elif args.stage:
        stage = args.stage.upper()
        print(f"Running stage {stage}...")
        if stage == "A":
            n = pipeline.run_stage_a()
            print(f"Seeded {n} pairs")
        else:
            print(f"Stage {stage} requires notebook IDs — run full cycle first")
    else:
        result = pipeline.run_full_cycle()
        print(f"\n=== Cycle complete ===")
        print(f"Direct seeded:   {result.direct_seeded}")
        print(f"Sources up:      {result.sources_uploaded}")
        print(f"Raw candidates:  {result.raw_candidates}")
        print(f"Structured:      {result.structured_candidates}")
        print(f"After dedup:     {result.after_dedup}")
        print(f"Essential:       {result.essential}")
        print(f"Useful:          {result.useful}")
        print(f"Skipped:         {result.skipped}")
        print(f"Stored:          {result.stored}")
        print(f"Gaps found:      {len(result.gaps)}")
        print(f"Duration:        {result.duration_s}s")
        if result.review_sheet_path:
            print(f"Review sheet:    {result.review_sheet_path}")
        if result.errors:
            print(f"Errors:          {result.errors}")
