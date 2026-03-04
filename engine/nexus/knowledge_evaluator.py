"""
KnowledgeCoverageEvaluator — daily knowledge gap analysis with auto-remediation.

Uses NotebookLM (or LMStudio fallback) to ask "what topics are underrepresented?"
across the current Nexus knowledge base, stores coverage reports in the Nexus DB,
and auto-triggers distill_to_nexus on detected gaps.

This is a core component of the self-improving knowledge loop:
    1. Evaluate coverage daily
    2. Find gaps
    3. Identify notebooks that cover those gaps
    4. Auto-distil gap areas to Nexus
    5. Repeat → knowledge base grows, coverage score improves

Usage (from scheduler_daemon):
    from engine.nexus.knowledge_evaluator import run_coverage_evaluation
    result = run_coverage_evaluation()
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Coverage Prompts ──────────────────────────────────────────────────

_COVERAGE_QUESTION = (
    "Looking at the knowledge base contents provided, what important topics, "
    "concepts, or domains are underrepresented, missing, or only shallowly covered? "
    "List the top 10 gap topics as a numbered list with a brief explanation for each."
)

_RECOMMENDATIONS_QUESTION = (
    "Given these knowledge gaps: {gaps}\n\n"
    "What specific steps should be taken to fill them? "
    "Provide 5 concrete, actionable recommendations."
)

# Token-saving estimate for avoided LLM calls
_COVERAGE_SCORE_EXCELLENT = 0.80  # Above this: no action needed
_COVERAGE_SCORE_GOOD = 0.65       # Above this: light distillation
_COVERAGE_SCORE_POOR = 0.40       # Below this: aggressive distillation


class KnowledgeCoverageEvaluator:
    """Evaluates knowledge coverage and triggers gap-filling distillation.

    Scoring model:
        - Entries per distinct category: up to 0.4
        - QA pairs coverage: up to 0.3
        - Recent activity (entries added in last 7 days): up to 0.15
        - Topic diversity (unique tags): up to 0.15
        Score range: 0.0 (empty) → 1.0 (excellent)
    """

    def __init__(self, nlm_node_bridge: Optional[Any] = None) -> None:
        """
        Args:
            nlm_node_bridge: Optional NLMNodeBridge for NLM-powered gap analysis.
                             If None, uses heuristic-only evaluation.
        """
        self._bridge = nlm_node_bridge

    def _get_bridge(self) -> Optional[Any]:
        """Lazy-load NLMNodeBridge."""
        if self._bridge is None:
            try:
                from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
                self._bridge = get_nlm_node_bridge()
            except Exception:
                pass
        return self._bridge

    def _get_client(self):
        """Return Nexus client for REST API access."""
        from engine.nexus.client import get_nexus_client
        return get_nexus_client()

    # ── Public API ───────────────────────────────────────────────────

    def evaluate(self, notebook_id: str = "") -> Dict[str, Any]:
        """Run a full coverage evaluation cycle.

        Steps:
            1. Compute heuristic coverage score from DB stats
            2. If NLM available: ask for gap analysis
            3. Store coverage report in Nexus DB
            4. If score below threshold: trigger auto-distillation
            5. Return full report

        Args:
            notebook_id: NLM notebook to use for gap analysis (optional).

        Returns:
            Coverage report dict with: coverage_score, gap_topics,
            underrepresented, recommendations, actions_taken.
        """
        client = self._get_client()

        # Step 1: Heuristic score from DB stats
        stats = self._compute_heuristic_score(client)
        coverage_score = stats["score"]
        underrepresented = stats["underrepresented_categories"]

        # Step 2: NLM gap analysis (if available)
        gap_topics: List[str] = []
        recommendations: List[str] = []
        if self._get_bridge():
            gap_topics, recommendations = self._nlm_gap_analysis(
                notebook_id=notebook_id,
                underrepresented=underrepresented,
            )
        else:
            # Heuristic fallback: flag thin categories as gaps
            gap_topics = [
                f"{cat}: only {count} entries"
                for cat, count in stats["category_counts"].items()
                if count < 5
            ][:10]
            recommendations = [
                f"Add more entries to the '{cat}' category (currently {count} entries)."
                for cat, count in stats["category_counts"].items()
                if count < 5
            ][:5]

        # Step 3: Store report in Nexus DB
        actions_taken: List[str] = []
        report_id = self._store_report(
            client=client,
            gap_topics=gap_topics,
            underrepresented=underrepresented,
            recommendations=recommendations,
            total_entries=stats["total_entries"],
            coverage_score=coverage_score,
            actions_taken=actions_taken,
        )

        # Step 4: Auto-trigger distillation if coverage is poor
        if coverage_score < _COVERAGE_SCORE_EXCELLENT and self._get_bridge():
            distill_actions = self._auto_distil_gaps(
                gap_topics=gap_topics,
                notebook_id=notebook_id,
                coverage_score=coverage_score,
            )
            actions_taken.extend(distill_actions)
            # Update report with actions
            if distill_actions:
                self._update_report_actions(client, actions_taken)

        report = {
            "report_id": report_id,
            "coverage_score": coverage_score,
            "total_entries": stats["total_entries"],
            "gap_topics": gap_topics,
            "underrepresented": underrepresented,
            "recommendations": recommendations,
            "actions_taken": actions_taken,
            "evaluated_at": _now(),
        }
        logger.info(
            "Coverage evaluation complete: score=%.2f, gaps=%d, actions=%d",
            coverage_score, len(gap_topics), len(actions_taken),
        )
        return report

    def compute_score_only(self) -> float:
        """Quick coverage score without full NLM analysis. Returns 0.0–1.0."""
        client = self._get_client()
        return self._compute_heuristic_score(client)["score"]

    # ── Scoring ──────────────────────────────────────────────────────

    def _compute_heuristic_score(self, client: Any) -> Dict[str, Any]:
        """Compute a heuristic coverage score from live Nexus stats."""
        try:
            stats = client.search("", limit=1)  # Not ideal but gets us a count
        except Exception:
            stats = []

        # Use client stats endpoint
        try:
            stats_result = client.stats()
            db_stats = stats_result.get("data", {}) if stats_result.get("ok") else {}
        except Exception:
            db_stats = {}

        total_entries = db_stats.get("knowledge_entries", 0)
        total_qa = db_stats.get("qa_pairs", 0)

        # Get category distribution via entries endpoint
        category_counts: Dict[str, int] = {}
        try:
            entries = client.list_entries(limit=1000)
            for e in entries:
                cat = e.category or "uncategorised"
                category_counts[cat] = category_counts.get(cat, 0) + 1
        except Exception as exc:
            logger.debug("Could not fetch category distribution: %s", exc)

        # Score components
        # 1. Category diversity (up to 0.40): ideal = 10+ categories with 20+ entries each
        num_rich_cats = sum(1 for c in category_counts.values() if c >= 10)
        cat_score = min(num_rich_cats / 10.0, 1.0) * 0.40

        # 2. QA coverage (up to 0.30): target = entries * 0.5 QA pairs
        qa_target = max(total_entries * 0.5, 50)
        qa_score = min(total_qa / qa_target, 1.0) * 0.30

        # 3. Volume (up to 0.20): target = 500 entries
        vol_score = min(total_entries / 500.0, 1.0) * 0.20

        # 4. Category breadth (up to 0.10): target = 15 distinct categories
        breadth_score = min(len(category_counts) / 15.0, 1.0) * 0.10

        total_score = round(cat_score + qa_score + vol_score + breadth_score, 3)

        # Find underrepresented categories
        thin_threshold = max(total_entries // 20, 3) if total_entries else 3
        underrepresented = [
            cat for cat, cnt in sorted(category_counts.items(), key=lambda x: x[1])
            if cnt < thin_threshold
        ][:8]

        return {
            "score": total_score,
            "total_entries": total_entries,
            "total_qa": total_qa,
            "category_counts": category_counts,
            "underrepresented_categories": underrepresented,
            "components": {
                "category_richness": round(cat_score, 3),
                "qa_coverage": round(qa_score, 3),
                "volume": round(vol_score, 3),
                "breadth": round(breadth_score, 3),
            },
        }

    # ── NLM Gap Analysis ──────────────────────────────────────────────

    def _nlm_gap_analysis(
        self,
        notebook_id: str,
        underrepresented: List[str],
    ) -> tuple[List[str], List[str]]:
        """Ask NLM for gap analysis. Returns (gap_topics, recommendations)."""
        bridge = self._get_bridge()
        if not bridge:
            return [], []

        try:
            # Use multi-ask to get both gaps and recommendations in one session
            nb_id = notebook_id or ""
            gaps_question = _COVERAGE_QUESTION
            recs_question = _RECOMMENDATIONS_QUESTION.format(
                gaps=", ".join(underrepresented[:5]) if underrepresented else "general gaps"
            )

            result = bridge.ask_multi(
                notebook_id=nb_id,
                questions=[gaps_question, recs_question],
            )

            gap_topics: List[str] = []
            recommendations: List[str] = []

            answers = result.get("answers", [])
            if answers and len(answers) >= 1:
                gap_text = answers[0].get("answer", "")
                gap_topics = self._parse_numbered_list(gap_text)[:10]

            if answers and len(answers) >= 2:
                rec_text = answers[1].get("answer", "")
                recommendations = self._parse_numbered_list(rec_text)[:5]

            return gap_topics, recommendations

        except Exception as exc:
            logger.warning("NLM gap analysis failed (non-fatal): %s", exc)
            return [], []

    def _parse_numbered_list(self, text: str) -> List[str]:
        """Parse a numbered list from text into a list of strings."""
        import re
        lines = text.strip().split("\n")
        items = []
        for line in lines:
            line = line.strip()
            # Match patterns like "1. ", "1) ", "• ", "- "
            m = re.match(r'^(?:\d+[\.\)]\s*|[•\-]\s*)(.+)', line)
            if m:
                items.append(m.group(1).strip())
            elif line and not items and len(line) > 10:
                # First non-empty line if no list found
                items.append(line)
        return [i for i in items if i]

    # ── Report Storage ────────────────────────────────────────────────

    def _store_report(
        self,
        client: Any,
        gap_topics: List[str],
        underrepresented: List[str],
        recommendations: List[str],
        total_entries: int,
        coverage_score: float,
        actions_taken: List[str],
    ) -> Optional[int]:
        """Store a coverage report in Nexus as a knowledge entry."""
        try:
            entry_content = json.dumps({
                "score": coverage_score,
                "gaps": gap_topics,
                "recommendations": recommendations,
                "actions": actions_taken,
            }, indent=2)
            return client.add_entry(
                f"Coverage Report {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                entry_content,
                content_type="note",
                category="system_metrics",
            )
        except Exception as exc:
            logger.warning("Coverage report storage failed: %s", exc)
        return None

    def _update_report_actions(self, client: Any, actions_taken: List[str]) -> None:
        """Update the most recent coverage report with actions taken."""
        logger.debug("Coverage report action update: no-op (coverage endpoint not in client)")

    # ── Auto-Distillation ─────────────────────────────────────────────

    def _auto_distil_gaps(
        self,
        gap_topics: List[str],
        notebook_id: str,
        coverage_score: float,
    ) -> List[str]:
        """Trigger distillation for gap areas. Returns list of actions taken."""
        bridge = self._get_bridge()
        if not bridge or not notebook_id:
            return []

        actions: List[str] = []

        # Decide how aggressively to distil based on score
        if coverage_score < _COVERAGE_SCORE_POOR:
            # Aggressive: full distil_to_nexus
            try:
                category = "distillation"
                result = bridge.distill_to_nexus(notebook_id, nexus_category=category)
                pairs = result.get("total_stored", 0)
                if pairs:
                    actions.append(
                        f"Full distillation: {pairs} Q&A pairs stored from notebook {notebook_id}"
                    )
                    logger.info("Auto-distil (aggressive): %d pairs stored", pairs)
            except Exception as exc:
                logger.warning("Auto-distil failed: %s", exc)

        elif coverage_score < _COVERAGE_SCORE_GOOD:
            # Moderate: extract flashcards only (quota-free)
            try:
                result = bridge.extract_flashcards(notebook_id, store_in_nexus=True)
                pairs = result.get("stored_count", 0)
                if pairs:
                    actions.append(
                        f"Flashcard distillation: {pairs} pairs stored from notebook {notebook_id}"
                    )
            except Exception as exc:
                logger.warning("Flashcard distil failed: %s", exc)

        return actions


# ── Scheduler Callback ─────────────────────────────────────────────

def run_coverage_evaluation(notebook_id: str = "") -> Dict[str, Any]:
    """Top-level entry point for the scheduler daemon callback.

    Args:
        notebook_id: Optional NLM notebook to use for gap analysis.
                     If empty, uses config value notebooklm.librarian_notebook_id.

    Returns:
        Coverage evaluation report dict.
    """
    if not notebook_id:
        try:
            from engine.config import get_config
            notebook_id = get_config().get("notebooklm.librarian_notebook_id", "")
        except Exception:
            pass

    evaluator = KnowledgeCoverageEvaluator()
    return evaluator.evaluate(notebook_id=notebook_id)
