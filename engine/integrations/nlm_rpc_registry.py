"""NLM RPC Registry — typed lookups and payload building from config/nlm_rpcids.yaml.

Singleton module that loads the YAML registry once and provides fast,
typed access to rpcids, payload templates, configurable parameters,
shared config objects, fallback chains, and gRPC method name mappings.

All parameters are runtime-overridable — tier gating is client-side,
the server accepts whatever values we send.

Version: v1.57.2 [2026-03-26]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-26] — gRPC method name lookup from heap-extracted methods
    v1.53.0 [2026-03-21] — Baseline registry with operations, parameters, payloads

Usage::

    from engine.integrations.nlm_rpc_registry import get_rpc_registry

    reg = get_rpc_registry()

    # Get the current rpcid for an operation
    rpcid = reg.get_rpcid("list_notebooks")            # "wXbhsf"
    rpcid = reg.get_rpcid("list_notebooks", "fallback") # "ub2Bae"

    # Build a payload with parameter substitution
    payload = reg.build_payload("list_notebooks", tier_marker=[2])

    # Get a configurable parameter
    tier = reg.get_parameter("tier_marker")             # [2]

    # Get shared config objects
    wc = reg.get_shared_config("write_config")          # full write config array

    # Get operation metadata
    info = reg.get_operation("create_notebook")
    print(info["description"])

    # gRPC method name lookup (heap-extracted)
    op = reg.get_operation_by_method("CreateProject")   # "create_notebook"
    rpcid = reg.get_rpcid_by_method("GetProject")       # "rLM1Ne"
    methods = reg.list_grpc_methods(category="sources")  # all source methods
"""
from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

logger = logging.getLogger(__name__)

_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "nlm_rpcids.yaml"

_registry_instance: Optional[NLMRpcRegistry] = None


