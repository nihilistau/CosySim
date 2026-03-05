"""ARGUS SDK gap analyzer — compare the endpoint registry against SDK clients.

Audits each integration client against its known API baseline (rpcid configs)
using AST-based method extraction.  Reports implemented methods, coverage %, gaps
(missing implementations), and extra methods (in SDK but not in the known API).

Also cross-references payload files in data/argus/payloads/ to flag which
discovered rpcids have SDK coverage.

CLI::

    python -m scripts.argus.sdk_auditor           # audit all clients, print report
    python -m scripts.argus.sdk_auditor --json     # also save JSON to disk
"""
from __future__ import annotations

import argparse
import ast
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from scripts.argus.config import (
    AISTUDIO_METHODS,
    DATA_DIR,
    GAS_RPCIDS,
    GEMINI_RPCIDS,
    NLM_RPCIDS,
    ROOT,
)

logger = logging.getLogger(__name__)

# ──── Paths ────────────────────────────────────────────────────────────────────

PAYLOADS_DIR = DATA_DIR / "payloads"
AUDIT_REPORT_PATH = DATA_DIR / "sdk_audit.json"

_INTEGRATIONS_DIR = ROOT / "engine" / "integrations"

# Client definitions: (file path, known API, service key)
_CLIENT_DEFS: List[Dict[str, Any]] = [
    {
        "key": "nlm",
        "file": _INTEGRATIONS_DIR / "nlm_direct_client.py",
        "known_api": NLM_RPCIDS,
        "label": "NotebookLM (NLM)",
    },
    {
        "key": "gas",
        "file": _INTEGRATIONS_DIR / "gas_client.py",
        "known_api": GAS_RPCIDS,
        "label": "Google Apps Script (GAS)",
    },
    {
        "key": "aistudio",
        "file": _INTEGRATIONS_DIR / "aistudio_client.py",
        "known_api": {m: m for m in AISTUDIO_METHODS},
        "label": "AI Studio",
    },
    {
        "key": "gemini",
        "file": _INTEGRATIONS_DIR / "gemini_direct_client.py",
        "known_api": GEMINI_RPCIDS,
        "label": "Gemini",
    },
    {
        "key": "gsheets",
        "file": _INTEGRATIONS_DIR / "gsheets_client.py",
        "known_api": {},
        "label": "Google Sheets",
    },
]

# Terminal colour codes (no external deps)
_RED = "\033[91m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


# ──── ClientAudit ──────────────────────────────────────────────────────────────

@dataclass
class ClientAudit:
    """Audit result for a single SDK client.

    Attributes:
        client_name: Stem of the client Python file.
        client_file: Absolute path to the client file.
        implemented_methods: Public method names found via AST (snake_case).
        known_api_items: Method names from the known API baseline (original
            casing, e.g. PascalCase from rpcid config values).
        coverage_pct: Percentage of known API items with a matching
            implemented method.
        missing: Known API items (snake_case) with no matching SDK method.
        extra: SDK methods not found in the known API (may be intentional
            helpers or utilities).
        payload_coverage: Mapping of rpcid → True if a payload file exists
            AND a matching SDK method is implemented.  Only populated when
            known_api is an rpcid-keyed dict.
    """

    client_name: str
    client_file: str
    implemented_methods: List[str]
    known_api_items: List[str]
    coverage_pct: float
    missing: List[str]
    extra: List[str]
    payload_coverage: Dict[str, bool] = field(default_factory=dict)


# ──── SDKAuditor ───────────────────────────────────────────────────────────────

