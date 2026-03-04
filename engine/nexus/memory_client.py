"""NexusMemoryClient — domain facade for agent memory + Q&A."""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

from engine.nexus.models import AgentMemory

if TYPE_CHECKING:
    from engine.nexus.client import NexusClient


class NexusMemoryClient:
    def __init__(self, client: NexusClient) -> None:
        self._c = client

    def agent_submit(self, agent_id: str, submit_type: str, title: str,
                     content: str, importance: float = 0.5,
                     tags: list = None) -> Optional[str]:
        return self._c.agent_submit(
            agent_id=agent_id, submit_type=submit_type, title=title,
            content=content, importance=importance, tags=tags,
        )

    def ask(self, question: str, depth: str = "auto", **kwargs) -> Dict:
        return self._c.ask(question=question, depth=depth, **kwargs)

    def add_qa(self, question: str, answer: str, **kwargs) -> Optional[str]:
        return self._c.add_qa(question=question, answer=answer, **kwargs)

    def find_qa(self, question: str, limit: int = 5) -> List[Dict]:
        return self._c.find_qa(question=question, limit=limit)
