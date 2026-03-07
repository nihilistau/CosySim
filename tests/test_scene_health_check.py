from __future__ import annotations


def test_scene_health_check_uses_canonical_port_map() -> None:
    from scripts.scene_health_check import SCENE_PORTS

    assert SCENE_PORTS[5565] == "heist"
    assert SCENE_PORTS[5566] == "command_center"
    assert SCENE_PORTS[5567] == "games"
    assert SCENE_PORTS[5568] == "asset_studio"
    assert SCENE_PORTS[5575] == "system_control"
    assert SCENE_PORTS[5580] == "intel_hub"


def test_scene_health_check_url_helpers_support_custom_hosts() -> None:
    from scripts.scene_health_check import _chrome_http_url, _chrome_ws_url, _scene_base_url

    assert _scene_base_url(5569, host="127.0.0.1") == "http://127.0.0.1:5569"
    assert _chrome_http_url(9222, "/json", host="chrome.local") == "http://chrome.local:9222/json"
    assert (
        _chrome_ws_url("tab-123", 9222, host="chrome.local")
        == "ws://chrome.local:9222/devtools/page/tab-123"
    )
