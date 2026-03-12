"""Workspace RPC Registry — parallel registry for Google Workspace Gemini endpoints.

Loads workspace_gemini, sheets_gemini, docs_gemini, drive_gemini,
cloud_search, workspace_support, drive_v2internal, sheets_extended,
people_stack, experiments, feedback, workspace_analytics, addons,
ogads, consent, and growth_promos sections from
``config/nlm_rpcids.yaml`` and provides typed lookup for endpoint
paths, auth methods, and operation metadata.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

_YAML_PATH = Path(__file__).resolve().parents[2] / "config" / "nlm_rpcids.yaml"

_WORKSPACE_SECTIONS = (
    "workspace_gemini",
    "sheets_gemini",
    "docs_gemini",
    "drive_gemini",
    "cloud_search",
    "workspace_support",
    "drive_v2internal",
    "sheets_extended",
    "people_stack",
    "experiments",
    "feedback",
    "workspace_analytics",
    "addons",
    "ogads",
    "consent",
    "growth_promos",
)

_registry_instance: Optional["WorkspaceRPCRegistry"] = None


class WorkspaceRPCRegistry:
    """Registry for Google Workspace RPC definitions.

    Mirrors the design of ``NLMRPCRegistry`` but covers 16 workspace sections
    spanning Gemini generation, Drive v2internal, Sheets extended ops,
    PeopleStack, Experiments, Feedback, Analytics, Add-ons, Consent, and
    Growth Promos.
    """

    def __init__(self, yaml_path: Optional[Path] = None) -> None:
        self._yaml_path = yaml_path or _YAML_PATH
        self._data: Dict[str, Any] = {}
        self._load()

    # ──── Loading ─────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load workspace sections from the YAML config."""
        try:
            with open(self._yaml_path, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
        except Exception as exc:
            logger.error("Failed to load workspace registry YAML: %s", exc)
            raw = {}

        for section in _WORKSPACE_SECTIONS:
            if section in raw:
                self._data[section] = raw[section]

        total_ops = sum(
            len(self._data.get(s, {}).get("operations", {}))
            for s in _WORKSPACE_SECTIONS
        )
        logger.info(
            "WorkspaceRPCRegistry loaded: %d sections, %d operations",
            len(self._data),
            total_ops,
        )

    def reload(self) -> None:
        """Force-reload the YAML config."""
        self._data.clear()
        self._load()

    # ──── Section Access ──────────────────────────────────────────────────────

    def get_section(self, section: str) -> Dict[str, Any]:
        """Get a full section (meta + operations).

        Args:
            section: Section name (e.g. 'workspace_gemini', 'sheets_gemini').

        Returns:
            Section dict, or empty dict if not found.
        """
        return self._data.get(section, {})

    def get_meta(self, section: str) -> Dict[str, Any]:
        """Get metadata for a section.

        Args:
            section: Section name.

        Returns:
            Meta dict with service_name, base_url, auth_method, etc.
        """
        return self._data.get(section, {}).get("meta", {})

    def get_operations(self, section: str) -> Dict[str, Any]:
        """Get all operations for a section.

        Args:
            section: Section name.

        Returns:
            Dict of operation_name → operation_config.
        """
        return self._data.get(section, {}).get("operations", {})

    # ──── Operation Lookup ────────────────────────────────────────────────────

    def get_operation(
        self,
        section: str,
        operation: str,
    ) -> Optional[Dict[str, Any]]:
        """Get a specific operation definition.

        Args:
            section: Section name (e.g. 'workspace_gemini').
            operation: Operation name (e.g. 'stream_generate').

        Returns:
            Operation dict, or None if not found.
        """
        ops = self.get_operations(section)
        return ops.get(operation)

    def get_path(self, section: str, operation: str) -> Optional[str]:
        """Get the URL path for an operation.

        Args:
            section: Section name.
            operation: Operation name.

        Returns:
            Path string (e.g. '/v1/genai/streamGenerate'), or None.
        """
        op = self.get_operation(section, operation)
        return op.get("path") if op else None

    def get_full_url(
        self,
        section: str,
        operation: str,
        path_params: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """Build the full URL for an operation.

        Combines the section's base_url with the operation path.  Substitutes
        any ``{param}`` placeholders in the path with values from path_params.

        Args:
            section: Section name.
            operation: Operation name.
            path_params: Dict of path parameter substitutions
                (e.g. ``{"spreadsheet_id": "abc123"}``).

        Returns:
            Full URL string, or None if section/operation not found.
        """
        meta = self.get_meta(section)
        base_url = meta.get("base_url", "")
        path = self.get_path(section, operation)

        if not path or path.startswith("via_"):
            return None

        if path_params:
            for key, value in path_params.items():
                path = path.replace(f"{{{key}}}", value)

        return f"{base_url}{path}"

    def is_streaming(self, section: str, operation: str) -> bool:
        """Check if an operation uses streaming responses.

        Args:
            section: Section name.
            operation: Operation name.

        Returns:
            True if operation is streaming.
        """
        op = self.get_operation(section, operation)
        return bool(op.get("streaming", False)) if op else False

    def get_auth_method(self, section: str) -> str:
        """Get the authentication method for a section.

        Args:
            section: Section name.

        Returns:
            Auth method string (e.g. 'api_key_query_param', 'cookie_sapisidhash').
        """
        return self.get_meta(section).get("auth_method", "cookie_sapisidhash")

    # ──── Cross-Section Queries ───────────────────────────────────────────────

    def list_all_operations(self) -> List[Tuple[str, str, str]]:
        """List all operations across all workspace sections.

        Returns:
            List of (section, operation_name, description) tuples.
        """
        results: List[Tuple[str, str, str]] = []
        for section in _WORKSPACE_SECTIONS:
            for op_name, op_config in self.get_operations(section).items():
                desc = op_config.get("description", "")
                results.append((section, op_name, desc))
        return results

    def find_operation(self, operation: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Find an operation by name across all sections.

        Args:
            operation: Operation name to search for.

        Returns:
            Tuple of (section_name, operation_config), or None if not found.
        """
        for section in _WORKSPACE_SECTIONS:
            op = self.get_operation(section, operation)
            if op is not None:
                return (section, op)
        return None

    def get_parameters(
        self,
        section: str,
        operation: str,
    ) -> Dict[str, Any]:
        """Get the parameter definitions for an operation.

        Args:
            section: Section name.
            operation: Operation name.

        Returns:
            Parameters dict, or empty dict.
        """
        op = self.get_operation(section, operation)
        return op.get("parameters", {}) if op else {}

    def summary(self) -> Dict[str, Any]:
        """Get a summary of the registry contents.

        Returns:
            Dict with section counts and total operations.
        """
        sections: Dict[str, int] = {}
        total = 0
        for section in _WORKSPACE_SECTIONS:
            count = len(self.get_operations(section))
            if count > 0:
                sections[section] = count
                total += count

        return {
            "sections_loaded": len(sections),
            "total_operations": total,
            "sections": sections,
        }


# ──── Factory ─────────────────────────────────────────────────────────────────


def get_workspace_registry(
    force_reload: bool = False,
) -> WorkspaceRPCRegistry:
    """Get the singleton WorkspaceRPCRegistry instance.

    Args:
        force_reload: If True, reload the YAML config.

    Returns:
        WorkspaceRPCRegistry instance.
    """
    global _registry_instance
    if _registry_instance is None or force_reload:
        _registry_instance = WorkspaceRPCRegistry()
    elif force_reload:
        _registry_instance.reload()
    return _registry_instance
