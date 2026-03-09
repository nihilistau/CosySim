"""Canonical system-domain registry for the system-first CosySim architecture."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Sequence

# NOTE: engine.nexus.knowledge_capture is imported lazily inside
# store_system_inventory_snapshot() so that importing this module does not
# fail when the Nexus KMS service is offline or its dependencies are missing.

from engine.port_registry import get_target_metadata

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SystemDomain:
    """Logical system domain in the user-defined CosySim architecture split."""

    id: str
    name: str
    description: str
    roots: List[str] = field(default_factory=list)
    service_targets: List[str] = field(default_factory=list)
    scene_targets: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)
    nexus_queries: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


SYSTEM_DOMAINS: List[SystemDomain] = [
    SystemDomain(
        id="control_plane",
        name="Control Plane",
        description="Canonical runtime truth for launcher behavior, ports, health, and operator-facing status surfaces.",
        roots=[
            "launcher.py",
            "main.py",
            "engine/port_registry.py",
            "content/scenes/system_control",
            "scripts/scene_health_check.py",
        ],
        service_targets=["hub", "nexus_panel", "dashboard", "admin", "canvas", "canvas_api", "system_control"],
        depends_on=["nexus"],
        nexus_queries=["control plane", "port registry", "system control"],
        tags=["core", "operator", "control-plane"],
    ),
    SystemDomain(
        id="copilot_assistant",
        name="Copilot / Assistant",
        description="Copilot hooks, self-configuration, local-agent governance, and the future assistant interface.",
        roots=[
            ".github",
            "engine/nexus/copilot_bridge.py",
            "engine/nexus/copilot_self_config.py",
            "engine/assistant",
        ],
        depends_on=["nexus", "control_plane"],
        nexus_queries=["copilot", "assistant", "governance", "hooks"],
        tags=["copilot", "assistant", "governance"],
    ),
    SystemDomain(
        id="nexus",
        name="Nexus",
        description="Central knowledge, rules, history, workflows, and durable memory for the whole system.",
        roots=["engine/nexus"],
        service_targets=["nexus", "nexus_panel", "canvas", "canvas_api"],
        depends_on=["control_plane"],
        nexus_queries=["nexus architecture", "knowledge capture", "governance rules"],
        tags=["knowledge", "rules", "memory"],
    ),
    SystemDomain(
        id="lmstudio_agents",
        name="LMStudio / Agents",
        description="Local inference, routing, training, benchmarks, and agent execution surfaces.",
        roots=["engine/lmstudio", "engine/agents", "training"],
        service_targets=["lmstudio", "tts", "orpheus_tts", "whisper_stt"],
        depends_on=["nexus", "control_plane"],
        nexus_queries=["lmstudio", "router", "benchmarks", "agents"],
        tags=["inference", "routing", "training"],
    ),
    SystemDomain(
        id="mcp_skills",
        name="MCP / Skills / Communication",
        description="Decorator-based tools, communication flow, skills, MCP state, and governance wiring.",
        roots=["engine/mcp", "engine/skills", "engine/agents"],
        service_targets=["bridge"],
        depends_on=["nexus", "lmstudio_agents"],
        nexus_queries=["mcp", "skills", "interceptor pipeline"],
        tags=["mcp", "skills", "communication"],
    ),
    SystemDomain(
        id="services_integrations",
        name="Services / Integrations",
        description="Reusable services, bridges, sidecars, and external integration modules that support the core system.",
        roots=["engine/services", "engine/integrations", "content/apps"],
        service_targets=["bridge", "canvas_api", "canvas_sidecar", "comfyui"],
        depends_on=["control_plane", "nexus"],
        nexus_queries=["integrations", "services", "sidecars"],
        tags=["services", "integrations", "automation"],
    ),
    SystemDomain(
        id="google_research",
        name="Google Research Layer",
        description="NotebookLM, Gemini, AI Studio, Colab, Drive, and their auth/direct-control tooling.",
        roots=[
            "engine/integrations/google_service_profiles.py",
            "engine/integrations/google_account_pool.py",
            "engine/integrations/nlm_direct_client.py",
            "engine/mcp/nlm_live_proxy.py",
            "scripts/har_capture.py",
        ],
        service_targets=["nlm_proxy", "canvas", "canvas_api"],
        depends_on=["nexus", "services_integrations"],
        nexus_queries=["NotebookLM", "Gemini", "Colab", "Google auth"],
        tags=["notebooklm", "google", "research"],
    ),
    SystemDomain(
        id="scenes",
        name="Scenes",
        description="Pluggable interfaces, simulations, panels, and evaluation harnesses that sit on top of the main system.",
        roots=["content/scenes", "content/shared", "engine/scenes"],
        depends_on=["control_plane", "nexus", "mcp_skills"],
        nexus_queries=["scenes", "base scene", "ui panels"],
        tags=["ui", "simulations", "pluggable"],
    ),
    SystemDomain(
        id="home_assistant_device_control",
        name="Home Assistant / Device Control",
        description="Home Assistant, sensors, automations, and future device-control modules such as Logitech integration.",
        roots=["engine/integrations", "content/scenes/system_control", "docs"],
        depends_on=["nexus", "services_integrations", "copilot_assistant"],
        nexus_queries=["home assistant", "device control", "logitech"],
        tags=["home-assistant", "devices", "automation"],
    ),
    SystemDomain(
        id="argus_browser_control",
        name="ARGUS / Browser Control",
        description="ARGUS capture/mining, Playwright vision, browser automation, and online/offline recon tooling.",
        roots=["scripts/argus", "data/har_files", "tools"],
        service_targets=["nlm_proxy"],
        depends_on=["google_research", "services_integrations", "nexus"],
        nexus_queries=["argus", "playwright", "vision", "har capture"],
        tags=["argus", "browser-control", "recon"],
    ),
]


def _display_name(target_id: str) -> str:
    return target_id.replace("_", " ").title()


@lru_cache(maxsize=1)
def _launcher_catalogues() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Load launcher services/scenes lazily to avoid import-time cycles."""
    try:
        from engine.control_plane_registry import get_launcher_catalogue_templates
    except Exception:
        logger.debug("Launcher unavailable while building system inventory", exc_info=True)
        return {"services": {}, "scenes": {}}
    return get_launcher_catalogue_templates()


