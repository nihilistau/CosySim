"""
qa_generator.py — Expand Nexus QA pairs from knowledge entries.

Two modes:
1. Rule-based (immediate): generates QA from entry titles/content patterns.
2. LMStudio-based: uses a local LLM to generate richer QA pairs.

Uses the Nexus client for knowledge reads and writes so generated Q&A follows
the same config-driven, server-backed path as the rest of the system.

Usage:
    python -m engine.nexus.qa_generator --mode rule --limit 500
    python -m engine.nexus.qa_generator --mode llm --limit 200
    python -m engine.nexus.qa_generator --mode both
    python -m engine.nexus.qa_generator --stats
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_BATCH_SLEEP = 0.05  # seconds between generated QA writes

# ── Priority categories for QA generation ─────────────────────────────
_HIGH_PRIORITY_CATEGORIES = {
    "architecture",
    "api",
    "system",
    "debugging",
    "testing",
    "dev",
    "infrastructure",
    "performance",
    "training",
    "agents",
    "copilot-instructions",
    "copilot-agents",
    "development",
}
_HIGH_PRIORITY_TYPES = {"document", "research", "note"}

# ── Rule templates for question generation ─────────────────────────────
_TITLE_TO_QUESTION_TEMPLATES = [
    # Architecture
    (r"(.+) Architecture", "What is the architecture of {0}?"),
    (r"(.+) Design", "How is {0} designed?"),
    (r"(.+) Pattern", "What is the {0} pattern?"),
    (r"How (.+) works?", "How does {0} work?"),
    (r"How to (.+)", "How do you {0}?"),
    # Configuration
    (r"(.+) Configuration", "How is {0} configured?"),
    (r"(.+) Setup", "How do you set up {0}?"),
    (r"Configure (.+)", "How do you configure {0}?"),
    # Integration
    (r"(.+) Integration", "How does {0} integrate?"),
    (r"(.+) API", "What is the {0} API?"),
    # System
    (r"(.+) System", "How does the {0} system work?"),
    (r"(.+) Pipeline", "How does the {0} pipeline work?"),
    (r"(.+) Framework", "What is the {0} framework?"),
    # Decisions
    (r"Decision: (.+)", "What was the decision regarding {0}?"),
    # Feature
    (r"(.+) Feature", "What is the {0} feature?"),
    (r"(.+) Skill", "How does the {0} skill work?"),
    (r"(.+) Module", "What does the {0} module do?"),
]


# ── Nexus client helpers ──────────────────────────────────────────────

def _get_nexus_client() -> Any:
    """Return the configured Nexus client."""
    from engine.nexus.client import get_nexus_client

    return get_nexus_client()


def _get_training_flywheel() -> Any:
    """Return the global training flywheel."""
    from engine.nexus.training_flywheel import get_training_flywheel

    return get_training_flywheel()


def _get_lmstudio_urls() -> Tuple[str, str]:
    """Resolve LMStudio chat and model endpoints from config."""
    from engine.config import get_config

    cfg = get_config()
    host = cfg.get("lmstudio.host", "localhost")
    port = int(cfg.get("lmstudio.port", 1234))
    base_url = f"http://{host}:{port}"
    return (f"{base_url}/api/v1/chat", f"{base_url}/api/v1/models")


def _stats_data(client: Any) -> Dict[str, Any]:
    """Extract the stats payload from the Nexus stats envelope."""
    stats = client.stats()
    if isinstance(stats, dict):
        return stats.get("data", stats)
    return {}


def _get_qa_count(client: Any) -> int:
    """Return the current Nexus Q&A pair count."""
    stats = _stats_data(client)
    return int(stats.get("qa_pairs", stats.get("qa_count", 0)) or 0)


def _get_entry_count(client: Any) -> int:
    """Return the current Nexus knowledge entry count."""
    stats = _stats_data(client)
    return int(stats.get("knowledge_entries", stats.get("entries", 0)) or 0)


def _qa_exists(client: Any, question: str) -> bool:
    """Check whether a near-identical question already exists in Nexus."""
    q_norm = question.lower().strip()
    if not q_norm:
        return False

    try:
        results = client.find_qa(question, limit=5)
    except Exception as exc:
        logger.debug("Could not query existing QA pairs for '%s': %s", question[:80], exc)
        return False

    for item in results or []:
        if hasattr(item, "get"):
            existing = item.get("question", "")
        else:
            existing = getattr(item, "question", "")
        existing_norm = existing.lower().strip()
        if not existing_norm:
            continue
        if existing_norm == q_norm:
            return True
        if existing_norm.startswith(q_norm[:80]) or q_norm.startswith(existing_norm[:80]):
            return True
    return False


def _insert_qa(
    client: Any,
    question: str,
    answer: str,
    category: str = "",
    source_type: str = "rule_based",
    quality_score: float = 0.5,
    tags: list = None,
) -> Optional[str]:
    """Insert a QA pair via the Nexus client and feed it into training."""
    if not question.strip() or not answer.strip():
        return None
    if len(answer.strip()) < 30:
        return None
    if _qa_exists(client, question):
        return None

    merged_tags = list(dict.fromkeys([*(tags or []), "qa-generator", source_type]))

    try:
        uid = client.add_qa(
            question=question.strip(),
            answer=answer.strip(),
            category=category,
            tags=merged_tags,
            quality_score=quality_score,
        )
        if not uid:
            return None
        try:
            model = "lmstudio" if source_type == "llm_generated" else ""
            _get_training_flywheel().collect_from_qa(
                question=question.strip(),
                answer=answer.strip(),
                source=source_type,
                confidence=quality_score,
                model=model,
            )
        except Exception as exc:
            logger.debug("Could not sync generated QA pair into training flywheel: %s", exc)
        return uid
    except Exception as exc:
        logger.warning("Nexus QA insert failed: %s", exc)
        return None


# ── Knowledge entry reader ────────────────────────────────────────────

def _looks_encoded_content(content: str) -> bool:
    """Return True when content looks like encoded or opaque payload data."""
    if re.match(r"^[A-Za-z0-9+/]{50,}", content):
        return True
    return content.startswith("C") and len(content) > 200 and "LL" in content[:20]


def _entry_priority_rank(category: str) -> int:
    """Return the ranking priority for a Nexus category."""
    if category not in _HIGH_PRIORITY_CATEGORIES:
        return 99
    return sorted(_HIGH_PRIORITY_CATEGORIES).index(category) + 1


def _load_entries(
    client: Any,
    limit: int = 2000,
    content_types: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Load knowledge entries suitable for QA generation."""
    types = content_types or list(_HIGH_PRIORITY_TYPES)
    fetch_limit = max(limit * 2, 200)
    merged: List[Dict[str, Any]] = []

    for content_type in types:
        try:
            merged.extend(client.list_entries(content_type=content_type, limit=fetch_limit))
        except Exception as exc:
            logger.warning("Could not list Nexus entries for type '%s': %s", content_type, exc)

    deduped: Dict[str, Dict[str, Any]] = {}
    for entry in merged:
        if hasattr(entry, "get"):
            entry_id = entry.get("id", "") or entry.get("title", "")
        else:
            entry_id = getattr(entry, "id", "") or getattr(entry, "title", "")
        if entry_id and entry_id not in deduped:
            deduped[entry_id] = entry

    filtered = [
        entry
        for entry in deduped.values()
        if len(entry.get("content", "")) > 100
        and not _looks_encoded_content(entry.get("content", ""))
    ]
    return sorted(
        filtered,
        key=lambda entry: (
            _entry_priority_rank(entry.get("category", "")),
            -len(entry.get("content", "")),
        ),
    )[:limit]


