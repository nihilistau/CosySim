"""CosySim Master Notebook Builder — the definitive system intelligence notebook.

Assembles ALL project knowledge into NotebookLM:
  - Hardware & system specification
  - Complete engine source code (12 categorised bundles)
  - All documentation (architecture, protocols, guides)
  - Config files & governance rules
  - JavaScript/frontend code
  - Official SDK & API documentation URLs (LMStudio, Flask, Python, MCP, etc.)

Then runs every available NotebookLM generator:
  - Audio overview (standard + deep dive)
  - Video overview
  - Study guide / briefing doc / FAQ
  - Q&A distillation (60+ pairs → Nexus)
  - Custom Q&A batch for local agents

Usage::

    # Full build (creates notebook, uploads, runs all generators)
    python -m engine.nexus.master_notebook_builder

    # Upload sources only (skip generators)
    python -m engine.nexus.master_notebook_builder --sources-only

    # Generators only (notebook already built)
    python -m engine.nexus.master_notebook_builder --notebook-id <id> --generators-only

    # Dry run (print what would be uploaded)
    python -m engine.nexus.master_notebook_builder --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Project root ──────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent.parent

# ── Notebook name ─────────────────────────────────────────────────────────
NOTEBOOK_NAME = "CosySim Master Intelligence"
NOTEBOOK_VERSION = "v0.62"

# ── State file ────────────────────────────────────────────────────────────
_STATE_FILE = _ROOT / ".github" / "hooks" / "logs" / "master_notebook_state.json"

# ── Official SDK / API documentation URLs ─────────────────────────────────
SDK_URLS: List[Dict[str, str]] = [
    # LMStudio
    {"url": "https://lmstudio.ai/docs/python", "label": "LMStudio Python SDK"},
    {"url": "https://lmstudio.ai/docs/app/api", "label": "LMStudio REST API"},
    {"url": "https://lmstudio.ai/docs/app/api/endpoints/openai-chat",
     "label": "LMStudio OpenAI Chat Completions"},
    {"url": "https://lmstudio.ai/docs/app/api/endpoints/openai-completions",
     "label": "LMStudio OpenAI Text Completions"},
    # Python ecosystem
    {"url": "https://flask.palletsprojects.com/en/3.1.x/", "label": "Flask 3.1 Docs"},
    {"url": "https://flask-socketio.readthedocs.io/en/latest/",
     "label": "Flask-SocketIO Docs"},
    {"url": "https://docs.python.org/3/library/typing.html",
     "label": "Python typing module"},
    {"url": "https://docs.python.org/3/library/sqlite3.html",
     "label": "Python sqlite3 module"},
    {"url": "https://docs.python.org/3/library/asyncio.html",
     "label": "Python asyncio module"},
    {"url": "https://docs.pytest.org/en/stable/", "label": "pytest Documentation"},
    {"url": "https://requests.readthedocs.io/en/latest/", "label": "requests library"},
    {"url": "https://docs.pydantic.dev/latest/", "label": "Pydantic v2 Docs"},
    {"url": "https://python-socketio.readthedocs.io/en/stable/",
     "label": "python-socketio Docs"},
    # MCP & Agents
    {"url": "https://modelcontextprotocol.io/introduction", "label": "MCP Protocol Spec"},
    {"url": "https://modelcontextprotocol.io/docs/concepts/tools", "label": "MCP Tools"},
    {"url": "https://modelcontextprotocol.io/docs/concepts/resources",
     "label": "MCP Resources"},
    # AI / ML
    {"url": "https://huggingface.co/docs/transformers/index",
     "label": "HuggingFace Transformers"},
    {"url": "https://onnxruntime.ai/docs/", "label": "ONNX Runtime Docs"},
    # GitHub Copilot
    {"url": "https://docs.github.com/en/copilot/using-github-copilot/using-github-copilot-in-the-command-line",
     "label": "GitHub Copilot CLI Docs"},
]

# ── Q&A distillation questions for local agent consumption ────────────────
DISTILLATION_QUESTIONS: List[str] = [
    # Architecture
    "What is the MCPFramework and how does it serve as the state backbone of CosySim?",
    "How does the InterceptorPipeline work and what does it intercept?",
    "What is the @skill decorator pattern and how are skills registered?",
    "How does the DialogSystem manage conversation threading between agents?",
    "What is the BaseScene class and what must subclasses override?",
    "How does the SceneStateManager differ from the MCPFramework tree?",
    "How does the AgentGovernor enforce rules on agent operations?",
    "What is the governance_context flow from AgentGovernor to VirtualAgent?",
    # LMStudio integration
    "How does LMStudio v1 API SSE streaming work in CosySim?",
    "What is the difference between infer_stream() and infer_processed()?",
    "How does stateful conversation threading work with store:true and previous_response_id?",
    "What are the 4 model profiles (big/small/router/draft) and when is each used?",
    "How does the InferenceOrchestrator route requests to different models?",
    # Nexus system
    "What is the 4-tier Nexus query pipeline (cache → FTS → NLM → LLM)?",
    "How does the NexusQueryRouter decide which tier to use?",
    "What is the NLMHybrid router and how does it combine batchexecute and Node MCP?",
    "How does the NotebookLM Node MCP server authenticate and what is Patchright?",
    "What does the news_nlm_pipeline do and how often does it run?",
    "How does the SchedulerDaemon work and what are its 19 built-in tasks?",
    "How should local agents use the LocalAgentBridge to claim and complete tasks?",
    # Coding standards
    "What are the absolute import and type hint requirements for all Python files?",
    "Why is print() forbidden and what logging pattern is used instead?",
    "What is the Google docstring format required for CosySim?",
    "How are tests structured — what fixtures, mocking patterns, and assertions are used?",
    # System & hardware
    "What hardware runs CosySim and what are its memory and GPU capabilities?",
    "What external services does CosySim depend on and what port does each use?",
    "How is the LMStudio SDK used versus the raw REST API?",
    "What is the Flask + Flask-SocketIO pattern used for scene web interfaces?",
    # Skills
    "What skill categories are available and what does each category contain?",
    "How is a new skill pack created and registered in CosySim?",
    "What is the NLM Forge skill pack and what tools does it provide?",
    # Deployment
    "What is the startup order for CosySim services?",
    "How does the Copilot CLI session_start hook use Nexus for onboarding context?",
    "How does the preCompaction hook protect Nexus knowledge before context loss?",
]

# ── Generator prompts ─────────────────────────────────────────────────────
STUDY_GUIDE_PROMPT = (
    "Create a comprehensive study guide covering: "
    "(1) CosySim architecture and core systems, "
    "(2) LMStudio integration patterns, "
    "(3) Nexus knowledge system design, "
    "(4) Agent skill development, "
    "(5) Scene creation workflow, "
    "(6) Local agent task execution, "
    "(7) NotebookLM integration and workflow. "
    "Include key concepts, code patterns, and best practices for each section."
)

BRIEFING_PROMPT = (
    "Generate an executive briefing document about the CosySim system covering: "
    "system purpose, core capabilities, hardware requirements, key integrations, "
    "current status (v0.62), and roadmap toward full local agent autonomy."
)

FAQ_PROMPT = (
    "Generate 30 frequently asked questions with detailed answers covering: "
    "how to create new scenes and skills, how to configure LMStudio models, "
    "how to use the Nexus knowledge system, how local agents pick up tasks, "
    "how NotebookLM integration works, and common debugging scenarios."
)


# ── Source bundle builders ────────────────────────────────────────────────

def _read_file(path: Path, max_chars: int = 80_000) -> str:
    """Read a file safely, truncating if needed."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[TRUNCATED — original {len(text):,} chars]"
        return text
    except Exception as exc:
        return f"[Could not read {path}: {exc}]"


