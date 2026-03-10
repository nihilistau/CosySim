"""Consumer Briefing — the living query taxonomy for the Nexus Q&A cache.

This module defines WHO queries the Nexus cache and HOW they phrase queries.
It is the single source of truth for:

  1. The Consumer Briefing document — natural-language description of all
     consumer classes and their query patterns.  Stored in Nexus as a
     governance document; editable without code changes.

  2. All Gemini prompts for the NLM cache pipeline — generation (CSV mode,
     code-generation mode), evaluation (ESSENTIAL/USEFUL/SKIP), and gap
     analysis.

The Consumer Briefing is loaded from Nexus at runtime if an entry exists with
category="governance" and a title containing "Consumer Briefing".  Otherwise
the built-in default is used.

Usage::

    from engine.nexus.consumer_briefing import get_consumer_briefing
    cb = get_consumer_briefing()

    # Build and store in Nexus
    client = get_nexus_client()
    cb.save_to_nexus(client)

    # Generate Gemini prompts
    csv_prompt = cb.build_csv_prompt(consumer_focus="agent-task")
    code_prompt = cb.build_code_gen_prompt()
    eval_prompt = cb.build_evaluation_prompt(pairs_csv)
    gap_prompt  = cb.build_gap_prompt(existing_questions)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ──── Consumer Classes ────────────────────────────────────────────────────────

CONSUMER_CLASSES: List[str] = [
    "copilot-startup",
    "agent-task",
    "governance",
    "developer",
    "news-retrieval",
]

# ──── Output Schema ───────────────────────────────────────────────────────────

# The required CSV header for all Gemini-generated Q&A output
CSV_HEADER = "Question,Answer,Consumer,Priority,Category,Reasoning"

# Column enumerations for validation
CONSUMER_ENUM = ["copilot", "agent", "governance", "developer", "news"]
CATEGORY_ENUM = [
    "architecture", "skills", "config", "testing",
    "nexus", "tools", "scenes", "general",
]
PRIORITY_RANGE = (1, 5)

# ──── Built-in Briefing Document ─────────────────────────────────────────────

_BUILT_IN_BRIEFING = """# CosySim Nexus Q&A Cache — Consumer Briefing

This document describes who queries the Nexus Q&A cache and how they phrase
their queries.  It is used to guide Gemini 3.0 when generating and evaluating
Q&A pairs.  A pair is ESSENTIAL if it directly serves a consumer class below.

---

## Consumer Class 1: Copilot CLI (startup and planning)

Copilot CLI loads on startup and immediately queries Nexus to orient itself.
It also queries before writing any plan or making any code change.

**Typical query patterns:**
- "What is the current version of CosySim?"
- "What are the pending todos in the plan?"
- "What conventions apply to Python files in this project?"
- "What port does the [scene name] scene run on?"
- "What MCP tools are available for NLM operations?"
- "What is the Nexus Q&A cache hit rate?"
- "How do I run the test suite?"
- "What was the last breaking change in the CHANGELOG?"
- "How do I create a new scene from scratch?"
- "What is the Co-authored-by trailer for git commits?"
- "What config key controls [specific setting]?"
- "What are the rules for the coding scope?"
- "How many tests are in the test suite?"
- "What scheduler tasks are registered?"
- "What is the NLM batchexecute proxy URL?"
- "Where is the Nexus KMS running?"
- "What models does LMStudio have loaded?"
- "What is the system architecture overview?"

---

## Consumer Class 2: Local LMStudio Agents (task execution)

Local agents (small models, e.g. Qwen 0.6B) pick up task tickets from the
scheduler and execute them.  They query Nexus for exact implementation details
before writing any code.

**Typical query patterns:**
- "How do I implement the @skill decorator?"
- "What is the exact signature for get_config()?"
- "How do I register a new MCP tool in devtools_server.py?"
- "What config key controls NLM notebook creation?"
- "How do I write a pytest test for a scene?"
- "What imports are needed for a skill pack file?"
- "How does mutable state sync to the MCP tree?"
- "What does the interceptor pipeline do to agent responses?"
- "What is the singleton pattern used in CosySim?"
- "How do I add a new scheduler task?"
- "What is the correct way to log in Python files?"
- "How do I mock LMStudio in a test?"
- "What is the BaseScene class and which methods must I override?"
- "How do I access the Nexus client from Python code?"
- "What is the NLM hybrid router and when does it use each backend?"
- "What is the format of an LMStudio v1 API chat request?"
- "How does the 4-tier query router work?"
- "What is the batchexecute proxy and which operations use it?"

