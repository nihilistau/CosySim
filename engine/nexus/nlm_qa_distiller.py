"""
NLM QA Distiller — Use NotebookLM to generate high-quality Q&A pairs for Nexus.

This module provides two main capabilities:

1. **QA generation from Nexus knowledge entries** — Takes existing Nexus entries,
   creates an NLM notebook, asks deliberate questions, and stores the answers
   back in Nexus as Q&A pairs.

2. **Question prompt templates** — Pre-designed question sets for specific topics
   that local models can use to generate training data or trigger NLM research.

The compound effect: every Q&A pair stored in Nexus is one fewer LLM call in
the future. Cache hit rate increases over time. Compute decreases.

Version: v1.57.0 [2026-03-26]
Author:  CosySim Team

Change Log:
    v1.57.0 [2026-03-26] — Add structured output path for Q&A parsing via Gemini;
                             _parse_qa_response() prefers generate_structured(),
                             _parse_qa_legacy() contains original regex/line parsing

Usage::

    from engine.nexus.nlm_qa_distiller import NLMQADistiller

    distiller = NLMQADistiller()

    # Distill a topic using an existing notebook
    pairs = distiller.distill_topic(
        notebook_id="de7fee37-...",
        topic="MCP Framework Architecture",
        num_questions=20,
    )

    # Generate Q&A from Nexus entries
    pairs = distiller.distill_from_entries(
        category="architecture",
        limit=50,
    )

    # CLI:
    python -m engine.nexus.nlm_qa_distiller --topic "interceptor pipeline" --questions 20
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from engine.config import get_config

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ── Question Templates ────────────────────────────────────────────────────
#
# These are carefully designed question sets for generating high-quality
# Q&A pairs. Questions are grouped into batches of 5 for efficient NLM usage.
#
# Format: {topic: [[batch1_q1, batch1_q2, ...], [batch2_q1, ...]]}

QUESTION_TEMPLATES: Dict[str, List[List[str]]] = {

    "cosysim_architecture": [
        [
            "What is the overall architecture of CosySim and how do the major components interact?",
            "How does the MCPFramework tree work as a state container and what are its key operations?",
            "Describe the InterceptorPipeline — how are interceptors registered and called?",
            "How does the DialogSystem manage conversation threading and character interactions?",
            "What is the lifecycle of a skill call from agent request to execution and result?",
        ],
        [
            "How does the AgentGovernor enforce rules and what happens when a rule is violated?",
            "Explain the EventChain audit logging system and how events are stored and queried.",
            "How does the SceneStateManager persist state and what triggers state saves?",
            "What is the role of MCPCharacterNode and how does it sync with the character database?",
            "How does the VirtualAgent differ from CharacterAgent and when is each used?",
        ],
        [
            "What are the key failure modes in the MCP system and how should they be handled?",
            "How does the @skill decorator work and what metadata does it capture?",
            "Describe the request/response flow for a streamed LMStudio inference call.",
            "How does the NLM-first query router decide which tier to use?",
            "What are the performance bottlenecks in the current architecture?",
        ],
    ],

    "nlm_integration": [
        [
            "How does the NotebookLM batchexecute API work at the protocol level?",
            "What is the CYK0Xb RPC and how do you ask a question to NotebookLM?",
            "How does multi-question batching work and what are its limits?",
            "What is the ciyUvf RPC used for and what does it return?",
            "How should Google auth cookies be managed and refreshed automatically?",
        ],
        [
            "What is the SAPISIDHASH and how is it computed for the Authorization header?",
            "How does the build label (bl parameter) work and what happens when it expires?",
            "Describe the 5-layer response decode pipeline for batchexecute responses.",
            "How should NLM be integrated into the Nexus self-improvement loop?",
            "What is the optimal question strategy to maximize knowledge extraction per NLM call?",
        ],
    ],

    "nexus_knowledge_system": [
        [
            "What are the three layers of the Nexus knowledge database and what does each store?",
            "How does the 4-tier query router work (cache → FTS → NLM → LLM)?",
            "What is the difference between nexus_search and nexus_ask?",
            "How should content_type and category be used to organize knowledge entries?",
            "What triggers a cache hit and how is the Q&A cache populated?",
        ],
        [
            "How does the knowledge quality scorer identify low-quality entries?",
            "What is the compound improvement loop and how does it make the system smarter?",
            "How should training data be exported from Nexus for model fine-tuning?",
            "What are the key metrics to monitor for Nexus health?",
            "How does the governance rules engine enforce coding standards?",
        ],
    ],

    "agent_operations": [
        [
            "How should a local LMStudio agent pick up and execute a task from the scheduler?",
            "What information does an agent need at startup to operate effectively?",
            "How should an agent decide which LMStudio model size to use for a given task?",
            "What is the correct pattern for an agent to search Nexus before doing work?",
            "How should an agent store its findings and decisions in Nexus after completing work?",
        ],
        [
            "What governance rules must an agent follow when modifying code?",
            "How should an agent handle errors and escalate to a larger model?",
            "Describe the retry and escalation strategy for failed agent tasks.",
            "How does an agent validate its own output before marking a task complete?",
            "What training data should agents generate from their operations?",
        ],
    ],

    "lmstudio_integration": [
        [
            "How does the LMStudio v1 API differ from OpenAI API and what are the key format differences?",
            "What is the correct input format for LMStudio v1 — why are type/text items required?",
            "How does stateful conversation work with store:true and previous_response_id?",
            "What is SSE streaming format in LMStudio v1 and how should it be parsed?",
            "How should VRAM be managed across multiple model loads?",
        ],
        [
            "What are the model profiles (big, small, router, draft) and when is each used?",
            "How does speculative decoding work and when should it be enabled?",
            "What is the InferenceOrchestrator and how does it route requests across models?",
            "How should the router model (270M) be used to classify incoming requests?",
            "What metrics should be collected per inference call for benchmarking?",
        ],
    ],

    "scene_development": [
        [
            "What is the required structure for a CosySim scene and what must be implemented?",
            "How does a scene register itself with the MCPFramework on startup?",
            "What is the correct pattern for scene-specific skills using the @skill decorator?",
            "How should a scene handle character lifecycle events (add/remove)?",
            "What is the Flask startup pattern for a scene and how should health checks work?",
        ],
        [
            "How should Socket.IO be used for real-time scene updates?",
            "What state must a scene sync to MCP and what can stay local?",
            "How does a scene use the AgentGovernor for character agent calls?",
            "What is the correct error handling pattern for scene operations?",
            "How should a scene implement graceful shutdown and state persistence?",
        ],
    ],

    "self_improvement": [
        [
            "What is the autonomous improvement loop and what are its key components?",
            "How does the scheduler daemon drive the autonomous system?",
            "What metrics indicate that the system is improving over time?",
            "How should failed tests trigger automatic diagnosis and fix tasks?",
            "What is the experiment proposal system and how does it suggest improvements?",
        ],
        [
            "How does the training flywheel convert system operations into training data?",
            "What is the knowledge graph and how does it identify knowledge gaps?",
            "How should system reflection work to generate weekly improvement tasks?",
            "What A/B experiments should the system run automatically?",
            "How does copilot self-configuration work and what does it read from Nexus?",
        ],
    ],
}

# Minimum batch size for efficient NLM calls
MIN_BATCH_SIZE = 3
# Maximum questions per HTTP request (tested up to 5)
MAX_BATCH_SIZE = 5


# ── NLMQADistiller class ──────────────────────────────────────────────────

class NLMQADistiller:
    """Orchestrates NLM-powered Q&A generation for Nexus population.

    Connects to the NLM proxy at :8800 and uses ask_questions_batch
    to efficiently extract knowledge from notebooks, then stores results
    in Nexus as Q&A pairs.
    """

    def __init__(
        self,
        proxy_url: str = "",
        nexus_url: str = "",
    ) -> None:
        if not proxy_url:
            from engine.port_registry import get_service_url
            proxy_url = get_service_url("nlm_proxy")
        if not nexus_url:
            from engine.port_registry import get_service_url
            nexus_url = get_service_url("nexus")
        self._proxy_url = proxy_url.rstrip("/")
        self._nexus_url = nexus_url.rstrip("/")

    def _proxy_request(self, method: str, path: str, data: Any = None) -> Optional[Dict]:
        """Make an HTTP request to the NLM proxy.

        Args:
            method: HTTP method (GET/POST).
            path: URL path (e.g. "/notebooks").
            data: JSON body for POST requests.

        Returns:
            Parsed JSON response dict, or None on error.
        """
        import urllib.error
        import urllib.request

        url = f"{self._proxy_url}{path}"
        headers = {"Content-Type": "application/json"}
        body = json.dumps(data).encode() if data else None

        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode(errors="replace") if exc.fp else ""
            logger.warning("NLM proxy %s %s → HTTP %s: %s", method, path, exc.code, body_text[:200])
            return None
        except Exception as exc:
            logger.error("NLM proxy request failed: %s", exc)
            return None

    def _is_proxy_ready(self) -> bool:
        """Check if the NLM proxy is running and has auth cookies."""
        health = self._proxy_request("GET", "/health")
        if not health:
            return False
        if health.get("status") == "no_cookies":
            logger.warning("NLM proxy running but no auth cookies. Use /cookies/capture.")
            return False
        return health.get("status") == "ok"

    def ask_batch(
        self,
        notebook_id: str,
        questions: List[str],
    ) -> List[Dict[str, Any]]:
        """Send a batch of questions to a notebook and return answers.

        Args:
            notebook_id: UUID of the target notebook.
            questions: List of question strings (up to 20 recommended).

        Returns:
            List of answer dicts {answer_id, answer, sources}.
        """
        result = self._proxy_request(
            "POST",
            f"/notebooks/{notebook_id}/ask_batch",
            {"questions": questions, "max_batch": MAX_BATCH_SIZE},
        )
        if not result:
            return [{"answer": "", "answer_id": None, "sources": []}] * len(questions)
        return result.get("answers", [])

    def distill_topic(
        self,
        notebook_id: str,
        topic: str,
        num_questions: int = 20,
        template_key: Optional[str] = None,
        store_in_nexus: bool = True,
    ) -> List[Dict[str, Any]]:
        """Distill a topic from a notebook into Q&A pairs.

        Args:
            notebook_id: UUID of the target notebook.
            topic: Human-readable topic name (for Nexus storage).
            num_questions: Total number of questions to ask.
            template_key: Key from QUESTION_TEMPLATES to use. Auto-detected if None.
            store_in_nexus: Whether to store results in Nexus (default True).

        Returns:
            List of {question, answer, answer_id, sources} dicts.
        """
        if not self._is_proxy_ready():
            logger.error("NLM proxy not ready — cannot distill topic '%s'", topic)
            return []

        # Get questions — from template or generate automatically
        questions = self._get_questions(topic, num_questions, template_key)
        if not questions:
            logger.warning("No questions generated for topic '%s'", topic)
            return []

        logger.info("Distilling topic '%s' with %d questions from notebook %s",
                    topic, len(questions), notebook_id)

        # Ask all questions (batched automatically)
        answers = self.ask_batch(notebook_id, questions)

        # Build Q&A pairs
        pairs = []
        for q, a in zip(questions, answers):
            if a.get("answer"):
                pairs.append({
                    "question": q,
                    "answer": a["answer"],
                    "answer_id": a.get("answer_id"),
                    "sources": a.get("sources", []),
                    "notebook_id": notebook_id,
                    "topic": topic,
                })

        logger.info("Got %d/%d answers for topic '%s'", len(pairs), len(questions), topic)

        # Store in Nexus
        if store_in_nexus and pairs:
            self._store_pairs_in_nexus(pairs, topic)

        return pairs

    def distill_from_entries(
        self,
        category: Optional[str] = None,
        content_type: Optional[str] = None,
        limit: int = 50,
        notebook_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Generate Q&A pairs from existing Nexus knowledge entries.

        Takes Nexus entries, uses their content to formulate questions,
        asks NLM, and stores answers back in Nexus.

        Args:
            category: Filter entries by category (e.g. "architecture").
            content_type: Filter by content type (e.g. "document").
            limit: Maximum number of entries to process.
            notebook_id: NLM notebook to query (uses cosysim-architecture if None).

        Returns:
            List of Q&A pairs stored in Nexus.
        """
        from engine.nexus.client import get_nexus_client

        client = get_nexus_client()

        # Search for knowledge entries
        search_query = category or content_type or "system architecture MCP"
        results = client.search(search_query)
        if not results:
            logger.warning("No Nexus entries found for distillation query: %s", search_query)
            return []

        entries = results[:limit]
        logger.info("Distilling %d Nexus entries into Q&A pairs", len(entries))

        # Auto-detect or use provided notebook
        if not notebook_id:
            notebooks_resp = self._proxy_request("GET", "/notebooks")
            if notebooks_resp and notebooks_resp.get("notebooks"):
                # Use the first available notebook
                notebook_id = notebooks_resp["notebooks"][0]["id"]
            if not notebook_id:
                logger.error("No NLM notebook available for distillation")
                return []

        # Generate entry-based questions
        questions = []
        entry_map = {}
        for entry in entries:
            title = entry.get("title", "")
            content_preview = (entry.get("content", "") or "")[:200]
            if title:
                q = f"Based on the knowledge about '{title}', {content_preview[:100]}... what are the key implementation details and best practices?"
                questions.append(q)
                entry_map[q] = entry

        if not questions:
            return []

        # Ask NLM and store pairs
        answers = self.ask_batch(notebook_id, questions[:20])  # Cap at 20
        pairs = []
        for q, a in zip(questions, answers):
            if a.get("answer"):
                pair = {
                    "question": q,
                    "answer": a["answer"],
                    "answer_id": a.get("answer_id"),
                    "sources": a.get("sources", []),
                    "notebook_id": notebook_id,
                }
                pairs.append(pair)

        if pairs:
            self._store_pairs_in_nexus(pairs, "nexus_entry_distillation")

        return pairs

    def distill_template(
        self,
        template_key: str,
        notebook_id: str,
        store_in_nexus: bool = True,
    ) -> List[Dict[str, Any]]:
        """Distill an entire question template from QUESTION_TEMPLATES.

        Args:
            template_key: Key in QUESTION_TEMPLATES (e.g. "cosysim_architecture").
            notebook_id: NLM notebook to query.
            store_in_nexus: Store results in Nexus (default True).

        Returns:
            All Q&A pairs from the template.
        """
        if template_key not in QUESTION_TEMPLATES:
            raise ValueError(f"Unknown template: {template_key}. "
                             f"Available: {list(QUESTION_TEMPLATES.keys())}")

        all_questions = []
        for batch in QUESTION_TEMPLATES[template_key]:
            all_questions.extend(batch)

        return self.distill_topic(
            notebook_id=notebook_id,
            topic=template_key.replace("_", " ").title(),
            num_questions=len(all_questions),
            store_in_nexus=store_in_nexus,
        )

    def bulk_distill(
        self,
        notebook_id: str,
        template_keys: Optional[List[str]] = None,
        delay_seconds: float = 2.0,
    ) -> Dict[str, int]:
        """Distill multiple templates sequentially.

        Args:
            notebook_id: NLM notebook to use for all templates.
            template_keys: List of template keys. All templates if None.
            delay_seconds: Pause between template groups (rate limiting).

        Returns:
            Dict of {template_key: qa_pairs_stored}.
        """
        if not template_keys:
            template_keys = list(QUESTION_TEMPLATES.keys())

        results: Dict[str, int] = {}
        for key in template_keys:
            logger.info("Distilling template: %s", key)
            pairs = self.distill_template(key, notebook_id)
            results[key] = len(pairs)
            logger.info("Stored %d Q&A pairs for %s", len(pairs), key)
            if delay_seconds > 0:
                time.sleep(delay_seconds)

        total = sum(results.values())
        logger.info("Bulk distillation complete: %d total Q&A pairs across %d templates",
                    total, len(template_keys))
        return results

    def _get_questions(
        self,
        topic: str,
        num_questions: int,
        template_key: Optional[str],
    ) -> List[str]:
        """Get question list for a topic from template or auto-generate.

        Args:
            topic: Topic name.
            num_questions: Desired question count.
            template_key: Template key to use (auto-detect if None).

        Returns:
            List of question strings.
        """
        # Try template match
        if template_key and template_key in QUESTION_TEMPLATES:
            questions = []
            for batch in QUESTION_TEMPLATES[template_key]:
                questions.extend(batch)
            return questions[:num_questions]

        # Auto-detect from topic
        topic_lower = topic.lower().replace(" ", "_")
        for key in QUESTION_TEMPLATES:
            if key in topic_lower or topic_lower in key:
                questions = []
                for batch in QUESTION_TEMPLATES[key]:
                    questions.extend(batch)
                return questions[:num_questions]

        # Generic questions for unknown topics
        return [
            f"What is the overall architecture of {topic} and how do its components interact?",
            f"What are the main use cases and capabilities of {topic}?",
            f"What are the key implementation patterns and best practices for {topic}?",
            f"What are the main failure modes and how should they be handled in {topic}?",
            f"How should {topic} be configured for optimal performance?",
            f"What metrics should be monitored for {topic}?",
            f"How does {topic} integrate with other system components?",
            f"What improvements would have the highest impact on {topic}?",
            f"What are the key quality requirements for {topic}?",
            f"How should {topic} be tested and validated?",
        ][:num_questions]

    def _store_pairs_in_nexus(
        self,
        pairs: List[Dict[str, Any]],
        topic: str,
    ) -> int:
        """Store Q&A pairs in Nexus via the REST API.

        Args:
            pairs: List of {question, answer, ...} dicts.
            topic: Topic name for categorization.

        Returns:
            Number of pairs successfully stored.
        """
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
        except Exception as exc:
            logger.warning("Could not get Nexus client, using direct storage: %s", exc)
            return self._store_pairs_direct(pairs)

        stored = 0
        for pair in pairs:
            q = pair.get("question", "")
            a = pair.get("answer", "")
            if not q or not a:
                continue
            try:
                client.add_qa(
                    question=q,
                    answer=a,
                    category="nlm_distilled",
                )
                stored += 1
            except Exception as exc:
                logger.warning("Failed to store Q&A pair: %s", exc)

        # Also store as a research entry
        if pairs:
            try:
                content = "\n\n".join(
                    f"**Q: {p['question']}**\n\n{p['answer']}"
                    for p in pairs
                    if p.get("answer")
                )
                client.add_entry(
                    title=f"NLM Distillation: {topic}",
                    content=content,
                    content_type="research",
                    category="nlm_distilled",
                )
            except Exception as exc:
                logger.warning("Failed to store research entry: %s", exc)

        logger.info("Stored %d/%d Q&A pairs in Nexus for topic '%s'", stored, len(pairs), topic)
        return stored

    # v1.57.0 [2026-03-26] — Prefer structured output for Q&A distillation
    # CONNECTS: engine.integrations.aistudio_client.generate_structured, engine.nexus.schemas
    # CALLED BY: distill_topic(), distill_from_entries() when processing raw NLM text
    def _parse_qa_response(self, text: str) -> List[Dict]:
        """Parse Q&A pairs from NLM response, preferring Gemini structured output.

        Tries Gemini structured output first for guaranteed valid JSON,
        then falls back to the legacy Q:/A: line-pair parsing.

        Args:
            text: Raw NLM response text.

        Returns:
            List of dicts with at least 'question' and 'answer' keys.
        """
        try:
            from engine.integrations.aistudio_client import generate_structured
            from engine.nexus.schemas import QA_BATCH_SCHEMA

            pairs = generate_structured(
                f"Extract Q&A pairs from this text. Return ONLY the pairs:\n\n{text[:5000]}",
                QA_BATCH_SCHEMA,
            )
            if pairs and isinstance(pairs, list):
                normalized = []
                for p in pairs:
                    if isinstance(p, dict) and p.get("question") and p.get("answer"):
                        normalized.append({
                            "question": str(p["question"]).strip(),
                            "answer": str(p["answer"]).strip(),
                        })
                if normalized:
                    logger.info(
                        "[NLMQADistiller] Extracted %d Q&A via structured output (operation=parse_qa)",
                        len(normalized),
                    )
                    return normalized
        except Exception as exc:
            logger.debug(
                "[NLMQADistiller] Structured extraction failed, using legacy (operation=parse_qa): %s",
                exc,
            )

        return self._parse_qa_legacy(text)

    # v1.57.0 [2026-03-26] — Legacy Q&A parsing (regex / line-pair based)
    def _parse_qa_legacy(self, text: str) -> List[Dict]:
        """Parse Q&A pairs from text using Q:/A: line-pair format.

        This is the original parsing logic, preserved as a fallback for
        when Gemini structured output is unavailable.

        Args:
            text: Raw NLM or LLM response text containing Q:/A: pairs.

        Returns:
            List of dicts with 'question' and 'answer' keys.
        """
        pairs: List[Dict] = []
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith("Q:") or line.startswith("**Q:"):
                question = line.lstrip("*").lstrip("Q:").strip().rstrip("*").strip()
                answer_lines: List[str] = []
                i += 1
                while i < len(lines):
                    aline = lines[i].strip()
                    if aline.startswith("A:") or aline.startswith("**A:"):
                        answer_lines.append(
                            aline.lstrip("*").lstrip("A:").strip().rstrip("*").strip()
                        )
                        i += 1
                        while i < len(lines):
                            nline = lines[i].strip()
                            if nline.startswith("Q:") or nline.startswith("**Q:") or not nline:
                                break
                            answer_lines.append(nline)
                            i += 1
                        break
                    i += 1
                answer = " ".join(answer_lines).strip()
                if question and answer:
                    pairs.append({"question": question, "answer": answer})
            else:
                i += 1

        return pairs

    def _store_pairs_direct(self, pairs: List[Dict[str, Any]]) -> int:
        """Fallback: write Q&A pairs directly to SQLite if Nexus is offline."""
        import sqlite3

        db_paths = [
            Path(r"C:\Files\Nexus\data\nexus.db"),
            _PROJECT_ROOT / "data" / "nexus.db",
        ]
        db_path = next((p for p in db_paths if p.exists()), None)
        if not db_path:
            logger.error("No Nexus database found for direct storage")
            return 0

        stored = 0
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            for pair in pairs:
                q = pair.get("question", "")
                a = pair.get("answer", "")
                if not q or not a:
                    continue
                cur.execute(
                    "INSERT OR IGNORE INTO qa_pairs (question, answer, category, created_at) "
                    "VALUES (?, ?, ?, datetime('now'))",
                    (q, a, "nlm_distilled"),
                )
                stored += 1
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.error("Direct SQLite storage failed: %s", exc)

        return stored


