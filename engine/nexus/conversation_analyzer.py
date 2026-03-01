"""Conversation Analyzer — post-conversation fact extraction pipeline.

After every conversation ends (or on a scheduler trigger), this module
analyzes recent conversation turns to extract:

  - User facts (name, age, location, hardware, preferences)
  - Project information (what projects they work on, current state)
  - Technical background (languages, tools, frameworks they use)
  - Topics of interest (AI, fine-tuning, NotebookLM, etc.)
  - Decisions made (architecture choices, approaches taken)
  - Action items (things they want to do next)

The extraction pipeline runs in three modes:

  1. ``extract_fast(text)``   — local Qwen router model, instant, coarse
  2. ``extract_nlm(text)``    — NLM/Gemini 3.0, rich, structured JSON
  3. ``extract_lm(text)``     — LMStudio 7B, intermediate quality

All extracted data is merged into UserProfileStore and stored in Nexus.

Scheduler hook: ``post-conversation-analyze`` (triggered by MCP dialog hook)

MCP tools::

    analyze_conversation(text, mode)  — extract facts from conversation text
    conversation_analyzer_status()    — last extraction result

Usage::

    from engine.nexus.conversation_analyzer import get_conversation_analyzer
    analyzer = get_conversation_analyzer()
    result = analyzer.analyze(conversation_text)
    print(result["facts"])        # ["User has RTX 2060", ...]
    print(result["preferences"])  # {"verbosity": "concise"}
"""
from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ──── Extraction Prompts ──────────────────────────────────────────────────────

_EXTRACT_SYSTEM_PROMPT = """You are a meticulous conversation analyst.
Your job is to read a conversation and extract structured facts about the user.
Output ONLY valid JSON, no prose, no markdown code fences.
"""

_EXTRACT_USER_PROMPT = """Read this conversation and extract all facts about the user.

Return a JSON object with these fields:
{{
  "name": "string or null",
  "age": "number or null",
  "location": "string or null",
  "technical_background": ["list of tech/languages/tools they know or use"],
  "projects": {{
    "project_name": {{"description": "...", "status": "...", "tech": [...]}}
  }},
  "preferences": {{
    "key": "value"
  }},
  "facts": ["list of notable facts about the user"],
  "topics_of_interest": ["topics they discuss or care about"],
  "decisions_made": ["architectural or technical decisions mentioned"],
  "action_items": ["things they want to do, build, or fix next"]
}}

Extract ONLY facts explicitly stated or clearly implied. Leave fields null/empty if not mentioned.

CONVERSATION:
{conversation}
"""

_NLM_EXTRACT_PROMPT = """Read the following conversation excerpt and extract ALL factual information about the user.
Produce a structured JSON extraction with these exact fields:
- name, age, location (personal facts)
- technical_background (array of languages/frameworks/tools)
- projects (object mapping project names to {description, status, tech_stack})
- preferences (object of key→value preference pairs)
- facts (array of notable factual statements about the user)
- topics_of_interest (array of topics they discuss)
- decisions_made (array of decisions made in this conversation)
- action_items (array of things they want to do next)

Be thorough and extract everything mentioned, both explicitly and implicitly.
Focus on hardware specs, work style, technical choices, project names, goals.

Conversation to analyze:
{conversation}

Output only the JSON object."""

# ──── Data Classes ────────────────────────────────────────────────────────────


@dataclass
class ExtractionResult:
    """Result from a conversation analysis extraction run."""

    name: Optional[str] = None
    age: Optional[int] = None
    location: Optional[str] = None
    technical_background: List[str] = field(default_factory=list)
    projects: Dict[str, Any] = field(default_factory=dict)
    preferences: Dict[str, Any] = field(default_factory=dict)
    facts: List[str] = field(default_factory=list)
    topics_of_interest: List[str] = field(default_factory=list)
    decisions_made: List[str] = field(default_factory=list)
    action_items: List[str] = field(default_factory=list)
    extraction_mode: str = "none"
    confidence: float = 0.5
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "age": self.age,
            "location": self.location,
            "technical_background": self.technical_background,
            "projects": self.projects,
            "preferences": self.preferences,
            "facts": self.facts,
            "topics_of_interest": self.topics_of_interest,
            "decisions_made": self.decisions_made,
            "action_items": self.action_items,
            "extraction_mode": self.extraction_mode,
            "confidence": self.confidence,
            "error": self.error,
        }

    def to_profile_update(self) -> Dict[str, Any]:
        """Return a dict suitable for merging into UserProfileStore."""
        update: Dict[str, Any] = {}
        if self.name:
            update["name"] = self.name
        if self.technical_background:
            update["technical_background"] = self.technical_background
        if self.projects:
            update["projects"] = self.projects
        if self.preferences:
            update["preferences"] = self.preferences
        if self.facts:
            update["facts"] = self.facts
        if self.topics_of_interest:
            update["topics_of_interest"] = self.topics_of_interest
        return update


# ──── ConversationAnalyzer ────────────────────────────────────────────────────