def _bundle_files(paths: List[Path], header: str, max_total: int = 150_000) -> str:
    """Bundle multiple files into one labelled text block."""
    parts = [f"{'='*70}\n{header}\nGenerated: {datetime.now(timezone.utc).isoformat()}\n{'='*70}\n"]
    total = len(parts[0])
    for p in paths:
        if not p.exists():
            continue
        label = f"\n{'─'*50}\nFILE: {p.relative_to(_ROOT)}\n{'─'*50}\n"
        content = _read_file(p, max_chars=min(20_000, max_total - total))
        entry = label + content + "\n"
        if total + len(entry) > max_total:
            parts.append(f"\n[Bundle truncated at {p.name} — size limit reached]")
            break
        parts.append(entry)
        total += len(entry)
    return "".join(parts)


def build_hardware_system_doc() -> str:
    """Build a comprehensive hardware + system specification document."""
    changelog = _read_file(_ROOT / "CHANGELOG.md", max_chars=8000)
    readme = _read_file(_ROOT / "README.md", max_chars=6000)
    roadmap = _read_file(_ROOT / "ROADMAP.md", max_chars=6000)

    return f"""{'='*70}
COSYSIM SYSTEM SPECIFICATION
Hardware, Software, Models, Services
Generated: {datetime.now(timezone.utc).isoformat()}
{'='*70}

## HARDWARE

### Primary Workstation — NUC Beast Canyon
- CPU: Intel Core i9 (NUC Beast Canyon)
- RAM: 32 GB DDR4
- GPU: NVIDIA RTX 2060 12GB VRAM (CUDA enabled)
- Storage: NVMe SSD
- OS: Windows 11
- Shell: PowerShell 7+
- Python: 3.10+
- Node.js: 18+ (for MCP servers)

### Mobile Device
- Phone: Samsung Galaxy S22 Ultra (12GB RAM, 256GB, Snapdragon 8 Gen 1)
- Software: Google Edge Gallery Beta (tflite/onnx model server), AnythingLLM mobile
- On-device models: gemma-3n-E2B-it-int4, gemma-E4B-int4, gemma3-1B-IT-q4,
  Qwen2.5-1B-Instruct-q8, gemma-function-270m

## EXTERNAL SERVICES

| Service       | Port | Purpose                                       |
|---------------|------|-----------------------------------------------|
| LMStudio      | 1234 | LLM inference (v1 API + OpenAI compat)        |
| ComfyUI       | 8188 | Image/video generation                        |
| Nexus KMS     | 8700 | Knowledge management + NLM proxy              |
| TTS Server    | 8600 | Text-to-speech (Qwen3 GPU)                    |
| Web Bridge    | 8601 | Socket.IO real-time bridge                    |
| Hub           | 8500 | Scene hub + admin navigation                  |
| Nexus Panel   | 5570 | Nexus dashboard + Librarian UI                |
| NLM Node MCP  | stdio| NotebookLM MCP via Patchright browser         |

## SOFTWARE STACK

### AI / ML Runtime
- LMStudio v1.x — local LLM inference server at localhost:1234
  - OpenAI-compatible API at /v1/chat/completions
  - Native v1 API at /api/v1/chat (SSE streaming, stateful, store:true)
  - Model loading: JIT (just-in-time), preload, or manual
  - Concurrent slots: 2 (configurable)
  - VRAM cap: 11,500 MB (leaves 500MB for OS/display)
- Python lmstudio SDK (lmstudio>=1.0.0) — typed Python client
- OpenAI Python SDK (openai>=2.14.0) — used for OpenAI-compat endpoint

### Web Framework
- Flask 2.x with Flask-SocketIO 5.x — scene web interfaces
- FastMCP 2.x — MCP server implementation (214 tools)
- Socket.IO — real-time bidirectional scene communication
- Jinja2 — HTML template engine
- Werkzeug — WSGI utilities

### Database / Storage
- Nexus KMS: SQLite3 + FTS5 at C:/Files/Nexus/data/nexus.db
  - 500+ knowledge entries, 1,720+ Q&A pairs, 40 governance rules
- SQLAlchemy 2.x — ORM for scene databases
- ChromaDB — vector embeddings (optional)

### AI / Training
- PyTorch 2.7.1 + CUDA 12.x — deep learning runtime
- Transformers 4.53.x — HuggingFace model loading
- PEFT 0.18.x — LoRA fine-tuning
- TensorRT 10.x — GPU inference optimisation
- ONNX Runtime GPU — Piper TTS acceleration
- llama-cpp-python — GGUF model inference (Orpheus TTS)

### NotebookLM Integration
- @pan-sec/notebooklm-mcp — Node.js MCP server (Patchright browser automation)
- Chrome profile: C:/Users/Knack/AppData/Local/notebooklm-mcp/chrome_profile
- 47 NLM tools exposed via stdio MCP protocol
- Batchexecute HTTP RPCs — direct API for batch operations
- HAR-based auth backup (cookie extraction from browser)

### Other Tools
- pytest 9.x — 5,147+ tests across 176 files
- Git — version control (conventional commits)
- VS Code — editor + Copilot CLI integration
- GitHub Copilot CLI — AI pair programmer + orchestrator
- psutil 7.x — system monitoring
- pydantic 2.x — data validation

## MODELS IN USE

| Model | Size | Use | Runtime |
|-------|------|-----|---------|
| Primary LLM | 7-70B | Reasoning, planning, coding | LMStudio |
| Router model | 270M | Request classification | LMStudio |
| Draft model | 3B | Speculative decoding | LMStudio |
| Piper TTS | ~80MB | Fast CPU TTS | ONNX Runtime |
| Orpheus 3B | Q4_K_M | Quality neural TTS | LMStudio / llama-cpp |
| Qwen3 TTS | 7B | GPU TTS | PyTorch CUDA |
| Gemma-3n-E2B | int4 | On-device (phone) | Edge Gallery |

## COSYSIM VERSION

{changelog[:4000]}

## README

{readme[:3000]}

## ROADMAP

{roadmap[:3000]}
"""


