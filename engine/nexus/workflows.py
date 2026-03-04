"""
workflows.py — Structured workflows for Nexus knowledge management.

Provides three core workflows:
1. ContentWorkflow — Generate pre-built dialog/descriptions for characters
2. ResearchWorkflow — Structured research pipeline with Nexus storage
3. NotebookWorkflow — NotebookLM integration for deep knowledge generation

Usage:
    from engine.nexus.workflows import ContentWorkflow, ResearchWorkflow

    # Generate character content
    cw = ContentWorkflow()
    cw.generate_greetings("lola", personality_tags=["flirty", "confident"])
    cw.generate_scene_descriptions("bedroom")

    # Research a topic
    rw = ResearchWorkflow()
    result = rw.research("How should we implement voice cloning?")
    rw.store_findings(result)
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from engine.nexus.nexus_namespaces import enforce_namespace

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
#  Content Generation Workflow
# ══════════════════════════════════════════════════════════════════════

class ContentWorkflow:
    """Generate pre-built content for CosySim characters and scenes.

    Creates templated dialog, descriptions, and responses that can be
    used to replace some LLM calls with cached, pre-built content.
    Stores everything in Nexus under the 'content' namespace.

    Args:
        nexus_url: Nexus API base URL.
    """

    def __init__(self, nexus_url: str = "http://127.0.0.1:8700") -> None:
        self._url = nexus_url

    def _store(self, title: str, content: str, tags: List[str]) -> Optional[str]:
        """Store content in Nexus under the content namespace."""
        from engine.nexus.client import get_nexus_client
        entry = enforce_namespace(
            title=title, content=content,
            content_type="snippet", category="dialog",
            tags=tags, namespace="content",
        )
        try:
            return get_nexus_client().add_entry(
                title=entry["title"],
                content=entry["content"],
                content_type="snippet",
                category="dialog",
                tags=entry["tags"],
                created_by="content_workflow",
            )
        except Exception:
            return None

    def generate_greetings(
        self,
        character_id: str,
        personality_tags: Optional[List[str]] = None,
    ) -> List[str]:
        """Generate a set of greeting templates for a character.

        Args:
            character_id: Character ID (e.g., 'lola').
            personality_tags: Personality descriptors.

        Returns:
            List of entry IDs created.
        """
        p_tags = personality_tags or ["friendly"]
        ids: List[str] = []

        # Mood-based greetings
        moods = {
            "happy": [
                f'*beams brightly* [ACTION:waves enthusiastically] "Hey there! I was just thinking about you!" [MOOD:happy] [STAT:engagement+2]',
                f'*bounces excitedly* [ACTION:clasps hands together] "Oh, you\'re back! I have so much to tell you!" [MOOD:excited]',
            ],
            "flirty": [
                f'*leans against the doorframe* [ACTION:plays with hair] "Well, look who decided to show up..." [MOOD:playful] [STAT:arousal+2]',
                f'*gives a sly smile* [ACTION:bites lip] "Mmm, I was hoping you\'d come by." [MOOD:flirtatious] [STAT:arousal+3]',
            ],
            "shy": [
                f'*fidgets nervously* [ACTION:looks away] "Oh... h-hi. I didn\'t expect to see you." [MOOD:nervous] [STAT:trust+1]',
                f'*peeks out from behind a book* [ACTION:blushes] "Um... welcome back." [MOOD:bashful]',
            ],
            "tired": [
                f'*yawns softly* [ACTION:stretches] "Hey... sorry, long day." [MOOD:tired] [STAT:energy-2]',
                f'*rubs eyes* [ACTION:curls up on couch] "Come sit with me? I could use the company." [MOOD:mellow]',
            ],
            "confident": [
                f'*strikes a pose* [ACTION:flips hair] "About time! The party doesn\'t start without me." [MOOD:confident] [STAT:engagement+3]',
                f'*smirks knowingly* [ACTION:leans forward] "I knew you couldn\'t resist." [MOOD:self-assured]',
            ],
        }

        for mood, greetings_list in moods.items():
            content = json.dumps({
                "character": character_id,
                "mood": mood,
                "greetings": greetings_list,
                "personality": p_tags,
            }, indent=2)
            entry_id = self._store(
                f"Greetings [{character_id}] mood:{mood}",
                content,
                ["content", f"character:{character_id}", f"mood:{mood}", "greetings"] + p_tags,
            )
            if entry_id:
                ids.append(entry_id)

        logger.info("ContentWorkflow: generated %d greeting sets for %s", len(ids), character_id)
        return ids

    def generate_scene_descriptions(self, scene_id: str) -> List[str]:
        """Generate atmospheric scene descriptions.

        Args:
            scene_id: Scene identifier.

        Returns:
            List of entry IDs created.
        """
        ids: List[str] = []

        times_of_day = {
            "morning": "Soft golden light filters through the curtains. The room feels fresh and peaceful, with the faint scent of coffee in the air.",
            "afternoon": "Warm sunlight fills the space. The atmosphere is relaxed and comfortable, with a lazy, unhurried quality to the air.",
            "evening": "The room is bathed in warm amber light. Shadows grow longer, and the mood shifts to something more intimate and quiet.",
            "night": "Dim lighting casts soft shadows across the room. The night wraps everything in a cocoon of privacy and possibility.",
            "late_night": "Only the faintest glow remains — perhaps candles or a bedside lamp. The world outside is silent. This space feels like a secret.",
        }

        for tod, description in times_of_day.items():
            content = json.dumps({
                "scene": scene_id,
                "time_of_day": tod,
                "description": description,
                "atmosphere_tags": ["intimate", "cozy"] if "night" in tod else ["warm", "relaxed"],
            }, indent=2)
            entry_id = self._store(
                f"Scene [{scene_id}] time:{tod}",
                content,
                ["content", f"scene:{scene_id}", f"time:{tod}", "atmosphere"],
            )
            if entry_id:
                ids.append(entry_id)

        return ids

    def generate_reactions(self, character_id: str) -> List[str]:
        """Generate emotional reaction templates.

        Args:
            character_id: Character identifier.

        Returns:
            List of entry IDs created.
        """
        ids: List[str] = []

        reactions = {
            "complimented": [
                '*cheeks flush pink* [ACTION:tucks hair behind ear] "That\'s... really sweet of you to say." [MOOD:flattered] [STAT:affection+4]',
                '*grins widely* [ACTION:does a little spin] "Aren\'t you just full of charm today?" [MOOD:delighted] [STAT:trust+2]',
            ],
            "teased": [
                '*gasps playfully* [ACTION:swats arm lightly] "Oh, you did NOT just say that!" [MOOD:amused] [STAT:arousal+2]',
                '*narrows eyes with a smirk* [ACTION:steps closer] "You\'re playing with fire, you know that?" [MOOD:mischievous]',
            ],
            "insulted": [
                '*expression falls* [ACTION:steps back] "That... actually hurt." [MOOD:wounded] [STAT:trust-5] [STAT:affection-3]',
                '*jaw tightens* [ACTION:crosses arms] "Wow. Okay then." [MOOD:cold] [STAT:trust-4]',
            ],
            "surprised": [
                '*eyes go wide* [ACTION:covers mouth] "Wait, WHAT?!" [MOOD:shocked] [STAT:engagement+5]',
                '*freezes mid-motion* [ACTION:blinks rapidly] "I... did not see that coming." [MOOD:stunned]',
            ],
        }

        for trigger, responses in reactions.items():
            content = json.dumps({
                "character": character_id,
                "trigger": trigger,
                "reactions": responses,
            }, indent=2)
            entry_id = self._store(
                f"Reactions [{character_id}] trigger:{trigger}",
                content,
                ["content", f"character:{character_id}", f"trigger:{trigger}", "reactions"],
            )
            if entry_id:
                ids.append(entry_id)

        return ids

    def lookup_content(
        self,
        character_id: str = "",
        content_type: str = "",
        mood: str = "",
    ) -> List[Dict[str, Any]]:
        """Look up pre-built content from Nexus.

        Args:
            character_id: Filter by character.
            content_type: Filter by type (greetings, reactions, etc).
            mood: Filter by mood.

        Returns:
            List of matching content entries.
        """
        from engine.nexus.client import get_nexus_client
        query_parts = ["content"]
        if character_id:
            query_parts.append(f"character:{character_id}")
        if content_type:
            query_parts.append(content_type)
        if mood:
            query_parts.append(f"mood:{mood}")

        try:
            return get_nexus_client().search(" ".join(query_parts), limit=20)
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)
        return []


# ══════════════════════════════════════════════════════════════════════
#  Research Workflow
# ══════════════════════════════════════════════════════════════════════

class ResearchWorkflow:
    """Structured research pipeline with Nexus storage.

    Pipeline: Question → Search Nexus → [Optional: NLM] → Distill → Store

    Args:
        nexus_url: Nexus API base URL.
    """

    def __init__(self, nexus_url: str = "http://127.0.0.1:8700") -> None:
        self._url = nexus_url

    def research(
        self,
        question: str,
        depth: str = "auto",
        store_result: bool = True,
    ) -> Dict[str, Any]:
        """Run the full research pipeline.

        Args:
            question: Research question.
            depth: Search depth ('shallow', 'auto', 'deep').
            store_result: Whether to store findings in Nexus.

        Returns:
            Research result dict.
        """
        result: Dict[str, Any] = {
            "question": question,
            "depth": depth,
            "sources": [],
            "answer": "",
            "stored": False,
        }

        # Step 1: Search existing knowledge
        from engine.nexus.client import get_nexus_client
        nx = get_nexus_client()

        # Check Q&A cache
        qa_result = nx.ask(question, depth="shallow")
        if qa_result and qa_result.get("answer"):
            result["answer"] = qa_result["answer"]
            result["sources"].append({"type": "qa_cache", "data": qa_result})
            if qa_result.get("confidence", 0) > 0.7:
                result["depth"] = "cache_hit"
                return result

        # Search knowledge entries
        search_results = nx.search(question, limit=10)
        if search_results:
            result["sources"].append({"type": "fts_search", "count": len(search_results)})
            # Synthesize from search results
            snippets = [
                e.content[:200] for e in search_results
                if e.content
            ]
            if snippets:
                result["answer"] = (
                    f"Based on {len(snippets)} knowledge entries:\n\n"
                    + "\n\n".join(f"- {s}" for s in snippets[:5])
                )

        # Step 2: Deep research via NLM (if available and needed)
        if depth == "deep" or (depth == "auto" and not result["answer"]):
            try:
                research_result = nx.research(question)
                if research_result and research_result.get("research_id"):
                    result["sources"].append({
                        "type": "nlm_research",
                        "research_id": research_result.get("research_id"),
                    })
                    if research_result.get("answer"):
                        result["answer"] = research_result["answer"]
            except Exception as exc:
                logger.debug("ResearchWorkflow: NLM unavailable: %s", exc)

        # Step 3: Store findings
        if store_result and result["answer"]:
            self.store_findings(result)
            result["stored"] = True

        return result

    def store_findings(self, result: Dict[str, Any]) -> Optional[str]:
        """Store research findings in Nexus.

        Args:
            result: Research result dict from research().

        Returns:
            Entry ID if stored.
        """
        from engine.nexus.client import get_nexus_client

        question = result.get("question", "")
        answer = result.get("answer", "")

        if not answer:
            return None

        entry = enforce_namespace(
            title=f"Research: {question[:80]}",
            content=answer,
            content_type="research",
            category="research",
            tags=["research", f"depth:{result.get('depth', 'auto')}"],
            namespace="research",
        )

        try:
            nx = get_nexus_client()
            entry_id = nx.add_entry(
                title=entry["title"],
                content=entry["content"],
                content_type="research",
                category="research",
                tags=entry["tags"],
                created_by="research_workflow",
            )
            if entry_id:
                # Also store as Q&A for future cache hits
                nx.add_qa(
                    question=question,
                    answer=answer,
                    category="research",
                    tags=["research", "auto-generated"],
                )
                return entry_id
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)
        return None


# ══════════════════════════════════════════════════════════════════════
#  NotebookLM Workflow
# ══════════════════════════════════════════════════════════════════════

class NotebookWorkflow:
    """Manage NotebookLM notebooks for deep knowledge generation.

    Creates project notebooks, generates Q&A from them,
    and stores everything in Nexus.

    Args:
        nexus_url: Nexus API base URL.
    """

    # Pre-defined notebook seeds for the project
    NOTEBOOK_SEEDS = {
        "cosysim-architecture": {
            "name": "CosySim Architecture Deep Dive",
            "description": "Complete architecture of CosySim: MCP framework, interceptor pipeline, state management, skill system, dialog system, agent governance",
            "topics": ["mcp", "interceptors", "state", "skills", "agents", "governance"],
            "sources": [
                "docs/ARCHITECTURE.md",
                "docs/MCP_FRAMEWORK.md",
                "docs/SKILLS.md",
                "docs/INTERCEPTORS.md",
            ],
        },
        "cosysim-scenes": {
            "name": "CosySim Scene Design Patterns",
            "description": "How scenes work in CosySim: BaseScene lifecycle, character management, game mechanics, Flask integration, Socket.IO events",
            "topics": ["scenes", "characters", "games", "flask", "socketio"],
            "sources": [
                "docs/SCENES.md",
                "docs/CHARACTERS.md",
                "docs/GAME_MECHANICS.md",
            ],
        },
        "nexus-knowledge-system": {
            "name": "Nexus Knowledge Management System",
            "description": "How Nexus KMS works: FTS5 search, Q&A pipeline, rules engine, NotebookLM integration, namespace separation, training data",
            "topics": ["nexus", "knowledge", "fts5", "rules", "research", "notebooklm"],
            "sources": [
                "docs/NEXUS_INTEGRATION.md",
                "engine/nexus/client.py",
                "engine/nexus/nexus_namespaces.py",
            ],
        },
    }

    def __init__(self, nexus_url: str = "http://127.0.0.1:8700") -> None:
        self._url = nexus_url

    def seed_notebook_knowledge(self, notebook_id: str = "all") -> Dict[str, Any]:
        """Seed notebook reference content into Nexus.

        Even if NotebookLM is offline, this creates the reference
        entries in Nexus that can be used when NLM comes online.

        Args:
            notebook_id: Specific notebook or 'all'.

        Returns:
            Dict with creation stats.
        """
        from engine.nexus.client import get_nexus_client

        seeds = self.NOTEBOOK_SEEDS if notebook_id == "all" else {
            notebook_id: self.NOTEBOOK_SEEDS.get(notebook_id, {})
        }

        nx = get_nexus_client()
        created = 0
        for nb_id, seed in seeds.items():
            if not seed:
                continue

            entry = enforce_namespace(
                title=f"Notebook: {seed['name']}",
                content=json.dumps({
                    "notebook_id": nb_id,
                    "name": seed["name"],
                    "description": seed["description"],
                    "topics": seed["topics"],
                    "sources": seed["sources"],
                    "status": "seed",
                    "questions_to_explore": self._generate_questions(seed["topics"]),
                }, indent=2),
                content_type="document",
                category="research",
                tags=["research", "notebook", f"notebook:{nb_id}"] + seed["topics"],
                namespace="research",
            )

            entry_id = nx.add_entry(
                title=entry["title"],
                content=entry["content"],
                content_type="document",
                category="research",
                tags=entry["tags"],
                created_by="notebook_workflow",
            )
            if entry_id:
                created += 1

            # Generate and store Q&A pairs for this notebook
            qa_pairs = self._generate_qa(nb_id, seed)
            for qa in qa_pairs:
                nx.add_qa(
                    question=qa["question"],
                    answer=qa["answer"],
                    category=qa.get("category", "research"),
                    tags=qa.get("tags", []),
                )
                created += 1

        return {"notebooks_seeded": len(seeds), "entries_created": created}

    def _generate_questions(self, topics: List[str]) -> List[str]:
        """Generate research questions from topics."""
        base_questions = [
            "How does {topic} work in the system?",
            "What are the key design decisions for {topic}?",
            "What are common issues with {topic}?",
            "How does {topic} integrate with other components?",
            "What improvements could be made to {topic}?",
        ]
        questions = []
        for topic in topics[:3]:
            for template in base_questions:
                questions.append(template.format(topic=topic))
        return questions

    def _generate_qa(
        self, notebook_id: str, seed: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate Q&A pairs from notebook seed data."""
        topics = seed.get("topics", [])
        desc = seed.get("description", "")
        name = seed.get("name", "")

        pairs = [
            {
                "question": f"What is covered in the {name} notebook?",
                "answer": desc,
                "category": "research",
                "tags": ["research", "notebook", f"notebook:{notebook_id}"],
            },
        ]

        # Topic-specific Q&A
        topic_qa = {
            "mcp": ("What is the MCP framework?", "MCPFramework is the central state tree and tool registry. It manages scene nodes, character nodes, timers, and provides the singleton pattern via get_framework()."),
            "interceptors": ("How does the interceptor pipeline work?", "InterceptorPipeline wraps LLM calls with pre/post hooks. 25 interceptors run in priority order (lower first). Pre-call modifies system prompt/messages, post-call processes the response."),
            "scenes": ("How do CosySim scenes work?", "Scenes inherit from BaseScene, override start/stop/get_plugin_info. Each scene has MCP nodes, skills, templates, and Flask routes. SceneManager handles lifecycle."),
            "nexus": ("What is Nexus KMS?", "Nexus is the central knowledge management system. It provides FTS5 search, Q&A caching, rules engine, research sessions, and NotebookLM integration. API on port 8700."),
            "skills": ("How does the skill system work?", "Skills use the @skill decorator with pack, description, category, cooldown, cost. They're registered in SKILL_REGISTRY and exposed to agents via SkillAwarenessInterceptor."),
            "agents": ("How do CosySim agents work?", "VirtualAgent handles LLM inference. CharacterAgent adds personality. AgentGovernor manages the interceptor pipeline. Governance context flows through the chain."),
        }

        for topic in topics:
            if topic in topic_qa:
                q, a = topic_qa[topic]
                pairs.append({
                    "question": q,
                    "answer": a,
                    "category": "research",
                    "tags": ["research", "notebook", topic],
                })

        return pairs

    def check_nlm_status(self) -> Dict[str, Any]:
        """Check if NotebookLM backends are available."""
        from engine.nexus.client import get_nexus_client
        status: Dict[str, Any] = {"http": False, "browser": False}

        try:
            data = get_nexus_client().nlm_status()
            if data.get("ok"):
                inner = data.get("data", {})
                status["http"] = inner.get("status") == "ok"
                status["details"] = inner
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

        return status
