"""Tests for launcher control-plane helpers."""

from __future__ import annotations

from unittest.mock import patch


def test_hub_url_uses_canonical_port_registry() -> None:
    import launcher

    with patch("launcher.get_port", return_value=9900) as mock_get_port:
        assert launcher._hub_url() == "http://localhost:9900"

    mock_get_port.assert_called_once_with("hub")