def build_engine_framework_bundle() -> str:
    """Bundle engine core: config, MCP framework, scenes base, agents."""
    paths = [
        _ROOT / "engine" / "config.py",
        _ROOT / "engine" / "mcp" / "__init__.py",
        _ROOT / "engine" / "mcp" / "framework.py",
        _ROOT / "engine" / "mcp" / "cosysim_server.py",
        _ROOT / "engine" / "scenes" / "base_scene.py",
        _ROOT / "engine" / "scenes" / "scene_manager.py",
        _ROOT / "engine" / "agents" / "virtual_agent.py",
        _ROOT / "engine" / "agents" / "interceptor_pipeline.py",
        _ROOT / "engine" / "agents" / "stream_processor.py",
        _ROOT / "engine" / "pipeline" / "virtual_pipeline.py",
    ]
    return _bundle_files(paths, "ENGINE FRAMEWORK — Config, MCP, Scenes, Agents")


def build_engine_nexus_bundle() -> str:
    """Bundle Nexus KMS engine modules."""
    paths = sorted((_ROOT / "engine" / "nexus").glob("*.py"))
    # Prioritise the most important ones first
    priority = [
        "client.py", "query_router.py", "governance_rules.py",
        "task_scheduler.py", "scheduler_daemon.py", "knowledge_forge.py",
        "nlm_notebook_manager.py", "news_nlm_pipeline.py",
        "local_agent_bridge.py", "copilot_bridge.py", "copilot_self_config.py",
        "nlm_research_pipeline.py", "qa_generator.py", "meta_metrics.py",
    ]
    ordered = []
    by_name = {p.name: p for p in paths}
    for name in priority:
        if name in by_name:
            ordered.append(by_name.pop(name))
    ordered.extend(sorted(by_name.values()))
    return _bundle_files(ordered, "ENGINE NEXUS — Knowledge Management System")


