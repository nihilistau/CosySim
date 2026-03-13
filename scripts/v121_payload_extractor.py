"""v1.21 Deep Payload Extractor — extracts actual payload structures for new services.

Targets:
- 15 Apps Script rpcids from script.google.com
- 26 AI Studio MakerSuiteService gRPC methods
- 2 AppletControl methods
- 6 Colab Agent gRPC methods
- 1 NLM direct gRPC-web method (GenerateFreeFormStreamed)
- 4 Drive v1 frontend endpoints
- Workspace Gemini payloads from docs-sheets HAR
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import urllib.parse
from collections import defaultdict
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

HAR_DIR = os.path.join("data", "har_files", "users_dump_folder")

# Target-specific HARs for deep payload extraction
TARGETS = {
    "appscript": {
        "hars": ["script.google.com.har"],
        "host_match": "script.google.com",
        "type": "batchexecute",
    },
    "aistudio_grpc": {
        "hars": [
            "aistudio.google.com-clean.har",
            "aistudio.google.com-gemini-app-2.har",
            "aistudio.google.com-nihilistcod.har",
            "aistudio.google.com-capped-apprunning.har",
        ],
        "host_match": "alkalimakersuite-pa.clients6.google.com",
        "type": "grpc",
    },
    "colab_grpc": {
        "hars": ["colab.research.google.com-goldmine-nihilistcod.har"],
        "host_match": "colab.clients6.google.com",
        "type": "grpc",
    },
    "nlm_grpc": {
        "hars": [
            "notebooklm_knack112358-latest.har",
            "notebooklm.google.com-FRESH.har",
            "notebooklm.google.com-jackpot-nihilistcod.har",
        ],
        "host_match": "notebooklm.google.com",
        "type": "grpc_and_batch",
    },
    "drive_frontend": {
        "hars": ["drive.google.com.har", "docs.-google.com-sheets-gemini2.har"],
        "host_match": "drivefrontend-pa.clients6.google.com",
        "type": "grpc",
    },
    "workspace_gemini": {
        "hars": ["docs.-google.com-sheets-gemini2.har"],
        "host_match": "appsgenaiserver-pa.clients6.google.com",
        "type": "rest",
    },
}


def extract_batchexecute_payloads(har_path: str, host_filter: str) -> dict[str, list[dict]]:
    """Extract full batchexecute payloads per rpcid from a HAR file."""
    results: dict[str, list[dict]] = defaultdict(list)
    try:
        with open(har_path, "r", encoding="utf-8", errors="replace") as f:
            har = json.load(f)
    except Exception as e:
        logger.error("Failed to load %s: %s", har_path, e)
        return results

    entries = har.get("log", {}).get("entries", [])
    for entry in entries:
        req = entry.get("request", {})
        url = req.get("url", "")
        parsed = urllib.parse.urlparse(url)

        if host_filter not in (parsed.hostname or ""):
            continue
        if "batchexecute" not in url:
            continue

        body = _get_post_body(req)
        if not body:
            continue

        decoded = urllib.parse.unquote(body)
        # Extract individual rpc envelopes from the f.req payload
        rpcid_blocks = _parse_freq_envelopes(decoded)
        for rpcid, envelope in rpcid_blocks:
            resp = entry.get("response", {})
            resp_body = resp.get("content", {}).get("text", "")
            resp_size = resp.get("bodySize", len(resp_body))
            status = resp.get("status", 0)

            # Extract source-path from URL
            qs = urllib.parse.parse_qs(parsed.query)
            source_path = qs.get("source-path", [""])[0]

            results[rpcid].append({
                "envelope": envelope[:2000],  # truncate large payloads
                "envelope_full_size": len(envelope),
                "response_size": resp_size,
                "status": status,
                "source_path": source_path,
                "url_params": {k: v[0] for k, v in qs.items() if k != "f.req"},
            })

    return dict(results)


def _parse_freq_envelopes(decoded: str) -> list[tuple[str, str]]:
    """Parse f.req body into (rpcid, inner_payload) pairs."""
    results = []
    # Pattern: [["rpcid","payload_json",null,"generic"]
    pattern = r'\[\["([A-Za-z0-9_]{3,12})","((?:[^"\\]|\\.)*)","?(null|"[^"]*")"?'
    for match in re.finditer(pattern, decoded):
        rpcid = match.group(1)
        inner = match.group(2)
        # Unescape the inner JSON
        try:
            inner_clean = inner.replace('\\"', '"').replace("\\\\", "\\")
            results.append((rpcid, inner_clean))
        except Exception:
            results.append((rpcid, inner[:500]))

    # Also try the simpler extraction for cases where payload is null
    simple_pattern = r'\["([A-Za-z0-9_]{3,12})",null,null'
    for match in re.finditer(simple_pattern, decoded):
        rpcid = match.group(1)
        if not any(r[0] == rpcid for r in results):
            results.append((rpcid, "null"))

    return results


def extract_grpc_payloads(har_path: str, host_filter: str) -> dict[str, list[dict]]:
    """Extract gRPC-web request/response info from HAR."""
    results: dict[str, list[dict]] = defaultdict(list)
    try:
        with open(har_path, "r", encoding="utf-8", errors="replace") as f:
            har = json.load(f)
    except Exception as e:
        logger.error("Failed to load %s: %s", har_path, e)
        return results

    entries = har.get("log", {}).get("entries", [])
    for entry in entries:
        req = entry.get("request", {})
        resp = entry.get("response", {})
        url = req.get("url", "")
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""

        if host_filter not in host:
            continue

        path = parsed.path
        # Match gRPC paths: /$rpc/service.name/Method or /service.path/Method
        if "$rpc/" in path or "google.internal" in path or "LabsTailwind" in path:
            # Extract method name
            if "$rpc/" in path:
                method_path = path.split("$rpc/")[1]
            else:
                # Direct gRPC path like /google.internal.labs.tailwind.../Method
                method_path = path.lstrip("/").split("?")[0]

            # Get request body info
            req_body = _get_post_body(req)
            req_ct = _get_header(req, "content-type")
            resp_body = resp.get("content", {}).get("text", "")
            resp_ct = _get_header(resp, "content-type")
            status = resp.get("status", 0)

            # Try to parse request body as JSON
            req_structure = _analyze_body(req_body, req_ct)
            resp_structure = _analyze_body(resp_body, resp_ct)

            # Extract auth info
            auth = _get_header(req, "authorization")
            api_key = ""
            qs = urllib.parse.parse_qs(parsed.query)
            if "key" in qs:
                api_key = qs["key"][0]

            results[method_path].append({
                "status": status,
                "request_content_type": req_ct,
                "response_content_type": resp_ct,
                "request_size": len(req_body) if req_body else 0,
                "response_size": len(resp_body) if resp_body else 0,
                "request_structure": req_structure,
                "response_structure": resp_structure,
                "auth_type": "bearer" if auth and "Bearer" in auth else "sapisidhash" if auth and "SAPISIDHASH" in auth else "api_key" if api_key else "none",
                "api_key": api_key[:20] + "..." if api_key else "",
                "url_params": {k: v[0] for k, v in qs.items() if k not in ("key",)},
            })

    return dict(results)


def extract_rest_payloads(har_path: str, host_filter: str) -> dict[str, list[dict]]:
    """Extract REST endpoint payloads from HAR."""
    results: dict[str, list[dict]] = defaultdict(list)
    try:
        with open(har_path, "r", encoding="utf-8", errors="replace") as f:
            har = json.load(f)
    except Exception as e:
        logger.error("Failed to load %s: %s", har_path, e)
        return results

    entries = har.get("log", {}).get("entries", [])
    for entry in entries:
        req = entry.get("request", {})
        resp = entry.get("response", {})
        url = req.get("url", "")
        method = req.get("method", "")
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""

        if host_filter not in host:
            continue
        if method not in ("POST", "PUT", "PATCH"):
            continue

        path = parsed.path
        # Normalize path — strip dynamic IDs
        norm_path = re.sub(r"/[a-zA-Z0-9_-]{20,}/", "/{id}/", path)

        req_body = _get_post_body(req)
        req_ct = _get_header(req, "content-type")
        resp_body = resp.get("content", {}).get("text", "")
        status = resp.get("status", 0)

        req_structure = _analyze_body(req_body, req_ct)
        resp_structure = _analyze_body(resp_body, _get_header(resp, "content-type"))

        # Extract API key
        qs = urllib.parse.parse_qs(parsed.query)
        api_key = qs.get("key", [""])[0]

        endpoint = f"{method} {norm_path}"
        results[endpoint].append({
            "status": status,
            "request_content_type": req_ct,
            "request_size": len(req_body) if req_body else 0,
            "response_size": len(resp_body) if resp_body else 0,
            "request_structure": req_structure,
            "response_structure": resp_structure,
            "api_key": api_key[:20] + "..." if api_key else "",
        })

    return dict(results)


def _get_post_body(req: dict) -> str:
    """Extract POST body from HAR request."""
    pd = req.get("postData", {})
    if pd.get("text"):
        return pd["text"]
    if pd.get("params"):
        for p in pd["params"]:
            if p.get("name") == "f.req":
                return p.get("value", "")
        # Return all params concatenated
        return "&".join(f"{p.get('name', '')}={p.get('value', '')}" for p in pd["params"])
    return ""


def _get_header(obj: dict, name: str) -> str:
    """Get header value from HAR request/response."""
    for h in obj.get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _analyze_body(body: str, content_type: str) -> dict[str, Any] | None:
    """Analyze request/response body structure."""
    if not body:
        return None

    result: dict[str, Any] = {"size": len(body)}

    # Try JSON parse
    if "json" in content_type.lower() or body.strip().startswith(("{", "[")):
        try:
            parsed = json.loads(body)
            result["format"] = "json"
            if isinstance(parsed, dict):
                result["top_keys"] = list(parsed.keys())[:20]
                result["key_count"] = len(parsed)
            elif isinstance(parsed, list):
                result["format"] = "json_array"
                result["length"] = len(parsed)
                if parsed and isinstance(parsed[0], dict):
                    result["first_item_keys"] = list(parsed[0].keys())[:10]
            return result
        except (json.JSONDecodeError, TypeError):
            pass

    # Try protobuf-JSON (array of arrays)
    if body.strip().startswith("["):
        try:
            parsed = json.loads(body)
            result["format"] = "protobuf_json"
            result["depth"] = _depth(parsed)
            if isinstance(parsed, list):
                result["length"] = len(parsed)
            return result
        except (json.JSONDecodeError, TypeError):
            pass

    # Binary (gRPC-web)
    if "grpc" in content_type.lower() or "proto" in content_type.lower():
        result["format"] = "grpc_binary"
        return result

    # Text
    result["format"] = "text"
    result["preview"] = body[:200]
    return result


def _depth(obj: Any, current: int = 0) -> int:
    """Get nesting depth."""
    if isinstance(obj, list) and obj:
        return max(_depth(item, current + 1) for item in obj)
    if isinstance(obj, dict) and obj:
        return max(_depth(v, current + 1) for v in obj.values())
    return current


def main() -> None:
    all_results: dict[str, Any] = {}

    for target_name, config in TARGETS.items():
        logger.info("=" * 60)
        logger.info("Extracting: %s", target_name)
        logger.info("=" * 60)

        target_results: dict[str, Any] = {"methods": {}}

        for har_name in config["hars"]:
            har_path = os.path.join(HAR_DIR, har_name)
            if not os.path.isfile(har_path):
                logger.warning("  SKIP: %s not found", har_name)
                continue

            fsize = os.path.getsize(har_path) / (1024 * 1024)
            logger.info("  Processing %s (%.1f MB)...", har_name, fsize)

            if config["type"] == "batchexecute":
                payloads = extract_batchexecute_payloads(har_path, config["host_match"])
                for rpcid, samples in payloads.items():
                    if rpcid not in target_results["methods"]:
                        target_results["methods"][rpcid] = {
                            "type": "batchexecute",
                            "samples": [],
                            "total_count": 0,
                        }
                    target_results["methods"][rpcid]["samples"].extend(samples[:3])
                    target_results["methods"][rpcid]["total_count"] += len(samples)
                logger.info("    Found %d unique rpcids", len(payloads))

            elif config["type"] == "grpc":
                payloads = extract_grpc_payloads(har_path, config["host_match"])
                for method, samples in payloads.items():
                    if method not in target_results["methods"]:
                        target_results["methods"][method] = {
                            "type": "grpc",
                            "samples": [],
                            "total_count": 0,
                        }
                    target_results["methods"][method]["samples"].extend(samples[:3])
                    target_results["methods"][method]["total_count"] += len(samples)
                logger.info("    Found %d unique gRPC methods", len(payloads))

            elif config["type"] == "rest":
                payloads = extract_rest_payloads(har_path, config["host_match"])
                for endpoint, samples in payloads.items():
                    if endpoint not in target_results["methods"]:
                        target_results["methods"][endpoint] = {
                            "type": "rest",
                            "samples": [],
                            "total_count": 0,
                        }
                    target_results["methods"][endpoint]["samples"].extend(samples[:3])
                    target_results["methods"][endpoint]["total_count"] += len(samples)
                logger.info("    Found %d unique REST endpoints", len(payloads))

            elif config["type"] == "grpc_and_batch":
                # Both gRPC-web and batchexecute
                grpc_payloads = extract_grpc_payloads(har_path, config["host_match"])
                for method, samples in grpc_payloads.items():
                    if method not in target_results["methods"]:
                        target_results["methods"][method] = {
                            "type": "grpc",
                            "samples": [],
                            "total_count": 0,
                        }
                    target_results["methods"][method]["samples"].extend(samples[:3])
                    target_results["methods"][method]["total_count"] += len(samples)

                batch_payloads = extract_batchexecute_payloads(har_path, config["host_match"])
                for rpcid, samples in batch_payloads.items():
                    if rpcid not in target_results["methods"]:
                        target_results["methods"][rpcid] = {
                            "type": "batchexecute",
                            "samples": [],
                            "total_count": 0,
                        }
                    target_results["methods"][rpcid]["samples"].extend(samples[:3])
                    target_results["methods"][rpcid]["total_count"] += len(samples)

                logger.info("    Found %d gRPC + %d batch methods",
                            len(grpc_payloads), len(batch_payloads))

        all_results[target_name] = target_results
        logger.info("  Total methods for %s: %d", target_name, len(target_results["methods"]))

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("EXTRACTION SUMMARY")
    logger.info("=" * 60)

    for target_name, data in all_results.items():
        methods = data["methods"]
        logger.info("\n%s: %d methods", target_name.upper(), len(methods))
        for method_name in sorted(methods.keys()):
            info = methods[method_name]
            mtype = info["type"]
            count = info["total_count"]
            sample = info["samples"][0] if info["samples"] else {}

            if mtype == "batchexecute":
                env_size = sample.get("envelope_full_size", 0) if sample else 0
                logger.info("  [batch] %s: count=%d, payload_size=%d", method_name, count, env_size)
            elif mtype == "grpc":
                req_size = sample.get("request_size", 0) if sample else 0
                auth = sample.get("auth_type", "") if sample else ""
                logger.info("  [grpc]  %s: count=%d, req_size=%d, auth=%s", method_name, count, req_size, auth)
            elif mtype == "rest":
                req_ct = sample.get("request_content_type", "") if sample else ""
                logger.info("  [rest]  %s: count=%d, content_type=%s", method_name, count, req_ct)

    # Save results
    outpath = os.path.join("data", "heap_output", "v121_payload_extraction.json")
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, default=str)
    logger.info("\nSaved to %s", outpath)


if __name__ == "__main__":
    main()
