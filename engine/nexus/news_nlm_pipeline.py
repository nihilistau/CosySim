"""News NLM Pipeline — distil fetched news articles through NotebookLM.

After news articles are fetched and stored in Nexus, this pipeline:
1. Creates/finds a daily news NLM notebook
2. Uploads the day's digest as a text source
3. Runs targeted distillation questions via batch-ask
4. Stores Q&A pairs in Nexus (news category) for agent consumption
5. Feeds training flywheel immediately for real-time learning
6. Persists notebook ID for continuity across runs

The pipeline uses a multi-strategy approach for NotebookLM access:
- Primary: NLMDirectClient (batchexecute RPCs via browser-attached cookies)
- Secondary: NLMClient from nlm_live_proxy (ask_batch with citations)
- Fallback: NLM hybrid router (routes through node bridge / proxy)

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

# ── Retry queue for failed distillations ────────────────────────────────
_RETRY_QUEUE_FILE = _STATE_FILE.parent / "news_nlm_retry_queue.json"

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


# ── Retry queue helpers ─────────────────────────────────────────────────

def _load_retry_queue() -> List[Dict[str, Any]]:
    """Load failed distillation attempts from retry queue."""
    try:
        if _RETRY_QUEUE_FILE.exists():
            return json.loads(_RETRY_QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _save_retry_queue(queue: List[Dict[str, Any]]) -> None:
    """Persist failed distillation attempts for later retry."""
    try:
        _RETRY_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _RETRY_QUEUE_FILE.write_text(json.dumps(queue, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.debug("Could not save retry queue: %s", exc)


def _enqueue_retry(digest_text: str, date_label: str, reason: str) -> None:
    """Add a failed distillation attempt to the retry queue."""
    queue = _load_retry_queue()
    # Cap queue size to prevent unbounded growth
    if len(queue) >= 10:
        queue = queue[-9:]  # Keep newest 9, make room for this one
    queue.append({
        "digest_text": digest_text[:50000],  # Cap text size
        "date_label": date_label,
        "reason": reason,
        "queued_at": time.time(),
        "attempts": 0,
    })
    _save_retry_queue(queue)
    logger.info("Retry queue: added failed distillation for %s (%s)", date_label, reason)


# ── Pipeline ─────────────────────────────────────────────────────────────

class NewsNLMPipeline:
    """Distils daily news articles through NotebookLM for AI-curated insights.

    Designed to be called after the news-fetch scheduler task has stored
    articles in Nexus. Reads the digest from Nexus or accepts a pre-built
    text block, uploads to NLM, distils answers, and stores them back.

    NLM access strategy (in priority order):
    1. NLMDirectClient — batchexecute RPCs using browser-attached cookies
       from the GoogleAccountPool. Supports create_notebook + add_source_text.
    2. NLMClient — nlm_live_proxy batch-ask with citations (CYK0Xb RPC).
       Used for distillation questions after notebook/source creation.
    3. NLM hybrid router — last resort, routes through node bridge.
    """

    def __init__(self) -> None:
        self._state = _load_state()
        self._direct_client = None
        self._proxy_client = None

    def _get_nlm_direct_client(self):
        """Lazy-load NLMDirectClient from the GoogleAccountPool.

        Returns:
            NLMDirectClient instance, or None if unavailable.
        """
        if self._direct_client is not None:
            return self._direct_client
        try:
            from engine.integrations.google_account_pool import get_account_pool
            from engine.integrations.nlm_direct_client import NLMDirectClient
            pool = get_account_pool()
            account = pool.get_account("notebooklm")
            if account is None:
                account = pool.get_by_name("knack112358")
            if account:
                # Credential guard: verify cookies exist and aren't obviously stale
                if not account.cookies:
                    logger.warning("NLM account '%s' has no cookies — auth refresh needed", account.name)
                    return None
                if account.is_stale():
                    logger.warning("NLM account '%s' cookies are stale (>7 days) — auth refresh recommended", account.name)
                self._direct_client = NLMDirectClient(account)
                return self._direct_client
            logger.warning("No NotebookLM-capable account in pool — run cookie refresh")
        except Exception as exc:
            logger.warning("Could not load NLM direct client: %s", exc)
        return None

    def _get_nlm_proxy_client(self):
        """Lazy-load NLMClient from nlm_live_proxy for batch asking.

        Returns:
            NLMClient instance, or None if no cookies available.
        """
        if self._proxy_client is not None:
            return self._proxy_client
        try:
            from engine.mcp.nlm_live_proxy import NLMClient
            client = NLMClient()
            if client.has_cookies():
                self._proxy_client = client
                return self._proxy_client
            logger.debug("NLM proxy client has no cookies")
        except Exception as exc:
            logger.debug("Could not load NLM proxy client: %s", exc)
        return None

    def _get_hybrid(self):
        """Lazy-load NLM hybrid router (fallback path)."""
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        return get_nlm_hybrid()

    def _get_nexus(self):
        """Lazy-load Nexus client."""
        from engine.nexus.client import get_nexus_client
        return get_nexus_client()

    def _get_or_create_notebook(self) -> Optional[str]:
        """Get current week's news notebook ID, creating it if needed.

        Delegates to the centralised NLMNotebookFactory for deduplication,
        state persistence, and credential management.

        Returns:
            Notebook ID string, or None if NLM unavailable.
        """
        from engine.nexus.nlm_notebook_factory import get_notebook_factory

        week = _get_week_label()
        notebook_name = f"{_NOTEBOOK_NAME_PREFIX} {week}"

        factory = get_notebook_factory()
        notebook_id = factory.get_or_create(
            name=notebook_name,
            category="news",
        )

        if notebook_id:
            # Keep local state in sync for backward compatibility
            notebook_key = f"news_notebook_{week}"
            self._state[notebook_key] = notebook_id
            _save_state(self._state)

        return notebook_id

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

        Strategy:
        1. Try NLMDirectClient.add_source_text() — proven batchexecute RPC.
        2. Try nlm_live_proxy.add_text_source() with disk cookies.
        3. Return False if both fail.

        Args:
            notebook_id: Target NLM notebook.
            digest_text: Full formatted text of today's news.

        Returns:
            True if upload succeeded.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        source_title = f"News Digest {today}"

        # Primary: NLMDirectClient.add_source_text()
        direct = self._get_nlm_direct_client()
        if direct:
            try:
                source_id = direct.add_source_text(notebook_id, source_title, digest_text)
                if source_id:
                    logger.info("Uploaded news digest to notebook %s via direct client", notebook_id)
                    return True
            except Exception as exc:
                logger.debug("NLMDirectClient.add_source_text failed: %s", exc)

        # Secondary: nlm_live_proxy module-level add_text_source()
        try:
            from engine.mcp.nlm_live_proxy import add_text_source, _load_cookies
            cookies = _load_cookies()
            if cookies:
                result = add_text_source(notebook_id, source_title, digest_text, cookies)
                if isinstance(result, dict) and result.get("source_id"):
                    logger.info("Uploaded news digest to notebook %s via proxy", notebook_id)
                    return True
                logger.debug("Proxy upload returned: %s", result)
        except Exception as exc:
            logger.debug("Proxy add_text_source failed: %s", exc)

        logger.warning("Digest upload failed — no NLM path available for notebook %s", notebook_id)
        return False

    def _run_distillation(
        self,
        notebook_id: str,
        questions: Optional[List[str]] = None,
    ) -> List[Dict[str, str]]:
        """Run batch distillation questions against the news notebook.

        Strategy:
        1. Try NLMClient.ask_batch() — direct batchexecute RPC with citations.
        2. Fall back to NLM hybrid router.
        3. Return empty list if all paths fail.

        Args:
            notebook_id: NLM notebook containing today's news.
            questions: Optional override questions. Defaults to DISTILLATION_QUESTIONS.

        Returns:
            List of {question, answer} dicts from NLM.
        """
        active_questions = questions if questions else DISTILLATION_QUESTIONS
        results = None

        # Primary: NLMClient.ask_batch() from nlm_live_proxy (citations via CYK0Xb)
        proxy = self._get_nlm_proxy_client()
        if proxy:
            try:
                results = proxy.ask_batch(notebook_id, active_questions)
            except Exception as exc:
                logger.debug("NLMClient.ask_batch failed: %s", exc)

        # Secondary: NLM hybrid router (tries node bridge then proxy)
        if results is None:
            try:
                hybrid = self._get_hybrid()
                results = hybrid.ask_batch(notebook_id, active_questions)
            except Exception as exc:
                logger.debug("Hybrid ask_batch failed: %s", exc)
                return []

        if results is None:
            return []

        qa_pairs = []
        for q, r in zip(active_questions, results):
            if isinstance(r, dict):
                answer = r.get("answer", "")
            else:
                answer = str(r)
            if answer and "error" not in answer.lower()[:20]:
                qa_pairs.append({"question": q, "answer": answer})

        logger.info("Distilled %d Q&A pairs from news notebook", len(qa_pairs))
        return qa_pairs

    def _store_qa_to_nexus(self, qa_pairs: List[Dict[str, str]], date_label: str) -> int:
        """Store distilled Q&A pairs into Nexus and feed the training flywheel.

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
                tagged_q = f"[News {date_label}] {q}"
                nexus.add_qa(tagged_q, a, category="news")
                stored += 1
                time.sleep(0.02)
        except Exception as exc:
            logger.warning("Nexus Q&A storage failed after %d pairs: %s", stored, exc)

        # Feed training flywheel immediately (don't wait for daily sync)
        if stored > 0:
            try:
                from engine.nexus.training_flywheel import get_training_flywheel
                flywheel = get_training_flywheel()
                for pair in qa_pairs:
                    flywheel.collect_from_qa(
                        question=pair["question"],
                        answer=pair["answer"],
                        source="nlm",
                        metadata={"date": date_label, "pipeline": "news_nlm"},
                    )
                logger.info("Training flywheel: fed %d news Q&A pairs", stored)
            except Exception as exc:
                logger.debug("Training flywheel feed skipped: %s", exc)

        return stored

    def run(
        self,
        articles: Optional[List[Any]] = None,
        digest_text: Optional[str] = None,
        max_articles: int = 20,
        dry_run: bool = False,
        questions: Optional[List[str]] = None,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run the full news NLM distillation pipeline.

        Args:
            articles: List of NewsArticle objects (if None, reads from Nexus).
            digest_text: Pre-built digest text (overrides article building).
            max_articles: Cap on articles to include.
            dry_run: If True, build but don't upload or store.
            questions: Optional category-specific questions (overrides generic).
            category: Optional category label for tagging Q&A.

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
                result["error"] = "NLM notebook unavailable — queuing for retry"
                logger.warning("News NLM pipeline: NLM offline, queuing digest for retry")
                if digest_text or articles:
                    text = digest_text or self._build_digest_text(articles, max_articles)
                    _enqueue_retry(text, date_label, "notebook_unavailable")
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
            result["error"] = "Digest upload failed — queuing for retry"
            _enqueue_retry(digest_text, date_label, "upload_failed")
            return result

        # 4. Wait briefly for NLM to index the source
        time.sleep(3)

        # 5. Run distillation
        qa_pairs = self._run_distillation(notebook_id, questions=questions)
        result["qa_count"] = len(qa_pairs)

        if not qa_pairs and digest_text:
            result["error"] = "Distillation returned no Q&A — queuing for retry"
            _enqueue_retry(digest_text, date_label, "distillation_failed")

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

    def process_retries(self, max_retries: int = 3) -> Dict[str, Any]:
        """Process queued failed distillations.

        Called by the scheduler or manually to retry previously failed
        NLM distillation attempts. Items exceeding max_retries are dropped.

        Args:
            max_retries: Max attempts per queued item before dropping.

        Returns:
            Dict with processed, succeeded, dropped, remaining counts.
        """
        queue = _load_retry_queue()
        if not queue:
            return {"processed": 0, "succeeded": 0, "dropped": 0, "remaining": 0}

        succeeded = 0
        dropped = 0
        remaining_items: List[Dict[str, Any]] = []

        for item in queue:
            if item.get("attempts", 0) >= max_retries:
                dropped += 1
                logger.info("Retry queue: dropping %s after %d attempts", item["date_label"], max_retries)
                continue

            item["attempts"] = item.get("attempts", 0) + 1
            result = self.run(digest_text=item["digest_text"])

            if result.get("stored", 0) > 0:
                succeeded += 1
                logger.info("Retry queue: succeeded for %s (%d Q&A stored)", item["date_label"], result["stored"])
            else:
                remaining_items.append(item)

        _save_retry_queue(remaining_items)
        return {
            "processed": len(queue),
            "succeeded": succeeded,
            "dropped": dropped,
            "remaining": len(remaining_items),
        }


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
    parser.add_argument("--retry", action="store_true", help="Process retry queue only")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    pipeline = get_news_nlm_pipeline()

    if args.retry:
        result = pipeline.process_retries()
    else:
        result = pipeline.run(max_articles=args.articles_limit, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
