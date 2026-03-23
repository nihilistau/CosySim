"""
nexus_distiller.py — Distills raw session data into reusable knowledge.

Processes conversation logs, session histories, and checkpoint data stored
in Nexus to extract:
  - Reusable Q&A pairs (removes context-specific details)
  - Architecture decisions
  - Bug fix patterns
  - File-specific conventions
  - Compacted session summaries

Designed to run periodically (via MCP tool, cron, or manual) to keep
the knowledge base lean and high-signal. Old raw session data gets
compacted into distilled entries, reducing token usage for future lookups.

Usage:
    python -m engine.nexus.nexus_distiller distill
    python -m engine.nexus.nexus_distiller compact
    python -m engine.nexus.nexus_distiller stats
"""
from __future__ import annotations

import json
import logging
import re
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from engine.nexus.client import get_nexus_client

logger = logging.getLogger(__name__)


def _get_nexus_url() -> str:
    from engine.port_registry import get_service_url
    return get_service_url("nexus")


# ══════════════════════════════════════════════════════════════════════
#  API Helpers
# ══════════════════════════════════════════════════════════════════════

def _api_get(path: str, params: Dict[str, Any] | None = None) -> list:
    """GET from Nexus via client, returns list."""
    p = params or {}
    try:
        client = get_nexus_client()
        if "/api/search" in path:
            return client.search(p.get("q", ""), limit=int(p.get("limit", 10)))
        if "/api/qa" in path:
            return client.find_qa("", limit=int(p.get("limit", 50)))
        if "/api/rules" in path:
            return client.get_rules()
        if "/api/entries" in path:
            return client.list_entries(limit=int(p.get("limit", 20)))
        return []
    except Exception as e:
        logger.warning("Nexus API error: %s", e)
        return []


def _api_post(path: str, data: Dict[str, Any]) -> Optional[str]:
    """POST to Nexus via client, returns entry ID or None."""
    try:
        client = get_nexus_client()
        if "/api/qa" in path:
            return client.add_qa(
                question=data.get("question", ""),
                answer=data.get("answer", ""),
                category=data.get("category", ""),
                tags=data.get("tags", []),
            )
        return client.add_entry(
            title=data.get("title", ""),
            content=data.get("content", ""),
            content_type=data.get("content_type", "note"),
            category=data.get("category", ""),
            tags=data.get("tags", []),
        )
    except Exception:
        return None


def _api_delete(entry_id: str) -> bool:
    """DELETE entry from Nexus via client."""
    try:
        return get_nexus_client().delete_entry(entry_id)
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════
#  Pattern Extractors
# ══════════════════════════════════════════════════════════════════════

def _extract_decisions_from_text(text: str) -> List[str]:
    """Extract decision-like statements from conversation text."""
    decisions = []
    markers = [
        r"Decision:\s*(.+)",
        r"(?:I|We) decided to\s+(.+)",
        r"The approach (?:is|will be)\s+(.+)",
        r"(?:Created|Added|Built|Implemented)\s+(.+?)(?:\.|$)",
        r"Architecture:\s*(.+)",
        r"Design:\s*(.+)",
    ]
    for marker in markers:
        for match in re.finditer(marker, text, re.IGNORECASE):
            dec = match.group(1).strip()[:200]
            if len(dec) > 20:
                decisions.append(dec)
    return decisions


def _extract_fixes_from_text(text: str) -> List[Dict[str, str]]:
    """Extract bug fix patterns from conversation text."""
    fixes = []
    fix_patterns = [
        r"Fixed?\s+(.+?)(?:by|via|with)\s+(.+?)(?:\.|$)",
        r"(?:Bug|Error|Issue):\s*(.+?)(?:\.\s*Fix|Solution):\s*(.+?)(?:\.|$)",
        r"(.+?)\s*(?:was broken|didn't work|failed)\s*(?:because|due to)\s+(.+?)(?:\.|$)",
    ]
    for pat in fix_patterns:
        for match in re.finditer(pat, text, re.IGNORECASE):
            if len(match.group(1)) > 10:
                fixes.append({
                    "problem": match.group(1).strip()[:200],
                    "solution": match.group(2).strip()[:200],
                })
    return fixes


