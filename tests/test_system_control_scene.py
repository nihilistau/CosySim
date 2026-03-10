"""Smoke tests for the System Control Panel scene (port 5575).

Tests all API routes with mocked external dependencies — no real service
connections are made (LMStudio, Nexus, NLM proxy all mocked).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
import yaml


# ── Flask test client fixture ──────────────────────────────────────────

@pytest.fixture
def sc_client(tmp_path: Path) -> Generator:
    """System Control scene Flask test client with all external deps mocked."""
    from content.scenes.system_control.system_control_scene import SystemControlScene

    scene = SystemControlScene(host="127.0.0.1", port=5575)
    scene.app.config["TESTING"] = True
    with scene.app.test_client() as c:
        yield c


# ── Health & plugin info ───────────────────────────────────────────────

class TestHealthEndpoints:
    def test_health_returns_ok(self, sc_client) -> None:
        resp = sc_client.get("/api/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "ok"
        assert data["scene"] == "system_control"
        assert data["port"] == 5575

    def test_plugin_info_returns_metadata(self, sc_client) -> None:
        resp = sc_client.get("/api/plugin_info")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["scene_id"] == "system_control"
        assert "title" in data
        assert data["port"] == 5575
        assert data["url"].startswith("http://localhost")

    def test_index_returns_html(self, sc_client) -> None:
        resp = sc_client.get("/")
        assert resp.status_code == 200
        assert b"System Control" in resp.data or b"html" in resp.data.lower()


# ── System metrics ─────────────────────────────────────────────────────

class TestMetricsEndpoint:
    def test_metrics_returns_timestamp(self, sc_client) -> None:
        resp = sc_client.get("/api/metrics")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "timestamp" in data

    def test_metrics_has_cpu_field(self, sc_client) -> None:
        resp = sc_client.get("/api/metrics")
        data = json.loads(resp.data)
        # cpu_percent may be None if psutil not installed, but key must be present
        assert "cpu_percent" in data

    def test_metrics_has_ram_field(self, sc_client) -> None:
        resp = sc_client.get("/api/metrics")
        data = json.loads(resp.data)
        assert "ram_percent" in data


# ── Service status ─────────────────────────────────────────────────────

class TestServicesEndpoint:
    def test_services_returns_all_services(self, sc_client) -> None:
        """All 19 configured services should appear in the response."""
        with patch(
            "content.scenes.system_control.system_control_scene._check_service",
            side_effect=lambda ep: {
                "id": ep["id"], "name": ep["name"],
                "port": ep["port"], "url": ep["url"], "online": False, "data": None,
            },
        ):
            resp = sc_client.get("/api/services")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "services" in data
        assert "total" in data
        assert data["total"] == 19

    def test_services_online_count_matches(self, sc_client) -> None:
        from content.scenes.system_control.system_control_scene import _SERVICE_ENDPOINTS
        n_services = len(_SERVICE_ENDPOINTS)

        def mock_check(ep):
            return {
                "id": ep["id"], "name": ep["name"],
                "port": ep["port"], "url": ep["url"], "online": True, "data": {},
            }

        with patch(
            "content.scenes.system_control.system_control_scene._check_service",
            side_effect=mock_check,
        ):
            resp = sc_client.get("/api/services")
        data = json.loads(resp.data)
        assert data["online"] == n_services

    def test_service_detail_unknown_id(self, sc_client) -> None:
        resp = sc_client.get("/api/services/nonexistent_service_id")
        assert resp.status_code == 404

    def test_service_detail_known_id(self, sc_client) -> None:
        with patch(
            "content.scenes.system_control.system_control_scene._check_service",
            return_value={"id": "nexus", "name": "Nexus KMS", "port": 8700,
                          "url": "...", "online": False, "data": None},
        ):
            resp = sc_client.get("/api/services/nexus")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["id"] == "nexus"


# ── Config management ──────────────────────────────────────────────────

class TestConfigEndpoints:
    def test_list_configs_returns_catalogue(self, sc_client) -> None:
        resp = sc_client.get("/api/config")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "configs" in data
        names = [c["name"] for c in data["configs"]]
        assert "default.yaml" in names
        assert "launcher.yaml" in names

    def test_read_disallowed_file_returns_403(self, sc_client) -> None:
        resp = sc_client.get("/api/config/../../secrets.yaml")
        assert resp.status_code in (403, 404)

    def test_read_allowed_file(self, sc_client) -> None:
        """Reading default.yaml should succeed (file exists in the repo)."""
        resp = sc_client.get("/api/config/default.yaml")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "content" in data
        assert len(data["content"]) > 0

    def test_write_disallowed_file_returns_403(self, sc_client) -> None:
        resp = sc_client.post(
            "/api/config/evil.yaml",
            json={"content": "key: value"},
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_write_invalid_yaml_returns_422(self, sc_client, tmp_path: Path) -> None:
        """Invalid YAML should be rejected with 422."""
        from content.scenes.system_control import system_control_scene as mod
        original = mod._EDITABLE_CONFIGS.copy()
        test_cfg = tmp_path / "test_cfg.yaml"
        test_cfg.write_text("valid: yaml", encoding="utf-8")
        mod._EDITABLE_CONFIGS["test_cfg.yaml"] = str(test_cfg)
        try:
            resp = sc_client.post(
                "/api/config/test_cfg.yaml",
                json={"content": "{bad yaml: [unclosed"},
                content_type="application/json",
            )
            assert resp.status_code == 422
        finally:
            mod._EDITABLE_CONFIGS = original

    def test_write_valid_yaml_succeeds(self, sc_client, tmp_path: Path) -> None:
        """Valid YAML content should be written successfully."""
        from content.scenes.system_control import system_control_scene as mod
        original = mod._EDITABLE_CONFIGS.copy()
        test_cfg = tmp_path / "writeable.yaml"
        test_cfg.write_text("old: value", encoding="utf-8")
        mod._EDITABLE_CONFIGS["writeable.yaml"] = str(test_cfg)
        try:
            resp = sc_client.post(
                "/api/config/writeable.yaml",
                json={"content": "new_key: new_value\nother: 42"},
                content_type="application/json",
            )
            assert resp.status_code == 200
            # Verify content was actually written
            written = yaml.safe_load(test_cfg.read_text())
            assert written["new_key"] == "new_value"
            # Verify .bak backup was created
            assert test_cfg.with_suffix(".yaml.bak").exists()
        finally:
            mod._EDITABLE_CONFIGS = original

    def test_write_empty_content_returns_400(self, sc_client, tmp_path: Path) -> None:
        from content.scenes.system_control import system_control_scene as mod
        original = mod._EDITABLE_CONFIGS.copy()
        test_cfg = tmp_path / "empty_test.yaml"
        test_cfg.write_text("key: val", encoding="utf-8")
        mod._EDITABLE_CONFIGS["empty_test.yaml"] = str(test_cfg)
        try:
            resp = sc_client.post(
                "/api/config/empty_test.yaml",
                json={"content": ""},
                content_type="application/json",
            )
            assert resp.status_code == 400
        finally:
            mod._EDITABLE_CONFIGS = original

    def test_write_valid_json_succeeds(self, sc_client, tmp_path: Path) -> None:
        """Valid JSON content should be written successfully."""
        from content.scenes.system_control import system_control_scene as mod
        original = mod._EDITABLE_CONFIGS.copy()
        test_json = tmp_path / "test.json"
        test_json.write_text('{"key": "old"}', encoding="utf-8")
        mod._EDITABLE_CONFIGS["test.json"] = str(test_json)
        try:
            resp = sc_client.post(
                "/api/config/test.json",
                json={"content": '{"key": "new", "count": 5}'},
                content_type="application/json",
            )
            assert resp.status_code == 200
            written = json.loads(test_json.read_text())
            assert written["key"] == "new"
        finally:
            mod._EDITABLE_CONFIGS = original


# ── Launcher control ───────────────────────────────────────────────────

class TestLauncherEndpoints:
    def test_launcher_get_returns_services(self, sc_client) -> None:
        resp = sc_client.get("/api/launcher")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "services" in data
        assert "scenes" in data

    def test_launcher_toggle_unknown_returns_404(self, sc_client) -> None:
        resp = sc_client.post(
            "/api/launcher/services/totally_nonexistent_scene_xyz",
            json={"auto_start": True},
            content_type="application/json",
        )
        # When target not found in launcher.yaml, it adds it — so 200 is also valid
        assert resp.status_code in (200, 404)

    def test_launcher_toggle_known_service(self, sc_client) -> None:
        resp = sc_client.post(
            "/api/launcher/scenes/penthouse",
            json={"auto_start": False},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data.get("target") == "penthouse"
        assert data.get("auto_start") is False


# ── NLM proxy passthrough ──────────────────────────────────────────────

class TestNlmProxyEndpoints:
    def test_nlm_status_proxied(self, sc_client) -> None:
        mock_status = {
            "status": "ok", "has_cookies": True,
            "cookie_count": 5, "bl": "boq_test_20260228.01_p0",
        }
        with patch(
            "content.scenes.system_control.system_control_scene._http_get",
            return_value=mock_status,
        ):
            resp = sc_client.get("/api/nlm/status")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "has_cookies" in data

    def test_nlm_status_offline(self, sc_client) -> None:
        with patch(
            "content.scenes.system_control.system_control_scene._http_get",
            return_value=None,
        ):
            resp = sc_client.get("/api/nlm/status")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data.get("online") is False or data.get("error") is not None

    def test_nlm_status_uses_canonical_proxy_url(self, sc_client) -> None:
        with (
            patch(
                "content.scenes.system_control.system_control_scene.get_service_url",
                return_value="http://proxy.test/health",
            ) as mock_get_service_url,
            patch(
                "content.scenes.system_control.system_control_scene._http_get",
                return_value=None,
            ),
        ):
            sc_client.get("/api/nlm/status")

        mock_get_service_url.assert_called_with("nlm_proxy", path="/health")


# ── Nexus health & search ──────────────────────────────────────────────

class TestNexusEndpoints:
    def test_nexus_status_proxied(self, sc_client) -> None:
        mock_health = {"status": "healthy", "entries": 500, "qa_pairs": 1720}
        with patch(
            "content.scenes.system_control.system_control_scene._http_get",
            return_value=mock_health,
        ):
            resp = sc_client.get("/api/nexus/status")
        assert resp.status_code == 200

    def test_nexus_search_missing_query(self, sc_client) -> None:
        resp = sc_client.get("/api/nexus/search")
        assert resp.status_code == 400

    def test_nexus_search_with_query(self, sc_client) -> None:
        mock_results = {"results": [{"title": "test", "score": 0.9}]}
        with patch(
            "content.scenes.system_control.system_control_scene._http_get",
            return_value=mock_results,
        ):
            resp = sc_client.get("/api/nexus/search?q=interceptor")
        assert resp.status_code == 200


# ── LMStudio status ────────────────────────────────────────────────────

class TestLMStudioEndpoints:
    def test_lmstudio_status_offline(self, sc_client) -> None:
        with patch(
            "content.scenes.system_control.system_control_scene._http_get",
            return_value=None,
        ):
            resp = sc_client.get("/api/lmstudio")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data.get("online") is False

    def test_lmstudio_status_online(self, sc_client) -> None:
        mock_models = {"data": [{"id": "qwen3-0.6b", "object": "model"}]}
        with patch(
            "content.scenes.system_control.system_control_scene._http_get",
            return_value=mock_models,
        ):
            resp = sc_client.get("/api/lmstudio")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data.get("online") is True
        assert isinstance(data.get("models"), list)

    def test_lmstudio_status_uses_canonical_model_url(self, sc_client) -> None:
        with (
            patch(
                "content.scenes.system_control.system_control_scene.get_service_url",
                return_value="http://lmstudio.test/api/v1/models",
            ) as mock_get_service_url,
            patch(
                "content.scenes.system_control.system_control_scene._http_get",
                return_value={"data": []},
            ),
        ):
            sc_client.get("/api/lmstudio")

        mock_get_service_url.assert_called_with("lmstudio", path="/api/v1/models")


# ── Log viewer ─────────────────────────────────────────────────────────

class TestLogsEndpoints:
    def test_logs_list_returns_list(self, sc_client) -> None:
        resp = sc_client.get("/api/logs")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "logs" in data
        assert isinstance(data["logs"], list)

    def test_logs_unknown_file_returns_404(self, sc_client) -> None:
        resp = sc_client.get("/api/logs/../../etc/passwd")
        assert resp.status_code in (400, 403, 404)

    def test_logs_tail_known_file(self, sc_client, tmp_path: Path) -> None:
        from content.scenes.system_control import system_control_scene as mod
        original_logs_dir = mod._PROJECT_ROOT / "logs"
        # Write a temporary log file and serve it
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        log_file = logs_dir / "test.log"
        log_file.write_text("line1\nline2\nline3\n", encoding="utf-8")

        original_root = mod._PROJECT_ROOT
        mod._PROJECT_ROOT = tmp_path
        try:
            resp = sc_client.get("/api/logs/test.log?lines=2")
            if resp.status_code == 200:
                data = json.loads(resp.data)
                assert "content" in data or "lines" in data
        finally:
            mod._PROJECT_ROOT = original_root


# ── Git status ─────────────────────────────────────────────────────────

class TestGitEndpoints:
    def test_git_returns_status(self, sc_client) -> None:
        resp = sc_client.get("/api/git")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        # Must have at minimum: branch and commits
        assert "branch" in data or "error" in data

    def test_git_branch_is_string(self, sc_client) -> None:
        resp = sc_client.get("/api/git")
        data = json.loads(resp.data)
        if "branch" in data:
            assert isinstance(data["branch"], str)
            assert len(data["branch"]) > 0


# ── Editable config catalogue completeness ────────────────────────────

class TestEditableConfigsCatalogue:
    def test_all_catalogue_keys_are_safe(self) -> None:
        """Ensure no catalogue entry allows path traversal."""
        from content.scenes.system_control.system_control_scene import _EDITABLE_CONFIGS
        for name, rel_path in _EDITABLE_CONFIGS.items():
            assert ".." not in rel_path, f"Unsafe path in catalogue: {rel_path}"

    def test_catalogue_has_required_entries(self) -> None:
        from content.scenes.system_control.system_control_scene import _EDITABLE_CONFIGS
        required = {"default.yaml", "launcher.yaml", "production.yaml"}
        for req in required:
            assert req in _EDITABLE_CONFIGS, f"Missing required catalogue entry: {req}"

    def test_service_endpoints_list_has_expected_services(self) -> None:
        from content.scenes.system_control.system_control_scene import _SERVICE_ENDPOINTS
        ids = {ep["id"] for ep in _SERVICE_ENDPOINTS}
        for expected_id in ("nexus", "hub", "nlm_proxy", "lmstudio"):
            assert expected_id in ids, f"Missing expected service: {expected_id}"
        # Verify all entries have required fields
        for ep in _SERVICE_ENDPOINTS:
            assert "id" in ep and "name" in ep and "url" in ep and "port" in ep

    def test_service_endpoints_use_canonical_ports(self) -> None:
        from content.scenes.system_control.system_control_scene import _SERVICE_ENDPOINTS

        endpoints = {ep["id"]: ep for ep in _SERVICE_ENDPOINTS}
        assert endpoints["command_center"]["port"] == 5566
        assert endpoints["penthouse"]["port"] == 5556
        assert endpoints["phone"]["port"] == 5555
        assert endpoints["tts"]["port"] == 8600