class SDKAuditor:
    """Compares the ARGUS endpoint registry against SDK client implementations.

    Args:
        payloads_dir: Directory containing rpcid payload files (default:
            data/argus/payloads/).
    """

    def __init__(self, payloads_dir: Optional[Path] = None) -> None:
        self._payloads_dir = payloads_dir or PAYLOADS_DIR

    # ──── Public API ──────────────────────────────────────────────────────────

    def audit_client(
        self,
        client_file: Path,
        known_api: Union[Dict[str, str], List[str]],
    ) -> ClientAudit:
        """Audit one client file against a known API baseline.

        Args:
            client_file: Path to the Python integration client.
            known_api: Either a dict of {rpcid: method_name} or a list of
                method names (PascalCase) representing the known API.

        Returns:
            ClientAudit with full coverage analysis.
        """
        implemented = self._extract_methods(client_file)
        impl_set = set(implemented)

        # Normalise known_api to a list of (original_name, snake_name) tuples
        if isinstance(known_api, dict):
            api_pairs = [(name, _pascal_to_snake(name)) for name in known_api.values()]
            rpcid_map: Dict[str, str] = known_api  # rpcid -> name
        else:
            api_pairs = [(name, _pascal_to_snake(name)) for name in known_api]
            rpcid_map = {}

        api_originals = [orig for orig, _ in api_pairs]
        api_snake_set = {snake for _, snake in api_pairs}

        matched = impl_set & api_snake_set
        missing_snake = sorted(api_snake_set - impl_set)
        extra = sorted(impl_set - api_snake_set)

        coverage_pct = (
            round(len(matched) / len(api_snake_set) * 100, 1)
            if api_snake_set
            else 100.0
        )

        # Payload coverage: rpcids that have payload files — are they implemented?
        payload_coverage: Dict[str, bool] = {}
        if rpcid_map:
            for rpcid, name in rpcid_map.items():
                payload_file = self._payloads_dir / f"{rpcid}_request.json"
                if payload_file.exists():
                    snake = _pascal_to_snake(name)
                    payload_coverage[rpcid] = snake in impl_set

        return ClientAudit(
            client_name=client_file.stem,
            client_file=str(client_file),
            implemented_methods=sorted(implemented),
            known_api_items=api_originals,
            coverage_pct=coverage_pct,
            missing=missing_snake,
            extra=extra,
            payload_coverage=payload_coverage,
        )

    def audit_all(self) -> Dict[str, ClientAudit]:
        """Audit all five integration clients.

        Returns:
            Dict mapping service key to ClientAudit (keys: nlm, gas,
            aistudio, gemini, gsheets).
        """
        results: Dict[str, ClientAudit] = {}
        for defn in _CLIENT_DEFS:
            key: str = defn["key"]
            client_file: Path = defn["file"]
            known_api: Union[Dict[str, str], List[str]] = defn["known_api"]
            logger.info("Auditing %s ...", defn["label"])
            try:
                results[key] = self.audit_client(client_file, known_api)
            except Exception as exc:
                logger.error("Audit failed for %s: %s", key, exc)
        return results

    def print_report(self, audits: Dict[str, ClientAudit]) -> None:
        """Print a colour-coded coverage report to stdout.

        Args:
            audits: Output from audit_all().
        """
        _label_map = {defn["key"]: defn["label"] for defn in _CLIENT_DEFS}

        print(f"\n{_BOLD}{'=' * 60}{_RESET}")
        print(f"{_BOLD}  ARGUS SDK Audit Report{_RESET}")
        print(f"{_BOLD}{'=' * 60}{_RESET}\n")

        for key, audit in audits.items():
            label = _label_map.get(key, audit.client_name)
            pct = audit.coverage_pct
            colour = _GREEN if pct >= 80 else (_YELLOW if pct >= 50 else _RED)

            print(f"{_BOLD}{_CYAN}{label}{_RESET}  ({audit.client_name}.py)")
            print(f"  Coverage   : {colour}{pct:.1f}%{_RESET}  "
                  f"({len(audit.known_api_items) - len(audit.missing)}"
                  f"/{len(audit.known_api_items)} known API items)")
            print(f"  Implemented: {len(audit.implemented_methods)} methods")

            if audit.missing:
                print(f"  {_RED}Missing ({len(audit.missing)}):{_RESET}")
                for m in audit.missing:
                    print(f"    - {m}")

            if audit.extra:
                print(f"  {_YELLOW}Extra / unlisted ({len(audit.extra)}):{_RESET}")
                for m in audit.extra[:10]:
                    print(f"    + {m}")
                if len(audit.extra) > 10:
                    print(f"    ... and {len(audit.extra) - 10} more")

            if audit.payload_coverage:
                missing_payload = [
                    rpcid for rpcid, ok in audit.payload_coverage.items() if not ok
                ]
                if missing_payload:
                    print(f"  {_RED}Discovered rpcids with payload but no SDK method"
                          f" ({len(missing_payload)}):{_RESET}")
                    for rpcid in missing_payload:
                        print(f"    ⚠  {rpcid}")

            print()

    def save_report(
        self,
        audits: Dict[str, ClientAudit],
        path: Path = AUDIT_REPORT_PATH,
    ) -> None:
        """Save the audit results as JSON.

        Args:
            audits: Output from audit_all().
            path: Destination path (default: data/argus/sdk_audit.json).
        """
        serialisable = {key: asdict(audit) for key, audit in audits.items()}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(serialisable, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("SDKAuditor: report saved to %s", path)

    # ──── Helpers ─────────────────────────────────────────────────────────────

    def _extract_methods(self, path: Path) -> List[str]:
        """Extract all public method names from a Python file via AST.

        Includes top-level functions and class methods.  Skips names that
        start with ``_`` (private/dunder).

        Args:
            path: Path to the Python source file.

        Returns:
            Deduplicated list of public method names in definition order.
        """
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(path))
        except Exception as exc:
            logger.warning("AST parse error for %s: %s", path, exc)
            return []

        seen: Dict[str, None] = {}  # ordered set via dict keys

        # Top-level functions
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    seen[node.name] = None

        # Class methods (one level deep only — no nested class methods)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not item.name.startswith("_"):
                            seen[item.name] = None

        return list(seen)


# ──── Utilities ────────────────────────────────────────────────────────────────

def _pascal_to_snake(name: str) -> str:
    """Convert PascalCase or camelCase identifier to snake_case.

    Args:
        name: PascalCase identifier (e.g. "ListNotebooks").

    Returns:
        snake_case version (e.g. "list_notebooks").
    """
    step1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    step2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", step1)
    return step2.lower()


# ──── CLI ──────────────────────────────────────────────────────────────────────

def _cli() -> None:
    """Entry point for ``python -m scripts.argus.sdk_auditor``."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

    parser = argparse.ArgumentParser(
        description="ARGUS SDK auditor — compare registry against SDK clients",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help=f"Save JSON report to {AUDIT_REPORT_PATH}",
    )
    args = parser.parse_args()

    auditor = SDKAuditor()
    audits = auditor.audit_all()
    auditor.print_report(audits)

    if args.json:
        auditor.save_report(audits)
        print(f"JSON report saved to: {AUDIT_REPORT_PATH}")


if __name__ == "__main__":
    _cli()
