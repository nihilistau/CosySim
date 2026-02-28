"""
qa_generator.py — Expand Nexus QA pairs from knowledge entries.

Two modes:
1. Rule-based (immediate): generates QA from entry titles/content patterns.
2. LMStudio-based: uses a local LLM to generate richer QA pairs.

Writes directly to the Nexus SQLite DB (no Nexus server required).

Usage:
    python -m engine.nexus.qa_generator --mode rule --limit 500
    python -m engine.nexus.qa_generator --mode llm --limit 200
    python -m engine.nexus.qa_generator --mode both
    python -m engine.nexus.qa_generator --stats
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_NEXUS_DB = Path("C:/Files/Nexus/data/nexus.db")
_LMS_URL = "http://localhost:1234"
_LMS_CHAT = f"{_LMS_URL}/api/v1/chat"
_LMS_MODELS = f"{_LMS_URL}/api/v1/models"
_BATCH_SLEEP = 0.05  # seconds between DB inserts

# ── Priority categories for QA generation ─────────────────────────────
_HIGH_PRIORITY_CATEGORIES = {
    "architecture", "api", "system", "debugging", "testing", "dev",
    "infrastructure", "performance", "training", "agents", "copilot-instructions",
    "copilot-agents", "development",
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

# ── Direct SQLite helpers ─────────────────────────────────────────────

def _get_connection() -> sqlite3.Connection:
    """Open a connection to the Nexus SQLite DB."""
    if not _NEXUS_DB.exists():
        raise FileNotFoundError(f"Nexus DB not found: {_NEXUS_DB}")
    conn = sqlite3.connect(str(_NEXUS_DB))
    conn.row_factory = sqlite3.Row
    return conn


def _get_qa_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM qa_pairs").fetchone()[0]


def _qa_exists(conn: sqlite3.Connection, question: str) -> bool:
    """Check if a near-identical question already exists."""
    q_norm = question.lower().strip()
    existing = conn.execute(
        "SELECT question FROM qa_pairs WHERE question LIKE ? LIMIT 1",
        (q_norm[:60] + "%",),
    ).fetchone()
    return existing is not None


def _insert_qa(
    conn: sqlite3.Connection,
    question: str,
    answer: str,
    category: str = "",
    source_type: str = "rule_based",
    quality_score: float = 0.5,
    tags: list = None,
) -> Optional[str]:
    """Insert a QA pair directly into qa_pairs and sync FTS."""
    if not question.strip() or not answer.strip():
        return None
    if len(answer.strip()) < 30:
        return None
    if _qa_exists(conn, question):
        return None

    uid = hashlib.sha1(
        (question + answer[:100]).encode()
    ).hexdigest()[:16]
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    tags_str = json.dumps(tags or [])

    try:
        conn.execute(
            """INSERT OR IGNORE INTO qa_pairs
               (id, question, answer, source_type, quality_score, tags, category,
                created_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (uid, question.strip(), answer.strip(), source_type,
             quality_score, tags_str, category, "qa_generator", now, now),
        )
        # Sync FTS
        try:
            conn.execute(
                "INSERT OR IGNORE INTO qa_fts(rowid, question, answer) "
                "SELECT rowid, question, answer FROM qa_pairs WHERE id=?",
                (uid,),
            )
        except sqlite3.OperationalError:
            pass  # FTS might not be available
        conn.commit()
        return uid
    except sqlite3.Error as exc:
        logger.warning("DB insert failed: %s", exc)
        conn.rollback()
        return None


# ── Knowledge entry reader ────────────────────────────────────────────

