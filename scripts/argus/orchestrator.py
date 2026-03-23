"""ARGUS orchestrator — master controller that runs all phases sequentially.

Usage::

    # Run full scan (requires Chrome on CDP port 9223, logged into Google)
    python -m scripts.argus.orchestrator

    # Run a specific target only
    python -m scripts.argus.orchestrator --target nlm

    # Dry-run: decode existing captures only, no new crawling
    python -m scripts.argus.orchestrator --decode-only

    # Generate docs from current registry
    python -m scripts.argus.orchestrator --docs-only
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from scripts.argus.config import CDP_URL, DATA_DIR
from scripts.argus.crawlers.aistudio_crawler import AIStudioCrawler
from scripts.argus.crawlers.gemini_crawler import GeminiCrawler
from scripts.argus.crawlers.nlm_crawler import NLMCrawler
from scripts.argus.decoders.batchexecute import BatchExecuteDecoder
from scripts.argus.decoders.grpc_web import GrpcWebDecoder
from scripts.argus.decoders.heap_diffing import HeapDiffer
from scripts.argus.discovery.endpoint_registry import EndpointRegistry, get_registry
from scripts.argus.discovery.feature_flag_probe import FeatureFlagProber
from scripts.argus.discovery.proto_reconstructor import get_reconstructor
from scripts.argus.discovery.rpcid_detector import get_detector
from scripts.argus.network_monitor import NetworkMonitor
from scripts.argus.nexus_sink import get_sink
from scripts.argus.reporting.api_doc_generator import ApiDocGenerator, DiffReporter

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """Aggregated result from a full ARGUS scan."""
    target: str
    duration_s: float = 0.0
    new_nlm: List[str] = field(default_factory=list)
    new_gemini: List[str] = field(default_factory=list)
    new_ais: List[str] = field(default_factory=list)
    new_endpoints: List[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def total_new(self) -> int:
        return len(self.new_nlm) + len(self.new_gemini) + len(self.new_ais) + len(self.new_endpoints)


class ArgusOrchestrator:
    """Master ARGUS controller."""

    def __init__(self) -> None:
        self._registry = get_registry()
        self._sink = get_sink()
        self._detector = get_detector()
        self._reconstructor = get_reconstructor()
        self._doc_gen = ApiDocGenerator()

        # Register discovery callback → auto-store in Nexus
        self._detector.on_discovery(
            lambda ev: self._sink.store_new_rpcid(
                ev.rpcid, ev.rpcid, ev.target, ev.context
            )
        )

    # ──── Entry points ────

    async def run_full_scan(
        self,
        targets: Optional[List[str]] = None,
        probe_flags: bool = False,
    ) -> List[ScanResult]:
        """Run a full ARGUS scan across all (or specified) targets.

        Args:
            targets:     List of target names to scan: "nlm", "gemini", "aistudio".
                         Defaults to all three.
            probe_flags: If True, also run feature flag probing.

        Returns:
            List of ScanResult objects per target.
        """
        targets = targets or ["nlm", "gemini", "aistudio"]
        results: List[ScanResult] = []
        scan_start = time.monotonic()

        # Save pre-scan registry snapshot for diffing
        pre_scan_data = self._registry.get_full_data()

        # Attach network monitor (shared across crawlers)
        monitor = NetworkMonitor()

        for target in targets:
            result = await self._run_target(target, monitor)
            results.append(result)

        # Feature flag probe (NLM only, optional)
        if probe_flags and "nlm" in targets:
            await self._run_flag_probe()

        # Rebuild proto files
        self._save_protos()

        # Generate diff report
        post_scan_data = self._registry.get_full_data()
        diff = DiffReporter(post_scan_data, pre_scan_data)
        diff_report = diff.generate_report()
        self._sink.store_diff_report(diff_report)

        # Aggregate totals and store scan summary
        all_new_nlm: List[str] = []
        all_new_gem: List[str] = []
        all_new_ais: List[str] = []
        all_new_eps: List[str] = []
        for r in results:
            all_new_nlm.extend(r.new_nlm)
            all_new_gem.extend(r.new_gemini)
            all_new_ais.extend(r.new_ais)
            all_new_eps.extend(r.new_endpoints)

        duration = time.monotonic() - scan_start
        self._registry.record_run(
            new_rpcids=all_new_nlm + all_new_gem,
            new_methods=all_new_ais,
            duration_s=duration,
        )
        self._registry.save()

        self._sink.store_scan_results(
            new_nlm=all_new_nlm,
            new_gemini=all_new_gem,
            new_ais=all_new_ais,
            new_endpoints=all_new_eps,
            stats=self._registry.get_stats(),
        )

        # Generate API reference docs
        self._doc_gen.write_all()

        total = len(all_new_nlm) + len(all_new_gem) + len(all_new_ais) + len(all_new_eps)
        logger.info(
            "ARGUS scan complete in %.1fs. %d new discoveries across %d targets.",
            duration, total, len(targets),
        )
        return results

    async def generate_docs_only(self) -> List[Path]:
        """Regenerate API reference docs from current registry without crawling."""
        docs = self._doc_gen.write_all()
        logger.info("ARGUS: wrote %d doc files", len(docs))
        return docs

    # ──── Per-target scan ────

    async def _run_target(
        self, target: str, monitor: NetworkMonitor
    ) -> ScanResult:
        result = ScanResult(target=target)
        start = time.monotonic()

        try:
            # Attach CDP network monitor
            await monitor.start()

            # Run the appropriate crawler
            crawler_cls = {"nlm": NLMCrawler, "gemini": GeminiCrawler, "aistudio": AIStudioCrawler}.get(target)
            if not crawler_cls:
                result.error = f"Unknown target: {target}"
                return result

            crawler = crawler_cls(monitor=monitor)
            await crawler.start()
            steps = await crawler.run_flows()
            await crawler.stop()

            # Decode all captured traffic
            be_decoder = BatchExecuteDecoder()
            grpc_decoder = GrpcWebDecoder()
            crawl_results: List[Dict[str, Any]] = []

            for step in steps:
                for req in step.traffic:
                    if req.is_batchexecute:
                        calls = be_decoder.decode_request(req.post_data or "")
                        # Each decoded call becomes a crawl_results entry
                        for call in calls:
                            tgt = "nlm" if "notebooklm" in req.url else "gemini"
                            crawl_results.append({
                                "type": f"{tgt}_rpcid",
                                "value": call.rpcid,
                                "name": call.rpcid,
                            })
                    elif req.is_grpc_web:
                        grpc_resp = grpc_decoder.decode_response(
                            req.response_body or b"",
                            req.url,
                        )
                        for method in [grpc_resp.method]:
                            if method:
                                crawl_results.append({
                                    "type": "aistudio_method",
                                    "value": method,
                                    "service": grpc_resp.service,
                                })
                        # Feed fields to proto reconstructor
                        if grpc_resp.frames:
                            for fr in grpc_resp.frames:
                                self._reconstructor.ingest_grpc_frame(
                                    method=grpc_resp.method,
                                    service=grpc_resp.service,
                                    direction="response",
                                    raw_fields=[(f.field_number, f.wire_type, b"") for f in fr.fields],
                                )

            # Register everything in the endpoint registry
            new = self._registry.process_crawl_results(crawl_results)
            result.new_nlm = new["new_nlm"]
            result.new_gemini = new["new_gemini"]
            result.new_ais = new["new_ais"]
            result.new_endpoints = new["new_endpoints"]

        except Exception as exc:
            logger.error("ARGUS: target '%s' failed: %s", target, exc, exc_info=True)
            result.error = str(exc)
        finally:
            result.duration_s = time.monotonic() - start

        return result

    # ──── Feature flag probe ────

    async def _run_flag_probe(self) -> None:
        """Probe NLM feature flag IDs."""
        try:
            from engine.integrations.nlm_direct_client import get_nlm_client
            client = get_nlm_client()
        except ImportError:
            client = None

        prober = FeatureFlagProber()
        await prober.probe_all(client=client)
        prober.save()
        self._sink.store_feature_flags(prober.get_active_flags())
        entries = prober.to_nexus_entries()
        self._sink.store_bulk(entries)

    # ──── Proto output ────

    def _save_protos(self) -> None:
        """Save reconstructed .proto files and store in Nexus."""
        paths = self._reconstructor.save_all()
        for path in paths:
            proto_text = path.read_text(encoding="utf-8")
            service_name = path.stem
            self._sink.store_proto_reconstruction(service_name, proto_text)
        if paths:
            logger.info("ARGUS: wrote %d .proto files", len(paths))


# ──── CLI entry point ────

async def _main() -> None:
    parser = argparse.ArgumentParser(description="ARGUS — Google API Intelligence Scanner")
    parser.add_argument("--target", choices=["nlm", "gemini", "aistudio", "all"],
                        default="all", help="Target to scan")
    parser.add_argument("--probe-flags", action="store_true",
                        help="Probe NLM feature flag IDs")
    parser.add_argument("--docs-only", action="store_true",
                        help="Regenerate docs only (no crawling)")
    parser.add_argument("--decode-only", action="store_true",
                        help="Decode existing captures only (no crawling)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    orchestrator = ArgusOrchestrator()

    if args.docs_only:
        await orchestrator.generate_docs_only()
        return

    targets = ["nlm", "gemini", "aistudio"] if args.target == "all" else [args.target]
    results = await orchestrator.run_full_scan(
        targets=targets,
        probe_flags=args.probe_flags,
    )

    print("\n-- ARGUS Scan Summary --")
    for r in results:
        status = "OK" if not r.error else f"ERR {r.error[:60]}"
        print(f"  {r.target:12s} {status:56s} +{r.total_new:3d} new  ({r.duration_s:.1f}s)")
    total = sum(r.total_new for r in results)
    print(f"\n  TOTAL NEW DISCOVERIES: {total}")


if __name__ == "__main__":
    asyncio.run(_main())
