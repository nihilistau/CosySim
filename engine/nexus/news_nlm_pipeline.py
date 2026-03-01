"""News NLM Pipeline — distil fetched news articles through NotebookLM.

After news articles are fetched and stored in Nexus, this pipeline:
1. Creates/finds a daily news NLM notebook
2. Uploads the day's digest as a text source
3. Runs targeted distillation questions via batch-ask
4. Stores Q&A pairs in Nexus (news category) for agent consumption
5. Persists notebook ID for continuity across runs

Usage:
    python -m engine.nexus.news_nlm_pipeline --articles-limit 20
    python -m engine.nexus.news_nlm_pipeline --dry-run
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── State file for notebook ID persistence ──────────────────────────────
_STATE_FILE = Path(__file__).resolve().parent.parent.parent / ".github" / "hooks" / "logs" / "news_nlm_state.json"

# ── Notebook name (rolling — replaced each week) ────────────────────────
_NOTEBOOK_NAME_PREFIX = "CosySim News Intelligence"

# ── Distillation questions — targeted for developer news consumption ─────
DISTILLATION_QUESTIONS: List[str] = [
    "What are the 5 most significant AI and machine learning developments in these articles?",
    "What practical actions should a developer or engineer take based on this news?",
    "What new tools, libraries, or frameworks are mentioned and worth evaluating?",
    "What risks, security issues, or breaking changes are discussed?",
    "Which developments are most relevant to LLM agents, local inference, or knowledge systems?",
    "What key trends are emerging across multiple articles today?",
    "Are there any notable research papers, benchmarks, or technical advances referenced?",
    "What companies or open-source projects are doing the most interesting AI work right now?",
    "Summarize the top 3 actionable takeaways from today's news in one sentence each.",
    "What information from these articles should be stored long-term in a knowledge base?",
]


# ── State helpers ────────────────────────────────────────────────────────

def _load_state() -> Dict[str, Any]:
    """Load persistent pipeline state."""
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_state(state: Dict[str, Any]) -> None:
    """Save persistent pipeline state."""
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.debug("Could not save news NLM state: %s", exc)


def _get_week_label() -> str:
    """Return current ISO week label, e.g. '2026-W09'."""
    now = datetime.now(timezone.utc)
    return f"{now.year}-W{now.isocalendar()[1]:02d}"


# ── Pipeline ─────────────────────────────────────────────────────────────

class NewsNLMPipeline:
    """Distils daily news articles through NotebookLM for AI-curated insights.

    Designed to be called after the news-fetch scheduler task has stored
    articles in Nexus. Reads the digest from Nexus or accepts a pre-built
    text block, uploads to NLM, distils answers, and stores them back.
    """

    def __init__(self) -> None:
        self._state = _load_state()

    def _get_hybrid(self):
        """Lazy-load NLM hybrid router."""
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        return get_nlm_hybrid()

    def _get_nexus(self):
        """Lazy-load Nexus client."""
        from engine.nexus.client import get_nexus_client
        return get_nexus_client()

    def _get_or_create_notebook(self) -> Optional[str]:
        """Get current week's news notebook ID, creating it if needed.

        Returns:
            Notebook ID string, or None if NLM unavailable.
        """
        week = _get_week_label()
        notebook_key = f"news_notebook_{week}"
        notebook_id = self._state.get(notebook_key)

        if notebook_id:
            logger.debug("Reusing news notebook %s for week %s", notebook_id, week)
            return notebook_id

        # Create a new notebook for this week
        hybrid = self._get_hybrid()
        notebook_name = f"{_NOTEBOOK_NAME_PREFIX} {week}"
        try:
            from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
            result = get_nlm_node_bridge().create_notebook(
                title=notebook_name,
                description=(
                    f"Daily AI/tech news intelligence for week {week}. "
                    "Articles fetched, filtered, and distilled via CosySim news pipeline."
                ),
            )
            if isinstance(result, dict) and result.get("notebook_id"):
                notebook_id = result["notebook_id"]
                self._state[notebook_key] = notebook_id
                _save_state(self._state)
                logger.info("Created news notebook %s → %s", notebook_name, notebook_id)
                return notebook_id
        except Exception as exc:
            logger.debug("Could not create news notebook: %s", exc)
        return None

    def _build_digest_text(self, articles: List[Any], max_articles: int = 20) -> str:
        """Build a formatted text digest from article objects.

        Args:
            articles: List of NewsArticle-like objects (title, url, summary, score).
            max_articles: Maximum articles to include.

        Returns:
            Formatted text suitable for NLM source upload.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            f"# CosySim Daily News Digest — {today}",
            f"Articles: {min(len(articles), max_articles)} of {len(articles)} fetched",
            "",
        ]
        for i, art in enumerate(articles[:max_articles], 1):
            title = getattr(art, "title", art.get("title", "Unknown") if isinstance(art, dict) else "Unknown")
            url = getattr(art, "url", art.get("url", "") if isinstance(art, dict) else "")
            summary = getattr(art, "summary", art.get("summary", "") if isinstance(art, dict) else "")
            score = getattr(art, "score", art.get("score", 0.0) if isinstance(art, dict) else 0.0)
            category = getattr(art, "category", art.get("category", "") if isinstance(art, dict) else "")

            lines.append(f"## {i}. {title}")
            if category:
                lines.append(f"**Category:** {category} | **Score:** {score:.2f}")
            if url:
                lines.append(f"**URL:** {url}")
            if summary:
                lines.append(f"\n{summary}")
            lines.append("")

        return "\n".join(lines)

    def _upload_digest(self, notebook_id: str, digest_text: str) -> bool:
        """Upload the digest as a text source to the NLM notebook.

        Args:
            notebook_id: Target NLM notebook.
            digest_text: Full formatted text of today's news.

        Returns:
            True if upload succeeded.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
            result = get_nlm_node_bridge().add_source(
                notebook_id,
                text_content=digest_text,
                title=f"News Digest {today}",
            )
            if isinstance(result, dict) and not result.get("error"):
                logger.info("Uploaded news digest to notebook %s", notebook_id)
                return True
            logger.debug("Upload returned: %s", result)
        except Exception as exc:
            logger.debug("Digest upload failed: %s", exc)
        return False

    def _run_distillation(self, notebook_id: str) -> List[Dict[str, str]]:
        """Run batch distillation questions against the news notebook.

        Args:
            notebook_id: NLM notebook containing today's news.

        Returns:
            List of {question, answer} dicts from NLM.
        """
        try:
            hybrid = self._get_hybrid()
            results = hybrid.ask_batch(notebook_id, DISTILLATION_QUESTIONS)
            qa_pairs = []
            for q, r in zip(DISTILLATION_QUESTIONS, results):
                if isinstance(r, dict):
                    answer = r.get("answer", "")
                else:
                    answer = str(r)
                if answer and "error" not in answer.lower()[:20]:
                    qa_pairs.append({"question": q, "answer": answer})
            logger.info("Distilled %d Q&A pairs from news notebook", len(qa_pairs))
            return qa_pairs
        except Exception as exc:
            logger.debug("Distillation batch failed: %s", exc)
            return []

    def _store_qa_to_nexus(self, qa_pairs: List[Dict[str, str]], date_label: str) -> int:
        """Store distilled Q&A pairs into Nexus.

        Args:
            qa_pairs: List of {question, answer} dicts.
            date_label: Date string for tagging.

        Returns:
            Count of pairs stored.
        """
        stored = 0
        try:
            nexus = self._get_nexus()
            for pair in qa_pairs:
                q = pair["question"]
                a = pair["answer"]
                # Prefix questions with date context so they remain searchable
                tagged_q = f"[News {date_label}] {q}"
                nexus.add_qa(tagged_q, a, category="news")
                stored += 1
                time.sleep(0.02)  # avoid hammering DB
        except Exception as exc:
            logger.debug("Nexus Q&A storage failed: %s", exc)
        return stored

    def run(
        self,
        articles: Optional[List[Any]] = None,
        digest_text: Optional[str] = None,
        max_articles: int = 20,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Run the full news NLM distillation pipeline.

        Args:
            articles: List of NewsArticle objects (if None, reads from Nexus).
            digest_text: Pre-built digest text (overrides article building).
            max_articles: Cap on articles to include.
            dry_run: If True, build but don't upload or store.

        Returns:
            Dict with keys: notebook_id, uploaded, qa_count, stored, error.
        """
        date_label = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        result: Dict[str, Any] = {
            "notebook_id": None,
            "uploaded": False,
            "qa_count": 0,
            "stored": 0,
            "dry_run": dry_run,
        }

        # 1. Get or create this week's notebook
        if not dry_run:
            notebook_id = self._get_or_create_notebook()
            if not notebook_id:
                result["error"] = "NLM notebook unavailable — skipping distillation"
                logger.info("News NLM pipeline skipped: NLM offline")
                return result
            result["notebook_id"] = notebook_id
        else:
            notebook_id = "dry-run-nb"
            result["notebook_id"] = notebook_id

        # 2. Build digest text
        if not digest_text:
            if articles:
                digest_text = self._build_digest_text(articles, max_articles)
            else:
                # Fall back to reading today's digest from Nexus
                try:
                    nexus = self._get_nexus()
                    found = nexus.search(f"News Digest: {date_label}", limit=1)
                    if found:
                        digest_text = found[0].get("content", "")
                except Exception:
                    pass
            if not digest_text:
                result["error"] = "No articles or digest available"
                return result

        if dry_run:
            result["digest_length"] = len(digest_text)
            result["questions"] = len(DISTILLATION_QUESTIONS)
            return result

        # 3. Upload digest as source
        uploaded = self._upload_digest(notebook_id, digest_text)
        result["uploaded"] = uploaded

        if not uploaded:
            result["error"] = "Digest upload failed — distillation skipped"
            return result

        # 4. Wait briefly for NLM to index the source
        time.sleep(3)

        # 5. Run distillation
        qa_pairs = self._run_distillation(notebook_id)
        result["qa_count"] = len(qa_pairs)

        # 6. Store Q&A in Nexus
        if qa_pairs:
            stored = self._store_qa_to_nexus(qa_pairs, date_label)
            result["stored"] = stored

            # Also store a consolidated insight entry
            try:
                nexus = self._get_nexus()
                insights = "\n\n".join(
                    f"**Q:** {p['question']}\n**A:** {p['answer']}"
                    for p in qa_pairs
                )
                nexus.add_entry(
                    title=f"News Intelligence: {date_label}",
                    content=insights,
                    content_type="research",
                    category="news",
                    tags=["nlm-distilled", "daily-news", date_label],
                )
            except Exception as exc:
                logger.debug("Could not store consolidated insights: %s", exc)

        logger.info(
            "News NLM pipeline: uploaded=%s qa=%d stored=%d notebook=%s",
            uploaded, result["qa_count"], result["stored"], notebook_id,
        )
        return result


# ── Singleton ────────────────────────────────────────────────────────────

_PIPELINE: Optional[NewsNLMPipeline] = None


def get_news_nlm_pipeline() -> NewsNLMPipeline:
    """Return shared NewsNLMPipeline instance."""
    global _PIPELINE
    if _PIPELINE is None:
        _PIPELINE = NewsNLMPipeline()
    return _PIPELINE


# ── CLI ──────────────────────────────────────────────────────────────────

def main() -> None:
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Run News NLM distillation pipeline")
    parser.add_argument("--articles-limit", type=int, default=20, help="Max articles to include")
    parser.add_argument("--dry-run", action="store_true", help="Build digest but don't upload")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    pipeline = get_news_nlm_pipeline()
    result = pipeline.run(max_articles=args.articles_limit, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