class ConversationAnalyzer:
    """Extracts structured user facts from conversation text.

    Uses a cascading extraction strategy:
      1. Try NLM (Gemini 3.0) for best quality if available
      2. Fall back to LMStudio 7B+ model
      3. Fall back to regex/heuristic extraction
    """

    def __init__(self) -> None:
        self._last_result: Optional[ExtractionResult] = None

    # ── Public API ────────────────────────────────────────────────────────────

    def analyze(
        self,
        conversation_text: str,
        mode: str = "auto",
        store_to_profile: bool = True,
    ) -> ExtractionResult:
        """Analyze a conversation and extract structured user facts.

        Args:
            conversation_text: Full conversation text (multi-turn, markdown OK).
            mode: "auto" | "nlm" | "lm" | "heuristic"
            store_to_profile: If True, merge extracted facts into UserProfileStore
                and Nexus.

        Returns:
            ExtractionResult with all extracted fields.
        """
        if not conversation_text or len(conversation_text.strip()) < 50:
            return ExtractionResult(error="Conversation too short for analysis")

        result = self._extract(conversation_text, mode)
        self._last_result = result

        if store_to_profile and not result.error:
            self._store_result(result)

        return result

    def analyze_recent_turns(
        self,
        session_id: Optional[str] = None,
        turns_back: int = 50,
        store_to_profile: bool = True,
    ) -> ExtractionResult:
        """Fetch recent turns from session store and analyze them.

        Args:
            session_id: Specific session to analyze (defaults to most recent).
            turns_back: How many turns to include.
            store_to_profile: If True, store extracted data.

        Returns:
            ExtractionResult with extracted user facts.
        """
        text = self._fetch_recent_turns(session_id, turns_back)
        if not text:
            return ExtractionResult(error="No turns found in session store")
        return self.analyze(text, store_to_profile=store_to_profile)

    def get_last_result(self) -> Optional[Dict[str, Any]]:
        """Return the last extraction result as a dict."""
        return self._last_result.to_dict() if self._last_result else None

    # ── Extraction Cascade ────────────────────────────────────────────────────

    def _extract(self, text: str, mode: str) -> ExtractionResult:
        """Try extraction modes in order until one succeeds."""
        if mode in ("nlm", "auto"):
            result = self._extract_nlm(text)
            if result and not result.error:
                return result

        if mode in ("lm", "auto"):
            result = self._extract_lm(text)
            if result and not result.error:
                return result

        return self._extract_heuristic(text)

    def _extract_nlm(self, text: str) -> Optional[ExtractionResult]:
        """Use NLM (Gemini 3.0) for structured fact extraction."""
        try:
            from engine.mcp.nlm_hybrid import get_nlm_hybrid
            hybrid = get_nlm_hybrid()
            # Use the NLM ask interface to extract facts
            prompt = _NLM_EXTRACT_PROMPT.format(conversation=text[:8000])
            response = hybrid.ask(
                notebook_id=None,  # Uses default notebook
                question=prompt,
                create_if_missing=False,
            )
            if not response or response.get("error"):
                return None
            answer = response.get("answer", "")
            return self._parse_json_response(answer, mode="nlm")
        except Exception as exc:
            logger.debug("NLM extraction failed: %s", exc)
            return None

    def _extract_lm(self, text: str) -> Optional[ExtractionResult]:
        """Use LMStudio model for structured fact extraction."""
        try:
            from engine.lmstudio.client import get_lmstudio_client
            client = get_lmstudio_client()
            prompt = _EXTRACT_USER_PROMPT.format(conversation=text[:6000])
            response = client.chat(
                messages=[
                    {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=2000,
            )
            if not response:
                return None
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            return self._parse_json_response(content, mode="lm")
        except Exception as exc:
            logger.debug("LMStudio extraction failed: %s", exc)
            return None

    def _extract_heuristic(self, text: str) -> ExtractionResult:
        """Heuristic pattern-based extraction (no LLM, low confidence)."""
        result = ExtractionResult(extraction_mode="heuristic", confidence=0.3)

        # Hardware patterns
        hw_patterns = [
            r"(RTX\s*\d{4}(?:\s*\d{2}GB)?)",
            r"(i[3579]-\d{4,5}[A-Z]{0,2})",
            r"(\d+\s*GB\s*(?:VRAM|RAM|memory))",
            r"(NUC|Beast Canyon|Hades Canyon)",
            r"(CUDA|NVIDIA|AMD|Intel\s*Arc)",
        ]
        for pattern in hw_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                fact = f"Hardware: {match.group(0)}"
                if fact not in result.facts:
                    result.facts.append(fact)

        # Tech mentions
        tech_keywords = [
            "Python", "JavaScript", "TypeScript", "Flask", "FastAPI",
            "PyTorch", "ONNX", "Unsloth", "LMStudio", "HuggingFace",
            "SQLite", "ChromaDB", "NotebookLM", "Gemini", "Qwen",
            "LoRA", "QLoRA", "GGUF", "GGML", "VS Code", "PowerShell",
        ]
        mentioned = set()
        for tech in tech_keywords:
            if tech.lower() in text.lower() and tech not in mentioned:
                result.technical_background.append(tech)
                mentioned.add(tech)

        # Project names from "CosySim", "Nexus" etc
        project_patterns = [r"\bCosySim\b", r"\bNexus\b", r"\bNLM\b"]
        for pattern in project_patterns:
            if re.search(pattern, text):
                name = re.search(pattern, text).group(0)
                if name not in result.projects:
                    result.projects[name] = {"mentioned": True}

        return result

    # ── Storage ───────────────────────────────────────────────────────────────

    def _store_result(self, result: ExtractionResult) -> None:
        """Merge extraction result into UserProfileStore and Nexus."""
        try:
            from engine.nexus.user_profile import get_user_profile_store
            store = get_user_profile_store()
            update = result.to_profile_update()
            if update:
                store.merge(update)
                logger.info(
                    "Profile updated from conversation analysis (%s mode, %.0f confidence)",
                    result.extraction_mode, result.confidence,
                )
        except Exception as exc:
            logger.warning("Failed to store profile update: %s", exc)

        # Store action items as Nexus tasks
        if result.action_items:
            try:
                from engine.nexus.client import get_nexus_client
                client = get_nexus_client()
                if client.is_available():
                    items_text = "\n".join(f"- {item}" for item in result.action_items)
                    client.add_entry(
                        title=f"Action Items — {_now()[:10]}",
                        content=items_text,
                        content_type="note",
                        category="copilot",
                        tags=["action-items", "conversation-analysis"],
                    )
            except Exception as exc:
                logger.debug("Action items Nexus store failed: %s", exc)

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _parse_json_response(self, text: str, mode: str) -> Optional[ExtractionResult]:
        """Parse a JSON string into an ExtractionResult."""
        # Strip markdown fences if present
        text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
        # Extract the first JSON object
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            result = ExtractionResult(extraction_mode=mode, confidence=0.8)
            result.name = data.get("name") or None
            result.age = data.get("age") or None
            result.location = data.get("location") or None
            result.technical_background = _list_of_str(data.get("technical_background"))
            result.projects = data.get("projects") or {}
            result.preferences = data.get("preferences") or {}
            result.facts = _list_of_str(data.get("facts"))
            result.topics_of_interest = _list_of_str(data.get("topics_of_interest"))
            result.decisions_made = _list_of_str(data.get("decisions_made"))
            result.action_items = _list_of_str(data.get("action_items"))
            return result
        except json.JSONDecodeError as exc:
            logger.debug("JSON parse failed: %s", exc)
            return None

    def _fetch_recent_turns(
        self, session_id: Optional[str], turns_back: int
    ) -> str:
        """Fetch recent conversation turns from the Copilot session store."""
        try:
            import sqlite3 as _sqlite
            from pathlib import Path as _Path
            store_path = _Path("~/.copilot/session-store/store.sqlite").expanduser()
            if not store_path.exists():
                return ""
            conn = _sqlite.connect(
                f"file:{store_path}?mode=ro", uri=True, timeout=10.0
            )
            try:
                if session_id:
                    rows = conn.execute(
                        "SELECT user_message, assistant_response FROM turns "
                        "WHERE session_id = ? ORDER BY turn_index DESC LIMIT ?",
                        (session_id, turns_back),
                    ).fetchall()
                else:
                    # Most recent session
                    row = conn.execute(
                        "SELECT id FROM sessions ORDER BY created_at DESC LIMIT 1"
                    ).fetchone()
                    if not row:
                        return ""
                    rows = conn.execute(
                        "SELECT user_message, assistant_response FROM turns "
                        "WHERE session_id = ? ORDER BY turn_index DESC LIMIT ?",
                        (row[0], turns_back),
                    ).fetchall()
                parts = []
                for user_msg, asst_resp in reversed(rows):
                    if user_msg:
                        parts.append(f"User: {user_msg[:1000]}")
                    if asst_resp:
                        parts.append(f"Assistant: {asst_resp[:500]}")
                return "\n\n".join(parts)
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("Failed to fetch turns: %s", exc)
            return ""


# ──── Helpers ─────────────────────────────────────────────────────────────────


def _list_of_str(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [str(value)]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ──── Singleton ───────────────────────────────────────────────────────────────

_analyzer_instance: Optional[ConversationAnalyzer] = None
_analyzer_lock = threading.Lock()


def get_conversation_analyzer() -> ConversationAnalyzer:
    """Get the singleton ConversationAnalyzer instance."""
    global _analyzer_instance
    if _analyzer_instance is None:
        with _analyzer_lock:
            if _analyzer_instance is None:
                _analyzer_instance = ConversationAnalyzer()
    return _analyzer_instance


def run_conversation_analysis() -> Dict[str, Any]:
    """Scheduler callback: analyze most recent conversation session.

    Returns:
        ExtractionResult as a dict.
    """
    analyzer = get_conversation_analyzer()
    result = analyzer.analyze_recent_turns(store_to_profile=True)
    return result.to_dict()