def _target_metadata(target_ids: Sequence[str]) -> List[Dict[str, Any]]:
    """Return normalized target metadata for the given IDs."""
    metadata: List[Dict[str, Any]] = []
    seen: List[str] = []
    for target_id in target_ids:
        if target_id in seen:
            continue
        seen.append(target_id)
        try:
            target = get_target_metadata(target_id)
            metadata.append(
                {
                    "id": target["id"],
                    "label": target["label"],
                    "group": target["group"],
                    "type": target.get("type"),
                    "port": target.get("port"),
                }
            )
        except KeyError:
            metadata.append(
                {
                    "id": target_id,
                    "label": _display_name(target_id),
                    "group": "external",
                    "type": None,
                    "port": None,
                }
            )
    return metadata


def _resolve_scene_targets(domain: SystemDomain) -> List[str]:
    """Resolve dynamic scene target membership for a domain."""
    if domain.id == "scenes" and not domain.scene_targets:
        return list(_launcher_catalogues()["scenes"].keys())
    return list(domain.scene_targets)


def _domain_inventory(domain: SystemDomain) -> Dict[str, Any]:
    """Convert a domain definition into a serializable inventory record."""
    service_target_ids = list(domain.service_targets)
    scene_target_ids = _resolve_scene_targets(domain)
    payload = asdict(domain)
    payload["service_target_ids"] = service_target_ids
    payload["scene_target_ids"] = scene_target_ids
    payload["service_targets"] = _target_metadata(service_target_ids)
    payload["scene_targets"] = _target_metadata(scene_target_ids)
    payload["root_count"] = len(domain.roots)
    payload["service_count"] = len(service_target_ids)
    payload["scene_count"] = len(scene_target_ids)
    return payload


def list_system_domains() -> List[SystemDomain]:
    """Return the ordered list of canonical system domains."""
    return list(SYSTEM_DOMAINS)


def get_system_domain(domain_id: str) -> SystemDomain:
    """Return a system domain by ID."""
    for domain in SYSTEM_DOMAINS:
        if domain.id == domain_id:
            return domain
    raise KeyError(f"Unknown system domain: {domain_id!r}")


