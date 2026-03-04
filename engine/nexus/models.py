"""Pydantic v2 domain models for the Nexus knowledge system.

These models serve as typed wrappers around the dict-heavy Nexus API responses.
All persistent models include ``.get()`` and ``__getitem__`` for backward
compatibility with code that treats entries as plain dicts.

Usage::

    from engine.nexus.models import NexusEntry, BenchmarkResult

    entry = NexusEntry(id="abc", title="My note", content="...", created_by="cosysim")
    print(entry.get("title"))       # dict-style access (compat)
    print(entry["content"])         # dict-style index (compat)
    print(entry.model_dump_json())  # Pydantic v2 serialisation
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utcnow() -> datetime:
    """Return current UTC datetime (timezone-aware, deprecation-free)."""
    return datetime.now(timezone.utc)

from pydantic import BaseModel, Field


# ──── Backward-compat mixin ────────────────────────────────────────────────


class _DictCompat:
    """Mixin that adds dict-style ``.get()`` and ``[]`` access to Pydantic models.

    Allows drop-in replacement for code that does ``entry.get("content")``
    or ``entry["title"]`` without changes.
    """

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


# ──── Nexus Entry models ────────────────────────────────────────────────────


class NexusEntryBase(BaseModel):
    """Shared fields for all Nexus entry shapes."""

    title: str = Field(..., description="Title of the entry")
    content: str = Field(..., description="Main content/payload of the entry")
    content_type: str = Field(
        default="note",
        description="Type of content (note, rule, memory, benchmark, code, etc.)",
    )
    category: str = Field(default="", description="Logical category or namespace")
    tags: List[str] = Field(default_factory=list, description="Tags for search/filter")


class NexusEntryCreate(NexusEntryBase):
    """Payload for creating a new Nexus entry."""

    created_by: str = Field(default="cosysim", description="Entity that created the entry")


class NexusEntry(_DictCompat, NexusEntryBase):
    """A fully materialised Nexus entry, as returned by the API."""

    id: str = Field(..., description="Unique identifier for the entry")
    created_by: str = Field(default="cosysim")
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: Optional[datetime] = None


# ──── Agent / Memory models ────────────────────────────────────────────────


class AgentMemory(_DictCompat, BaseModel):
    """A single agent memory fragment stored in Nexus."""

    agent_id: str
    memory_type: str = Field(default="observation")
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    content: str
    tags: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=_utcnow)


# ──── Rules / Governance models ───────────────────────────────────────────


class NexusRule(_DictCompat, BaseModel):
    """A governance rule stored in and enforced via Nexus."""

    rule_id: str
    scope: str
    rule_type: str
    condition: Dict[str, Any] = Field(default_factory=dict)
    action: Dict[str, Any] = Field(default_factory=dict)
    active: bool = True


# ──── Session / Audit models ──────────────────────────────────────────────


class SessionLog(_DictCompat, BaseModel):
    """A recorded CosySim dev session."""

    session_id: str
    project: str
    repo: str
    branch: str
    start_time: datetime
    end_time: Optional[datetime] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)
    summary: str = ""


# ──── NotebookLM models ───────────────────────────────────────────────────


class NLMNotebook(_DictCompat, BaseModel):
    """A NotebookLM notebook record."""

    id: str
    title: str
    source_count: int = 0
    created_at: Optional[datetime] = None


class NLMSource(_DictCompat, BaseModel):
    """A source document within a NotebookLM notebook."""

    id: str
    title: str
    type: str = Field(default="document")
    char_count: int = 0


class NLMAnswer(_DictCompat, BaseModel):
    """A response from a NotebookLM ask query."""

    text: str
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    notebook_id: str = ""
    duration_ms: float = 0.0


# ──── Benchmark / Training models (v0.83b+) ──────────────────────────────


class BenchmarkResult(_DictCompat, BaseModel):
    """A single benchmark evaluation result."""

    model: str
    method: str
    metrics: Dict[str, Any] = Field(default_factory=dict)
    score: float = 0.0
    timestamp: datetime = Field(default_factory=_utcnow)
    notes: str = ""


class TrainingRun(_DictCompat, BaseModel):
    """A fine-tuning or training job record."""

    run_id: str
    model_type: str
    dataset_path: str
    epochs: int = 3
    lora_r: int = 16
    status: str = Field(default="pending")  # pending | running | done | failed
    loss: Optional[float] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class RouterDecision(_DictCompat, BaseModel):
    """A routing decision logged by the InferenceOrchestrator."""

    request_hash: str
    chosen_model: str
    confidence: float = 0.0
    latency_ms: float = 0.0
    timestamp: datetime = Field(default_factory=_utcnow)


class NewsArticle(_DictCompat, BaseModel):
    """A distilled news article stored in Nexus."""

    url: str
    title: str
    summary: str = ""
    category: str = ""  # ai | tech | world | science
    source: str = ""
    published_at: Optional[datetime] = None
    tags: List[str] = Field(default_factory=list)


# ──── Generic API response wrappers ─────────────────────────────────────


class NexusResponse(BaseModel):
    """Standard API response envelope."""

    ok: bool
    error: Optional[str] = None
    data: Optional[Any] = None


class NexusSearchResponse(NexusResponse):
    """Search result response."""

    data: List[NexusEntry] = Field(default_factory=list)


class NexusEntryResponse(NexusResponse):
    """Single-entry response."""

    data: Optional[NexusEntry] = None


class PaginatedNexusResponse(NexusResponse):
    """Paginated list response."""

    data: List[NexusEntry] = Field(default_factory=list)
    total_count: int = 0
    page: int = 1
    limit: int = 20
