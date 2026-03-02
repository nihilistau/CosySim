"""Tests for Intel Hub benchmark dashboard."""
from pathlib import Path
import os


INTEL_HUB_SCENE = Path("content/scenes/intel_hub/intel_hub_scene.py")
INTEL_HUB_TEMPLATE = Path("content/scenes/intel_hub/templates/intel_hub.html")
INTEL_HUB_CSS = Path("content/scenes/intel_hub/static/css/intel_hub.css")


def test_benchmark_workflows_route_exists():
    code = INTEL_HUB_SCENE.read_text(encoding="utf-8")
    assert "/api/benchmark/workflows" in code


def test_benchmark_run_route_exists():
    code = INTEL_HUB_SCENE.read_text(encoding="utf-8")
    assert "/api/benchmark/run" in code


def test_benchmark_trend_route_exists():
    code = INTEL_HUB_SCENE.read_text(encoding="utf-8")
    assert "/api/benchmark/trend" in code


def test_benchmark_panel_in_template():
    html = INTEL_HUB_TEMPLATE.read_text(encoding="utf-8")
    assert "panel-benchmarks" in html or "benchmark-grid" in html


def test_benchmark_css_exists():
    css = INTEL_HUB_CSS.read_text(encoding="utf-8")
    assert "benchmark" in css.lower()


def test_benchmark_js_load_logic():
    html = INTEL_HUB_TEMPLATE.read_text(encoding="utf-8")
    js_dir = "content/scenes/intel_hub/static/js"
    js_content = ""
    if os.path.exists(js_dir):
        for f in os.listdir(js_dir):
            if f.endswith(".js"):
                js_content += open(os.path.join(js_dir, f), encoding="utf-8", errors="replace").read()
    combined = html + js_content
    assert "benchmark" in combined.lower()
    assert "/api/benchmark" in combined


def test_benchmark_run_btn_in_html():
    html = INTEL_HUB_TEMPLATE.read_text(encoding="utf-8")
    js_dir = "content/scenes/intel_hub/static/js"
    js_content = ""
    if os.path.exists(js_dir):
        for f in os.listdir(js_dir):
            if f.endswith(".js"):
                js_content += open(os.path.join(js_dir, f), encoding="utf-8", errors="replace").read()
    combined = html + js_content
    assert "benchmark-run-btn" in combined or "RUN NOW" in combined