# ── Rule-based QA generation ──────────────────────────────────────────

def _title_to_question(title: str) -> Optional[str]:
    """Convert an entry title to a natural question."""
    if title.strip().endswith("?"):
        return title.strip()

    for pattern, template in _TITLE_TO_QUESTION_TEMPLATES:
        match = re.match(pattern, title, re.IGNORECASE)
        if match:
            question = template.format(*match.groups())
            return question[0].upper() + question[1:]

    clean = re.sub(r"\s*\(.*?\)\s*", "", title).strip()
    if not clean:
        return None
    if len(clean.split()) <= 6:
        return f"What is {clean}?"
    return f"What is the purpose of {clean}?"


def _extract_key_sentences(content: str, max_sentences: int = 4) -> str:
    """Extract the most informative sentences from content."""
    content = re.sub(r"```[\s\S]*?```", "[code]", content)
    lines = [line.strip() for line in content.split("\n") if line.strip()]
    useful: List[str] = []
    skip_prefixes = ("#", "http", "---", "===", "```", "//", "/*")
    for line in lines:
        if any(line.startswith(prefix) for prefix in skip_prefixes):
            continue
        if len(line) < 20:
            continue
        useful.append(line)
        if len(useful) >= max_sentences:
            break
    if not useful:
        return content[:300]
    return " ".join(useful[:max_sentences])