def build_engine_lmstudio_bundle() -> str:
    """Bundle LMStudio integration engine."""
    paths = sorted((_ROOT / "engine" / "lmstudio").glob("*.py"))
    return _bundle_files(paths, "ENGINE LMSTUDIO — LLM Inference Integration")


def build_engine_skills_bundle() -> str:
    """Bundle skill decorator + all builtin skill packs."""
    paths = [
        _ROOT / "engine" / "skills" / "skill.py",
        _ROOT / "engine" / "skills" / "registry.py",
    ]
    builtin_dir = _ROOT / "engine" / "skills" / "builtin"
    if builtin_dir.exists():
        paths.extend(sorted(builtin_dir.glob("*.py")))
    return _bundle_files(paths, "ENGINE SKILLS — @skill Decorator + All Builtin Packs")


def build_engine_mcp_tools_bundle() -> str:
    """Bundle MCP server tool definitions."""
    paths = [
        _ROOT / "engine" / "mcp" / "devtools_server.py",
        _ROOT / "engine" / "mcp" / "skills_server.py",
        _ROOT / "engine" / "mcp" / "nlm_hybrid.py",
        _ROOT / "engine" / "mcp" / "nlm_node_bridge.py",
        _ROOT / "engine" / "mcp" / "nlm_live_proxy.py",
    ]
    return _bundle_files(paths, "ENGINE MCP SERVERS — DevTools, NLM Hybrid, Node Bridge")


def build_engine_services_bundle() -> str:
    """Bundle TTS, integrations, services."""
    paths = []
    for subdir in ["tts", "integrations", "services", "assistant"]:
        d = _ROOT / "engine" / subdir
        if d.exists():
            paths.extend(sorted(d.glob("*.py")))
    return _bundle_files(paths, "ENGINE SERVICES — TTS, Integrations, Assistant, Services")


def build_scenes_bundle() -> str:
    """Bundle scene implementations (top 8 scenes)."""
    key_scenes = [
        "bedroom", "nexus_panel", "phone", "command_center",
        "lounge", "heist", "system_control", "games",
    ]
    paths = []
    for scene in key_scenes:
        scene_dir = _ROOT / "content" / "scenes" / scene
        if scene_dir.exists():
            paths.extend(sorted(scene_dir.glob("*.py")))
    return _bundle_files(paths, "SCENE IMPLEMENTATIONS — Top 8 Scenes")


def build_config_rules_bundle() -> str:
    """Bundle all config YAML + governance rules + Copilot instructions."""
    parts = ["=" * 70 + "\nCONFIG FILES, GOVERNANCE RULES & COPILOT INSTRUCTIONS\n" + "=" * 70 + "\n"]

    # YAML configs
    config_dir = _ROOT / "config"
    for yaml_file in sorted(config_dir.glob("*.yaml")):
        parts.append(f"\n{'─'*50}\nCONFIG: {yaml_file.name}\n{'─'*50}\n")
        parts.append(_read_file(yaml_file, max_chars=15_000))

    # Copilot instructions
    instructions_dir = _ROOT / ".github" / "instructions"
    if instructions_dir.exists():
        for md_file in sorted(instructions_dir.glob("*.md")):
            parts.append(f"\n{'─'*50}\nINSTRUCTION: {md_file.name}\n{'─'*50}\n")
            parts.append(_read_file(md_file, max_chars=8_000))

    # Copilot global instructions
    copilot_inst = _ROOT / ".github" / "copilot-instructions.md"
    if copilot_inst.exists():
        parts.append(f"\n{'─'*50}\nCOPILOT GLOBAL INSTRUCTIONS\n{'─'*50}\n")
        parts.append(_read_file(copilot_inst, max_chars=15_000))

    # Hooks config
    hooks_json = _ROOT / ".github" / "hooks" / "cosysim-hooks.json"
    if hooks_json.exists():
        parts.append(f"\n{'─'*50}\nHOOKS CONFIG: cosysim-hooks.json\n{'─'*50}\n")
        parts.append(_read_file(hooks_json, max_chars=5_000))

    return "".join(parts)[:150_000]


