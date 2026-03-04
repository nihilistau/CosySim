from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime

# --- Core Nexus Base Models ---


class NexusEntryBase(BaseModel):
    title: str = Field(..., description="Title of the entry")
    content: str = Field(..., description="Main content/payload of the entry")
    content_type: str = Field(
        default="note",
        description="Type of content (note, rule, memory, benchmark, etc.)",
    )
    category: str = Field(default="", description="Logical category or namespace")
    tags: List[str] = Field(
        default_factory=list, description="Tags for searching and filtering"
    )


class NexusEntryCreate(NexusEntryBase):
    created_by: str = Field(
        default="cosysim", description="Entity that created the entry"
    )


class NexusEntry(NexusEntryBase):
    id: str = Field(..., description="Unique identifier for the entry")
    created_by: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __getitem__(self, key):
        return getattr(self, key)


# --- Domain-Specific Nexus Models ---


class AgentMemory(BaseModel):
    agent_id: str
    memory_type: str = Field(default="observation")
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    content: str
    tags: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class NexusRule(BaseModel):
    rule_id: str
    scope: str
    rule_type: str
    condition: Dict[str, Any] = Field(
        default_factory=dict, description="Structured condition for the rule"
    )
    action: Dict[str, Any] = Field(
        default_factory=dict, description="Structured action/consequence"
    )
    active: bool = True

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __getitem__(self, key):
        return getattr(self, key)


class SessionLog(BaseModel):
    session_id: str
    project: str
    repo: str
    branch: str
    start_time: datetime
    end_time: Optional[datetime] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)
    summary: str = ""

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __getitem__(self, key):
        return getattr(self, key)


class NLMNotebook(BaseModel):
    id: str
    title: str
    source_count: int = 0
    created_at: Optional[datetime] = None

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __getitem__(self, key):
        return getattr(self, key)


class NLMSource(BaseModel):
    id: str
    title: str
    type: str = Field(default="document")
    char_count: int = 0

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __getitem__(self, key):
        return getattr(self, key)


class NLMAnswer(BaseModel):
    text: str
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    notebook_id: str = ""
    duration_ms: float = 0.0

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __getitem__(self, key):
        return getattr(self, key)


# --- Generic API Responses ---


class NexusResponse(BaseModel):
    ok: bool
    error: Optional[str] = None
    data: Optional[Any] = None


class NexusSearchResponse(NexusResponse):
    data: List[NexusEntry] = Field(default_factory=list)


class NexusEntryResponse(NexusResponse):
    data: Optional[NexusEntry] = None


class PaginatedNexusResponse(NexusResponse):
    data: List[NexusEntry] = Field(default_factory=list)
    total_count: int = 0
    page: int = 1
    limit: int = 20
