"""Data models for the News & Intelligence system."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class NewsItem:
    title: str
    url: str
    summary: str
    published_at: datetime
    source_name: str
    category: str
    fingerprint: str = ""  # hash of url+title for dedup
    raw_content: str = ""


@dataclass
class NewsDigest:
    category: str
    date: str  # YYYY-MM-DD
    items: list[NewsItem] = field(default_factory=list)
    qa_pairs: list[dict] = field(default_factory=list)  # [{q, a}]
    session_id: Optional[str] = None
    notebook_id: Optional[str] = None
