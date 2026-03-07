"""Tests for ARGUS path layout and legacy artifact migration."""
from __future__ import annotations

from pathlib import Path


def _patch_paths(paths_module, root: Path, monkeypatch) -> None:
    data_dir = root / "data" / "argus"
    raw_dir = root / "artifacts" / "argus"
    mapping = {
        "ROOT": root,
        "DATA_DIR": data_dir,
        "SELECTORS_DIR": data_dir / "selectors",
        "PROTOS_DIR": data_dir / "protos",
        "REGISTRY_PATH": data_dir / "registry.json",
        "FEATURE_FLAGS_PATH": data_dir / "feature_flags.json",
        "HAR_SCAN_REPORT_PATH": data_dir / "har_scan_report.json",
        "SDK_AUDIT_REPORT_PATH": data_dir / "sdk_audit.json",
        "RAW_DIR": raw_dir,
        "HAR_DIR": raw_dir / "har",
        "SCREENSHOTS_DIR": raw_dir / "screenshots",
        "REPORTS_DIR": raw_dir / "reports",
        "CAPTURES_DIR": raw_dir / "captures",
        "HEAP_DIR": raw_dir / "heaps",
        "PAYLOADS_DIR": raw_dir / "payloads",
        "PCAP_DIR": raw_dir / "pcap",
        "TOKENS_DIR": raw_dir / "tokens",
        "HISTORY_DIR": raw_dir / "history",
        "STATE_DIR": raw_dir / "state",
        "TLS_DIR": raw_dir / "tls",
        "BROWSER_PROFILES_DIR": raw_dir / "browser_profiles",
        "CHROME_PROFILE_DIR": raw_dir / "browser_profiles" / "chrome_profile",
        "SSLKEYS_PATH": raw_dir / "tls" / "sslkeys.log",
        "NLM_PIPELINE_STATE_PATH": raw_dir / "state" / "nlm_pipeline_state.json",
        "QA_SEEDER_PROGRESS_PATH": raw_dir / "state" / "qa_seeder_progress.json",
        "SCREENSHOT_SCRIPT_PATH": root / "scripts" / "argus" / "screenshot.ps1",
    }
    for name, value in mapping.items():
        monkeypatch.setattr(paths_module, name, value)


def test_history_path_uses_raw_artifact_root() -> None:
    from scripts.argus.paths import history_path

    path = history_path("notebooklm")
    assert "artifacts" in str(path)
    assert path.name == "notebooklm_history.json"


def test_migrate_legacy_artifacts_moves_raw_content(tmp_path: Path, monkeypatch) -> None:
    from scripts.argus import paths

    _patch_paths(paths, tmp_path, monkeypatch)

    legacy_har_dir = tmp_path / "data" / "har_files" / "users_dump_folder" / "screenshots"
    legacy_har_dir.mkdir(parents=True)
    (legacy_har_dir / "legacy.png").write_text("png-data", encoding="utf-8")
    (tmp_path / "data" / "har_files" / "sample.har").write_text("{}", encoding="utf-8")

    legacy_argus_dir = tmp_path / "data" / "argus"
    legacy_argus_dir.mkdir(parents=True, exist_ok=True)
    (legacy_argus_dir / "reports").mkdir()
    (legacy_argus_dir / "reports" / "crawl.png").write_text("report", encoding="utf-8")
    (legacy_argus_dir / "aistudio_history.json").write_text("[]", encoding="utf-8")
    (legacy_argus_dir / "nlm_pipeline_state.json").write_text("{}", encoding="utf-8")
    (legacy_argus_dir / "registry.json").write_text("{}", encoding="utf-8")

    result = paths.migrate_legacy_artifacts()

    assert not result.errors
    assert (tmp_path / "artifacts" / "argus" / "screenshots" / "legacy.png").exists()
    assert (tmp_path / "artifacts" / "argus" / "har" / "sample.har").exists()
    assert (tmp_path / "artifacts" / "argus" / "reports" / "crawl.png").exists()
    assert (tmp_path / "artifacts" / "argus" / "history" / "aistudio_history.json").exists()
    assert (tmp_path / "artifacts" / "argus" / "state" / "nlm_pipeline_state.json").exists()
    assert (tmp_path / "data" / "argus" / "registry.json").exists()