class NLMRpcRegistry:
    """Typed registry for NotebookLM batchexecute RPC operations.

    Loads config/nlm_rpcids.yaml once and caches the result.  Provides
    fast lookups, payload building with parameter substitution, and
    runtime parameter overrides.

    Args:
        yaml_path: Path to the registry YAML file.
    """

    def __init__(self, yaml_path: Optional[Path] = None) -> None:
        self._path = yaml_path or _REGISTRY_PATH
        self._data: Dict[str, Any] = {}
        self._parameter_overrides: Dict[str, Any] = {}
        self._load()

    # ──── Loading ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load and validate the YAML registry."""
        if not self._path.exists():
            raise FileNotFoundError(f"NLM RPC registry not found: {self._path}")

        with open(self._path, "r", encoding="utf-8") as f:
            self._data = yaml.safe_load(f) or {}

        op_count = len(self._data.get("operations", {}))
        param_count = len(self._data.get("parameters", {}))
        logger.info(
            "NLM RPC registry loaded: %d operations, %d parameters from %s",
            op_count, param_count, self._path.name,
        )

    def reload(self) -> None:
        """Force-reload the YAML from disk."""
        self._load()
        logger.info("NLM RPC registry reloaded from %s", self._path.name)

    # ──── Operation Access ───────────────────────────────────────────────────

    def get_operation(self, name: str) -> Dict[str, Any]:
        """Get full operation metadata by name.

        Args:
            name: Operation name (e.g. "list_notebooks", "create_notebook").

        Returns:
            Full operation dict from YAML.

        Raises:
            KeyError: If operation not found.
        """
        ops = self._data.get("operations", {})
        if name in ops:
            entry = ops[name]
            if isinstance(entry, dict):
                return entry
        # Try alias search
        for op_name, op_data in ops.items():
            if not isinstance(op_data, dict):
                continue
            aliases = op_data.get("aliases", [])
            if name in aliases:
                return op_data
        raise KeyError(f"Unknown NLM operation: {name!r}")

    def get_rpcid(self, operation: str, tier: str = "primary") -> str:
        """Get the rpcid string for an operation.

        Args:
            operation: Operation name (e.g. "list_notebooks").
            tier: "primary" for current Pro-tier rpcid, "fallback" for
                  legacy Free-tier rpcid.

        Returns:
            rpcid string.

        Raises:
            KeyError: If operation not found.
            ValueError: If tier is "fallback" but no fallback_rpcid exists.
        """
        op = self.get_operation(operation)
        if tier == "primary":
            return op["rpcid"]
        elif tier == "fallback":
            fallback = op.get("fallback_rpcid")
            if fallback is None:
                raise ValueError(
                    f"Operation {operation!r} has no fallback rpcid"
                )
            return fallback
        else:
            raise ValueError(f"Unknown tier: {tier!r} (use 'primary' or 'fallback')")

    def get_fallback_rpcid(self, operation: str) -> Optional[str]:
        """Get the fallback rpcid or None if no fallback exists.

        Args:
            operation: Operation name.

        Returns:
            Fallback rpcid string or None.
        """
        op = self.get_operation(operation)
        return op.get("fallback_rpcid")

    def has_fallback(self, operation: str) -> bool:
        """Check whether an operation has a legacy fallback rpcid.

        Args:
            operation: Operation name.

        Returns:
            True if a fallback rpcid is defined.
        """
        return self.get_fallback_rpcid(operation) is not None

    def get_timeout(self, operation: str) -> int:
        """Get the default timeout for an operation.

        Args:
            operation: Operation name.

        Returns:
            Timeout in seconds.
        """
        op = self.get_operation(operation)
        return op.get("timeout", 30)

    def requires_notebook(self, operation: str) -> bool:
        """Check whether an operation requires notebook context in the URL.

        Args:
            operation: Operation name.

        Returns:
            True if the operation requires source-path=/notebook/<id>.
        """
        op = self.get_operation(operation)
        return op.get("requires_notebook", False)

    # ──── Parameter Access ───────────────────────────────────────────────────

    def get_parameter(self, name: str, option: Optional[str] = None) -> Any:
        """Get a configurable parameter value.

        Checks runtime overrides first, then the YAML defaults.

        Args:
            name: Parameter name (e.g. "tier_marker", "doc_type").
            option: Named option to look up (e.g. "pro", "deep_dive").
                    If None, returns the default value.

        Returns:
            Parameter value.

        Raises:
            KeyError: If parameter name not found.
        """
        params = self._data.get("parameters", {})
        if name not in params:
            raise KeyError(f"Unknown NLM parameter: {name!r}")

        param = params[name]

        # Runtime override takes precedence
        if name in self._parameter_overrides and option is None:
            return copy.deepcopy(self._parameter_overrides[name])

        if option is not None:
            options = param.get("options", {})
            if option not in options:
                raise KeyError(
                    f"Unknown option {option!r} for parameter {name!r}. "
                    f"Available: {list(options.keys())}"
                )
            return copy.deepcopy(options[option])

        return copy.deepcopy(param["default"])

    def set_parameter(self, name: str, value: Any) -> None:
        """Override a parameter at runtime.

        This does NOT persist to YAML — it's an in-memory override for
        the current session.

        Args:
            name: Parameter name.
            value: New value.

        Raises:
            KeyError: If parameter name not found.
        """
        params = self._data.get("parameters", {})
        if name not in params:
            raise KeyError(f"Unknown NLM parameter: {name!r}")
        self._parameter_overrides[name] = value
        logger.info("NLM parameter override: %s = %r", name, value)

    def clear_overrides(self) -> None:
        """Remove all runtime parameter overrides."""
        self._parameter_overrides.clear()

    def list_parameters(self) -> Dict[str, Any]:
        """Return all parameters with current effective values.

        Returns:
            Dict of parameter name → {description, default, current, options}.
        """
        result: Dict[str, Any] = {}
        for name, param in self._data.get("parameters", {}).items():
            result[name] = {
                "description": param.get("description", ""),
                "default": param.get("default"),
                "current": self._parameter_overrides.get(name, param.get("default")),
                "options": param.get("options", {}),
                "overridden": name in self._parameter_overrides,
            }
        return result

    # ──── Shared Config Access ───────────────────────────────────────────────

    def get_shared_config(self, name: str, **overrides: Any) -> List[Any]:
        """Get a shared config object (write_config, source_config, etc.).

        Optionally override configurable slots.

        Args:
            name: Config name (e.g. "write_config", "source_config").
            **overrides: Slot overrides. For write_config:
                         doc_type=9, model_quality=[3,1].

        Returns:
            Deep copy of the config array with overrides applied.

        Raises:
            KeyError: If config name not found.
        """
        configs = self._data.get("shared_configs", {})
        if name not in configs:
            raise KeyError(f"Unknown shared config: {name!r}")

        config_def = configs[name]
        result = copy.deepcopy(config_def["value"])

        # Apply slot overrides
        slots = config_def.get("configurable_slots", {})
        for slot_name, slot_value in overrides.items():
            for idx_str, mapped_name in slots.items():
                if mapped_name == slot_name or slot_name == mapped_name:
                    idx = int(idx_str)
                    if isinstance(slot_value, list) and isinstance(result[idx], list):
                        result[idx] = slot_value
                    elif isinstance(result[idx], list):
                        result[idx] = [slot_value]
                    else:
                        result[idx] = slot_value

        return result

    # ──── Payload Building ───────────────────────────────────────────────────

    def build_payload(
        self,
        operation: str,
        tier: str = "primary",
        **kwargs: Any,
    ) -> List[Any]:
        """Build a payload array for an operation with parameter substitution.

        Resolves $param references in the payload template using the
        parameter registry defaults, runtime overrides, and explicit kwargs.

        Args:
            operation: Operation name.
            tier: "primary" or "fallback" — selects which payload template.
            **kwargs: Explicit parameter values (override defaults and
                      runtime overrides for this call only).

        Returns:
            Payload list ready for batchexecute.
        """
        op = self.get_operation(operation)

        if tier == "fallback":
            template = op.get("fallback_payload")
            if template is None:
                raise ValueError(
                    f"Operation {operation!r} has no fallback_payload"
                )
        else:
            template = op.get("payload", [])

        return self._resolve_payload(copy.deepcopy(template), kwargs)

    def _resolve_payload(
        self, template: Any, kwargs: Dict[str, Any]
    ) -> Any:
        """Recursively resolve $param references in a payload template.

        Args:
            template: Payload template (may be nested list/str).
            kwargs: Explicit overrides for this call.

        Returns:
            Resolved payload.
        """
        if isinstance(template, str) and template.startswith("$"):
            param_name = template[1:]
            # Explicit kwarg takes priority
            if param_name in kwargs:
                return kwargs[param_name]
            # Check shared configs
            configs = self._data.get("shared_configs", {})
            if param_name in configs:
                return copy.deepcopy(configs[param_name]["value"])
            # Check parameters
            params = self._data.get("parameters", {})
            if param_name in params:
                return self.get_parameter(param_name)
            # Unknown — leave as-is (caller must supply)
            return template
        elif isinstance(template, list):
            return [self._resolve_payload(item, kwargs) for item in template]
        else:
            return template

    # ──── Listing / Discovery ────────────────────────────────────────────────

    def list_operations(
        self, category: Optional[str] = None
    ) -> Dict[str, Dict[str, Any]]:
        """List all operations, optionally filtered by category.

        Args:
            category: Filter by category (e.g. "notebook", "source", "chat").

        Returns:
            Dict of operation name → {rpcid, category, description, ...}.
        """
        ops = self._data.get("operations", {})
        if category is None:
            return {
                name: copy.deepcopy(op)
                for name, op in ops.items()
                if isinstance(op, dict)
            }
        return {
            name: copy.deepcopy(op)
            for name, op in ops.items()
            if isinstance(op, dict) and op.get("category") == category
        }

    def list_categories(self) -> List[str]:
        """Return sorted list of unique operation categories.

        Returns:
            List of category strings.
        """
        ops = self._data.get("operations", {})
        categories = {
            op.get("category", "unknown")
            for op in ops.values()
            if isinstance(op, dict)
        }
        return sorted(categories)

    def get_meta(self) -> Dict[str, Any]:
        """Return registry metadata (version, base_url, etc.).

        Returns:
            Meta dict from YAML.
        """
        return copy.deepcopy(self._data.get("meta", {}))

    def get_mime_types(self) -> Dict[str, str]:
        """Return flat extension → MIME type map for file uploads.

        Returns:
            Dict of ".ext" → "mime/type".
        """
        mime_data = self._data.get("mime_types", {})
        flat: Dict[str, str] = {}
        for group in mime_data.values():
            if isinstance(group, dict):
                flat.update(group)
        return flat

    def find_operation_by_rpcid(self, rpcid: str) -> Optional[str]:
        """Find an operation name by its rpcid string.

        Args:
            rpcid: rpcid string to look up.

        Returns:
            Operation name or None if not found.
        """
        for name, op in self._data.get("operations", {}).items():
            if not isinstance(op, dict):
                continue
            if op.get("rpcid") == rpcid:
                return name
            if op.get("fallback_rpcid") == rpcid:
                return name
        return None

    # ──── gRPC Method Name Lookup ────────────────────────────────────────────

    # v1.57.2 [2026-03-26] — gRPC method name lookup from heap-extracted methods
    # CONNECTS: config/nlm_rpcids.yaml grpc_methods section
    # CALLED BY: ARGUS heap analysis, transport rotation recovery, diagnostics

    def get_operation_by_method(self, method_name: str) -> Optional[str]:
        """Map a gRPC method name to an operation name.

        Uses the grpc_methods section of nlm_rpcids.yaml to resolve
        heap-extracted proto service method names (e.g. "CreateProject")
        to CosySim operation names (e.g. "create_notebook").

        Args:
            method_name: gRPC method name (e.g. "AddSources", "GetProject").

        Returns:
            Operation name string, or None if method is not mapped.
        """
        grpc = self._data.get("grpc_methods", {})
        entry = grpc.get(method_name, {})
        return entry.get("operation") if isinstance(entry, dict) else None

    def get_rpcid_by_method(self, method_name: str) -> Optional[str]:
        """Map a gRPC method name to its batchexecute rpcid.

        Looks up the rpcid directly from the grpc_methods mapping.
        Returns None if the method has no known rpcid (many gRPC methods
        are internal-only and don't have a batchexecute equivalent).

        Args:
            method_name: gRPC method name (e.g. "LoadSource", "GetProject").

        Returns:
            rpcid string, or None if no rpcid is mapped.
        """
        grpc = self._data.get("grpc_methods", {})
        entry = grpc.get(method_name, {})
        rpcid = entry.get("rpcid") if isinstance(entry, dict) else None
        # YAML null values load as None — treat as no mapping
        return rpcid if rpcid is not None else None

    def list_grpc_methods(self, category: Optional[str] = None) -> List[Dict]:
        """List all known gRPC methods, optionally filtered by category.

        Returns the full grpc_methods registry enriched with the method
        name as a "method" key. Useful for diagnostics and ARGUS reporting.

        Args:
            category: Optional category filter (e.g. "sources", "projects",
                      "chat", "generation", "account", "artifacts", "notes",
                      "export", "media", "feedback").

        Returns:
            List of dicts, each with keys: method, operation, rpcid, category.
        """
        grpc = self._data.get("grpc_methods", {})
        results: List[Dict] = []
        for name, info in grpc.items():
            if not isinstance(info, dict):
                continue
            if category and info.get("category") != category:
                continue
            results.append({"method": name, **info})
        return results

    def to_summary(self) -> str:
        """Return a human-readable summary of the registry.

        Returns:
            Multi-line string summary.
        """
        meta = self.get_meta()
        ops = self._data.get("operations", {})
        params = self._data.get("parameters", {})
        configs = self._data.get("shared_configs", {})
        grpc = self._data.get("grpc_methods", {})

        lines = [
            f"NLM RPC Registry v{meta.get('version', '?')}",
            f"  Updated: {meta.get('updated', '?')}",
            f"  Operations: {len(ops)}",
            f"  Parameters: {len(params)}",
            f"  Shared configs: {len(configs)}",
            f"  gRPC methods: {len(grpc)}",
            f"  Categories: {', '.join(self.list_categories())}",
            "",
            "Operations with fallbacks:",
        ]
        for name, op in ops.items():
            if not isinstance(op, dict):
                continue
            if op.get("fallback_rpcid"):
                lines.append(
                    f"  {name}: {op['rpcid']} (fallback: {op['fallback_rpcid']})"
                )

        overrides = self._parameter_overrides
        if overrides:
            lines.append("")
            lines.append("Active parameter overrides:")
            for k, v in overrides.items():
                lines.append(f"  {k} = {v!r}")

        return "\n".join(lines)

    def __repr__(self) -> str:
        ops = self._data.get("operations", {})
        return (
            f"<NLMRpcRegistry "
            f"ops={len(ops)} "
            f"path={self._path.name}>"
        )


def get_rpc_registry(yaml_path: Optional[Path] = None) -> NLMRpcRegistry:
    """Get the singleton NLM RPC registry.

    Args:
        yaml_path: Override path to the YAML file (mainly for testing).

    Returns:
        The shared NLMRpcRegistry instance.
    """
    global _registry_instance
    if _registry_instance is None or yaml_path is not None:
        _registry_instance = NLMRpcRegistry(yaml_path)
    return _registry_instance


def reset_registry() -> None:
    """Reset the singleton registry (for testing)."""
    global _registry_instance
    _registry_instance = None