def build_docs_bundle() -> str:
    """Bundle all documentation files."""
    docs_dir = _ROOT / "docs"
    priority_docs = [
        "ARCHITECTURE.md", "MCP_FRAMEWORK.md", "NEXUS_INTEGRATION.md",
        "LMSTUDIO.md", "NOTEBOOKLM.md", "NOTEBOOKLM_PROTOCOL.md",
        "NOTEBOOKLM_SDK.md", "SKILLS.md", "SCENES.md", "API.md",
        "AGENT_ONBOARDING.md", "LOCAL_AGENT_GUIDE.md", "CONFIGURATION.md",
        "TESTING.md", "TTS.md", "DEPLOYMENT.md", "INTERCEPTORS.md",
    ]
    paths = []
    by_name = {p.name: p for p in docs_dir.glob("*.md")}
    for name in priority_docs:
        if name in by_name:
            paths.append(by_name.pop(name))
    paths.extend(sorted(by_name.values()))

    # Also include internal notes
    internal_dir = docs_dir / "internal"
    if internal_dir.exists():
        paths.extend(sorted(internal_dir.glob("*.md")))

    return _bundle_files(paths, "DOCUMENTATION — Architecture, Guides, Protocols")


def build_frontend_js_bundle() -> str:
    """Bundle all JavaScript frontend files."""
    js_dirs = [
        _ROOT / "content" / "shared" / "static" / "js",
        _ROOT / "content" / "scenes" / "bedroom" / "static" / "js",
        _ROOT / "content" / "scenes" / "nexus_panel" / "static" / "js",
        _ROOT / "content" / "scenes" / "phone" / "static" / "js",
        _ROOT / "content" / "scenes" / "command_center" / "static" / "js",
        _ROOT / "content" / "scenes" / "system_control" / "static" / "js",
        _ROOT / "deployment" / "chrome-nexus",
    ]
    paths = []
    for d in js_dirs:
        if d.exists():
            paths.extend(sorted(d.glob("*.js")))
    return _bundle_files(paths, "FRONTEND JAVASCRIPT — All Scene + Shared JS Code")


def build_tests_bundle() -> str:
    """Bundle key test files showing patterns and conventions."""
    key_tests = [
        "conftest.py",
        "test_mcp_framework.py",
        "test_nexus_client.py",
        "test_task_scheduler.py",
        "test_scheduler_daemon.py",
        "test_local_agent_bridge.py",
        "test_nlm_forge_skills.py",
        "test_nexus_panel.py",
        "test_bedroom_game.py",
        "test_copilot_bridge.py",
        "test_autonomy_skills.py",
        "test_news_nlm_pipeline.py",
    ]
    tests_dir = _ROOT / "tests"
    paths = []
    for name in key_tests:
        p = tests_dir / name
        if p.exists():
            paths.append(p)
    return _bundle_files(paths, "TEST SUITE — Key Tests Showing Patterns and Conventions")


def build_dependencies_bundle() -> str:
    """Bundle requirements, package.json, and pyproject.toml."""
    parts = ["=" * 70 + "\nDEPENDENCIES & PACKAGE MANIFESTS\n" + "=" * 70 + "\n"]

    # requirements.txt
    req = _ROOT / "requirements.txt"
    if req.exists():
        parts.append("\n## requirements.txt (Python)\n")
        parts.append(_read_file(req, max_chars=25_000))

    # pyproject.toml
    pyp = _ROOT / "pyproject.toml"
    if pyp.exists():
        parts.append("\n\n## pyproject.toml\n")
        parts.append(_read_file(pyp, max_chars=5_000))

    # package.json files
    for pj in _ROOT.rglob("package.json"):
        if "node_modules" in str(pj):
            continue
        parts.append(f"\n\n## {pj.relative_to(_ROOT)}\n")
        parts.append(_read_file(pj, max_chars=3_000))

    # .python-version
    pv = _ROOT / ".python-version"
    if pv.exists():
        parts.append(f"\n\n## .python-version\n{pv.read_text().strip()}\n")

    return "".join(parts)[:80_000]


# ── Source manifest ───────────────────────────────────────────────────────

