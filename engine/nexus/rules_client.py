"""NexusRulesClient — domain facade for Nexus rules + governance."""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from engine.nexus.models import NexusRule

if TYPE_CHECKING:
    from engine.nexus.client import NexusClient


class NexusRulesClient:
    def __init__(self, client: NexusClient) -> None:
        self._c = client

    def get_rules(self, scope: str = "", rule_type: str = "") -> List[NexusRule]:
        return self._c.get_rules(scope=scope, rule_type=rule_type)

    def add_rule(self, scope: str, rule_type: str, name: str,
                 condition: dict = None, action: dict = None,
                 active: bool = True) -> Optional[str]:
        return self._c.add_rule(
            scope=scope, rule_type=rule_type, name=name,
            condition=condition, action=action, active=active,
        )