---

## Consumer Class 3: Governance Engine (rule enforcement)

The governance engine (AgentGovernor, consensus_gate hook) queries Nexus for
rules and constraints before allowing operations on core files.

**Typical query patterns:**
- "What rules apply to the coding scope?"
- "Is print() allowed in Python files?"
- "What is required in a git commit message?"
- "What tests must pass before a commit is allowed?"
- "What naming convention applies to MCP tool functions?"
- "Are relative imports allowed?"
- "What must every scene class inherit from?"
- "What is the approved logger pattern?"
- "What config keys are hardcoded and therefore prohibited?"
- "What is the enforcement policy for core architecture files?"
- "What are the governance rules for the nexus scope?"

---

## Consumer Class 4: Developer / User (exploratory)

The human developer (and Copilot in exploratory mode) asks architectural and
diagnostic questions when debugging or planning.

**Typical query patterns:**
- "How does the NLM hybrid router decide which backend to use?"
- "Why does the QA expander skip entries with content type 'qa'?"
- "Where is the Nexus client singleton created?"
- "What changed in [version number]?"
- "How does the 4-tier query router escalate through tiers?"
- "What is the difference between flashcard and quiz NLM generation?"
- "How does the source pyramid shape NLM tile output?"
- "What is the session store and where is it located?"
- "How does TrainingCapture feed into the training flywheel?"
- "What is the difference between store=true and store=false in LMStudio?"
- "How does stateful conversation work with previous_response_id?"
- "Why does the Orpheus TTS use LMStudio API rather than native?"
- "What VRAM does the RTX 2060 have and how does CosySim budget it?"
- "How do I add a new knowledge theme to the history miner?"
- "What is the CycleResult dataclass and what does each field mean?"
- "How does the consumer briefing get stored and loaded from Nexus?"

---

## Consumer Class 5: News and Knowledge Retrieval (runtime context injection)

Scheduled tasks and the news pipeline query Nexus to get current system state,
news digests, and runtime context for injection into agent prompts.

**Typical query patterns:**
- "What AI news was ingested today?"
- "What is the current NLM router hit rate?"
- "What tasks are scheduled to run in the next hour?"
- "What experiments are currently active in the experiment tracker?"
- "What is the current Nexus health status?"
- "What was the result of the last test-monitor run?"
- "What is the latest benchmark result for [model name]?"
- "What knowledge was added to Nexus this week?"

---

## Priority Rubric

Score each Q&A pair 1–5:

| Score | Meaning | Example |
|-------|---------|---------|
| 5 | Queried daily by Copilot or agents.  Saves significant compute. | "How do I run the test suite?" |
| 4 | Queried frequently during normal development work. | "What is the @skill decorator signature?" |
| 3 | Queried occasionally; useful reference. | "How does the interceptor pipeline work?" |
| 2 | Queried rarely; nice to have cached. | "What changed in v0.57b?" |
| 1 | Almost never queried; low cache value. | Very specific one-time question |

---

## What to AVOID