def build_all_sources() -> List[Tuple[str, str, str]]:
    """Build all source bundles.

    Returns:
        List of (label, content, source_type) tuples.
        source_type is 'text' (for bundles) or 'url' (for SDK docs).
    """
    logger.info("Building source bundles...")
    bundles: List[Tuple[str, str, str]] = [
        ("CosySim Hardware & System Specification", build_hardware_system_doc(), "text"),
        ("Engine Framework: Config, MCP, Scenes, Agents", build_engine_framework_bundle(), "text"),
        ("Engine Nexus: Knowledge Management System", build_engine_nexus_bundle(), "text"),
        ("Engine LMStudio: LLM Inference Integration", build_engine_lmstudio_bundle(), "text"),
        ("Engine MCP Servers: DevTools, NLM Hybrid, Bridges", build_engine_mcp_tools_bundle(), "text"),
        ("Engine Skills: @skill Decorator + All Builtin Packs", build_engine_skills_bundle(), "text"),
        ("Engine Services: TTS, Integrations, Assistant", build_engine_services_bundle(), "text"),
        ("Scene Implementations: Top 8 Scenes", build_scenes_bundle(), "text"),
        ("Config Files, Governance Rules & Copilot Instructions", build_config_rules_bundle(), "text"),
        ("Documentation: Architecture, Guides, Protocols", build_docs_bundle(), "text"),
        ("Frontend JavaScript: All Scene + Shared JS", build_frontend_js_bundle(), "text"),
        ("Test Suite: Patterns and Conventions", build_tests_bundle(), "text"),
        ("Dependencies: requirements.txt, package.json, pyproject.toml", build_dependencies_bundle(), "text"),
    ]
    # Add SDK URL sources
    for sdk in SDK_URLS:
        bundles.append((sdk["label"], sdk["url"], "url"))

    logger.info("Built %d source bundles (%d text, %d URLs)",
                len(bundles),
                sum(1 for _, _, t in bundles if t == "text"),
                sum(1 for _, _, t in bundles if t == "url"))
    return bundles


# ── Main workflow ─────────────────────────────────────────────────────────

