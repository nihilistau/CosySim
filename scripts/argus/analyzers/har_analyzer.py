"""
ARGUS Generic HAR Analyzer
============================

Analyzes ANY HAR file to discover API endpoints, authentication schemes,
protocol types, tokens, rate limits, and GraphQL operations. Not limited
to Google services — works on traffic from any web application.

Usage:
    from scripts.argus.analyzers.har_analyzer import HARAnalyzer

    analyzer = HARAnalyzer()
    report = analyzer.analyze_file(Path("traffic.har"))
    print(report.to_dict())

Version: v1.50.0 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.50.0 [2026-03-25] — Initial generic HAR analyzer

CONNECTS: ProtocolDetector, BatchExecuteDecoder, GrpcWebDecoder, GenericEndpointRegistry
CALLED BY: CLI (analyze.py), MCP skills
EMITS: HARAnalysisReport
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlparse

from scripts.argus.analyzers.data_types import (
    APIPattern,
    AuthScheme,
    CookieInfo,
    EndpointInfo,
    GraphQLOperation,
    HARAnalysisReport,
    ProtocolType,
    RateLimitInfo,
    ServiceGroup,
    TokenInfo,
)
from scripts.argus.analyzers.protocol_detector import ProtocolDetector

logger = logging.getLogger(__name__)

# ──── Token / Key Patterns ───────────────────────────────────────────────────

_API_KEY_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),         # Google API key
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),            # OpenAI / Stripe secret
    re.compile(r"pk_(live|test)_[a-zA-Z0-9]{20,}"), # Stripe publishable
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),             # GitHub PAT
    re.compile(r"glpat-[a-zA-Z0-9_-]{20,}"),        # GitLab PAT
    re.compile(r"xoxb-[0-9]{10,}-[a-zA-Z0-9]{20,}"), # Slack bot token
]

_AUTH_HEADER_PATTERNS = re.compile(
    r"(auth|token|api.?key|secret|credential|x-api|x-auth)", re.I
)

# ──── Utility ────────────────────────────────────────────────────────────────


def _redact(value: str) -> str:
    """Redact a token value: first8...last4."""
    if len(value) <= 16:
        return value[:4] + "..." + value[-2:] if len(value) > 6 else "***"
    return value[:8] + "..." + value[-4:]


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    try:
        return urlparse(url).netloc.split(":")[0]
    except Exception:
        return ""


def _detect_service_name(domain: str) -> str:
    """Auto-detect a human-readable service name from a domain.

    Examples:
        api.stripe.com -> stripe
        hooks.slack.com -> slack
        notebooklm.google.com -> notebooklm
        graph.facebook.com -> facebook
        us-east-1.execute-api.amazonaws.com -> aws_apigateway
    """
    if not domain:
        return "unknown"

    parts = domain.split(".")
    # Remove common prefixes
    prefixes = {"api", "www", "hooks", "graph", "rest", "data", "cdn", "static", "assets"}
    # Remove common TLDs
    tlds = {"com", "org", "net", "io", "dev", "co", "uk", "app", "cloud"}

    clean = [p for p in parts if p not in prefixes and p not in tlds and len(p) > 1]
    if not clean:
        clean = [parts[0]]

    name = clean[0]

    # Special cases
    if "google" in domain and len(clean) > 1:
        name = clean[0]  # notebooklm.google.com -> notebooklm
    elif "amazonaws" in domain:
        name = "aws_apigateway"
    elif "azure" in domain:
        name = "azure"

    return name.replace("-", "_").lower()


# ──── HAR Analyzer ───────────────────────────────────────────────────────────


class HARAnalyzer:
    """Generic HAR file analyzer — discovers API endpoints in any traffic.

    CONNECTS: ProtocolDetector, existing ARGUS decoders
    CALLED BY: CLI (analyze.py), MCP skills
    EMITS: HARAnalysisReport
    """

    # Files over this size use streaming mode
    STREAMING_THRESHOLD_MB = 100

    def __init__(self) -> None:
        self._detector = ProtocolDetector()

    def analyze_file(self, path: Path) -> HARAnalysisReport:
        """Analyze a single HAR file.

        Args:
            path: Path to the .har file.

        Returns:
            Complete HARAnalysisReport.
        """
        start = time.time()
        file_size_mb = path.stat().st_size / (1024 * 1024)

        report = HARAnalysisReport(
            file_path=str(path),
            file_size_mb=file_size_mb,
        )

        try:
            har_data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("[ARGUS] Failed to parse HAR: %s", exc)
            report.errors = 1
            report.analysis_duration_ms = (time.time() - start) * 1000
            return report

        entries = har_data.get("log", {}).get("entries", [])
        report.total_entries = len(entries)

        # Accumulators
        endpoints: Dict[str, EndpointInfo] = {}       # key: "METHOD base_path"
        auth_schemes: Dict[str, AuthScheme] = {}       # key: scheme_type:header
        tokens: Dict[str, TokenInfo] = {}              # key: redacted_value
        rate_limits: Dict[str, RateLimitInfo] = {}     # key: endpoint
        graphql_ops: Dict[str, GraphQLOperation] = {}  # key: op_name
        cookies: Dict[str, CookieInfo] = {}            # key: name
        ws_urls: Set[str] = set()
        domains: Dict[str, int] = defaultdict(int)
        protocol_counts: Dict[str, int] = defaultdict(int)

        for entry in entries:
            try:
                self._process_entry(
                    entry, endpoints, auth_schemes, tokens,
                    rate_limits, graphql_ops, cookies, ws_urls,
                    domains, protocol_counts,
                )
            except Exception as exc:
                report.errors += 1
                logger.debug("[ARGUS] Entry processing error: %s", exc)

        # Build report
        report.unique_endpoints = sorted(endpoints.values(), key=lambda e: e.frequency, reverse=True)
        report.auth_schemes = list(auth_schemes.values())
        report.tokens_found = list(tokens.values())
        report.rate_limits = [r for r in rate_limits.values() if r.status_429_count > 0]
        report.graphql_operations = sorted(graphql_ops.values(), key=lambda g: g.frequency, reverse=True)
        report.websocket_urls = sorted(ws_urls)
        report.cookies = sorted(cookies.values(), key=lambda c: c.frequency, reverse=True)
        report.domains = dict(sorted(domains.items(), key=lambda x: x[1], reverse=True))
        report.protocol_breakdown = dict(sorted(protocol_counts.items(), key=lambda x: x[1], reverse=True))

        # Build service groups
        report.service_groups = self._build_service_groups(endpoints, auth_schemes, domains)

        # Build API patterns
        report.api_patterns = self._build_api_patterns(endpoints, protocol_counts)

        report.analysis_duration_ms = (time.time() - start) * 1000
        return report

    def analyze_directory(self, dir_path: Path, pattern: str = "*.har") -> List[HARAnalysisReport]:
        """Analyze all HAR files in a directory.

        Args:
            dir_path: Directory to scan.
            pattern: Glob pattern for HAR files.

        Returns:
            List of HARAnalysisReport, one per file.
        """
        reports = []
        for har_file in sorted(dir_path.glob(pattern)):
            logger.info("[ARGUS] Analyzing: %s", har_file.name)
            reports.append(self.analyze_file(har_file))
        return reports

    def compare(self, report_a: HARAnalysisReport, report_b: HARAnalysisReport) -> Dict[str, Any]:
        """Diff two analysis reports.

        Returns:
            Dict with new_endpoints, removed_endpoints, new_auth, new_tokens.
        """
        urls_a = {(e.base_path, e.method) for e in report_a.unique_endpoints}
        urls_b = {(e.base_path, e.method) for e in report_b.unique_endpoints}

        new = urls_b - urls_a
        removed = urls_a - urls_b

        return {
            "file_a": report_a.file_path,
            "file_b": report_b.file_path,
            "new_endpoints": [f"{m} {p}" for p, m in sorted(new)],
            "removed_endpoints": [f"{m} {p}" for p, m in sorted(removed)],
            "new_count": len(new),
            "removed_count": len(removed),
            "shared_count": len(urls_a & urls_b),
        }

    # ──── Entry Processing ───────────────────────────────────────────

    def _process_entry(
        self,
        entry: Dict[str, Any],
        endpoints: Dict[str, EndpointInfo],
        auth_schemes: Dict[str, AuthScheme],
        tokens: Dict[str, TokenInfo],
        rate_limits: Dict[str, RateLimitInfo],
        graphql_ops: Dict[str, GraphQLOperation],
        cookies: Dict[str, CookieInfo],
        ws_urls: Set[str],
        domains: Dict[str, int],
        protocol_counts: Dict[str, int],
    ) -> None:
        """Process a single HAR entry into all accumulators."""
        req = entry.get("request", {})
        resp = entry.get("response", {})
        url = req.get("url", "")
        method = req.get("method", "GET")

        if not url:
            return

        # Protocol detection
        detection = self._detector.detect_har_entry(entry)
        protocol_counts[detection.protocol.value] += 1

        # Domain tracking
        domain = _extract_domain(url)
        domains[domain] += 1

        # WebSocket
        if detection.protocol == ProtocolType.WEBSOCKET:
            ws_urls.add(url)
            return

        # Endpoint tracking
        parsed = urlparse(url)
        base_path = parsed.path
        key = f"{method} {domain}{base_path}"

        if key in endpoints:
            endpoints[key].frequency += 1
        else:
            qp = list(parse_qs(parsed.query).keys())
            ct_set: Set[str] = set()
            for h in req.get("headers", []):
                if h.get("name", "").lower() == "content-type":
                    ct_set.add(h.get("value", "").split(";")[0].strip())
            endpoints[key] = EndpointInfo(
                url=url, method=method, protocol=detection.protocol,
                frequency=1, domain=domain, base_path=base_path,
                query_params=qp, content_types=ct_set,
            )

        # Status code tracking
        status = resp.get("status", 0)
        if status:
            endpoints[key].status_codes.append(status)

        # Rate limit detection
        if status == 429:
            if key not in rate_limits:
                rate_limits[key] = RateLimitInfo(endpoint=key)
            rate_limits[key].status_429_count += 1
            for h in resp.get("headers", []):
                name = h.get("name", "").lower()
                if "retry" in name or "ratelimit" in name:
                    rate_limits[key].rate_limit_headers[h["name"]] = h.get("value", "")
                    if "retry-after" in name:
                        rate_limits[key].retry_after_values.append(h.get("value", ""))

        # Auth detection
        self._detect_auth(req, url, auth_schemes, tokens, key)

        # GraphQL extraction
        if detection.protocol == ProtocolType.GRAPHQL:
            self._extract_graphql(req, graphql_ops)

        # Cookie extraction
        for h in resp.get("headers", []):
            if h.get("name", "").lower() == "set-cookie":
                self._extract_cookie(h.get("value", ""), domain, cookies)

    # ──── Auth Detection ─────────────────────────────────────────────

    def _detect_auth(
        self,
        req: Dict[str, Any],
        url: str,
        auth_schemes: Dict[str, AuthScheme],
        tokens: Dict[str, TokenInfo],
        endpoint_key: str,
    ) -> None:
        """Detect authentication schemes from request headers and URL."""
        headers = {h.get("name", ""): h.get("value", "") for h in req.get("headers", [])}

        # Authorization header
        auth_val = headers.get("Authorization", "")
        if auth_val:
            if auth_val.lower().startswith("bearer "):
                self._register_auth(auth_schemes, "bearer", "Authorization", auth_val, endpoint_key)
                token = auth_val[7:]
                self._register_token(tokens, "bearer", "header", "Authorization", token)
            elif auth_val.lower().startswith("basic "):
                self._register_auth(auth_schemes, "basic", "Authorization", auth_val, endpoint_key)
            elif "SAPISIDHASH" in auth_val:
                self._register_auth(auth_schemes, "sapisidhash", "Authorization", auth_val, endpoint_key)
            else:
                self._register_auth(auth_schemes, "custom", "Authorization", auth_val, endpoint_key)

        # Custom auth headers
        for name, value in headers.items():
            if name == "Authorization":
                continue
            if _AUTH_HEADER_PATTERNS.search(name) and value:
                self._register_auth(auth_schemes, "custom_header", name, value, endpoint_key)
                self._register_token(tokens, "api_key", "header", name, value)

        # API keys in URL params
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        for key_name in ("key", "api_key", "apiKey", "apikey", "token", "access_token"):
            if key_name in params:
                val = params[key_name][0]
                self._register_auth(auth_schemes, "api_key", f"?{key_name}", val, endpoint_key)
                self._register_token(tokens, "api_key", "url_param", key_name, val)

        # Scan for known API key patterns in headers
        for name, value in headers.items():
            for pattern in _API_KEY_PATTERNS:
                if pattern.search(value):
                    self._register_token(tokens, "api_key", "header", name, value)

    def _register_auth(
        self, schemes: Dict, scheme_type: str, header: str, value: str, endpoint: str
    ) -> None:
        key = f"{scheme_type}:{header}"
        if key in schemes:
            schemes[key].frequency += 1
            if endpoint not in schemes[key].endpoints:
                schemes[key].endpoints.append(endpoint)
        else:
            schemes[key] = AuthScheme(
                scheme_type=scheme_type, header_name=header,
                example_pattern=_redact(value), frequency=1,
                endpoints=[endpoint],
            )

    def _register_token(
        self, tokens: Dict, token_type: str, location: str, key_name: str, value: str
    ) -> None:
        redacted = _redact(value)
        if redacted in tokens:
            tokens[redacted].frequency += 1
        else:
            tokens[redacted] = TokenInfo(
                token_type=token_type, location=location,
                key_name=key_name, redacted_value=redacted,
            )

    # ──── GraphQL Extraction ─────────────────────────────────────────

    def _extract_graphql(self, req: Dict[str, Any], ops: Dict[str, GraphQLOperation]) -> None:
        """Extract GraphQL operation details from request body."""
        post_data = req.get("postData", {})
        body_text = post_data.get("text", "")
        if not body_text:
            return
        try:
            body = json.loads(body_text)
            if isinstance(body, dict):
                self._parse_gql_body(body, ops)
            elif isinstance(body, list):
                for item in body:
                    if isinstance(item, dict):
                        self._parse_gql_body(item, ops)
        except (json.JSONDecodeError, ValueError):
            pass

    def _parse_gql_body(self, body: Dict, ops: Dict[str, GraphQLOperation]) -> None:
        query_str = body.get("query", body.get("mutation", ""))
        if not query_str:
            return

        # Detect operation type and name
        op_type = "query"
        op_name = None
        m = re.match(r"\s*(query|mutation|subscription)\s+(\w+)", query_str)
        if m:
            op_type = m.group(1)
            op_name = m.group(2)

        key = f"{op_type}:{op_name or 'anonymous'}"
        if key in ops:
            ops[key].frequency += 1
        else:
            vars_keys = list(body.get("variables", {}).keys()) if isinstance(body.get("variables"), dict) else []
            ops[key] = GraphQLOperation(
                operation_type=op_type, operation_name=op_name,
                frequency=1, variables_keys=vars_keys,
            )

    # ──── Cookie Extraction ──────────────────────────────────────────

    def _extract_cookie(self, set_cookie: str, domain: str, cookies: Dict[str, CookieInfo]) -> None:
        """Parse a Set-Cookie header value."""
        if not set_cookie:
            return
        parts = set_cookie.split(";")
        name_val = parts[0].strip()
        if "=" not in name_val:
            return
        name = name_val.split("=")[0].strip()
        if name in cookies:
            cookies[name].frequency += 1
            return

        secure = any("secure" in p.lower() for p in parts[1:])
        http_only = any("httponly" in p.lower() for p in parts[1:])
        same_site = ""
        for p in parts[1:]:
            if "samesite" in p.lower():
                same_site = p.split("=")[-1].strip() if "=" in p else ""

        cookies[name] = CookieInfo(
            name=name, domain=domain, secure=secure,
            http_only=http_only, same_site=same_site,
        )

    # ──── Service Grouping ───────────────────────────────────────────

    def _build_service_groups(
        self,
        endpoints: Dict[str, EndpointInfo],
        auth_schemes: Dict[str, AuthScheme],
        domains: Dict[str, int],
    ) -> List[ServiceGroup]:
        """Group endpoints by domain into ServiceGroups."""
        by_domain: Dict[str, List[EndpointInfo]] = defaultdict(list)
        for ep in endpoints.values():
            by_domain[ep.domain].append(ep)

        groups = []
        for domain, eps in sorted(by_domain.items(), key=lambda x: len(x[1]), reverse=True):
            if not domain:
                continue
            protocols = {ep.protocol for ep in eps}
            # Find auth schemes used on this domain's endpoints
            domain_auth = [
                a for a in auth_schemes.values()
                if any(domain in ep for ep in a.endpoints)
            ]
            groups.append(ServiceGroup(
                service_name=_detect_service_name(domain),
                domain=domain,
                endpoints=eps,
                auth_schemes=domain_auth,
                protocols=protocols,
                request_count=domains.get(domain, 0),
            ))
        return groups

    def _build_api_patterns(
        self, endpoints: Dict[str, EndpointInfo], protocol_counts: Dict[str, int]
    ) -> List[APIPattern]:
        """Build API pattern summary from endpoints."""
        by_protocol: Dict[ProtocolType, List[EndpointInfo]] = defaultdict(list)
        for ep in endpoints.values():
            by_protocol[ep.protocol].append(ep)

        patterns = []
        for proto, eps in sorted(by_protocol.items(), key=lambda x: len(x[1]), reverse=True):
            domains = {ep.domain for ep in eps}
            patterns.append(APIPattern(
                pattern_type=proto,
                base_url=sorted(domains)[0] if domains else "",
                endpoints_count=len(eps),
                example_urls=[ep.url[:100] for ep in eps[:5]],
            ))
        return patterns