# ── QA Generation Instructions ─────────────────────────────────────────────
#
# Instructions for small local models on HOW to generate QA pairs.
# These are used by the training flywheel and agent tasks.

QA_GENERATION_PROMPT = """You are generating question-answer pairs for a knowledge base.

Given the following knowledge entry:

TITLE: {title}
CONTENT: {content}

Generate {count} question-answer pairs that:
1. Cover the most important concepts in the content
2. Are clear and specific (not vague)
3. Have complete, accurate answers based solely on the content
4. Range from basic understanding to nuanced implementation details

Format each pair as:
Q: [question]
A: [answer]

Generate exactly {count} pairs. Be concise but complete in answers."""


QUESTION_DESIGN_GUIDE = """
# How to Design Effective NLM Questions

## Principles

1. **Be specific** — "How does the InterceptorPipeline process requests?" not "How does it work?"
2. **Request concrete examples** — "Show the code pattern for registering a skill"
3. **Ask for comparisons** — "When should I use approach A vs approach B?"
4. **Ask about failure modes** — "What goes wrong when X happens?"
5. **Ask for criteria** — "What makes a good skill description for LLM consumption?"

## Question Types

### Understanding questions (start here)
- "What is X and what problem does it solve?"
- "Describe the main components of X and how they interact"
- "What is the lifecycle of X?"

### Implementation questions (most useful)
- "What is the exact code pattern to implement X?"
- "What are the required vs optional parameters for X?"
- "What are the common mistakes when implementing X?"

### Decision questions (high value)
- "When should I use X vs Y?"
- "What are the tradeoffs of approach X?"
- "What criteria determine the right choice?"

### Quality questions (build confidence)
- "What makes a high-quality implementation of X?"
- "How should X be tested?"
- "What metrics indicate X is working correctly?"

## Batch Design

Design question sets that build on each other:
1. Start with "what is" and "how does it work"
2. Move to "how do I implement"
3. Then "when should I use" and "what are tradeoffs"
4. Finally "how do I test" and "what can go wrong"

Group 5 related questions per batch for efficient NLM calls.
Ask all 5 in a single request. Store all 5 answers in Nexus.
"""