def _generate_rule_qa(entries: List[Dict]) -> List[Tuple[str, str, str, float]]:
    """Generate (question, answer, category, quality) tuples via rules."""
    results: List[Tuple[str, str, str, float]] = []

    for entry in entries:
        title = entry.get("title", "").strip()
        content = entry.get("content", "").strip()
        category = entry.get("category", "")

        if not title or not content or len(content) < 80:
            continue
        if _looks_encoded_content(content):
            continue

        question = _title_to_question(title)
        if not question:
            continue

        answer = _extract_key_sentences(content, max_sentences=5)
        if len(answer) < 50:
            continue

        quality = min(1.0, len(content) / 2000)
        if category in _HIGH_PRIORITY_CATEGORIES:
            quality = min(1.0, quality + 0.2)

        results.append((question, answer[:2000], category, quality))

        if re.search(r"^\d+\.", content, re.MULTILINE) or "- " in content[:200]:
            list_question = f"What are the key points about {title.lower()}?"
            items = re.findall(r"^[-*\d.]+\s+(.+)", content, re.MULTILINE)
            if len(items) >= 2:
                list_answer = ". ".join(items[:5])
                results.append((list_question, list_answer[:1500], category, quality * 0.9))

    return results


# ── LMStudio-based QA generation ─────────────────────────────────────

def _check_lmstudio() -> Optional[str]:
    """Return a loaded model ID if LMStudio is running, else None."""
    _, models_url = _get_lmstudio_urls()
    try:
        with urllib.request.urlopen(models_url, timeout=3) as response:
            data = json.loads(response.read())
            models = data.get("data", [])
            return models[0]["id"] if models else None
    except Exception:
        return None