def find_domains_for_path(path: str) -> List[SystemDomain]:
    """Find all domains whose declared roots cover the given repository path."""
    normalized = path.replace("\\", "/").strip("/")
    matches: List[SystemDomain] = []
    for domain in SYSTEM_DOMAINS:
        for root in domain.roots:
            root_normalized = root.replace("\\", "/").strip("/")
            if normalized == root_normalized or normalized.startswith(f"{root_normalized}/"):
                matches.append(domain)
                break
    return matches


def build_system_inventory(include_catalog: bool = True) -> Dict[str, Any]:
    """Build a machine-readable snapshot of the system-first architecture split."""
    catalogues = _launcher_catalogues()
    domains = [_domain_inventory(domain) for domain in SYSTEM_DOMAINS]
    inventory: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "domain_count": len(domains),
            "service_count": len(catalogues["services"]),
            "scene_count": len(catalogues["scenes"]),
            "nexus_first": True,
            "scene_plugin_model": True,
            "backfill_on_nexus_miss": True,
        },
        "capture_policy": {
            "nexus_first": True,
            "backfill_external_discoveries": True,
            "preferred_capture": ["knowledge_entry", "qa_pair"],
        },
        "domains": domains,
    }
    if include_catalog:
        inventory["services"] = _target_metadata(list(catalogues["services"].keys()))
        inventory["scenes"] = _target_metadata(list(catalogues["scenes"].keys()))
    return inventory


def render_system_inventory_text(include_catalog: bool = True) -> str:
    """Render the system inventory as a readable plain-text report."""
    inventory = build_system_inventory(include_catalog=include_catalog)
    summary = inventory["summary"]
    lines = [
        "CosySim System Inventory",
        "=" * 40,
        f"Domains: {summary['domain_count']}",
        f"Services: {summary['service_count']}",
        f"Scenes: {summary['scene_count']}",
        f"Nexus-first: {'yes' if summary['nexus_first'] else 'no'}",
        f"Backfill on Nexus miss: {'yes' if summary['backfill_on_nexus_miss'] else 'no'}",
    ]
    for domain in inventory["domains"]:
        lines.append(f"\n{domain['name'].upper()} [{domain['id']}]")
        lines.append(f"  {domain['description']}")
        if domain["depends_on"]:
            lines.append(f"  Depends on: {', '.join(domain['depends_on'])}")
        if domain["roots"]:
            lines.append(f"  Roots: {', '.join(domain['roots'])}")
        if domain["service_target_ids"]:
            lines.append(f"  Services: {', '.join(domain['service_target_ids'])}")
        if domain["scene_target_ids"]:
            lines.append(f"  Scenes: {', '.join(domain['scene_target_ids'])}")
    return "\n".join(lines)


def summarize_system_inventory() -> str:
    """Return a concise Q&A-friendly summary of the system split."""
    inventory = build_system_inventory(include_catalog=False)
    fragments = []
    for domain in inventory["domains"]:
        fragments.append(f"{domain['name']}: {domain['description']}")
    return (
        "CosySim is currently split into these system domains: "
        + "; ".join(fragments)
        + ". Scenes are treated as pluggable interfaces on top of the control plane, and Nexus is the central knowledge and rule layer."
    )


def store_system_inventory_snapshot(
    *,
    title: str = "System inventory snapshot",
    client: Any = None,
) -> Dict[str, Any]:
    """Store the current system inventory in Nexus as a document plus Q&A."""
    # Import lazily so this module is always importable even when Nexus is offline.
    from engine.nexus.knowledge_capture import capture_entry_and_qa  # noqa: PLC0415

    inventory = build_system_inventory(include_catalog=True)
    content = (
        f"{render_system_inventory_text(include_catalog=True)}\n\n"
        f"JSON Snapshot:\n{json.dumps(inventory, indent=2)}"
    )
    result = capture_entry_and_qa(
        title,
        content,
        question="How is CosySim currently split into systems?",
        answer=summarize_system_inventory(),
        category="architecture",
        content_type="document",
        tags=["system-inventory", "control-plane", "nexus-first"],
        client=client,
    )
    payload = result.to_dict()
    payload["inventory"] = inventory
    return payload