def _extract_file_conventions(text: str) -> Dict[str, List[str]]:
    """Extract file-specific notes from conversation text."""
    conventions: Dict[str, List[str]] = defaultdict(list)
    # Look for file path mentions with associated notes
    file_pattern = r"(?:in|at|file)\s+[`'\"]?([\w/\\._-]+\.(?:py|yaml|json|md|ts|js))[`'\"]?"
    for match in re.finditer(file_pattern, text):
        filepath = match.group(1)
        # Get surrounding context
        start = max(0, match.start() - 100)
        end = min(len(text), match.end() + 200)
        context = text[start:end].strip()
        if len(context) > 30:
            conventions[filepath].append(context[:300])
    return dict(conventions)


# ══════════════════════════════════════════════════════════════════════
#  Distiller
# ══════════════════════════════════════════════════════════════════════

class NexusDistiller:
    """Distills raw session data into reusable knowledge entries."""

    def __init__(self, nexus_url: str = "") -> None:
        self._url = nexus_url or _get_nexus_url()

    def distill(self) -> Dict[str, int]:
        """Process all undistilled session data and extract knowledge.

        Returns:
            Dict with counts of extracted items by type.
        """
        counts: Dict[str, int] = {
            "decisions": 0, "fixes": 0, "qa_pairs": 0,
            "conventions": 0, "compacted": 0,
        }

        # Find all conversation logs that haven't been distilled yet
        conv_logs = _api_get("/api/search", {"q": "conversation-log", "limit": 100})
        if not isinstance(conv_logs, list):
            conv_logs = []

        # Filter to actual conversation logs
        logs = [
            e for e in conv_logs
            if "conversation-log" in str(e.get("tags", ""))
            and "distilled" not in str(e.get("tags", ""))
        ]

        logger.info("Found %d undistilled conversation logs", len(logs))

        for log_entry in logs:
            text = log_entry.get("content", "")
            entry_id = log_entry.get("id")

            if not text or len(text) < 50:
                continue

            # Extract decisions
            decisions = _extract_decisions_from_text(text)
            for dec in decisions[:5]:
                stored = _api_post("/api/entries", {
                    "title": f"Distilled decision: {dec[:60]}",
                    "content": dec,
                    "content_type": "note",
                    "category": "decisions",
                    "tags": ["copilot", "distilled", "decision"],
                })
                if stored:
                    counts["decisions"] += 1

            # Extract bug fixes as Q&A
            fixes = _extract_fixes_from_text(text)
            for fix in fixes[:3]:
                stored = _api_post("/api/qa", {
                    "question": f"How to fix: {fix['problem'][:100]}",
                    "answer": fix["solution"],
                    "category": "debugging",
                    "tags": ["copilot", "distilled", "fix"],
                })
                if stored:
                    counts["fixes"] += 1

            # Mark as distilled by updating tags (via NexusClient — no raw HTTP)
            existing_tags = log_entry.get("tags", "")
            if isinstance(existing_tags, str):
                try:
                    tag_list = json.loads(existing_tags)
                except Exception:
                    tag_list = [t.strip() for t in existing_tags.split(",") if t.strip()]
            else:
                tag_list = existing_tags or []
            tag_list.append("distilled")
            try:
                get_nexus_client().update_entry(entry_id, tags=tag_list)
            except Exception:
                logger.debug("Could not mark entry %s as distilled", entry_id, exc_info=True)

        # Process session summaries for pattern extraction
        summaries = _api_get("/api/search", {"q": "session ended summary", "limit": 50})
        if isinstance(summaries, list):
            for s in summaries:
                text = s.get("content", "")
                if "distilled" in str(s.get("tags", "")):
                    continue
                convs = _extract_file_conventions(text)
                for filepath, notes in list(convs.items())[:5]:
                    stored = _api_post("/api/entries", {
                        "title": f"Convention: {filepath}",
                        "content": "\n".join(notes[:3]),
                        "content_type": "note",
                        "category": "conventions",
                        "tags": ["copilot", "distilled", "convention",
                                 f"file:{filepath}"],
                    })
                    if stored:
                        counts["conventions"] += 1

        return counts

    def compact_sessions(self, max_age_days: int = 7) -> Dict[str, int]:
        """Compact old session entries into summaries.

        Merges multiple session start/end entries from the same day into
        a single summary entry, reducing storage and lookup noise.

        Args:
            max_age_days: Only compact entries older than this.

        Returns:
            Dict with compaction stats.
        """
        entries = _api_get("/api/entries", {"limit": 500})
        if not isinstance(entries, list):
            return {"error": "Could not fetch entries"}

        # Group session entries by date
        sessions_by_date: Dict[str, list] = defaultdict(list)
        for e in entries:
            tags = str(e.get("tags", ""))
            if "session" in tags and ("start" in tags or "end" in tags):
                created = e.get("created_at", "")[:10]
                if created:
                    sessions_by_date[created].append(e)

        compacted = 0
        removed = 0

        for date, day_sessions in sessions_by_date.items():
            # Only compact if there are multiple entries for a day
            if len(day_sessions) < 3:
                continue

            # Build summary
            summary_lines = [f"Session summary for {date}:"]
            summary_lines.append(f"Total session events: {len(day_sessions)}")
            for s in day_sessions:
                title = s.get("title", "")
                content = s.get("content", "")[:200]
                summary_lines.append(f"- {title}: {content}")

            # Store compacted summary
            stored = _api_post("/api/entries", {
                "title": f"Daily session summary — {date}",
                "content": "\n".join(summary_lines),
                "content_type": "history",
                "category": "sessions",
                "tags": ["session", "copilot", "compacted", "daily-summary"],
            })

            if stored:
                compacted += 1
                # Remove individual entries (keep conversation logs)
                for s in day_sessions:
                    if "conversation-log" not in str(s.get("tags", "")):
                        if _api_delete(s["id"]):
                            removed += 1

        return {"days_compacted": compacted, "entries_removed": removed}

    def get_stats(self) -> Dict[str, Any]:
        """Get knowledge base statistics for token usage optimization."""
        entries = _api_get("/api/entries", {"limit": 500})
        qa = _api_get("/api/qa", {"limit": 500})
        rules = _api_get("/api/rules")

        if not isinstance(entries, list):
            entries = []
        if not isinstance(qa, list):
            qa = []
        if not isinstance(rules, list):
            rules = []

        # Compute content sizes
        total_chars = sum(len(e.get("content", "")) for e in entries)
        avg_chars = total_chars // len(entries) if entries else 0

        # Namespace distribution
        ns_counts: Dict[str, int] = Counter()
        for e in entries:
            tags = str(e.get("tags", ""))
            for ns in ["system", "scene", "agent", "copilot",
                        "training", "research", "content"]:
                if ns in tags:
                    ns_counts[ns] += 1
                    break
            else:
                ns_counts["untagged"] += 1

        # Content type distribution
        type_counts = dict(Counter(e.get("content_type", "?") for e in entries))

        # Session-specific stats
        session_entries = [e for e in entries if "session" in str(e.get("tags", ""))]
        distilled = [e for e in entries if "distilled" in str(e.get("tags", ""))]
        conv_logs = [e for e in entries if "conversation-log" in str(e.get("tags", ""))]

        return {
            "total_entries": len(entries),
            "total_qa": len(qa),
            "total_rules": len(rules),
            "total_chars": total_chars,
            "avg_entry_chars": avg_chars,
            "by_namespace": dict(ns_counts),
            "by_type": type_counts,
            "session_entries": len(session_entries),
            "distilled_entries": len(distilled),
            "conversation_logs": len(conv_logs),
            "undistilled_logs": len([
                e for e in conv_logs
                if "distilled" not in str(e.get("tags", ""))
            ]),
            "token_estimate": total_chars // 4,
        }

    def generate_context_primer(self) -> str:
        """Generate a compact context primer for new Copilot sessions.

        Pulls the most important knowledge from Nexus and formats it as
        a compact string that can be injected into the system prompt,
        reducing the need for repeated Nexus lookups.

        Returns:
            Compact context string with project knowledge.
        """
        sections = []

        # 1. Recent decisions
        decisions = _api_get("/api/search", {"q": "decision architecture", "limit": 10})
        if isinstance(decisions, list) and decisions:
            dec_lines = ["## Recent Decisions"]
            for d in decisions[:5]:
                dec_lines.append(f"- {d.get('title', '')}: {d.get('content', '')[:100]}")
            sections.append("\n".join(dec_lines))

        # 2. Active rules
        rules = _api_get("/api/rules")
        if isinstance(rules, list) and rules:
            rule_lines = ["## Active Rules"]
            global_rules = [r for r in rules if r.get("scope") == "global"]
            for r in global_rules[:5]:
                rule_lines.append(f"- {r.get('name', '')}")
            sections.append("\n".join(rule_lines))

        # 3. Frequently hit Q&A
        qa = _api_get("/api/qa", {"limit": 50})
        if isinstance(qa, list):
            # Sort by hit_count if available
            sorted_qa = sorted(qa, key=lambda q: q.get("hit_count", 0), reverse=True)
            qa_lines = ["## Top Q&A"]
            for q in sorted_qa[:5]:
                qa_lines.append(f"Q: {q.get('question', '')[:80]}")
                qa_lines.append(f"A: {q.get('answer', '')[:120]}")
            sections.append("\n".join(qa_lines))

        # 4. Recent session context
        sessions = _api_get("/api/search", {"q": "session ended summary", "limit": 3})
        if isinstance(sessions, list) and sessions:
            sess_lines = ["## Recent Sessions"]
            for s in sessions[:2]:
                sess_lines.append(f"- {s.get('title', '')[:80]}")
            sections.append("\n".join(sess_lines))

        primer = "\n\n".join(sections)
        return primer[:4000]


