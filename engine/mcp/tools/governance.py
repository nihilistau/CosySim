"""MCP tool domain: governance.

Thin wrappers that delegate to *_tools.py implementations.
Apply @mcp_tool for unified error handling and serialisation.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.paths import ROOT as _root
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from engine.mcp.decorators import mcp_tool
from engine.mcp._lazy import _get_db, _get_rag, _get_config

logger = logging.getLogger(__name__)

# ──── GOVERNANCE TOOLS ───────────────────────────────────────────────────


@mcp_tool
def governance_validate(filepath: str) -> str:
    """Validate a Python file against all CosySim coding standards.
    Returns violations with rule names, severity, messages, and line numbers."""
    try:
        from engine.nexus.governance_rules import get_governance_manager
        return json.dumps(get_governance_manager().validate_file(filepath), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def governance_seed() -> str:
    """Seed all 18 governance rules into Nexus (idempotent). Rules cover
    coding standards, testing, Nexus workflow, agent permissions, and commits."""
    try:
        from engine.nexus.governance_rules import get_governance_manager
        return json.dumps(get_governance_manager().seed_rules(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def governance_check_permission(agent_id: str, operation: str) -> str:
    """Check if an agent can perform an operation. Agent permission rules
    are based on model parameter count (sub-1B=read-only, 1-10B=write,
    10B+/Copilot=full access)."""
    try:
        from engine.nexus.governance_rules import get_governance_manager
        allowed = get_governance_manager().check_permissions(agent_id, operation)
        return json.dumps({"agent_id": agent_id, "operation": operation, "allowed": allowed})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def governance_enforce(filepath: str = "", agent_id: str = "copilot",
                       operation: str = "write", commit_message: str = "") -> str:
    """Enforce governance rules — raises error if blocking violations found.
    Unlike governance_validate (advisory), this blocks on reject/block severity."""
    try:
        from engine.nexus.governance_rules import enforce_governance, GovernanceError
        try:
            violations = enforce_governance(
                filepath=filepath or None,
                agent_id=agent_id,
                operation=operation,
                commit_message=commit_message or None,
            )
            return json.dumps({"allowed": True, "advisory_violations": len(violations)})
        except GovernanceError as ge:
            return json.dumps({
                "allowed": False,
                "rule": ge.rule,
                "message": str(ge),
                "severity": ge.severity,
                "violations": ge.violations,
            }, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})