Do NOT generate Q&A pairs that are:
- Generic (could apply to any Python project, not specifically CosySim)
- Too vague ("What is Nexus?" without specifying CosySim's Nexus)
- Already well-answered by Python/Flask/LMStudio public documentation
- Duplicating pairs already in the cache
- Questions that no consumer would realistically ask

Focus on questions that are:
- Specific to CosySim's architecture, patterns, and conventions
- About exact API signatures, config keys, port numbers, file paths
- About integration points between systems (NLM, LMStudio, Nexus, TTS)
- About development workflow (tests, commits, skills, scenes)
"""

# ──── Consumer Briefing ───────────────────────────────────────────────────────

class ConsumerBriefing:
    """Living query taxonomy and all Gemini prompts for the cache pipeline.

    The briefing document and prompts can be stored in and loaded from Nexus,
    making them editable without code changes.

    Args:
        nexus_category: Nexus category to use when storing/loading briefing.
        nexus_title_prefix: Title prefix to identify the briefing in Nexus.
    """

    # Nexus identifiers
    NEXUS_CATEGORY = "governance"
    NEXUS_TITLE_PREFIX = "QA Consumer Briefing"

    def __init__(
        self,
        nexus_category: str = NEXUS_CATEGORY,
        nexus_title_prefix: str = NEXUS_TITLE_PREFIX,
    ) -> None:
        self._nexus_category = nexus_category
        self._nexus_title_prefix = nexus_title_prefix
        self._cached_briefing: Optional[str] = None

    # ── Briefing Document ───────────────────────────────────────────────────

    def build_briefing(self, from_nexus: bool = False, client: Any = None) -> str:
        """Return the Consumer Briefing document.

        Args:
            from_nexus: If True, attempt to load from Nexus first.
            client: NexusClient instance (required if from_nexus=True).

        Returns:
            The Consumer Briefing as a markdown string.
        """
        if from_nexus and client:
            loaded = self.load_from_nexus(client)
            if loaded:
                self._cached_briefing = loaded
                return loaded
        if self._cached_briefing:
            return self._cached_briefing
        return _BUILT_IN_BRIEFING

    def save_to_nexus(self, client: Any) -> str:
        """Store the Consumer Briefing in Nexus as a governance document.

        Args:
            client: NexusClient instance.

        Returns:
            The Nexus entry ID.
        """
        title = f"{self._nexus_title_prefix} — CosySim QA Cache"
        try:
            result = client.add_entry(
                title=title,
                content=_BUILT_IN_BRIEFING,
                content_type="document",
                category=self._nexus_category,
                tags=["qa-cache", "consumer-briefing", "governance"],
            )
            entry_id = result.get("id", result) if isinstance(result, dict) else str(result)
            logger.info("Consumer Briefing stored in Nexus: %s", entry_id)
            return entry_id
        except Exception as exc:
            logger.error("Failed to save Consumer Briefing to Nexus: %s", exc)
            return ""

    def load_from_nexus(self, client: Any) -> Optional[str]:
        """Load the Consumer Briefing from Nexus if present.

        Args:
            client: NexusClient instance.

        Returns:
            The briefing text, or None if not found.
        """
        try:
            results = client.search(
                f"{self._nexus_title_prefix}",
                category=self._nexus_category,
                limit=1,
            )
            if isinstance(results, list) and results:
                entry = results[0]
                content = entry.get("content", "") if isinstance(entry, dict) else ""
                if content and len(content) > 100:
                    logger.info("Consumer Briefing loaded from Nexus")
                    return content
        except Exception as exc:
            logger.warning("Failed to load Consumer Briefing from Nexus: %s", exc)
        return None

    # ── Gemini Prompts ──────────────────────────────────────────────────────

    def build_csv_prompt(self, consumer_focus: str = "all", count: int = 100) -> str:
        """Build the report prompt for CSV-format Q&A generation.

        The prompt instructs Gemini to generate Q&A pairs as a CSV table with
        the required schema, focused on a specific consumer class or all.

        Args:
            consumer_focus: "all" or one of CONSUMER_CLASSES.
            count: Number of pairs to generate.

        Returns:
            The full report prompt string.
        """
        if consumer_focus == "all":
            focus_instruction = (
                "Distribute pairs across ALL five consumer classes:\n"
                "  - copilot (25%): Copilot CLI startup and planning queries\n"
                "  - agent (30%): Local LMStudio agent task-execution queries\n"
                "  - governance (15%): Rule enforcement and policy queries\n"
                "  - developer (20%): Exploratory architecture and debugging queries\n"
                "  - news (10%): Runtime context and system state queries\n"
            )
        else:
            focus_instruction = (
                f"Focus ENTIRELY on the '{consumer_focus}' consumer class as described "
                "in the Consumer Briefing document (included as a source).\n"
            )

        return f"""You are generating Q&A pairs for the Nexus knowledge cache of CosySim,
an AI simulation framework.  Your output will be parsed by a Python script.

TASK: Generate exactly {count} high-value Q&A pairs from the attached CosySim
documentation and development history sources.

{focus_instruction}
REQUIREMENTS:
1. Each pair must be answerable from the attached sources.
2. Questions must be phrased exactly as a consumer would type them.
3. Answers must be complete, specific, and actionable (not "see docs").
4. Prioritise: exact API signatures, config keys, port numbers, file paths,
   import statements, conventions, workflow steps.
5. Avoid generic questions that could apply to any Python framework.
6. Do NOT duplicate questions from "_04_EXISTING_COVERAGE" source if present.

OUTPUT FORMAT: Respond with ONLY valid CSV.  First line is the header.
No preamble, no commentary, no code fences.

{CSV_HEADER}

Start immediately with the header row on line 1.
Quote fields that contain commas using double-quotes.
Priority column: integer 1-5 (5=queried daily, 1=rarely needed).
Consumer column: one of {CONSUMER_ENUM}.
Category column: one of {CATEGORY_ENUM}.
Reasoning column: one sentence explaining cache value (no commas — use semicolons).
"""

    def build_code_gen_prompt(self, count: int = 100) -> str:
        """Build the report prompt for Python code-generation mode.

        Asks Gemini to write a function ``build_qa_pairs() -> list[dict]``
        that returns a list of dicts.  We then ``exec()`` this in a sandboxed
        namespace for perfectly structured, parseable output.

        Args:
            count: Number of pairs to generate.

        Returns:
            The full report prompt string.
        """
        return f"""You are generating a Python dataset for the Nexus knowledge cache
of CosySim, an AI simulation framework.

TASK: Write a Python function that returns exactly {count} Q&A pairs as a list
of dicts, sourced ENTIRELY from the attached CosySim documentation.

REQUIRED FUNCTION SIGNATURE:
def build_qa_pairs() -> list:
    \"\"\"Returns {count} CosySim Q&A pairs for the Nexus knowledge cache.\"\"\"
    return [
        {{
            "q": "exact question as a consumer would type it",
            "a": "complete, specific, actionable answer",
            "consumer": "one of: copilot | agent | governance | developer | news",
            "priority": 4,  # int 1-5; 5=queried daily, 1=rarely
            "category": "one of: architecture | skills | config | testing | nexus | tools | scenes | general",
        }},
        # ... {count} total entries
    ]

RULES:
- Return ONLY the function definition.  No imports, no other code.
- Every answer must be answerable from the attached sources.
- Include exact values: port numbers, config keys, file paths, import paths.
- Distribute across consumer classes: copilot 25% / agent 30% / governance 15%
  / developer 20% / news 10%.
- Avoid any question that could apply to a generic Python project.
- Do NOT include questions from the "_04_EXISTING_COVERAGE" source.
"""

    def build_evaluation_prompt(self, pairs_csv: str) -> str:
        """Build the evaluation prompt for NLM self-evaluation.

        Asks Gemini to rate each candidate pair as ESSENTIAL, USEFUL, or SKIP.

        Args:
            pairs_csv: The CSV string of candidate pairs (with header).

        Returns:
            The full evaluation prompt string.
        """
        return f"""You are evaluating Q&A pairs for the Nexus knowledge cache of CosySim.

CONSUMER BRIEFING SUMMARY:
Five consumer classes query this cache:
1. copilot — Copilot CLI on startup; needs version, todos, conventions, ports
2. agent — Local LMStudio agents executing tasks; need exact API, config, patterns
3. governance — Rule enforcement; needs coding rules, commit requirements, naming
4. developer — Human developer; needs architecture, debugging, design explanations
5. news — Scheduled tasks; needs system state, metrics, recent activity

TASK: Rate each Q&A pair below as ESSENTIAL, USEFUL, or SKIP.

Criteria:
- ESSENTIAL: Queried frequently; saves real compute; specific to CosySim
- USEFUL: Queried occasionally; good reference; reasonably specific
- SKIP: Too generic; duplicates public docs; unlikely to be queried; too vague

OUTPUT FORMAT: Respond with ONLY valid JSON array.  No preamble.
Schema: [{{"q": "...", "a": "...", "rating": "ESSENTIAL|USEFUL|SKIP", "reason": "one sentence"}}]

PAIRS TO EVALUATE:
{pairs_csv}
"""

    def build_gap_prompt(self, covered_questions: List[str]) -> str:
        """Build the gap analysis prompt.

        Asks Gemini to identify query patterns that are NOT yet covered by the
        existing Q&A cache.

        Args:
            covered_questions: List of questions already in the Nexus cache.

        Returns:
            The full gap analysis prompt string.
        """
        covered_sample = "\n".join(f"- {q}" for q in covered_questions[:200])
        if len(covered_questions) > 200:
            covered_sample += f"\n... and {len(covered_questions) - 200} more"

        return f"""You are analysing the Q&A cache coverage for the Nexus knowledge base
of CosySim, an AI simulation framework.

TASK: Based on the Consumer Briefing (attached as a source) and the list of
questions already cached below, identify what is MISSING.

Return a JSON array of missing query patterns — questions that the five consumer
classes would realistically ask but are NOT yet answered in the cache.

Rules:
- Focus on the most valuable gaps (high consumer priority)
- Group similar gaps into a single representative question
- Be specific — not "more architecture questions" but the exact question
- Return exactly 20–30 gap questions

OUTPUT FORMAT: Respond with ONLY a JSON array of strings.
Example: ["What is the exact signature for get_config()?", ...]

ALREADY COVERED QUESTIONS:
{covered_sample}
"""

    def build_priority_rubric(self) -> str:
        """Return the priority rubric as a source document."""
        return """# Q&A Pair Priority Rubric — CosySim Nexus Cache

Use this rubric when scoring Q&A pairs for the Nexus knowledge cache.

## Priority 5 — Cache Critical
Queried almost every session by Copilot CLI or local agents.
Saves significant compute every day.
Examples:
- "How do I run the test suite?"
- "What is the @skill decorator signature?"
- "What port does the penthouse scene run on?"
- "What is the current CosySim version?"

## Priority 4 — Frequently Queried
Queried several times per week during normal development.
Examples:
- "How do I register a new MCP tool?"
- "What is the BaseScene class structure?"
- "How does stateful LMStudio conversation work?"

## Priority 3 — Useful Reference
Queried occasionally; good to have cached.
Examples:
- "How does the interceptor pipeline process agent responses?"
- "What is the relationship between MCPFramework and MCPSceneNode?"

## Priority 2 — Rare but Valid
Queried infrequently; nice to have but not critical.
Examples:
- "What changed in v0.57b?"
- "How does the Orpheus CUDA build work?"

## Priority 1 — Low Cache Value
Queried almost never; not worth caching unless very easy to answer.

## What lowers priority:
- Generic (applies to any Python project)
- Already in public Flask/pytest/LMStudio documentation
- Too specific to one debugging session
- Answers that change frequently (prefer config keys over values)
"""

    def get_schema_doc(self) -> str:
        """Return the output schema document (pyramid layer 1)."""
        return f"""# Q&A Pair Output Schema — CosySim Nexus Cache

All generated Q&A pairs must follow this schema exactly.

## CSV Format
Header: {CSV_HEADER}

Column definitions:
- Question: The exact question a consumer would type. No trailing punctuation needed.
- Answer: Complete, specific, actionable answer. No "see documentation" — give the actual answer.
- Consumer: Who would ask this. One of: {", ".join(CONSUMER_ENUM)}
- Priority: Integer 1-5 (see Priority Rubric source). 5 = queried daily.
- Category: System area. One of: {", ".join(CATEGORY_ENUM)}
- Reasoning: One sentence explaining why this pair is cache-valuable. Use semicolons not commas.

## Python Dict Format (code-generation mode)
{{
    "q": str,        # Question
    "a": str,        # Answer
    "consumer": str, # One of: {CONSUMER_ENUM}
    "priority": int, # 1-5
    "category": str, # One of: {CATEGORY_ENUM}
}}

## Quality Standards
- Answers must be specific to CosySim (not generic Python/Flask answers)
- Include exact values: port 5555, config key "lmstudio.port", path "engine/nexus/"
- Questions should use natural phrasing, not keyword soup
- One question = one clear, answerable thing
"""

    def get_good_examples(self) -> str:
        """Return the good examples document (pyramid layer 2)."""
        return """# Good Q&A Pair Examples — CosySim Nexus Cache

These examples show the quality bar for Q&A pairs in the cache.
Aim for this level of specificity and usefulness.

---

Q: How do I run the full CosySim test suite?
A: Run: python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py
Consumer: copilot | Priority: 5 | Category: testing

---

Q: What is the @skill decorator signature for a scene skill pack?
A: @skill(pack="scene_name", description="LLM-facing description", category="game", cooldown=5.0, cost=1.0, tags=["tag"], prerequisites=["other_skill"]) — then def my_skill(param: str) -> str:
Consumer: agent | Priority: 5 | Category: skills

---

Q: What port does the Nexus KMS server run on?
A: Port 8700. Health check: GET http://localhost:8700/api/health
Consumer: copilot | Priority: 5 | Category: nexus

---

Q: What config key controls the LMStudio host and port?
A: lmstudio.host (default: localhost) and lmstudio.port (default: 1234). Access: get_config().get("lmstudio.host", "localhost")
Consumer: agent | Priority: 4 | Category: config

---

Q: How does the NLM hybrid router decide between Node bridge and batchexecute proxy?
A: Chat/Q&A → Node bridge (browser-based). Source add/rename/delete → batchexecute proxy (fast HTTP). Studio tiles (flashcards, quiz, report) → Node bridge. If primary fails, tries the other backend automatically.
Consumer: developer | Priority: 3 | Category: architecture

---

Q: What is required in every git commit message?
A: Must use conventional commits (feat:, fix:, docs:, test:, chore:, refactor:) and include the trailer: Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
Consumer: governance | Priority: 4 | Category: general

---

Q: How do I mock LMStudio calls in pytest tests?
A: Patch at the client boundary: @patch("engine.lmstudio.lms_client.LMStudioClient.chat") — Never make real HTTP calls in tests. Use AsyncMock for async methods. Return a dict matching the LMStudio v1 response format.
Consumer: agent | Priority: 4 | Category: testing

---

Q: What is the singleton pattern used throughout CosySim?
A: Module-level _instance + threading.Lock: _instance = None; _lock = Lock(). get_X() checks if None, acquires lock, double-checks, creates. All singletons: get_framework(), get_nexus_client(), get_nlm_hybrid(), get_tts_manager(), etc.
Consumer: agent | Priority: 4 | Category: architecture
"""

    def get_bad_examples(self) -> str:
        """Return the bad examples document (pyramid layer 3)."""
        return """# Bad Q&A Pair Examples — DO NOT Generate These

These examples show what to AVOID when generating Q&A pairs.
These would receive a SKIP rating and waste cache space.

---

BAD: Q: What is Python?
Why: Generic — not CosySim-specific at all. Any Python docs answer this.

BAD: Q: How do I use Flask?
Why: Generic — public Flask documentation answers this. Not CosySim-specific.

BAD: Q: What does Nexus do?
Why: Too vague — doesn't specify what aspect of Nexus or who is asking.
Better: "How do I search the Nexus Q&A cache from Python code?"

BAD: Q: How does CosySim work?
Why: Far too broad — no specific consumer would search this exact phrase.
Better: Ask about a specific subsystem.

BAD: Q: What is the latest model?
Why: Answer changes frequently — not suitable for caching.

BAD: Q: Where are the tests?
Why: Too simple — "tests/" directory is obvious. Not cache-worthy.
Better: "What test fixtures are available in conftest.py?"

BAD: Q: How do I log things?
Why: Generic Python question. Every Python project uses logging.
Better: "What logger pattern is required in CosySim Python files?"

BAD: Q: What is config?
Why: Far too vague. Not a query any consumer would actually type.
Better: "What config key controls the NLM notebook rotation frequency?"
"""


# ──── Singleton ───────────────────────────────────────────────────────────────

_briefing_instance: Optional[ConsumerBriefing] = None
_briefing_lock = threading.Lock()


def get_consumer_briefing() -> ConsumerBriefing:
    """Get the singleton ConsumerBriefing instance."""
    global _briefing_instance
    if _briefing_instance is None:
        with _briefing_lock:
            if _briefing_instance is None:
                _briefing_instance = ConsumerBriefing()
    return _briefing_instance