# ══════════════════════════════════════════════════════════════════════
#  QA Deduplicator
# ══════════════════════════════════════════════════════════════════════

def _normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = re.sub(r"[^\w\s]", "", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _jaccard(a: str, b: str) -> float:
    """Word-level Jaccard similarity between two strings."""
    sa = set(_normalise(a).split())
    sb = set(_normalise(b).split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


class QADeduplicator:
    """Finds and merges duplicate or near-duplicate Q&A pairs.

    Uses word-level Jaccard similarity on questions. When two Q&A pairs
    are above the similarity threshold, keeps the longer answer and
    deletes the duplicate.
    """

    def __init__(self, nexus_url: str = "",
                 similarity_threshold: float = 0.75) -> None:
        self._url = nexus_url or _get_nexus_url()
        self._threshold = similarity_threshold

    def find_duplicates(self) -> List[Dict[str, Any]]:
        """Find near-duplicate Q&A pairs.

        Returns:
            List of dicts with keep_id, remove_id, similarity, questions.
        """
        qa_list = _api_get("/api/qa", {"limit": 500})
        if not isinstance(qa_list, list) or len(qa_list) < 2:
            return []

        duplicates: List[Dict[str, Any]] = []
        seen_ids: set = set()

        for i, a in enumerate(qa_list):
            if a.get("id") in seen_ids:
                continue
            for b in qa_list[i + 1:]:
                if b.get("id") in seen_ids:
                    continue
                sim = _jaccard(a.get("question", ""), b.get("question", ""))
                if sim >= self._threshold:
                    # Keep the one with the longer answer
                    ans_a = a.get("answer", "")
                    ans_b = b.get("answer", "")
                    keep, remove = (a, b) if len(ans_a) >= len(ans_b) else (b, a)
                    duplicates.append({
                        "keep_id": keep["id"],
                        "remove_id": remove["id"],
                        "similarity": round(sim, 3),
                        "keep_q": keep.get("question", "")[:80],
                        "remove_q": remove.get("question", "")[:80],
                    })
                    seen_ids.add(remove["id"])

        return duplicates

    def deduplicate(self, dry_run: bool = False) -> Dict[str, Any]:
        """Find and remove duplicate Q&A pairs.

        Args:
            dry_run: If True, report duplicates without deleting.

        Returns:
            Dict with duplicate count and removed count.
        """
        dupes = self.find_duplicates()
        removed = 0

        if not dry_run:
            client = get_nexus_client()
            for d in dupes:
                try:
                    # QA items are stored as entries in Nexus — use delete_entry
                    if client.delete_entry(d["remove_id"]):
                        removed += 1
                except Exception:
                    logger.debug("Could not delete duplicate QA %s", d.get("remove_id"), exc_info=True)

        return {
            "duplicates_found": len(dupes),
            "removed": removed,
            "dry_run": dry_run,
            "pairs": dupes[:20],
        }


# ══════════════════════════════════════════════════════════════════════
#  Skill Usage Distiller
# ══════════════════════════════════════════════════════════════════════

class SkillUsageDistiller:
    """Extracts skill/tool usage patterns from session logs.

    Analyses conversation logs and session summaries to identify which
    MCP skills are used most frequently, which fail, and which are
    underutilised. Stores aggregated findings as knowledge entries.
    """

    # Regex patterns for skill calls in conversation text
    _SKILL_PATTERNS = [
        r"\btool[_\s]*call[:\s]+(\w+)",
        r"\bskill[:\s]+(\w+)",
        r"`(\w+_skill)`",
        r"@skill.*?def\s+(\w+)",
        r"Called\s+(\w+)\s*\(",
        r"nexus_(\w+)\(",
        r"(?:used|called|invoked|ran)\s+(\w+?)(?:\s+tool|\s+skill|\()",
    ]

    def __init__(self, nexus_url: str = "") -> None:
        self._url = nexus_url or _get_nexus_url()

    def _extract_skill_mentions(self, text: str) -> List[str]:
        """Extract skill/tool names mentioned in text."""
        mentions: List[str] = []
        for pat in self._SKILL_PATTERNS:
            for match in re.finditer(pat, text, re.IGNORECASE):
                name = match.group(1).strip().lower()
                if len(name) > 2 and name not in {"the", "and", "for", "was"}:
                    mentions.append(name)
        return mentions

    def analyse(self) -> Dict[str, Any]:
        """Analyse all session logs for skill usage patterns.

        Returns:
            Dict with skill frequency counts, recommendations.
        """
        entries = _api_get("/api/search", {"q": "session conversation tool skill", "limit": 200})
        if not isinstance(entries, list):
            entries = []

        skill_counts: Counter = Counter()
        error_skills: Counter = Counter()

        for e in entries:
            text = e.get("content", "")
            mentions = self._extract_skill_mentions(text)
            skill_counts.update(mentions)

            # Check for error context around skill mentions
            for m in mentions:
                # Look for errors near this skill mention
                idx = text.lower().find(m)
                if idx >= 0:
                    window = text[max(0, idx - 100):idx + 200].lower()
                    if any(w in window for w in ["error", "failed", "exception",
                                                  "broken", "traceback"]):
                        error_skills[m] += 1

        top_skills = skill_counts.most_common(20)
        error_list = error_skills.most_common(10)

        return {
            "total_mentions": sum(skill_counts.values()),
            "unique_skills": len(skill_counts),
            "top_skills": [{"skill": s, "count": c} for s, c in top_skills],
            "error_prone": [{"skill": s, "errors": c} for s, c in error_list],
            "rarely_used": [
                {"skill": s, "count": c}
                for s, c in skill_counts.most_common()[-10:]
                if c <= 2
            ],
        }

    def distill_and_store(self) -> Dict[str, int]:
        """Analyse skill usage and store findings in Nexus.

        Returns:
            Dict with count of entries stored.
        """
        analysis = self.analyse()
        stored = 0

        if analysis["top_skills"]:
            top_report = "Most used skills:\n"
            for item in analysis["top_skills"][:15]:
                top_report += f"  - {item['skill']}: {item['count']} mentions\n"

            if analysis["error_prone"]:
                top_report += "\nError-prone skills:\n"
                for item in analysis["error_prone"][:5]:
                    top_report += f"  - {item['skill']}: {item['errors']} errors\n"

            if analysis["rarely_used"]:
                top_report += "\nRarely used skills:\n"
                for item in analysis["rarely_used"][:5]:
                    top_report += f"  - {item['skill']}: {item['count']} mentions\n"

            result = _api_post("/api/entries", {
                "title": "Skill usage analysis — distilled",
                "content": top_report,
                "content_type": "note",
                "category": "system",
                "tags": ["distilled", "skill-usage", "system", "analysis"],
            })
            if result:
                stored += 1

        # Store individual Q&A for top skills
        for item in analysis["top_skills"][:5]:
            _api_post("/api/qa", {
                "question": f"How often is the {item['skill']} skill used?",
                "answer": f"The {item['skill']} skill has been mentioned "
                          f"{item['count']} times in session logs, making it "
                          f"one of the most frequently used tools.",
                "category": "system",
                "tags": ["distilled", "skill-usage"],
            })
            stored += 1

        return {"entries_stored": stored, "skills_analysed": analysis["unique_skills"]}


# ══════════════════════════════════════════════════════════════════════
#  Prompt Evolution Distiller
# ══════════════════════════════════════════════════════════════════════

class PromptEvolutionDistiller:
    """Tracks how prompts evolve over time and distils effective patterns.

    Analyses stored prompt entries to detect versions, measure drift,
    and identify which prompt patterns correlate with positive outcomes.
    Produces a lineage report and stores best-practice observations.
    """

    def __init__(self, nexus_url: str = "") -> None:
        self._url = nexus_url or _get_nexus_url()

    def _group_prompts(self) -> Dict[str, List[Dict[str, Any]]]:
        """Group prompt entries by base name (stripping version suffixes)."""
        entries = _api_get("/api/search", {"q": "prompt", "limit": 200})
        if not isinstance(entries, list):
            return {}

        prompts = [
            e for e in entries
            if e.get("content_type") == "prompt"
            or "prompt" in str(e.get("tags", "")).lower()
        ]

        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for p in prompts:
            title = p.get("title", "")
            # Strip version indicators to find base name
            base = re.sub(r"\s*[vV]\d+(\.\d+)*\s*$", "", title)
            base = re.sub(r"\s*\(v\d+\)\s*$", "", base)
            base = re.sub(r"\s*—\s*v\d+\s*$", "", base)
            groups[base.strip()].append(p)

        # Sort each group by created_at
        for key in groups:
            groups[key].sort(key=lambda x: x.get("created_at", ""))

        return dict(groups)

    def get_lineage(self) -> Dict[str, Any]:
        """Get prompt evolution lineage — which prompts have multiple versions.

        Returns:
            Dict with prompt groups, version counts, total chars drift.
        """
        groups = self._group_prompts()
        lineage: List[Dict[str, Any]] = []

        for name, versions in groups.items():
            if not versions:
                continue
            lengths = [len(v.get("content", "")) for v in versions]
            lineage.append({
                "name": name[:80],
                "versions": len(versions),
                "first_created": versions[0].get("created_at", "?")[:10],
                "last_updated": versions[-1].get("created_at", "?")[:10],
                "length_trend": lengths,
                "avg_length": sum(lengths) // len(lengths) if lengths else 0,
                "grew": lengths[-1] > lengths[0] if len(lengths) > 1 else False,
            })

        multi_version = [l for l in lineage if l["versions"] > 1]
        single_version = [l for l in lineage if l["versions"] == 1]

        return {
            "total_prompts": sum(l["versions"] for l in lineage),
            "unique_prompt_names": len(lineage),
            "multi_version": len(multi_version),
            "single_version": len(single_version),
            "lineage": sorted(lineage, key=lambda x: x["versions"], reverse=True),
        }

    def distill_patterns(self) -> Dict[str, Any]:
        """Analyse prompt content for common structural patterns.

        Looks for patterns like role definitions, constraint lists,
        output formatting, and tool usage instructions. Stores a
        best-practices entry summarising findings.
        """
        entries = _api_get("/api/search", {"q": "prompt", "limit": 200})
        if not isinstance(entries, list):
            return {"error": "Could not fetch prompts"}

        prompts = [
            e for e in entries
            if e.get("content_type") == "prompt"
        ]

        pattern_counts: Dict[str, int] = Counter()
        pattern_examples: Dict[str, str] = {}

        # Patterns to look for in prompt text
        checks = {
            "role_definition": r"(?:You are|Act as|Your role)",
            "constraint_list": r"(?:You must|Never|Always|Do not|Rules:)",
            "output_format": r"(?:Format:|Output:|Respond with|Return as)",
            "examples_section": r"(?:Example:|For example|e\.g\.|Here is an example)",
            "tool_instructions": r"(?:tool|skill|function|call)\s+(?:to|for|when)",
            "persona_traits": r"(?:personality|traits|character|style|tone)",
            "context_injection": r"(?:context|knowledge|background|setting)",
            "guardrails": r"(?:avoid|refrain|don't|prohibit|censor|restrict)",
        }

        for p in prompts:
            content = p.get("content", "")
            for pattern_name, regex in checks.items():
                if re.search(regex, content, re.IGNORECASE):
                    pattern_counts[pattern_name] += 1
                    if pattern_name not in pattern_examples:
                        # Store first example
                        match = re.search(regex, content, re.IGNORECASE)
                        if match:
                            start = max(0, match.start() - 20)
                            end = min(len(content), match.end() + 80)
                            pattern_examples[pattern_name] = content[start:end].strip()

        report = f"Prompt pattern analysis ({len(prompts)} prompts):\n\n"
        for pat, count in sorted(pattern_counts.items(), key=lambda x: -x[1]):
            pct = (count / len(prompts) * 100) if prompts else 0
            report += f"  {pat}: {count}/{len(prompts)} ({pct:.0f}%)\n"
            if pat in pattern_examples:
                report += f"    Example: \"{pattern_examples[pat][:100]}\"\n"

        # Store analysis
        stored = _api_post("/api/entries", {
            "title": "Prompt patterns analysis — distilled",
            "content": report,
            "content_type": "note",
            "category": "system",
            "tags": ["distilled", "prompt-evolution", "system", "analysis"],
        })

        return {
            "prompts_analysed": len(prompts),
            "patterns_found": dict(pattern_counts),
            "stored": bool(stored),
        }


# ══════════════════════════════════════════════════════════════════════
#  Unified Runner
# ══════════════════════════════════════════════════════════════════════

def run_all_distillers(nexus_url: str = "") -> Dict[str, Any]:
    """Run all distillers in sequence and return combined results.

    Returns:
        Dict with results from each distiller.
    """
    results: Dict[str, Any] = {}

    nd = NexusDistiller(nexus_url)
    results["session_distiller"] = nd.distill()

    qa = QADeduplicator(nexus_url)
    results["qa_dedup"] = qa.deduplicate()

    su = SkillUsageDistiller(nexus_url)
    results["skill_usage"] = su.distill_and_store()

    pe = PromptEvolutionDistiller(nexus_url)
    results["prompt_evolution"] = pe.distill_patterns()

    return results


def main() -> None:
    """CLI entry point."""
    actions = (
        "distill, compact, stats, primer, dedup, dedup-dry, "
        "skills, prompts, lineage, all"
    )
    if len(sys.argv) < 2:
        logger.info("Usage: python -m engine.nexus.nexus_distiller [%s]", actions)
        sys.exit(1)

    action = sys.argv[1].lower()

    if action == "distill":
        logger.info(json.dumps(NexusDistiller().distill(), indent=2, default=str))
    elif action == "compact":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        logger.info(json.dumps(NexusDistiller().compact_sessions(days), indent=2, default=str))
    elif action == "stats":
        logger.info(json.dumps(NexusDistiller().get_stats(), indent=2, default=str))
    elif action == "primer":
        logger.info("%s", NexusDistiller().generate_context_primer())
    elif action == "dedup":
        logger.info(json.dumps(QADeduplicator().deduplicate(dry_run=False), indent=2, default=str))
    elif action == "dedup-dry":
        logger.info(json.dumps(QADeduplicator().deduplicate(dry_run=True), indent=2, default=str))
    elif action == "skills":
        logger.info(json.dumps(SkillUsageDistiller().distill_and_store(), indent=2, default=str))
    elif action == "prompts":
        logger.info(json.dumps(PromptEvolutionDistiller().distill_patterns(), indent=2, default=str))
    elif action == "lineage":
        logger.info(json.dumps(PromptEvolutionDistiller().get_lineage(), indent=2, default=str))
    elif action == "all":
        logger.info(json.dumps(run_all_distillers(), indent=2, default=str))
    else:
        logger.error("Unknown action: %s. Use: %s", action, actions)
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
