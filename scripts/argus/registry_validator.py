"""ARGUS Registry Validator — validates config/nlm_rpcids.yaml v6.0 sections.

Validates the new sections added in v1.37/v1.41:
  - ``opal`` — rpcid exists, REST endpoints have url+method
  - ``appcatalyst`` — all 9 endpoints present
  - ``gemini_streaming`` — streaming rpcids/endpoints are valid
  - ``account_linking_grpc`` — 5 methods present
  - ``gemini.rpcids`` — new HAR goldmine rpcids (HcT8bb etc.) are present

Usage::

    from scripts.argus.registry_validator import RegistryValidator

    validator = RegistryValidator()
    report = validator.validate_all()
    print(report.summary())
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

_YAML_PATH = Path(__file__).resolve().parents[2] / "config" / "nlm_rpcids.yaml"

# Required AppCatalyst endpoints (9 from YAML)
_REQUIRED_APPCATALYST_ENDPOINTS = {
    "check_app_access",
    "create_cached_content",
    "execute_step",
    "generate_webpage_stream",
    "get_email_preferences",
    "set_email_preferences",
    "get_location",
    "generate_content",
    "stream_generate_content",
}

# Required Account Linking gRPC methods (5 from YAML)
_REQUIRED_ACCOUNT_LINKING_METHODS = {
    "DeleteLink",
    "DepositGoogleCredential",
    "FinishOAuth",
    "GetLink",
    "StartLinkingSession",
}

# New Gemini rpcids from v1.37 HAR goldmine
_NEW_GEMINI_RPCIDS = {"HcT8bb", "XqA3Ic", "ZKcapf", "jGArJ", "sJBwce"}


# ──── Validation result types ─────────────────────────────────────────────────


@dataclass
class ValidationIssue:
    """A single validation finding."""

    severity: str  # "error" | "warning" | "info"
    section: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.section}: {self.message}"


@dataclass
class ValidationReport:
    """Aggregated result from a full registry validation run."""

    issues: List[ValidationIssue] = field(default_factory=list)
    sections_validated: List[str] = field(default_factory=list)

    @property
    def errors(self) -> List[ValidationIssue]:
        """Return only error-severity issues."""
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[ValidationIssue]:
        """Return only warning-severity issues."""
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def passed(self) -> bool:
        """True when no errors were found."""
        return len(self.errors) == 0

    def summary(self) -> str:
        """Return a human-readable summary string.

        Returns:
            Multi-line summary of validation results.
        """
        lines = [
            f"Registry Validation: {'PASSED' if self.passed else 'FAILED'}",
            f"  Sections validated: {', '.join(self.sections_validated)}",
            f"  Errors:   {len(self.errors)}",
            f"  Warnings: {len(self.warnings)}",
            f"  Total:    {len(self.issues)}",
        ]
        if self.issues:
            lines.append("")
            for issue in self.issues:
                lines.append(f"  {issue}")
        return "\n".join(lines)

    def add(self, severity: str, section: str, message: str) -> None:
        """Append a new issue.

        Args:
            severity: ``"error"``, ``"warning"``, or ``"info"``.
            section: YAML section name (e.g. ``"opal"``).
            message: Human-readable description of the finding.
        """
        self.issues.append(ValidationIssue(severity=severity, section=section, message=message))


# ──── Validator ───────────────────────────────────────────────────────────────


class RegistryValidator:
    """Validates config/nlm_rpcids.yaml v6.0 against known structural requirements.

    Args:
        yaml_path: Override the default YAML path (mainly for testing).
    """

    def __init__(self, yaml_path: Optional[Path] = None) -> None:
        self._path = yaml_path or _YAML_PATH
        self._data: Dict[str, Any] = {}

    def _load(self) -> None:
        """Load the YAML file into memory."""
        if not self._path.exists():
            raise FileNotFoundError(f"Registry YAML not found: {self._path}")
        with open(self._path, "r", encoding="utf-8") as fh:
            self._data = yaml.safe_load(fh) or {}

    # ──── Public interface ────────────────────────────────────────────────────

    def validate_all(self) -> ValidationReport:
        """Run all validation checks and return a combined report.

        Returns:
            ValidationReport with all issues found.
        """
        self._load()
        report = ValidationReport()

        self.validate_opal(report)
        self.validate_appcatalyst(report)
        self.validate_gemini_streaming(report)
        self.validate_account_linking_grpc(report)
        self.validate_new_gemini_rpcids(report)

        log_fn = logger.warning if not report.passed else logger.info
        log_fn("Registry validation: %s", "PASSED" if report.passed else "FAILED")
        return report

    # ──── Section validators ──────────────────────────────────────────────────

    def validate_opal(self, report: Optional[ValidationReport] = None) -> ValidationReport:
        """Validate the ``opal`` YAML section.

        Checks:
        - Section exists
        - ``rpcids.ug7pge`` is present
        - REST endpoints have ``path`` and ``method`` fields

        Args:
            report: Existing report to append issues to (creates new if None).

        Returns:
            The (possibly new) ValidationReport.
        """
        if report is None:
            self._load()
            report = ValidationReport()

        section = "opal"
        opal = self._data.get(section)
        if opal is None:
            report.add("error", section, "Section 'opal' is missing from registry")
            report.sections_validated.append(section)
            return report

        # Validate rpcids
        rpcids = opal.get("rpcids", {})
        if not rpcids:
            report.add("error", section, "No rpcids defined under opal.rpcids")
        elif "ug7pge" not in rpcids:
            report.add("error", section, "Required rpcid 'ug7pge' missing from opal.rpcids")
        else:
            rpc_entry = rpcids.get("ug7pge", {})
            if not isinstance(rpc_entry, dict):
                report.add("warning", section, "opal.rpcids.ug7pge is not a dict")
            else:
                if not rpc_entry.get("description"):
                    report.add("warning", section, "opal.rpcids.ug7pge missing description")

        # Validate REST endpoints
        rest_apis = opal.get("rest_apis", {})
        if not rest_apis:
            report.add("warning", section, "No rest_apis defined under opal")
        else:
            for ep_name, ep_data in rest_apis.items():
                if not isinstance(ep_data, dict):
                    report.add("error", section, f"REST endpoint '{ep_name}' is not a dict")
                    continue
                if not ep_data.get("path"):
                    report.add(
                        "error", section, f"REST endpoint '{ep_name}' missing 'path'"
                    )
                if not ep_data.get("method"):
                    report.add(
                        "error", section, f"REST endpoint '{ep_name}' missing 'method'"
                    )

        # Validate meta
        meta = opal.get("meta", {})
        if not meta.get("base_url"):
            report.add("warning", section, "opal.meta.base_url is missing")

        report.sections_validated.append(section)
        return report

    def validate_appcatalyst(
        self, report: Optional[ValidationReport] = None
    ) -> ValidationReport:
        """Validate the ``appcatalyst`` YAML section.

        Checks:
        - Section exists
        - All 9 required endpoints are present
        - Each endpoint has ``path`` and ``method``

        Args:
            report: Existing report to append issues to.

        Returns:
            ValidationReport.
        """
        if report is None:
            self._load()
            report = ValidationReport()

        section = "appcatalyst"
        cat = self._data.get(section)
        if cat is None:
            report.add("error", section, "Section 'appcatalyst' is missing from registry")
            report.sections_validated.append(section)
            return report

        endpoints = cat.get("endpoints", {})
        if not endpoints:
            report.add("error", section, "No endpoints defined under appcatalyst.endpoints")
        else:
            # Check all 9 required endpoints
            present = set(endpoints.keys())
            missing = _REQUIRED_APPCATALYST_ENDPOINTS - present
            if missing:
                for ep in sorted(missing):
                    report.add(
                        "error", section, f"Required endpoint '{ep}' missing"
                    )

            # Validate each present endpoint has path + method
            for ep_name, ep_data in endpoints.items():
                if not isinstance(ep_data, dict):
                    report.add("error", section, f"Endpoint '{ep_name}' is not a dict")
                    continue
                if not ep_data.get("path"):
                    report.add("error", section, f"Endpoint '{ep_name}' missing 'path'")
                if not ep_data.get("method"):
                    report.add("error", section, f"Endpoint '{ep_name}' missing 'method'")

        # Check meta
        meta = cat.get("meta", {})
        if not meta.get("grpc_host") and not meta.get("base_path"):
            report.add("warning", section, "appcatalyst.meta missing grpc_host and base_path")

        report.sections_validated.append(section)
        return report

    def validate_gemini_streaming(
        self, report: Optional[ValidationReport] = None
    ) -> ValidationReport:
        """Validate the ``gemini_streaming`` YAML section.

        Checks:
        - Section exists
        - ``endpoints.stream_generate`` is present with ``path`` and ``method``
        - Transport is ``grpc-web``

        Args:
            report: Existing report to append issues to.

        Returns:
            ValidationReport.
        """
        if report is None:
            self._load()
            report = ValidationReport()

        section = "gemini_streaming"
        gs = self._data.get(section)
        if gs is None:
            report.add("error", section, "Section 'gemini_streaming' is missing from registry")
            report.sections_validated.append(section)
            return report

        endpoints = gs.get("endpoints", {})
        if not endpoints:
            report.add("error", section, "No endpoints defined under gemini_streaming.endpoints")
        else:
            # stream_generate is the primary required endpoint
            sg = endpoints.get("stream_generate")
            if sg is None:
                report.add(
                    "error", section, "Required endpoint 'stream_generate' missing"
                )
            else:
                if not isinstance(sg, dict):
                    report.add("error", section, "stream_generate endpoint is not a dict")
                else:
                    if not sg.get("path"):
                        report.add("error", section, "stream_generate missing 'path'")
                    if not sg.get("method"):
                        report.add("error", section, "stream_generate missing 'method'")
                    transport = sg.get("transport", "")
                    if transport and transport != "grpc-web":
                        report.add(
                            "warning",
                            section,
                            f"stream_generate transport expected 'grpc-web', got '{transport}'",
                        )

        meta = gs.get("meta", {})
        if not meta.get("base_url"):
            report.add("warning", section, "gemini_streaming.meta.base_url is missing")

        report.sections_validated.append(section)
        return report

    def validate_account_linking_grpc(
        self, report: Optional[ValidationReport] = None
    ) -> ValidationReport:
        """Validate the ``account_linking_grpc`` YAML section.

        Checks:
        - Section exists
        - All 5 required methods are present

        Args:
            report: Existing report to append issues to.

        Returns:
            ValidationReport.
        """
        if report is None:
            self._load()
            report = ValidationReport()

        section = "account_linking_grpc"
        alg = self._data.get(section)
        if alg is None:
            report.add(
                "error", section, "Section 'account_linking_grpc' is missing from registry"
            )
            report.sections_validated.append(section)
            return report

        methods = alg.get("methods", {})
        if not methods:
            report.add(
                "error", section, "No methods defined under account_linking_grpc.methods"
            )
        else:
            present = set(methods.keys())
            missing = _REQUIRED_ACCOUNT_LINKING_METHODS - present
            if missing:
                for m in sorted(missing):
                    report.add(
                        "error", section, f"Required gRPC method '{m}' missing"
                    )
            if len(methods) < 5:
                report.add(
                    "warning",
                    section,
                    f"Expected 5 methods, found {len(methods)}",
                )

        meta = alg.get("meta", {})
        if not meta.get("grpc_service"):
            report.add("warning", section, "account_linking_grpc.meta.grpc_service is missing")

        report.sections_validated.append(section)
        return report

    def validate_new_gemini_rpcids(
        self, report: Optional[ValidationReport] = None
    ) -> ValidationReport:
        """Validate that all 5 new HAR goldmine rpcids are present in gemini.rpcids.

        Args:
            report: Existing report to append issues to.

        Returns:
            ValidationReport.
        """
        if report is None:
            self._load()
            report = ValidationReport()

        section = "gemini.rpcids (new)"
        gemini = self._data.get("gemini", {})
        if not gemini:
            report.add("error", section, "Section 'gemini' is missing from registry")
            report.sections_validated.append(section)
            return report

        rpcids = gemini.get("rpcids", {})
        if not rpcids:
            report.add("error", section, "gemini.rpcids is empty")
        else:
            missing = _NEW_GEMINI_RPCIDS - set(rpcids.keys())
            if missing:
                for rpcid in sorted(missing):
                    report.add(
                        "error", section, f"New rpcid '{rpcid}' missing from gemini.rpcids"
                    )
            # Validate each new rpcid has a description
            for rpcid in _NEW_GEMINI_RPCIDS:
                entry = rpcids.get(rpcid)
                if entry and isinstance(entry, dict) and not entry.get("description"):
                    report.add(
                        "warning",
                        section,
                        f"rpcid '{rpcid}' missing description",
                    )

        report.sections_validated.append(section)
        return report
