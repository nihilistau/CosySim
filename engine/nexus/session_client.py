"""NexusSessionClient — domain facade for session logging."""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

from engine.nexus.models import SessionLog

if TYPE_CHECKING:
    from engine.nexus.client import NexusClient


class NexusSessionClient:
    def __init__(self, client: NexusClient) -> None:
        self._c = client

    def log_session(self, session_id: str = None, project: str = "",
                    repo: str = "", branch: str = "", **kwargs) -> Optional[str]:
        return self._c.log_session(
            session_id=session_id, project=project, repo=repo, branch=branch, **kwargs
        )

    def get_session(self, session_id: str) -> Optional[Dict]:
        return self._c.get_session(session_id)

    def list_sessions(self, project: str = "", status: str = "",
                      limit: int = 20) -> List[Dict]:
        return self._c.list_sessions(project=project, status=status, limit=limit)