def _lms_generate_qa(
    title: str, content: str, model_id: str, n_pairs: int = 3
) -> List[Tuple[str, str]]:
    """Use LMStudio to generate N QA pairs from a knowledge entry."""
    chat_url, _ = _get_lmstudio_urls()
    system_prompt = (
        "You are a knowledge distiller. Given a knowledge entry, generate "
        f"{n_pairs} clear question-answer pairs that capture key facts. "
        "Format EXACTLY as:\n"
        "Q: <question>\nA: <answer>\n\n"
        "Each answer should be 1-3 sentences. Questions should be specific and useful."
    )
    user_message = f"Title: {title}\n\nContent: {content[:1500]}"

    payload = json.dumps(
        {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.4,
            "max_tokens": 600,
        }
    ).encode()

    request = urllib.request.Request(
        chat_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read())
            text = data["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.debug("LMStudio QA generation failed: %s", exc)
        return []

    pairs: List[Tuple[str, str]] = []
    for block in re.split(r"\n{2,}", text.strip()):
        question_match = re.search(r"Q:\s*(.+)", block)
        answer_match = re.search(r"A:\s*(.+)", block, re.DOTALL)
        if question_match and answer_match:
            question = question_match.group(1).strip()
            answer = answer_match.group(1).strip()
            if len(question) > 10 and len(answer) > 20:
                pairs.append((question, answer))
    return pairs[:n_pairs]


# ── Main runner ───────────────────────────────────────────────────────

def run_rule_based(limit: int = 800, dry_run: bool = False) -> int:
    """Generate QA from knowledge entries using rules. Returns count added."""
    client = _get_nexus_client()
    before = _get_qa_count(client)
    logger.info("QA before: %d  — loading entries...", before)

    entries = _load_entries(client, limit=min(limit * 2, 3000))
    logger.info("Loaded %d candidate entries", len(entries))

    pairs = _generate_rule_qa(entries)
    logger.info("Generated %d rule-based QA candidates", len(pairs))

    added = 0
    for question, answer, category, quality in pairs:
        if dry_run:
            logger.info("DRY: %s", question[:80])
            added += 1
            continue
        uid = _insert_qa(
            client,
            question,
            answer,
            category=category,
            source_type="rule_based",
            quality_score=quality,
        )
        if uid:
            added += 1
        time.sleep(_BATCH_SLEEP)

    after = _get_qa_count(client)
    logger.info("QA after: %d  (+%d added)", after, added)
    return added


def run_llm_based(limit: int = 200, n_pairs_each: int = 2, dry_run: bool = False) -> int:
    """Generate QA using LMStudio. Returns count added."""
    model_id = _check_lmstudio()
    if not model_id:
        logger.warning("LMStudio not running or no model loaded — skipping LLM mode")
        return 0

    client = _get_nexus_client()
    before = _get_qa_count(client)
    logger.info("LLM QA mode — model: %s  before: %d", model_id, before)

    entries = _load_entries(client, limit=limit, content_types=["document", "research"])
    priority_entries = [
        entry for entry in entries if entry.get("category", "") in _HIGH_PRIORITY_CATEGORIES
    ]
    logger.info("LLM-generating QA for %d priority entries", len(priority_entries))

    added = 0
    for entry in priority_entries[:limit]:
        title = entry.get("title", "")
        content = entry.get("content", "")
        category = entry.get("category", "")

        if not title or len(content) < 100:
            continue

        pairs = _lms_generate_qa(title, content, model_id, n_pairs=n_pairs_each)
        for question, answer in pairs:
            if dry_run:
                logger.info("DRY LLM: %s", question[:80])
                added += 1
                continue
            uid = _insert_qa(
                client,
                question,
                answer,
                category=category,
                source_type="llm_generated",
                quality_score=0.75,
            )
            if uid:
                added += 1
        time.sleep(0.1)

    after = _get_qa_count(client)
    logger.info("QA after LLM pass: %d  (+%d added)", after, added)
    return added


def print_stats() -> None:
    """Print current QA stats."""
    client = _get_nexus_client()
    total = _get_qa_count(client)
    entry_count = _get_entry_count(client)

    print(f"\n{'═' * 50}")
    print("  Nexus QA Stats")
    print(f"{'═' * 50}")
    print(f"  Total QA pairs:       {total:,}")
    print(f"  Knowledge entries:    {entry_count:,}")
    print("\n  Source/category breakdown: not exposed by current Nexus stats API")
    print()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Generate Nexus QA pairs from knowledge entries"
    )
    parser.add_argument(
        "--mode",
        choices=["rule", "llm", "both"],
        default="rule",
        help="Generation mode (default: rule)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=800,
        help="Max entries to process (default: 800)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print pairs without writing to Nexus",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print stats and exit",
    )
    args = parser.parse_args()

    if args.stats:
        print_stats()
    elif args.mode == "rule":
        added = run_rule_based(limit=args.limit, dry_run=args.dry_run)
        print(f"Rule-based: added {added} QA pairs")
    elif args.mode == "llm":
        added = run_llm_based(limit=args.limit, dry_run=args.dry_run)
        print(f"LLM-based: added {added} QA pairs")
    elif args.mode == "both":
        rule_added = run_rule_based(limit=args.limit, dry_run=args.dry_run)
        llm_added = run_llm_based(limit=min(args.limit // 4, 200), dry_run=args.dry_run)
        print(f"Total added: {rule_added + llm_added} (rule: {rule_added}, llm: {llm_added})")

    print_stats()
