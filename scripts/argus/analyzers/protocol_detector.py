"""
ARGUS Protocol Auto-Detector
==============================

Classifies any HTTP request into a protocol type based on URL patterns,
Content-Type headers, and request body shape. No hardcoded domain checks —
works on traffic from any web application.

Version: v1.50.0 [2026-03-25]
Author:  CosySim Team

CONNECTS: HARAnalyzer, GenericEndpointRegistry
CALLED BY: HARAnalyzer._classify_entry()
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from scripts.argus.analyzers.data_types import ProtocolDetection, ProtocolType


# ──── URL patterns ───────────────────────────────────────────────────────────

_BATCHEXECUTE_URL = re.compile(r"/_/[^/]+/data/batchexecute", re.I)
_GRPC_URL = re.compile(r"\$rpc/", re.I)
_GRAPHQL_URL = re.compile(r"/graphql\b", re.I)
_WEBSOCKET_URL = re.compile(r"^wss?://", re.I)

# ──── Content-Type patterns ──────────────────────────────────────────────────

_GRPC_CT = re.compile(r"application/grpc-web", re.I)
_PROTOBUF_CT = re.compile(r"application/(x-)?protobuf", re.I)
_JSON_CT = re.compile(r"application/json", re.I)
_FORM_CT = re.compile(r"application/x-www-form-urlencoded", re.I)
_MULTIPART_CT = re.compile(r"multipart/form-data", re.I)


class ProtocolDetector:
    """Auto-detect the protocol of any HTTP request.

    Detection priority (highest confidence first):
    1. URL pattern match (batchexecute, gRPC, GraphQL, WebSocket)
    2. Content-Type header match
    3. Request body shape heuristic (GraphQL query/mutation)
    4. Fallback to UNKNOWN
    """

    def detect(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        post_body: Optional[str] = None,
    ) -> ProtocolDetection:
        """Detect protocol from request components.

        Args:
            url: Full request URL.
            method: HTTP method.
            headers: Request headers (case-insensitive lookup).
            post_body: Raw POST body text.

        Returns:
            ProtocolDetection with type, confidence, and evidence.
        """
        headers = headers or {}
        ct = ""
        for k, v in headers.items():
            if k.lower() == "content-type":
                ct = v
                break

        # ── 1. URL pattern match (highest confidence) ────────────
        if _WEBSOCKET_URL.search(url):
            return ProtocolDetection(ProtocolType.WEBSOCKET, 1.0, f"WebSocket URL: {url[:60]}")

        if _BATCHEXECUTE_URL.search(url):
            return ProtocolDetection(ProtocolType.BATCHEXECUTE, 1.0, f"batchexecute URL pattern")

        if _GRPC_URL.search(url):
            return ProtocolDetection(ProtocolType.GRPC_WEB, 1.0, f"$rpc/ in URL")

        if _GRAPHQL_URL.search(url):
            return ProtocolDetection(ProtocolType.GRAPHQL, 0.95, f"/graphql in URL")

        # ── 2. Content-Type match ────────────────────────────────
        if _GRPC_CT.search(ct):
            return ProtocolDetection(ProtocolType.GRPC_WEB, 0.95, f"Content-Type: {ct}")

        if _PROTOBUF_CT.search(ct):
            return ProtocolDetection(ProtocolType.PROTOBUF, 0.9, f"Content-Type: {ct}")

        if _MULTIPART_CT.search(ct):
            return ProtocolDetection(ProtocolType.MULTIPART, 0.9, f"Content-Type: {ct}")

        # ── 3. Body heuristic (for JSON bodies) ─────────────────
        if post_body and _JSON_CT.search(ct):
            try:
                body = json.loads(post_body)
                if isinstance(body, dict):
                    if "query" in body or "mutation" in body:
                        return ProtocolDetection(ProtocolType.GRAPHQL, 0.85,
                                                 "JSON body with 'query'/'mutation' key")
            except (json.JSONDecodeError, ValueError):
                pass

        # ── 4. batchexecute body heuristic ───────────────────────
        if post_body and ("f.req=" in post_body or "f.req%3D" in post_body):
            return ProtocolDetection(ProtocolType.BATCHEXECUTE, 0.8, "f.req= in POST body")

        # ── 5. Generic Content-Type fallback ─────────────────────
        if _JSON_CT.search(ct):
            return ProtocolDetection(ProtocolType.REST_JSON, 0.7, f"Content-Type: {ct}")

        if _FORM_CT.search(ct):
            return ProtocolDetection(ProtocolType.REST_FORM, 0.7, f"Content-Type: {ct}")

        # ── 6. Method-based heuristic ────────────────────────────
        if method in ("GET", "HEAD", "OPTIONS", "DELETE"):
            return ProtocolDetection(ProtocolType.REST_JSON, 0.5, f"HTTP {method} (assumed REST)")

        return ProtocolDetection(ProtocolType.UNKNOWN, 0.1, "No matching pattern")

    def detect_har_entry(self, entry: Dict[str, Any]) -> ProtocolDetection:
        """Detect protocol from a HAR log entry.

        Args:
            entry: A single entry from har["log"]["entries"].

        Returns:
            ProtocolDetection.
        """
        req = entry.get("request", {})
        url = req.get("url", "")
        method = req.get("method", "GET")

        # Build headers dict from HAR format
        headers = {}
        for h in req.get("headers", []):
            headers[h.get("name", "")] = h.get("value", "")

        # Get POST body
        post_body = None
        post_data = req.get("postData", {})
        if post_data:
            post_body = post_data.get("text", "")

        return self.detect(url, method, headers, post_body)