# ── CLI ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
    )

    parser = argparse.ArgumentParser(description="NLM QA Distiller — Generate Nexus Q&A pairs")
    parser.add_argument("--notebook", help="NotebookLM notebook ID to query")
    parser.add_argument("--topic", default="cosysim_architecture", help="Topic/template key")
    parser.add_argument("--questions", type=int, default=20, help="Number of questions")
    parser.add_argument("--templates", action="store_true", help="List available templates")
    parser.add_argument("--bulk", action="store_true", help="Distill all templates")
    parser.add_argument("--proxy", default="", help="NLM proxy URL")
    args = parser.parse_args()

    if args.templates:
        print("Available templates:")
        for key, batches in QUESTION_TEMPLATES.items():
            total = sum(len(b) for b in batches)
            print(f"  {key}: {total} questions across {len(batches)} batches")
        sys.exit(0)

    distiller = NLMQADistiller(proxy_url=args.proxy)

    if not args.notebook:
        # Try to get first available notebook
        notebooks = distiller._proxy_request("GET", "/notebooks")
        if notebooks and notebooks.get("notebooks"):
            args.notebook = notebooks["notebooks"][0]["id"]
            print(f"Using notebook: {args.notebook}")
        else:
            print("ERROR: No notebook ID provided and no notebooks found.")
            print("  Provide: --notebook <uuid>")
            print("  Or check: POST http://localhost:8800/cookies/import")
            sys.exit(1)

    if args.bulk:
        results = distiller.bulk_distill(args.notebook)
        total = sum(results.values())
        print(f"\nBulk distillation complete: {total} Q&A pairs")
        for key, count in results.items():
            print(f"  {key}: {count} pairs")
    else:
        pairs = distiller.distill_topic(
            notebook_id=args.notebook,
            topic=args.topic,
            num_questions=args.questions,
        )
        print(f"\nDistilled {len(pairs)} Q&A pairs for topic: {args.topic}")
        for i, p in enumerate(pairs[:3], 1):
            print(f"\n--- Pair {i} ---")
            print(f"Q: {p['question']}")
            print(f"A: {p['answer'][:300]}...")