class MasterNotebookBuilder:
    """Orchestrates the complete master notebook build and generator workflow."""

    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self._bridge: Optional[Any] = None
        self._hybrid: Optional[Any] = None
        self._nexus: Optional[Any] = None
        self._state = _load_state()

    def _get_bridge(self) -> Any:
        if self._bridge is None:
            from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
            self._bridge = get_nlm_node_bridge()
        return self._bridge

    def _get_hybrid(self) -> Any:
        if self._hybrid is None:
            from engine.mcp.nlm_hybrid import get_nlm_hybrid
            self._hybrid = get_nlm_hybrid()
        return self._hybrid

    def _get_nexus(self) -> Any:
        if self._nexus is None:
            from engine.nexus.client import get_nexus_client
            self._nexus = get_nexus_client()
        return self._nexus

    # ── Step 1: Create notebook ───────────────────────────────────────────

    def create_or_find_notebook(self) -> str:
        """Create the master notebook, or return existing ID from state."""
        existing_id = self._state.get("notebook_id", "")
        if existing_id:
            logger.info("Reusing existing master notebook: %s", existing_id)
            return existing_id

        logger.info("Creating master notebook: %s %s", NOTEBOOK_NAME, NOTEBOOK_VERSION)
        if self.dry_run:
            fake_id = "dry-run-notebook-id"
            self._state["notebook_id"] = fake_id
            _save_state(self._state)
            return fake_id

        bridge = self._get_bridge()
        result = bridge.create_notebook(f"{NOTEBOOK_NAME} {NOTEBOOK_VERSION}")
        nb_id = result.get("notebook_id", result.get("id", ""))
        if not nb_id:
            raise RuntimeError(f"Failed to create notebook: {result}")

        self._state["notebook_id"] = nb_id
        self._state["created_at"] = datetime.now(timezone.utc).isoformat()
        self._state["sources_uploaded"] = []
        _save_state(self._state)
        logger.info("Created notebook: %s", nb_id)
        return nb_id

    # ── Step 2: Upload sources ────────────────────────────────────────────

    def upload_sources(self, notebook_id: str) -> Dict[str, Any]:
        """Upload all source bundles and SDK URLs to the notebook."""
        sources = build_all_sources()
        uploaded_labels = set(self._state.get("sources_uploaded", []))
        results: Dict[str, Any] = {"text": 0, "url": 0, "skipped": 0, "failed": 0}

        bridge = self._get_bridge()
        hybrid = self._get_hybrid()

        for label, content, source_type in sources:
            if label in uploaded_labels:
                logger.debug("Skipping already-uploaded: %s", label)
                results["skipped"] += 1
                continue

            logger.info("Uploading [%s]: %s", source_type.upper(), label[:60])
            if self.dry_run:
                logger.info("  [DRY-RUN] Would upload %d chars", len(content))
                results[source_type] += 1
                continue

            try:
                if source_type == "url":
                    r = bridge.add_url_source(notebook_id, content)  # content = URL
                else:
                    r = hybrid.add_text_source(notebook_id, content, title=label)

                if r.get("error"):
                    logger.warning("Failed to upload '%s': %s", label, r["error"])
                    results["failed"] += 1
                else:
                    results[source_type] += 1
                    uploaded_labels.add(label)
                    self._state["sources_uploaded"] = list(uploaded_labels)
                    _save_state(self._state)

                # Respectful pacing
                time.sleep(2.0)

            except Exception as exc:
                logger.warning("Error uploading '%s': %s", label, exc)
                results["failed"] += 1

        logger.info("Upload complete: %s", results)
        return results

    # ── Step 3: Run all generators ────────────────────────────────────────

    def run_all_generators(self, notebook_id: str) -> Dict[str, Any]:
        """Run every available NotebookLM generator and store outputs in Nexus."""
        results: Dict[str, Any] = {}
        nexus = self._get_nexus()

        # 3a. Audio overview — standard
        logger.info("Generating standard audio overview...")
        results["audio_standard"] = self._run_generator(
            "audio_standard", notebook_id,
            lambda nb: self._get_bridge().generate_audio(nb, style="standard"),
        )

        # 3b. Audio overview — deep dive
        logger.info("Generating deep-dive audio overview...")
        results["audio_deep"] = self._run_generator(
            "audio_deep", notebook_id,
            lambda nb: self._get_bridge().generate_audio(nb, style="deep_dive"),
        )

        # 3c. Video overview
        logger.info("Generating video overview...")
        results["video"] = self._run_generator(
            "video", notebook_id,
            lambda nb: self._get_bridge().generate_video(nb),
        )

        # 3d. Study guide (via ask)
        logger.info("Generating study guide...")
        results["study_guide"] = self._run_ask_generator(
            "study_guide", notebook_id, STUDY_GUIDE_PROMPT, nexus,
            nexus_title="CosySim Study Guide (NLM Generated)",
            nexus_type="document", nexus_category="learning",
        )

        # 3e. Briefing document
        logger.info("Generating briefing document...")
        results["briefing"] = self._run_ask_generator(
            "briefing", notebook_id, BRIEFING_PROMPT, nexus,
            nexus_title="CosySim Executive Briefing (NLM Generated)",
            nexus_type="document", nexus_category="architecture",
        )

        # 3f. FAQ document
        logger.info("Generating FAQ document...")
        results["faq"] = self._run_ask_generator(
            "faq", notebook_id, FAQ_PROMPT, nexus,
            nexus_title="CosySim FAQ: 30 Questions (NLM Generated)",
            nexus_type="document", nexus_category="learning",
        )

        # 3g. Data table extraction
        logger.info("Extracting data tables...")
        results["tables"] = self._run_generator(
            "tables", notebook_id,
            lambda nb: self._get_bridge().extract_tables(
                nb, query="service ports, model profiles, skill categories, hardware specs"
            ),
        )

        return results

    def _run_generator(self, key: str, notebook_id: str, fn: Any) -> Dict[str, Any]:
        """Run a generator, skip if already done, log result."""
        done = self._state.get("generators_done", [])
        if key in done:
            logger.debug("Skipping already-done generator: %s", key)
            return {"status": "skipped"}
        if self.dry_run:
            return {"status": "dry-run"}
        try:
            result = fn(notebook_id)
            if not result.get("error"):
                done.append(key)
                self._state["generators_done"] = done
                _save_state(self._state)
            return result
        except Exception as exc:
            logger.warning("Generator %s failed: %s", key, exc)
            return {"error": str(exc)}

    def _run_ask_generator(
        self,
        key: str,
        notebook_id: str,
        prompt: str,
        nexus: Any,
        nexus_title: str,
        nexus_type: str,
        nexus_category: str,
    ) -> Dict[str, Any]:
        """Run an ask-based generator and store result in Nexus."""
        done = self._state.get("generators_done", [])
        if key in done:
            return {"status": "skipped"}
        if self.dry_run:
            return {"status": "dry-run"}
        try:
            bridge = self._get_bridge()
            result = bridge.ask_question(notebook_id, prompt, session_id=f"gen-{key}")
            answer = result.get("answer", "")
            if answer and len(answer) > 100:
                nexus.add_entry(
                    title=nexus_title,
                    content=answer,
                    content_type=nexus_type,
                    category=nexus_category,
                )
                done.append(key)
                self._state["generators_done"] = done
                _save_state(self._state)
                logger.info("Stored %s in Nexus (%d chars)", nexus_title, len(answer))
            return {"status": "done", "chars": len(answer)}
        except Exception as exc:
            logger.warning("Ask generator %s failed: %s", key, exc)
            return {"error": str(exc)}

    # ── Step 4: Q&A distillation ──────────────────────────────────────────

    def run_qa_distillation(self, notebook_id: str) -> Dict[str, Any]:
        """Ask all 35 distillation questions and store answers in Nexus."""
        done_idx = self._state.get("qa_done_index", 0)
        questions = DISTILLATION_QUESTIONS[done_idx:]
        if not questions:
            logger.info("All distillation questions already answered.")
            return {"status": "complete", "total": len(DISTILLATION_QUESTIONS)}

        if self.dry_run:
            return {"status": "dry-run", "questions": len(questions)}

        logger.info("Running Q&A distillation: %d questions remaining", len(questions))
        nexus = self._get_nexus()
        bridge = self._get_bridge()
        stored = 0
        failed = 0

        for i, question in enumerate(questions, start=done_idx):
            logger.info("  Q%d/%d: %s", i + 1, len(DISTILLATION_QUESTIONS), question[:70])
            try:
                result = bridge.ask_question(notebook_id, question, session_id="master-qa")
                answer = result.get("answer", "")
                if answer and len(answer) > 50 and not result.get("error"):
                    nexus.add_qa(
                        question=question,
                        answer=answer,
                        category="master-notebook",
                    )
                    stored += 1
                else:
                    failed += 1

                self._state["qa_done_index"] = i + 1
                _save_state(self._state)
                time.sleep(3.0)  # respectful pacing between NLM requests

            except Exception as exc:
                logger.warning("Q&A distillation failed at Q%d: %s", i + 1, exc)
                failed += 1

        return {"stored": stored, "failed": failed, "total": len(DISTILLATION_QUESTIONS)}

    # ── Full orchestration ────────────────────────────────────────────────

    def build(
        self,
        notebook_id: Optional[str] = None,
        sources_only: bool = False,
        generators_only: bool = False,
    ) -> Dict[str, Any]:
        """Run the full master notebook build workflow.

        Args:
            notebook_id: Use existing notebook (skip creation).
            sources_only: Only upload sources, skip generators.
            generators_only: Skip sources, only run generators.

        Returns:
            Dict with all step results.
        """
        report: Dict[str, Any] = {"started_at": datetime.now(timezone.utc).isoformat()}

        # Step 1: Create or find notebook
        if notebook_id:
            self._state["notebook_id"] = notebook_id
            _save_state(self._state)
        else:
            notebook_id = self.create_or_find_notebook()
        report["notebook_id"] = notebook_id

        # Step 2: Upload sources
        if not generators_only:
            logger.info("=== STEP 2: Uploading sources ===")
            report["upload"] = self.upload_sources(notebook_id)

        # Step 3: Run generators
        if not sources_only:
            logger.info("=== STEP 3: Running generators ===")
            report["generators"] = self.run_all_generators(notebook_id)

            # Step 4: Q&A distillation
            logger.info("=== STEP 4: Q&A distillation ===")
            report["qa_distillation"] = self.run_qa_distillation(notebook_id)

        # Store completion record in Nexus
        if not self.dry_run:
            try:
                nexus = self._get_nexus()
                nexus.add_entry(
                    title=f"Master Notebook Build Complete — {NOTEBOOK_VERSION}",
                    content=json.dumps(report, indent=2, default=str),
                    content_type="history",
                    category="master-notebook",
                )
            except Exception as exc:
                logger.debug("Could not store build report in Nexus: %s", exc)

        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        self._state["last_build"] = report["completed_at"]
        _save_state(self._state)

        logger.info("=== MASTER NOTEBOOK BUILD COMPLETE ===")
        logger.info("Notebook ID: %s", notebook_id)
        return report


