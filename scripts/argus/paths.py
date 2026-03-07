"""Shared ARGUS path layout for curated data vs raw runtime artifacts.

Version-worthy outputs live under ``data/argus``.
Heavy, sensitive, or ephemeral runtime artifacts live under ``artifacts/argus``.
"""
from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[2]

# ──── Versionable ARGUS data ───────────────────────────────────────────────────

DATA_DIR = ROOT / "data" / "argus"
SELECTORS_DIR = DATA_DIR / "selectors"
PROTOS_DIR = DATA_DIR / "protos"

REGISTRY_PATH = DATA_DIR / "registry.json"
FEATURE_FLAGS_PATH = DATA_DIR / "feature_flags.json"
HAR_SCAN_REPORT_PATH = DATA_DIR / "har_scan_report.json"
SDK_AUDIT_REPORT_PATH = DATA_DIR / "sdk_audit.json"

# ──── Ignored raw/runtime ARGUS artifacts ──────────────────────────────────────

RAW_DIR = ROOT / "artifacts" / "argus"
HAR_DIR = RAW_DIR / "har"
SCREENSHOTS_DIR = RAW_DIR / "screenshots"
REPORTS_DIR = RAW_DIR / "reports"
CAPTURES_DIR = RAW_DIR / "captures"
HEAP_DIR = RAW_DIR / "heaps"
PAYLOADS_DIR = RAW_DIR / "payloads"
PCAP_DIR = RAW_DIR / "pcap"
TOKENS_DIR = RAW_DIR / "tokens"
HISTORY_DIR = RAW_DIR / "history"
STATE_DIR = RAW_DIR / "state"
TLS_DIR = RAW_DIR / "tls"
BROWSER_PROFILES_DIR = RAW_DIR / "browser_profiles"
CHROME_PROFILE_DIR = BROWSER_PROFILES_DIR / "chrome_profile"

SSLKEYS_PATH = TLS_DIR / "sslkeys.log"
NLM_PIPELINE_STATE_PATH = STATE_DIR / "nlm_pipeline_state.json"
QA_SEEDER_PROGRESS_PATH = STATE_DIR / "qa_seeder_progress.json"

# Versioned helper script; screenshots themselves go to SCREENSHOTS_DIR.
SCREENSHOT_SCRIPT_PATH = ROOT / "scripts" / "argus" / "screenshot.ps1"


def ensure_argus_directories() -> None:
    """Create the ARGUS directory structure if it does not already exist."""
    for directory in (
        DATA_DIR,
        SELECTORS_DIR,
        PROTOS_DIR,
        RAW_DIR,
        HAR_DIR,
        SCREENSHOTS_DIR,
        REPORTS_DIR,
        CAPTURES_DIR,
        HEAP_DIR,
        PAYLOADS_DIR,
        PCAP_DIR,
        TOKENS_DIR,
        HISTORY_DIR,
        STATE_DIR,
        TLS_DIR,
        BROWSER_PROFILES_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def history_path(target: str) -> Path:
    """Return the raw runtime history path for a crawler target."""
    return HISTORY_DIR / f"{target}_history.json"


@dataclass
class ArtifactMigrationResult:
    """Result of migrating legacy ARGUS artifact locations."""

    moved: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    removed_legacy: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, List[str]]:
        """Return a JSON-serializable summary."""
        return {
            "moved": list(self.moved),
            "skipped": list(self.skipped),
            "errors": list(self.errors),
            "removed_legacy": list(self.removed_legacy),
        }


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _same_file(source: Path, destination: Path) -> bool:
    if not source.exists() or not destination.exists():
        return False
    if source.stat().st_size != destination.stat().st_size:
        return False
    return _file_digest(source) == _file_digest(destination)


def _unique_destination(destination: Path) -> Path:
    if not destination.exists():
        return destination
    index = 1
    while True:
        candidate = destination.with_name(
            f"{destination.stem}_legacy{index}{destination.suffix}"
        )
        if not candidate.exists():
            return candidate
        index += 1


def _move_file(source: Path, destination: Path, result: ArtifactMigrationResult) -> None:
    if not source.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if destination.exists():
            if _same_file(source, destination):
                source.unlink()
                result.skipped.append(f"{source} -> {destination} (duplicate)")
                return
            destination = _unique_destination(destination)
        shutil.move(str(source), str(destination))
        result.moved.append(f"{source} -> {destination}")
    except Exception as exc:  # pragma: no cover - defensive
        result.errors.append(f"{source} -> {destination}: {exc}")


def _merge_directory(
    source: Path,
    destination: Path,
    result: ArtifactMigrationResult,
) -> None:
    if not source.exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for child in list(source.iterdir()):
        target = destination / child.name
        if child.is_dir():
            _merge_directory(child, target, result)
        else:
            _move_file(child, target, result)
    try:
        source.rmdir()
        result.removed_legacy.append(str(source))
    except OSError:
        # Non-empty or locked; leave it in place and let the caller inspect it.
        pass


def _legacy_directory_moves() -> Iterable[Tuple[Path, Path]]:
    legacy_data_dir = ROOT / "data"
    return (
        (legacy_data_dir / "har_files" / "users_dump_folder" / "screenshots", SCREENSHOTS_DIR),
        (legacy_data_dir / "har_files", HAR_DIR),
        (DATA_DIR / "har", HAR_DIR),
        (DATA_DIR / "captures", CAPTURES_DIR),
        (DATA_DIR / "heaps", HEAP_DIR),
        (DATA_DIR / "reports", REPORTS_DIR),
        (DATA_DIR / "payloads", PAYLOADS_DIR),
        (DATA_DIR / "tokens", TOKENS_DIR),
        (DATA_DIR / "chrome_profile", CHROME_PROFILE_DIR),
    )


def _legacy_file_moves() -> Iterable[Tuple[Path, Path]]:
    return (
        (DATA_DIR / "sslkeys.log", SSLKEYS_PATH),
        (DATA_DIR / "nlm_state.png", SCREENSHOTS_DIR / "nlm_state.png"),
        (DATA_DIR / "qa_seeder_progress.json", QA_SEEDER_PROGRESS_PATH),
        (DATA_DIR / "nlm_pipeline_state.json", NLM_PIPELINE_STATE_PATH),
    )


def migrate_legacy_artifacts() -> ArtifactMigrationResult:
    """Move legacy ARGUS raw artifacts into the ignored artifact root.

    The migration is best-effort and idempotent:
    - files are never overwritten silently
    - duplicate files are collapsed
    - legacy directories are removed only when emptied
    """
    ensure_argus_directories()
    result = ArtifactMigrationResult()

    for source, destination in _legacy_directory_moves():
        _merge_directory(source, destination, result)

    for source, destination in _legacy_file_moves():
        _move_file(source, destination, result)

    for history_file in list(DATA_DIR.glob("*_history.json")):
        _move_file(history_file, HISTORY_DIR / history_file.name, result)

    return result


ensure_argus_directories()
