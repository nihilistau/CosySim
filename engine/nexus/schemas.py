"""
Nexus Extraction Schemas -- JSON schemas for Gemini structured output
====================================================================

Defines typed schemas for Q&A extraction, task decomposition, knowledge
distillation, and agent decision parsing. Used with Gemini's structured
output to get guaranteed JSON instead of regex-parsing markdown.

These schemas use the Gemini JSON schema format (STRING, NUMBER, INTEGER,
OBJECT, ARRAY types) rather than standard JSON Schema draft, because the
google.genai SDK expects this format for response_schema enforcement.

Version: v1.57.0 [2026-03-26]
Author:  CosySim Team

Change Log:
    v1.57.0 [2026-03-26] -- Initial schema definitions: QA, task decomposition,
                             knowledge entry, agent decision, grounded answer
"""
from __future__ import annotations


# ---- Q&A Extraction Schemas ------------------------------------------------

# v1.57.0 [2026-03-26] -- Single Q&A pair with confidence scoring
QA_PAIR_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "question": {"type": "STRING"},
        "answer": {"type": "STRING"},
        "confidence": {"type": "NUMBER"},
        "category": {"type": "STRING"},
    },
    "required": ["question", "answer"],
}

# v1.57.0 [2026-03-26] -- Batch of Q&A pairs (array wrapper)
QA_BATCH_SCHEMA = {
    "type": "ARRAY",
    "items": QA_PAIR_SCHEMA,
}


# ---- Task Decomposition Schemas --------------------------------------------

# v1.57.0 [2026-03-26] -- Single step in a decomposed plan
TASK_STEP_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "step": {"type": "INTEGER"},
        "description": {"type": "STRING"},
        "files": {"type": "ARRAY", "items": {"type": "STRING"}},
        "complexity": {"type": "STRING"},  # "simple", "moderate", "complex"
    },
    "required": ["step", "description"],
}

# v1.57.0 [2026-03-26] -- Full decomposed plan (array of steps)
TASK_DECOMPOSITION_SCHEMA = {
    "type": "ARRAY",
    "items": TASK_STEP_SCHEMA,
}


# ---- Knowledge Entry Extraction Schema --------------------------------------

# v1.57.0 [2026-03-26] -- Structured knowledge entry for Nexus ingestion
KNOWLEDGE_ENTRY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title": {"type": "STRING"},
        "content": {"type": "STRING"},
        "content_type": {"type": "STRING"},
        "category": {"type": "STRING"},
        "tags": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["title", "content"],
}


# ---- Agent Decision Parsing Schema ------------------------------------------

# v1.57.0 [2026-03-26] -- Structured agent action/decision output
# CONNECTS: AgentGovernor, CharacterAgent, skill dispatch pipeline
AGENT_DECISION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "action": {"type": "STRING"},
        "target": {"type": "STRING"},
        "message": {"type": "STRING"},
        "mood": {"type": "STRING"},
        "reasoning": {"type": "STRING"},
    },
    "required": ["action"],
}


# ---- Search Result with Citations Schema ------------------------------------

# v1.57.0 [2026-03-26] -- Grounded answer with source citations
# CONNECTS: Nexus query router, knowledge retrieval pipeline
GROUNDED_ANSWER_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "answer": {"type": "STRING"},
        "citations": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "source": {"type": "STRING"},
                    "quote": {"type": "STRING"},
                },
            },
        },
        "confidence": {"type": "NUMBER"},
    },
    "required": ["answer"],
}
