"""ARGUS browser automation and HAR analysis MCP skills.

Provides agent-accessible tools for HAR file mining, rpcid discovery,
endpoint management, and cross-service intelligence gathering.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


@skill(pack="argus", description="Mine HAR files for rpcids, API endpoints, and service patterns", category="system")
def mine_har_files(har_dir: str = "artifacts/argus/har", pattern: str = "*.har") -> str:
    """Mine HAR files using streaming regex for large file support.

    Args:
        har_dir: Directory containing HAR files.
        pattern: Glob pattern for HAR files.

    Returns:
        JSON summary of discovered endpoints, rpcids, build labels.
    """
    from scripts.argus.har_miner import HARMiner
    miner = HARMiner()
    results = miner.mine_directory(Path(har_dir), pattern)
    return json.dumps({
        "rpcids_found": len(results.get("rpcids", [])),
        "api_urls_found": len(results.get("api_urls", [])),
        "build_labels": results.get("build_labels", []),
        "domains": results.get("domains", [])[:20],
        "files_scanned": results.get("files_scanned", 0)
    }, indent=2)


@skill(pack="argus", description="Map discovered rpcids to their batchexecute services", category="system")
def map_rpcids_to_services(har_path: str = "") -> str:
    """Map rpcids to batchexecute services by scanning URL context.

    Args:
        har_path: Path to specific HAR file (or empty for all).

    Returns:
        JSON mapping of rpcid -> service name.
    """
    from scripts.argus.rpcid_mapper import RpcidMapper
    mapper = RpcidMapper()
    if har_path:
        mapping = mapper.map_file(Path(har_path))
    else:
        mapping = mapper.map_directory(Path("artifacts/argus/har"))
    return json.dumps(mapping, indent=2)


@skill(pack="argus", description="Extract f.req payload patterns for rpcids to decode their operations", category="system")
def extract_rpcid_payloads(rpcids: str = "", har_path: str = "") -> str:
    """Extract f.req POST bodies to understand rpcid operation semantics.

    Args:
        rpcids: Comma-separated rpcids to extract (or empty for all).
        har_path: Specific HAR file path (or empty for all).

    Returns:
        JSON with decoded payload patterns per rpcid.
    """
    from scripts.argus.rpcid_payload_extractor import PayloadExtractor
    extractor = PayloadExtractor()
    target_rpcids = [r.strip() for r in rpcids.split(",")] if rpcids else None
    if har_path:
        results = extractor.extract_file(Path(har_path), target_rpcids)
    else:
        results = extractor.extract_directory(Path("artifacts/argus/har"), target_rpcids)
    return json.dumps(results, indent=2)


@skill(pack="argus", description="Get current RPC registry stats — counts per service, coverage metrics", category="system")
def get_rpc_registry_stats() -> str:
    """Get statistics about the NLM RPC registry YAML.

    Returns:
        JSON with section counts, rpcid totals, coverage metrics.
    """
    import yaml
    yaml_path = Path("config/nlm_rpcids.yaml")
    if not yaml_path.exists():
        return json.dumps({"error": "nlm_rpcids.yaml not found"})

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    stats: Dict[str, Any] = {
        "version": data.get("meta", {}).get("version", "unknown"),
        "har_enrichment": data.get("meta", {}).get("har_enrichment_version", "unknown"),
        "total_sections": len(data),
        "sections": {}
    }

    for section, content in data.items():
        if section == "meta":
            continue
        if isinstance(content, dict):
            rpcids = content.get("rpcids", {})
            operations = content.get("operations", {})
            endpoints = content.get("endpoints", {})
            methods = content.get("methods", {})
            count = len(rpcids) + len(operations) + len(endpoints) + len(methods)
            if count > 0:
                stats["sections"][section] = count

    stats["total_endpoints"] = sum(stats["sections"].values())
    return json.dumps(stats, indent=2)


@skill(pack="argus", description="Cross-reference rpcids between HAR captures and YAML registry", category="system")
def cross_reference_rpcids(har_dir: str = "artifacts/argus/har") -> str:
    """Find rpcids in HAR files not yet in the registry YAML.

    Args:
        har_dir: Directory to scan for HAR files.

    Returns:
        JSON with known, new, and missing rpcids.
    """
    import yaml
    from scripts.argus.har_miner import HARMiner

    miner = HARMiner()
    results = miner.mine_directory(Path(har_dir))
    har_rpcids = set(results.get("rpcids", []))

    yaml_path = Path("config/nlm_rpcids.yaml")
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    known_rpcids: set[str] = set()

    def _collect(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "rpcid" and isinstance(v, str):
                    known_rpcids.add(v)
                if k == "rpcids" and isinstance(v, dict):
                    known_rpcids.update(v.keys())
                _collect(v)
    _collect(data)

    new_rpcids = har_rpcids - known_rpcids
    confirmed = har_rpcids & known_rpcids

    return json.dumps({
        "har_total": len(har_rpcids),
        "yaml_total": len(known_rpcids),
        "confirmed_in_both": len(confirmed),
        "new_in_har": sorted(list(new_rpcids)),
        "new_count": len(new_rpcids)
    }, indent=2)


@skill(pack="argus", description="List all batchexecute services discovered across Google products", category="system")
def list_batchexecute_services() -> str:
    """List all known batchexecute service endpoints.

    Returns:
        JSON with service name, host, rpc path, and rpcid count.
    """
    import yaml
    yaml_path = Path("config/nlm_rpcids.yaml")
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    services_section = data.get("batchexecute_services", {}).get("services", {})
    if not services_section:
        return json.dumps({"error": "No batchexecute_services section in YAML"})

    services: List[Dict[str, Any]] = []
    for name, info in services_section.items():
        services.append({
            "name": name,
            "host": info.get("host", "unknown"),
            "path": info.get("path", "unknown"),
            "rpcid_count": info.get("rpcid_count", 0),
            "notes": info.get("notes", "")
        })

    return json.dumps({"services": services, "total": len(services)}, indent=2)


@skill(pack="argus", description="Get AppCatalyst API endpoints including Gemini 3 model access", category="system")
def get_appcatalyst_endpoints() -> str:
    """Get all discovered AppCatalyst API endpoints.

    Returns:
        JSON with endpoint paths, methods, and model info.
    """
    import yaml
    yaml_path = Path("config/nlm_rpcids.yaml")
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    ac = data.get("appcatalyst", {})
    if not ac:
        return json.dumps({"error": "No appcatalyst section in YAML"})

    endpoints: List[Dict[str, Any]] = []
    for name, info in ac.get("endpoints", {}).items():
        ep: Dict[str, Any] = {
            "name": name,
            "path": info.get("path", ""),
            "method": info.get("method", ""),
            "description": info.get("description", ""),
            "category": info.get("category", "")
        }
        if "models_confirmed" in info:
            ep["models"] = info["models_confirmed"]
        endpoints.append(ep)

    return json.dumps({
        "host": ac.get("meta", {}).get("grpc_host", ""),
        "base_path": ac.get("meta", {}).get("base_path", ""),
        "endpoints": endpoints,
        "total": len(endpoints)
    }, indent=2)


@skill(pack="argus", description="Search RPC registry for rpcids by category, service, or keyword", category="system")
def search_rpc_registry(query: str = "", service: str = "", category: str = "") -> str:
    """Search the RPC registry YAML for matching entries.

    Args:
        query: Free-text search in descriptions and notes.
        service: Filter by service section (gemini, opal, aistudio, etc.).
        category: Filter by category (chat, account, session, etc.).

    Returns:
        JSON with matching rpcid entries.
    """
    import yaml
    yaml_path = Path("config/nlm_rpcids.yaml")
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    matches: List[Dict[str, Any]] = []
    query_lower = query.lower() if query else ""

    def _search_section(section_name: str, section_data: Any) -> None:
        if not isinstance(section_data, dict):
            return
        for subsection in ["rpcids", "operations", "endpoints", "methods"]:
            items = section_data.get(subsection, {})
            if not isinstance(items, dict):
                continue
            for rpcid, info in items.items():
                if not isinstance(info, dict):
                    continue
                if service and section_name != service:
                    continue
                if category and info.get("category", "") != category:
                    continue
                if query_lower:
                    text = f"{info.get('description', '')} {info.get('notes', '')} {rpcid}".lower()
                    if query_lower not in text:
                        continue
                matches.append({
                    "service": section_name,
                    "rpcid": rpcid,
                    "description": info.get("description", ""),
                    "category": info.get("category", ""),
                    "confirmed": info.get("confirmed", "")
                })

    for section_name, section_data in data.items():
        if section_name == "meta":
            continue
        _search_section(section_name, section_data)

    return json.dumps({"matches": matches, "total": len(matches)}, indent=2)


@skill(pack="argus", description="Get Gemini streaming endpoint details for real-time chat integration", category="system")
def get_gemini_streaming_info() -> str:
    """Get Gemini streaming endpoint configuration.

    Returns:
        JSON with streaming endpoint path, transport, and auth details.
    """
    import yaml
    yaml_path = Path("config/nlm_rpcids.yaml")
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    streaming = data.get("gemini_streaming", {})
    if not streaming:
        return json.dumps({"error": "No gemini_streaming section in YAML"})

    return json.dumps({
        "service": streaming.get("meta", {}).get("service_name", ""),
        "base_url": streaming.get("meta", {}).get("base_url", ""),
        "transport": streaming.get("meta", {}).get("transport", ""),
        "endpoints": {
            name: {
                "path": ep.get("path", ""),
                "method": ep.get("method", ""),
                "transport": ep.get("transport", ""),
                "description": ep.get("description", "")
            }
            for name, ep in streaming.get("endpoints", {}).items()
        }
    }, indent=2)


@skill(pack="argus", description="Get build labels for all discovered Google services", category="system")
def get_build_labels() -> str:
    """Get the latest build labels for all Google services.

    Returns:
        JSON with service -> build label mapping.
    """
    import yaml
    yaml_path = Path("config/nlm_rpcids.yaml")
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    labels = data.get("meta", {}).get("build_labels_latest", {})

    for section_name, section_data in data.items():
        if isinstance(section_data, dict):
            meta = section_data.get("meta", {})
            bl = meta.get("build_label", "")
            if bl and section_name not in labels:
                labels[section_name] = bl

    return json.dumps(labels, indent=2)
