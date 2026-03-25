"""
ARGUS Deep Analyzer — Automated Intelligence Workflow
=======================================================

Takes the manual exploration workflow (HAR → endpoints → auth → flags →
configs → protocols → services → report) and automates it. Feed it HARs
and heaps, get a full intelligence package.

Discovers things a basic HAR scan misses:
  - Statsig/LaunchDarkly feature flags (enumerate + test email domains)
  - Firebase project config (API keys, auth providers, domains)
  - JWT token analysis (issuer, audience, claims, expiry)
  - WebSocket protocol extraction (message types, connection flow)
  - Refresh token extraction + auto-refresh
  - GCS bucket probing (public vs private)
  - Service instance enumeration (service-0, service-1, etc.)
  - Staff/employee domain detection

Usage:
    from scripts.argus.analyzers.deep_analyzer import DeepAnalyzer
    analyzer = DeepAnalyzer()
    result = analyzer.analyze("C:/path/to/hars/", output_dir="data/argus/reports/")

Version: v1.50.0 [2026-03-25]
Author:  CosySim Team

CONNECTS: HARAnalyzer, HeapAnalyzer, ProtocolDetector
CALLED BY: CLI (analyze.py deep), automated pipelines
EMITS: DeepAnalysisReport, Markdown report, JSON spec, research journal
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

from scripts.argus.analyzers.har_analyzer import HARAnalyzer
from scripts.argus.analyzers.heap_analyzer import GenericHeapAnalyzer
from scripts.argus.analyzers.data_types import HARAnalysisReport, HeapAnalysisReport, ProtocolType

logger = logging.getLogger(__name__)


# ──── Deep Analysis Report ───────────────────────────────────────────────────

@dataclass
class JWTInfo:
    """Decoded JWT token information."""
    issuer: str = ""
    audience: str = ""
    email: str = ""
    user_id: str = ""
    name: str = ""
    provider: str = ""  # "firebase", "google_iap", "auth0", "okta", "custom"
    expiry_seconds: int = 0
    claims: Dict[str, Any] = field(default_factory=dict)
    refresh_token: Optional[str] = None  # redacted


@dataclass
class FeatureFlagSystem:
    """Discovered feature flag system."""
    provider: str = ""        # "statsig", "launchdarkly", "custom"
    client_key: str = ""
    endpoint: str = ""
    gates_count: int = 0
    configs_count: int = 0
    employee_domains: List[str] = field(default_factory=list)
    staff_only_configs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WebSocketProtocol:
    """Discovered WebSocket protocol."""
    url: str = ""
    auth_method: str = ""     # "jwt_query", "jwt_header", "cookie", "none"
    message_types: Dict[str, str] = field(default_factory=dict)  # type → direction
    total_messages: int = 0
    connection_flow: List[str] = field(default_factory=list)


@dataclass
class ServiceInstance:
    """A discovered service instance."""
    name: str = ""
    url: str = ""
    status_code: int = 0
    auth_required: str = ""   # "firebase_jwt", "iap_jwt", "none", "unknown"


@dataclass
class DeepAnalysisReport:
    """Complete deep analysis report."""
    target: str = ""
    analysis_date: str = ""
    har_files: int = 0
    heap_files: int = 0
    total_entries: int = 0
    unique_endpoints: int = 0
    services_discovered: int = 0

    # Auth
    jwts: List[JWTInfo] = field(default_factory=list)
    firebase_project: Optional[str] = None
    firebase_api_key: Optional[str] = None

    # Feature flags
    feature_flags: Optional[FeatureFlagSystem] = None

    # WebSocket
    websocket_protocols: List[WebSocketProtocol] = field(default_factory=list)

    # Services
    service_instances: List[ServiceInstance] = field(default_factory=list)

    # Buckets
    public_buckets: List[str] = field(default_factory=list)

    # Base HAR report
    har_report: Optional[HARAnalysisReport] = None
    heap_report: Optional[HeapAnalysisReport] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target": self.target,
            "analysis_date": self.analysis_date,
            "har_files": self.har_files,
            "heap_files": self.heap_files,
            "total_entries": self.total_entries,
            "unique_endpoints": self.unique_endpoints,
            "services_discovered": self.services_discovered,
            "firebase_project": self.firebase_project,
            "feature_flags": {
                "provider": self.feature_flags.provider,
                "gates": self.feature_flags.gates_count,
                "configs": self.feature_flags.configs_count,
                "employee_domains": self.feature_flags.employee_domains,
            } if self.feature_flags else None,
            "websocket_protocols": len(self.websocket_protocols),
            "service_instances": len(self.service_instances),
            "public_buckets": self.public_buckets,
        }


# ──── Deep Analyzer ──────────────────────────────────────────────────────────

class DeepAnalyzer:
    """Automated intelligence workflow — HAR to full report.

    Runs: HAR analysis → JWT extraction → feature flag enumeration →
    domain testing → WebSocket protocol extraction → service instance
    probing → bucket testing → report generation.
    """

    def __init__(self) -> None:
        self._har_analyzer = HARAnalyzer()
        self._heap_analyzer = GenericHeapAnalyzer()

    def analyze(
        self,
        source_dir: str,
        output_dir: str = "data/argus/reports",
        har_pattern: str = "*.har",
        heap_pattern: str = "*.heapsnapshot",
    ) -> DeepAnalysisReport:
        """Run the full deep analysis workflow.

        Args:
            source_dir: Directory containing HAR and heap files.
            output_dir: Where to save reports.

        Returns:
            DeepAnalysisReport with all findings.
        """
        source = Path(source_dir)
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)

        report = DeepAnalysisReport(
            analysis_date=time.strftime("%Y-%m-%d %H:%M"),
        )

        # Phase 1: HAR analysis
        har_files = sorted(source.glob(har_pattern))
        heap_files = sorted(source.glob(heap_pattern))
        report.har_files = len(har_files)
        report.heap_files = len(heap_files)

        print(f"\n=== ARGUS Deep Analysis ===")
        print(f"  Source: {source}")
        print(f"  HAR files: {len(har_files)}")
        print(f"  Heap files: {len(heap_files)}")

        if not har_files:
            print("  [!] No HAR files found")
            return report

        # Analyze the largest HAR (most traffic)
        main_har = max(har_files, key=lambda f: f.stat().st_size)
        print(f"\n  [1/7] Analyzing HAR: {main_har.name} ({main_har.stat().st_size / 1024 / 1024:.1f} MB)")
        har_report = self._har_analyzer.analyze_file(main_har)
        report.har_report = har_report
        report.total_entries = har_report.total_entries
        report.unique_endpoints = len(har_report.unique_endpoints)
        report.services_discovered = len(har_report.service_groups)

        # Detect primary target domain
        if har_report.service_groups:
            report.target = har_report.service_groups[0].domain

        # Phase 2: JWT extraction
        print(f"  [2/7] Extracting JWTs...")
        report.jwts = self._extract_jwts(main_har)
        print(f"         Found {len(report.jwts)} unique JWTs")
        for jwt in report.jwts:
            print(f"         - {jwt.provider}: {jwt.email} (exp={jwt.expiry_seconds}s)")

        # Phase 3: Firebase detection
        print(f"  [3/7] Detecting Firebase...")
        fb = self._detect_firebase(main_har)
        if fb:
            report.firebase_project = fb.get("project")
            report.firebase_api_key = fb.get("api_key")
            print(f"         Project: {report.firebase_project}")

        # Phase 4: Feature flag enumeration
        print(f"  [4/7] Enumerating feature flags...")
        report.feature_flags = self._detect_feature_flags(main_har, report.jwts)
        if report.feature_flags:
            ff = report.feature_flags
            print(f"         Provider: {ff.provider}")
            print(f"         Gates: {ff.gates_count}, Configs: {ff.configs_count}")
            if ff.employee_domains:
                print(f"         Employee domains: {', '.join(ff.employee_domains)}")

        # Phase 5: WebSocket protocol extraction
        print(f"  [5/7] Extracting WebSocket protocols...")
        report.websocket_protocols = self._extract_websocket_protocols(main_har)
        for ws in report.websocket_protocols:
            print(f"         {ws.url[:60]}... ({ws.total_messages} msgs, {len(ws.message_types)} types)")

        # Phase 6: Service instance probing
        print(f"  [6/7] Probing service instances...")
        report.service_instances = self._probe_services(har_report)
        for svc in report.service_instances:
            print(f"         {svc.name}: HTTP {svc.status_code} ({svc.auth_required})")

        # Phase 7: Bucket detection
        print(f"  [7/7] Detecting public buckets...")
        report.public_buckets = self._detect_public_buckets(har_report)
        for bucket in report.public_buckets:
            print(f"         PUBLIC: {bucket}")

        # Heap analysis (if available)
        if heap_files:
            print(f"\n  [+] Analyzing {len(heap_files)} heap snapshots...")
            report.heap_report = self._heap_analyzer.analyze_file(heap_files[-1])
            print(f"      {report.heap_report.total_strings:,} strings, "
                  f"{len(report.heap_report.api_endpoints)} API endpoints")

        # Generate outputs
        target_name = report.target.split(".")[0] if report.target else "unknown"
        self._save_json(report, output / f"{target_name}_deep_analysis.json")
        self._save_journal(report, output / f"{target_name}_research_journal.md")

        print(f"\n  [+] Reports saved to {output}/")
        print(f"  [+] Analysis complete: {report.unique_endpoints} endpoints, "
              f"{report.services_discovered} services")

        return report

    # ──── Phase 2: JWT Extraction ────────────────────────────────────

    def _extract_jwts(self, har_path: Path) -> List[JWTInfo]:
        """Extract and decode all unique JWTs from HAR."""
        har = json.loads(har_path.read_text(errors="replace"))
        seen_tokens: Set[str] = set()
        jwts = []

        for entry in har.get("log", {}).get("entries", []):
            # Check Authorization headers
            for h in entry.get("request", {}).get("headers", []):
                if h.get("name", "").lower() == "authorization":
                    val = h.get("value", "")
                    if "eyJ" in val:
                        token = val.replace("Bearer ", "").strip()
                        sig = token.split(".")[-1][:20] if "." in token else token[:20]
                        if sig not in seen_tokens:
                            seen_tokens.add(sig)
                            jwt_info = self._decode_jwt(token)
                            if jwt_info:
                                jwts.append(jwt_info)

            # Check URL query params
            url = entry.get("request", {}).get("url", "")
            if "id_token=" in url:
                token = url.split("id_token=")[1].split("&")[0]
                sig = token.split(".")[-1][:20]
                if sig not in seen_tokens:
                    seen_tokens.add(sig)
                    jwt_info = self._decode_jwt(token)
                    if jwt_info:
                        jwts.append(jwt_info)

            # Extract refresh tokens
            resp_body = entry.get("response", {}).get("content", {}).get("text", "")
            if "refresh_token" in resp_body:
                try:
                    d = json.loads(resp_body)
                    rt = d.get("refresh_token") or d.get("refreshToken")
                    if rt and jwts:
                        jwts[-1].refresh_token = rt[:10] + "..." + rt[-5:]
                except Exception:
                    pass

        return jwts

    def _decode_jwt(self, token: str) -> Optional[JWTInfo]:
        """Decode a JWT and classify its provider."""
        try:
            parts = token.split(".")
            if len(parts) < 2:
                return None
            payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))

            iss = claims.get("iss", "")
            provider = "custom"
            if "securetoken.google.com" in iss:
                provider = "firebase"
            elif "accounts.google.com" in iss:
                provider = "google_iap"
            elif "auth0.com" in iss:
                provider = "auth0"

            return JWTInfo(
                issuer=iss,
                audience=str(claims.get("aud", "")),
                email=claims.get("email", ""),
                user_id=claims.get("user_id", claims.get("sub", "")),
                name=claims.get("name", ""),
                provider=provider,
                expiry_seconds=claims.get("exp", 0) - claims.get("iat", 0),
                claims=claims,
            )
        except Exception:
            return None

    # ──── Phase 3: Firebase Detection ────────────────────────────────

    def _detect_firebase(self, har_path: Path) -> Optional[Dict]:
        """Detect Firebase project from HAR entries."""
        har = json.loads(har_path.read_text(errors="replace"))
        for entry in har.get("log", {}).get("entries", []):
            url = entry.get("request", {}).get("url", "")
            # Firebase init.json
            if "__/firebase/init.json" in url:
                try:
                    resp = entry.get("response", {}).get("content", {}).get("text", "")
                    d = json.loads(resp)
                    return {"project": d.get("projectId"), "api_key": d.get("apiKey")}
                except Exception:
                    pass
            # apiKey in URL
            if "apiKey=" in url and "identitytoolkit" in url:
                key = url.split("apiKey=")[1].split("&")[0]
                project = None
                if "securetoken.google.com/" in str(entry):
                    m = re.search(r"securetoken\.google\.com/([^\"]+)", str(entry))
                    if m:
                        project = m.group(1)
                return {"project": project, "api_key": key}
        return None

    # ──── Phase 4: Feature Flag Detection ────────────────────────────

    def _detect_feature_flags(self, har_path: Path, jwts: List[JWTInfo]) -> Optional[FeatureFlagSystem]:
        """Detect and enumerate feature flag systems."""
        har = json.loads(har_path.read_text(errors="replace"))

        for entry in har.get("log", {}).get("entries", []):
            url = entry.get("request", {}).get("url", "")

            # Statsig
            if "featureassets.org" in url or "statsig" in url:
                return self._enumerate_statsig(url, entry, jwts)

            # LaunchDarkly
            if "launchdarkly" in url or "ld.com" in url:
                return FeatureFlagSystem(provider="launchdarkly", endpoint=url)

        return None

    def _enumerate_statsig(self, url: str, entry: Dict, jwts: List[JWTInfo]) -> FeatureFlagSystem:
        """Enumerate Statsig feature flags and test email domains."""
        # Extract client key from URL
        client_key = ""
        if "k=" in url:
            client_key = url.split("k=")[1].split("&")[0]

        # Get response data
        resp_body = entry.get("response", {}).get("content", {}).get("text", "")
        gates_count = 0
        configs_count = 0
        try:
            d = json.loads(resp_body)
            gates_count = len(d.get("feature_gates", {}))
            configs_count = len(d.get("dynamic_configs", {}))
        except Exception:
            pass

        ff = FeatureFlagSystem(
            provider="statsig",
            client_key=client_key,
            endpoint=url.split("?")[0],
            gates_count=gates_count,
            configs_count=configs_count,
        )

        # Test email domains if we have a client key
        if client_key:
            ff.employee_domains = self._test_email_domains(client_key, jwts)
            ff.staff_only_configs = self._find_staff_configs(client_key, jwts)

        return ff

    def _test_email_domains(self, client_key: str, jwts: List[JWTInfo]) -> List[str]:
        """Test which email domains unlock extra feature gates."""
        url = f"https://featureassets.org/v1/initialize?k={client_key}&st=javascript-client&sv=3.2"
        user_id = jwts[0].user_id if jwts else "test-user"

        # Get baseline
        try:
            r = requests.post(url, json={
                "user": {"userID": user_id, "email": "baseline@gmail.com"},
                "statsigMetadata": {"sdkType": "js-client", "sdkVersion": "3.2.0"},
            }, timeout=10)
            baseline_gates = r.json().get("feature_gates", {})
            baseline_count = sum(1 for v in baseline_gates.values() if v.get("value"))
        except Exception:
            return []

        # Test domains
        employee_domains = []
        test_domains = [
            "sesame.com", "sesameai.com", "google.com", "openai.com",
            "anthropic.com", "meta.com", "microsoft.com", "apple.com",
        ]

        for domain in test_domains:
            try:
                r = requests.post(url, json={
                    "user": {"userID": f"test-{domain}", "email": f"test@{domain}",
                             "custom": {"isStaff": True}},
                    "statsigMetadata": {"sdkType": "js-client", "sdkVersion": "3.2.0"},
                }, timeout=5)
                gates = r.json().get("feature_gates", {})
                enabled = sum(1 for v in gates.values() if v.get("value"))
                if enabled > baseline_count + 2:
                    employee_domains.append(domain)
            except Exception:
                continue

        return employee_domains

    def _find_staff_configs(self, client_key: str, jwts: List[JWTInfo]) -> Dict:
        """Find configs that differ between staff and normal users."""
        url = f"https://featureassets.org/v1/initialize?k={client_key}&st=javascript-client&sv=3.2"
        staff_only = {}

        try:
            # Normal user
            r1 = requests.post(url, json={
                "user": {"userID": "normal", "email": "user@gmail.com"},
                "statsigMetadata": {"sdkType": "js-client", "sdkVersion": "3.2.0"},
            }, timeout=10)
            normal_configs = r1.json().get("dynamic_configs", {})

            # Staff user (try detected employee domains)
            r2 = requests.post(url, json={
                "user": {"userID": "staff", "email": "test@sesame.com",
                         "custom": {"isStaff": True}},
                "statsigMetadata": {"sdkType": "js-client", "sdkVersion": "3.2.0"},
            }, timeout=10)
            staff_configs = r2.json().get("dynamic_configs", {})

            for name, cfg in staff_configs.items():
                normal_val = normal_configs.get(name, {}).get("value", {})
                staff_val = cfg.get("value", {})
                if staff_val != normal_val and isinstance(staff_val, dict):
                    for k, v in staff_val.items():
                        if k not in normal_val or normal_val.get(k) != v:
                            staff_only[k] = v
        except Exception:
            pass

        return staff_only

    # ──── Phase 5: WebSocket Protocol Extraction ─────────────────────

    def _extract_websocket_protocols(self, har_path: Path) -> List[WebSocketProtocol]:
        """Extract WebSocket protocol details from HAR."""
        har = json.loads(har_path.read_text(errors="replace"))
        protocols = []

        for entry in har.get("log", {}).get("entries", []):
            if entry.get("response", {}).get("status") != 101:
                continue

            url = entry.get("request", {}).get("url", "")
            messages = entry.get("_webSocketMessages", [])

            # Determine auth method
            auth = "none"
            if "id_token=" in url:
                auth = "jwt_query"
            elif any(h.get("name", "").lower() == "authorization"
                     for h in entry.get("request", {}).get("headers", [])):
                auth = "jwt_header"

            # Parse message types
            msg_types = {}
            flow = []
            for msg in messages:
                try:
                    data = json.loads(msg.get("data", "{}"))
                    msg_type = data.get("type", "binary")
                    direction = "client→server" if msg.get("type") == "send" else "server→client"
                    msg_types[msg_type] = direction
                    if len(flow) < 15:
                        flow.append(f"{direction}: {msg_type}")
                except Exception:
                    pass

            protocols.append(WebSocketProtocol(
                url=url.split("?")[0],
                auth_method=auth,
                message_types=msg_types,
                total_messages=len(messages),
                connection_flow=flow,
            ))

        return protocols

    # ──── Phase 6: Service Instance Probing ──────────────────────────

    def _probe_services(self, har_report: HARAnalysisReport) -> List[ServiceInstance]:
        """Probe for numbered service instances based on discovered patterns."""
        instances = []

        # Find service-N patterns in endpoints
        for ep in har_report.unique_endpoints:
            m = re.search(r"([\w-]+-\d+)/", ep.base_path)
            if m:
                base_service = re.sub(r"-\d+$", "", m.group(1))
                # Probe instances 0-4
                domain = ep.domain
                for i in range(5):
                    svc_name = f"{base_service}-{i}"
                    try:
                        url = f"https://{domain}/{svc_name}/v1/health"
                        r = requests.get(url, timeout=5)
                        auth = "unknown"
                        if r.status_code == 401:
                            if "IAP" in r.text:
                                auth = "google_iap"
                            elif "Firebase" in r.text or "JWT" in r.text:
                                auth = "firebase_jwt"
                            else:
                                auth = "unknown_jwt"
                        elif r.status_code == 200:
                            auth = "none"

                        instances.append(ServiceInstance(
                            name=svc_name, url=url,
                            status_code=r.status_code, auth_required=auth,
                        ))
                    except Exception:
                        break
                break  # Only probe first pattern found

        return instances

    # ──── Phase 7: Bucket Detection ──────────────────────────────────

    def _detect_public_buckets(self, har_report: HARAnalysisReport) -> List[str]:
        """Detect publicly accessible GCS/S3 buckets from endpoints."""
        public = []

        for ep in har_report.unique_endpoints:
            if "storage.googleapis.com" not in ep.domain:
                continue
            # Extract bucket name from path
            m = re.match(r"/([^/]+)/", ep.base_path)
            if not m:
                continue
            bucket = m.group(1)
            if bucket in public:
                continue

            # Check if any request to this bucket had no auth
            has_auth = any("authorization" in str(ep.content_types).lower()
                          for _ in [1])  # simplified check
            # Test direct access
            try:
                test_url = f"https://storage.googleapis.com/{bucket}/"
                r = requests.get(test_url, timeout=5)
                if r.status_code in (200, 404):  # 404 = exists but empty, 403 = private
                    public.append(bucket)
            except Exception:
                pass

        return public

    # ──── Output Generation ──────────────────────────────────────────

    def _save_json(self, report: DeepAnalysisReport, path: Path) -> None:
        """Save report as JSON."""
        path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

    def _save_journal(self, report: DeepAnalysisReport, path: Path) -> None:
        """Auto-generate a research journal entry."""
        lines = [
            f"# ARGUS Research Journal: {report.target}",
            f"",
            f"> Auto-generated: {report.analysis_date}",
            f"> Source: {report.har_files} HAR files, {report.heap_files} heap snapshots",
            f"",
            f"## Summary",
            f"- Endpoints: {report.unique_endpoints}",
            f"- Services: {report.services_discovered}",
            f"- JWTs found: {len(report.jwts)}",
            f"- WebSocket protocols: {len(report.websocket_protocols)}",
            f"- Public buckets: {len(report.public_buckets)}",
            f"",
        ]

        if report.firebase_project:
            lines.extend([
                f"## Firebase",
                f"- Project: {report.firebase_project}",
                f"- API Key: {report.firebase_api_key}",
                f"",
            ])

        if report.feature_flags:
            ff = report.feature_flags
            lines.extend([
                f"## Feature Flags ({ff.provider})",
                f"- Gates: {ff.gates_count}",
                f"- Configs: {ff.configs_count}",
                f"- Employee domains: {', '.join(ff.employee_domains) if ff.employee_domains else 'none detected'}",
                f"- Staff-only configs: {ff.staff_only_configs}",
                f"",
            ])

        if report.websocket_protocols:
            for ws in report.websocket_protocols:
                lines.extend([
                    f"## WebSocket Protocol",
                    f"- URL: {ws.url}",
                    f"- Auth: {ws.auth_method}",
                    f"- Message types: {len(ws.message_types)}",
                    f"- Total messages: {ws.total_messages}",
                    f"",
                ])

        if report.service_instances:
            lines.extend([f"## Service Instances", f""])
            for svc in report.service_instances:
                lines.append(f"- {svc.name}: HTTP {svc.status_code} ({svc.auth_required})")
            lines.append(f"")

        if report.public_buckets:
            lines.extend([f"## Public Buckets", f""])
            for bucket in report.public_buckets:
                lines.append(f"- {bucket}")
            lines.append(f"")

        lines.append(f"---")
        lines.append(f"*Auto-generated by ARGUS Deep Analyzer v1.50.0*")

        path.write_text("\n".join(lines), encoding="utf-8")