def _load_entries(
    conn: sqlite3.Connection,
    limit: int = 2000,
    content_types: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Load knowledge entries suitable for QA generation."""
    types = content_types or list(_HIGH_PRIORITY_TYPES)
    placeholders = ",".join("?" * len(types))
    rows = conn.execute(
        f"""SELECT id, title, content, content_type, category, tags
            FROM knowledge_entries
            WHERE content_type IN ({placeholders})
              AND length(content) > 100
              AND content NOT LIKE 'C%LCu%'  -- skip base64 NLM encoded content
            ORDER BY
              CASE category
                {' '.join(f"WHEN '{c}' THEN {i+1}" for i, c in enumerate(sorted(_HIGH_PRIORITY_CATEGORIES)))}
                ELSE 99
              END,
              length(content) DESC
            LIMIT ?""",
        (*types, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Rule-based QA generation ──────────────────────────────────────────

def _title_to_question(title: str) -> Optional[str]:
    """Convert an entry title to a natural question."""
    # If title already is a question
    if title.strip().endswith("?"):
        return title.strip()

    for pattern, template in _TITLE_TO_QUESTION_TEMPLATES:
        m = re.match(pattern, title, re.IGNORECASE)
        if m:
            q = template.format(*m.groups())
            return q[0].upper() + q[1:]

    # Generic fallback: "What is X?" / "How does X work?"
    clean = re.sub(r"\s*\(.*?\)\s*", "", title).strip()
    if not clean:
        return None
    if len(clean.split()) <= 6:
        return f"What is {clean}?"
    return f"What is the purpose of {clean}?"


def _extract_key_sentences(content: str, max_sentences: int = 4) -> str:
    """Extract the most informative sentences from content."""
    # Strip code blocks
    content = re.sub(r"```[\s\S]*?```", "[code]", content)
    # Split on newlines first (many entries are structured with newlines)
    lines = [l.strip() for l in content.split("\n") if l.strip()]
    # Keep only non-boilerplate lines
    useful = []
    skip_prefixes = ("#", "http", "---", "===", "```", "//", "/*")
    for line in lines:
        if any(line.startswith(p) for p in skip_prefixes):
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

        # Skip entries with base64 / encoded content
        if re.match(r"^[A-Za-z0-9+/]{50,}", content):
            continue
        if content.startswith("C") and len(content) > 200 and "LL" in content[:20]:
            continue  # Likely NLM base64 encoded

        question = _title_to_question(title)
        if not question:
            continue

        answer = _extract_key_sentences(content, max_sentences=5)
        if len(answer) < 50:
            continue

        # Quality score based on content richness
        quality = min(1.0, len(content) / 2000)
        if category in _HIGH_PRIORITY_CATEGORIES:
            quality = min(1.0, quality + 0.2)

        results.append((question, answer[:2000], category, quality))

        # Also add content-pattern QA if content has numbered/bulleted points
        if re.search(r"^\d+\.", content, re.MULTILINE) or "- " in content[:200]:
            list_q = f"What are the key points about {title.lower()}?"
            # Extract list items as answer
            items = re.findall(r"^[-*\d.]+\s+(.+)", content, re.MULTILINE)
            if len(items) >= 2:
                list_a = ". ".join(items[:5])
                results.append((list_q, list_a[:1500], category, quality * 0.9))

    return results


# ── LMStudio-based QA generation ─────────────────────────────────────

def _check_lmstudio() -> Optional[str]:
    """Return model ID if LMStudio is running with a model loaded, else None."""
    try:
        with urllib.request.urlopen(_LMS_MODELS, timeout=3) as resp:
            data = json.loads(resp.read())
            models = data.get("data", [])
            return models[0]["id"] if models else None
    except Exception:
        return None


def _lms_generate_qa(
    title: str, content: str, model_id: str, n_pairs: int = 3
) -> List[Tuple[str, str]]:
    """Use LMStudio to generate N QA pairs from a knowledge entry."""
    system_prompt = (
        "You are a knowledge distiller. Given a knowledge entry, generate "
        f"{n_pairs} clear question-answer pairs that capture key facts. "
        "Format EXACTLY as:\n"
        "Q: <question>\nA: <answer>\n\n"
        "Each answer should be 1-3 sentences. Questions should be specific and useful."
    )
    user_msg = f"Title: {title}\n\nContent: {content[:1500]}"

    payload = json.dumps({
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.4,
        "max_tokens": 600,
    }).encode()

    req = urllib.request.Request(
        _LMS_CHAT,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            text = data["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.debug("LMStudio QA generation failed: %s", exc)
        return []

    pairs = []
    blocks = re.split(r"\n{2,}", text.strip())
    for block in blocks:
        q_match = re.search(r"Q:\s*(.+)", block)
        a_match = re.search(r"A:\s*(.+)", block, re.DOTALL)
        if q_match and a_match:
            q = q_match.group(1).strip()
            a = a_match.group(1).strip()
            if len(q) > 10 and len(a) > 20:
                pairs.append((q, a))
    return pairs[:n_pairs]


# ── Main runner ───────────────────────────────────────────────────────

def run_rule_based(limit: int = 800, dry_run: bool = False) -> int:
    """Generate QA from knowledge entries using rules. Returns count added."""
    conn = _get_connection()
    before = _get_qa_count(conn)
    logger.info("QA before: %d  — loading entries...", before)

    entries = _load_entries(conn, limit=min(limit * 2, 3000))
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
            conn, question, answer,
            category=category,
            source_type="rule_based",
            quality_score=quality,
        )
        if uid:
            added += 1
        time.sleep(_BATCH_SLEEP)

    after = _get_qa_count(conn)
    logger.info("QA after: %d  (+%d added)", after, added)
    conn.close()
    return added


def run_llm_based(limit: int = 200, n_pairs_each: int = 2, dry_run: bool = False) -> int:
    """Generate QA using LMStudio. Returns count added."""
    model_id = _check_lmstudio()
    if not model_id:
        logger.warning("LMStudio not running or no model loaded — skipping LLM mode")
        return 0

    conn = _get_connection()
    before = _get_qa_count(conn)
    logger.info("LLM QA mode — model: %s  before: %d", model_id, before)

    # Focus on highest-quality entries: architecture + system + api docs
    entries = _load_entries(conn, limit=limit, content_types=["document", "research"])
    priority_entries = [
        e for e in entries
        if e.get("category", "") in _HIGH_PRIORITY_CATEGORIES
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
                conn, question, answer,
                category=category,
                source_type="llm_generated",
                quality_score=0.75,
            )
            if uid:
                added += 1
        time.sleep(0.1)

    after = _get_qa_count(conn)
    logger.info("QA after LLM pass: %d  (+%d added)", after, added)
    conn.close()
    return added


def print_stats() -> None:
    """Print current QA stats."""
    conn = _get_connection()
    total = _get_qa_count(conn)
    by_source = conn.execute(
        "SELECT source_type, COUNT(*) FROM qa_pairs GROUP BY source_type"
    ).fetchall()
    by_cat = conn.execute(
        "SELECT category, COUNT(*) FROM qa_pairs GROUP BY category ORDER BY 2 DESC LIMIT 15"
    ).fetchall()
    entry_count = conn.execute("SELECT COUNT(*) FROM knowledge_entries").fetchone()[0]
    conn.close()

    print(f"\n{'═'*50}")
    print(f"  Nexus QA Stats")
    print(f"{'═'*50}")
    print(f"  Total QA pairs:       {total:,}")
    print(f"  Knowledge entries:    {entry_count:,}")
    print(f"\n  By source:")
    for src, cnt in by_source:
        print(f"    {src or 'unset':<25} {cnt:>6}")
    print(f"\n  Top categories:")
    for cat, cnt in by_cat:
        print(f"    {cat or 'unset':<25} {cnt:>6}")
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
        "--mode", choices=["rule", "llm", "both"], default="rule",
        help="Generation mode (default: rule)",
    )
    parser.add_argument("--limit", type=int, default=800,
                        help="Max entries to process (default: 800)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print pairs without writing to DB")
    parser.add_argument("--stats", action="store_true",
                        help="Print stats and exit")
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
        r = run_rule_based(limit=args.limit, dry_run=args.dry_run)
        l = run_llm_based(limit=min(args.limit // 4, 200), dry_run=args.dry_run)
        print(f"Total added: {r + l} (rule: {r}, llm: {l})")
    print_stats()