# ── State persistence ─────────────────────────────────────────────────────

def _load_state() -> Dict[str, Any]:
    """Load persistent builder state."""
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text())
    except Exception:
        pass
    return {}


def _save_state(state: Dict[str, Any]) -> None:
    """Save persistent builder state."""
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as exc:
        logger.debug("Could not save state: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────────────

_builder_instance: Optional[MasterNotebookBuilder] = None


def get_master_notebook_builder(dry_run: bool = False) -> MasterNotebookBuilder:
    """Get the singleton MasterNotebookBuilder."""
    global _builder_instance
    if _builder_instance is None:
        _builder_instance = MasterNotebookBuilder(dry_run=dry_run)
    return _builder_instance


# ── Scheduler integration ─────────────────────────────────────────────────

def refresh_master_notebook() -> Dict[str, Any]:
    """Weekly refresh callback for the scheduler.

    Re-uploads changed sources and re-runs distillation for new Q&A.
    Does NOT recreate the notebook — reuses existing ID.
    """
    try:
        builder = MasterNotebookBuilder(dry_run=False)
        state = _load_state()
        # Reset source upload list so changed files are re-uploaded
        state["sources_uploaded"] = []
        state.pop("qa_done_index", None)
        _save_state(state)
        return builder.build(sources_only=False)
    except Exception as exc:
        logger.error("Master notebook refresh failed: %s", exc)
        return {"error": str(exc)}


# ── CLI ───────────────────────────────────────────────────────────────────

def _cli() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="CosySim Master Notebook Builder")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would happen without making NLM calls")
    parser.add_argument("--sources-only", action="store_true",
                        help="Only upload sources, skip generators and Q&A")
    parser.add_argument("--generators-only", action="store_true",
                        help="Skip source upload, only run generators and Q&A")
    parser.add_argument("--notebook-id", default="",
                        help="Use an existing notebook ID instead of creating a new one")
    parser.add_argument("--reset", action="store_true",
                        help="Reset state (forces fresh notebook creation and full re-upload)")
    args = parser.parse_args()

    if args.reset:
        _STATE_FILE.unlink(missing_ok=True)
        logger.info("State reset. Fresh build will start.")

    builder = MasterNotebookBuilder(dry_run=args.dry_run)
    report = builder.build(
        notebook_id=args.notebook_id or None,
        sources_only=args.sources_only,
        generators_only=args.generators_only,
    )

    print("\n=== BUILD REPORT ===")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    _cli()
