"""
ARGUS Analyzer Data Types
==========================

All dataclasses for the generic API discovery engine.
Used by HAR analyzer, heap analyzer, protocol detector, and registry.

Version: v1.50.0 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.50.0 [2026-03-25] — Initial generic analyzer data types
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


# ──── Protocol Types ─────────────────────────────────────────────────────────

class ProtocolType(Enum):
    """Detected protocol type for a network request."""
    BATCHEXECUTE = "batchexecute"
    GRPC_WEB = "grpc_web"
    GRAPHQL = "graphql"
    REST_JSON = "rest_json"
    REST_FORM = "rest_form"
    WEBSOCKET = "websocket"
    PROTOBUF = "protobuf"
    MULTIPART = "multipart"
    UNKNOWN = "unknown"


@dataclass
class ProtocolDetection:
    """Result of protocol auto-detection on a single request."""
    protocol: ProtocolType
    confidence: float  # 0.0–1.0
    evidence: str      # Why this was classified this way


# ──── Endpoint & Auth ────────────────────────────────────────────────────────

@dataclass
class EndpointInfo:
    """A discovered API endpoint."""
    url: str
    method: str                         # HTTP method (GET, POST, etc.)
    protocol: ProtocolType
    frequency: int = 1                  # How many times seen
    domain: str = ""
    base_path: str = ""                 # URL path without query params
    query_params: List[str] = field(default_factory=list)
    content_types: Set[str] = field(default_factory=set)
    status_codes: List[int] = field(default_factory=list)
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url, "method": self.method,
            "protocol": self.protocol.value, "frequency": self.frequency,
            "domain": self.domain, "base_path": self.base_path,
            "query_params": self.query_params,
            "content_types": sorted(self.content_types),
            "status_codes": self.status_codes,
        }


@dataclass
class AuthScheme:
    """A detected authentication scheme."""
    scheme_type: str       # "bearer", "cookie", "api_key", "basic", "sapisidhash", "custom_header"
    header_name: str       # e.g., "Authorization", "X-API-Key"
    example_pattern: str   # Redacted pattern
    frequency: int = 1
    endpoints: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scheme_type": self.scheme_type, "header_name": self.header_name,
            "example_pattern": self.example_pattern, "frequency": self.frequency,
            "endpoints_count": len(self.endpoints),
        }


@dataclass
class APIPattern:
    """A grouping of endpoints by protocol type."""
    pattern_type: ProtocolType
    base_url: str
    endpoints_count: int = 0
    example_urls: List[str] = field(default_factory=list)


@dataclass
class TokenInfo:
    """A discovered token or API key (REDACTED)."""
    token_type: str    # "api_key", "bearer", "session", "csrf"
    location: str      # "header", "url_param", "cookie", "body"
    key_name: str      # Parameter/header name
    redacted_value: str  # first8...last4
    frequency: int = 1


@dataclass
class RateLimitInfo:
    """Detected rate limiting on an endpoint."""
    endpoint: str
    status_429_count: int = 0
    retry_after_values: List[str] = field(default_factory=list)
    rate_limit_headers: Dict[str, str] = field(default_factory=dict)


@dataclass
class CookieInfo:
    """A discovered cookie."""
    name: str
    domain: str = ""
    secure: bool = False
    http_only: bool = False
    same_site: str = ""
    frequency: int = 1


@dataclass
class GraphQLOperation:
    """A discovered GraphQL operation."""
    operation_type: str        # "query" | "mutation" | "subscription"
    operation_name: Optional[str] = None
    frequency: int = 1
    variables_keys: List[str] = field(default_factory=list)


# ──── Service Grouping ───────────────────────────────────────────────────────

@dataclass
class ServiceGroup:
    """Endpoints grouped by service/domain."""
    service_name: str
    domain: str
    base_urls: List[str] = field(default_factory=list)
    endpoints: List[EndpointInfo] = field(default_factory=list)
    auth_schemes: List[AuthScheme] = field(default_factory=list)
    protocols: Set[ProtocolType] = field(default_factory=set)
    request_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "service_name": self.service_name, "domain": self.domain,
            "endpoints_count": len(self.endpoints),
            "protocols": sorted(p.value for p in self.protocols),
            "request_count": self.request_count,
        }


# ──── Analysis Reports ───────────────────────────────────────────────────────

@dataclass
class HARAnalysisReport:
    """Complete analysis report for a HAR file."""
    file_path: str
    file_size_mb: float = 0.0
    total_entries: int = 0
    unique_endpoints: List[EndpointInfo] = field(default_factory=list)
    auth_schemes: List[AuthScheme] = field(default_factory=list)
    api_patterns: List[APIPattern] = field(default_factory=list)
    tokens_found: List[TokenInfo] = field(default_factory=list)
    rate_limits: List[RateLimitInfo] = field(default_factory=list)
    graphql_operations: List[GraphQLOperation] = field(default_factory=list)
    websocket_urls: List[str] = field(default_factory=list)
    cookies: List[CookieInfo] = field(default_factory=list)
    service_groups: List[ServiceGroup] = field(default_factory=list)
    domains: Dict[str, int] = field(default_factory=dict)
    protocol_breakdown: Dict[str, int] = field(default_factory=dict)
    errors: int = 0
    analysis_duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "file_size_mb": round(self.file_size_mb, 2),
            "total_entries": self.total_entries,
            "unique_endpoints": len(self.unique_endpoints),
            "auth_schemes": [a.to_dict() for a in self.auth_schemes],
            "tokens_found": len(self.tokens_found),
            "rate_limits": len(self.rate_limits),
            "graphql_operations": len(self.graphql_operations),
            "websocket_urls": self.websocket_urls,
            "service_groups": [s.to_dict() for s in self.service_groups],
            "domains": self.domains,
            "protocol_breakdown": self.protocol_breakdown,
            "analysis_duration_ms": round(self.analysis_duration_ms, 1),
        }


@dataclass
class HeapAnalysisReport:
    """Analysis report for a V8 heap snapshot."""
    file_path: str
    file_size_mb: float = 0.0
    total_strings: int = 0
    urls: List[str] = field(default_factory=list)
    api_endpoints: List[str] = field(default_factory=list)
    method_names: List[str] = field(default_factory=list)
    rpcid_candidates: List[str] = field(default_factory=list)
    service_paths: List[str] = field(default_factory=list)
    config_objects: List[Dict] = field(default_factory=list)
    api_keys: List[str] = field(default_factory=list)  # redacted
    analysis_duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "file_size_mb": round(self.file_size_mb, 2),
            "total_strings": self.total_strings,
            "urls": len(self.urls),
            "api_endpoints": len(self.api_endpoints),
            "method_names": len(self.method_names),
            "rpcid_candidates": len(self.rpcid_candidates),
            "config_objects": len(self.config_objects),
            "api_keys": len(self.api_keys),
            "analysis_duration_ms": round(self.analysis_duration_ms, 1),
        }


@dataclass
class HeapDiffReport:
    """Diff report between two heap snapshots."""
    before_path: str
    after_path: str
    new_urls: List[str] = field(default_factory=list)
    new_api_endpoints: List[str] = field(default_factory=list)
    new_method_names: List[str] = field(default_factory=list)
    new_rpcid_candidates: List[str] = field(default_factory=list)
    new_config_objects: List[Dict] = field(default_factory=list)
    removed_count: int = 0
    analysis_duration_ms: float = 0.0
