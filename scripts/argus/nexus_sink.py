"""ARGUS Nexus sink — stores all ARGUS discoveries as Nexus knowledge entries.

Every new rpcid, method, endpoint, diff report, and feature flag is persisted
into the Nexus KMS so agents can query it instantly via ``nexus_search``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from engine.nexus.client import get_nexus_client

logger = logging.getLogger(__name__)


class ArgusNexusSink:
    """Pushes ARGUS discoveries into Nexus knowledge base."""

    def __init__(self) -> None:
        try:
            self._client = get_nexus_client()
        except Exception as exc:
            logger.warning("ArgusNexusSink: could not get Nexus client: %s", exc)
            self._client = None

    # ──── Core store ────

    def store(self, title: str, content: str, content_type: str = "note") -> Optional[str]:
        """Store a single entry in Nexus under the 'argus' category.

        Returns:
            The entry ID if successful, else None.
        """
        if not self._client:
            logger.debug("ArgusNexusSink.store: no client, skipping '%s'", title)
            return None
        try:
            entry_id = self._client.add_entry(
                title=title,
                content=content,
                content_type=content_type,
                category="argus",
            )
            logger.debug("ArgusNexusSink: stored '%s' → %s", title, entry_id)
            return entry_id
        except Exception as exc:
            logger.error("ArgusNexusSink.store error: %s", exc)
            return None

    def store_qa(self, question: str, answer: str) -> bool:
        """Store a Q&A pair in the fast Nexus QA cache."""
        if not self._client:
            return False
        try:
            self._client.add_qa(question, answer, category="argus")
            return True
        except Exception as exc:
            logger.error("ArgusNexusSink.store_qa error: %s", exc)
            return False

    # ──── Convenience store methods ────

    def store_new_rpcid(self, rpcid: str, name: str, target: str, context: str) -> None:
        """Store a newly discovered rpcid as a Nexus entry + Q&A."""
        self.store(
            title=f"ARGUS: New {target.upper()} rpcid — {rpcid}",
            content=(
                f"**New rpcid discovered by ARGUS**\n\n"
                f"- rpcid: `{rpcid}`\n"
                f"- Name/purpose: {name or 'Unknown'}\n"
                f"- Target: {target}\n"
                f"- Discovered: {_now()}\n\n"
                f"**Context:**\n{context[:500]}"
            ),
        )
        self.store_qa(
            f"What is rpcid {rpcid} in {target}?",
            f"rpcid `{rpcid}` ({name}) was discovered by ARGUS scanning {target}. "
            f"Context: {context[:200]}",
        )

    def store_new_aistudio_method(self, method: str, service: str) -> None:
        """Store a newly discovered AI Studio method."""
        self.store(
            title=f"ARGUS: New AI Studio method — {method}",
            content=(
                f"**New AI Studio gRPC method discovered by ARGUS**\n\n"
                f"- Method: `{method}`\n"
                f"- Service: `{service}`\n"
                f"- Endpoint: `.../$rpc/.../{service}/{method}`\n"
                f"- Discovered: {_now()}"
            ),
        )

    def store_scan_results(
        self,
        new_nlm: List[str],
        new_gemini: List[str],
        new_ais: List[str],
        new_endpoints: List[str],
        stats: Dict[str, Any],
    ) -> None:
        """Store a complete scan results summary in Nexus."""
        total_new = len(new_nlm) + len(new_gemini) + len(new_ais) + len(new_endpoints)
        content = (
            f"# ARGUS Scan Results — {_now()}\n\n"
            f"**Total new discoveries:** {total_new}\n\n"
        )
        if new_nlm:
            content += f"## New NLM rpcids ({len(new_nlm)})\n"
            for r in new_nlm:
                content += f"- `{r}`\n"
            content += "\n"
        if new_gemini:
            content += f"## New Gemini rpcids ({len(new_gemini)})\n"
            for r in new_gemini:
                content += f"- `{r}`\n"
            content += "\n"
        if new_ais:
            content += f"## New AI Studio methods ({len(new_ais)})\n"
            for m in new_ais:
                content += f"- `{m}`\n"
            content += "\n"
        if new_endpoints:
            content += f"## New unknown endpoints ({len(new_endpoints)})\n"
            for e in new_endpoints:
                content += f"- `{e}`\n"
            content += "\n"
        content += (
            f"## Coverage Stats\n"
            f"- NLM rpcids seen: {stats.get('nlm_rpcids_seen', '?')}/{stats.get('nlm_rpcids_total', '?')}\n"
            f"- Gemini rpcids seen: {stats.get('gemini_rpcids_seen', '?')}/{stats.get('gemini_rpcids_total', '?')}\n"
            f"- AI Studio methods seen: {stats.get('aistudio_methods_seen', '?')}/{stats.get('aistudio_methods_total', '?')}\n"
        )

        self.store(
            title=f"ARGUS Scan Results {_now()[:10]}",
            content=content,
            content_type="history",
        )

        if total_new > 0:
            self.store_qa(
                f"What did ARGUS discover on {_now()[:10]}?",
                f"ARGUS found {total_new} new items: "
                f"{len(new_nlm)} NLM rpcids, {len(new_gemini)} Gemini rpcids, "
                f"{len(new_ais)} AI Studio methods, {len(new_endpoints)} unknown endpoints.",
            )

    def store_feature_flags(self, active_flags: List[int]) -> None:
        """Store the feature flag probe results."""
        if not active_flags:
            return
        self.store(
            title="NLM Active Feature Flag IDs",
            content=(
                f"**Feature flags found active via ozz5Z (GetFeatureFlags) rpcid**\n\n"
                f"Active flag IDs: {active_flags}\n\n"
                f"Total active: {len(active_flags)}\n"
                f"Probed range: {min(active_flags)}–{max(active_flags)}\n\n"
                "Use these IDs with the feature flag rpcid to read configuration."
            ),
        )

    def store_proto_reconstruction(self, service: str, proto_text: str) -> None:
        """Store a reconstructed .proto file in Nexus."""
        self.store(
            title=f"Proto reconstruction: {service}",
            content=(
                f"**Auto-reconstructed .proto for {service}**\n\n"
                f"```protobuf\n{proto_text}\n```"
            ),
            content_type="code",
        )

    def store_diff_report(self, report_markdown: str) -> None:
        """Store a diff report between two ARGUS scans."""
        self.store(
            title=f"ARGUS Diff Report {_now()[:10]}",
            content=report_markdown,
            content_type="history",
        )

    def store_har_replay(
        self,
        target: str,
        har_path: str,
        new_rpcids: List[str],
        known_rpcids: List[str],
        endpoint_count: int,
        summary: str,
    ) -> None:
        """Store a HAR replay result in Nexus.

        Args:
            target: ARGUS target name (e.g. "apps_script").
            har_path: Path to the source HAR file.
            new_rpcids: Newly discovered rpcids not in any baseline.
            known_rpcids: Known rpcids confirmed present in the HAR.
            endpoint_count: Total unique endpoints seen.
            summary: Human-readable summary string from ReplayResult.
        """
        content = (
            f"# ARGUS HAR Replay — {target} — {_now()[:10]}\n\n"
            f"**Source:** `{har_path}`\n\n"
            f"{summary}\n\n"
        )
        if new_rpcids:
            content += f"## NEW rpcids ({len(new_rpcids)})\n"
            for r in new_rpcids:
                content += f"- `{r}` — **UNKNOWN** (needs investigation)\n"
            content += "\n"
        if known_rpcids:
            content += f"## Known rpcids confirmed ({len(known_rpcids)})\n"
            for r in known_rpcids:
                content += f"- `{r}`\n"
            content += "\n"

        self.store(
            title=f"ARGUS HAR Replay: {target} {_now()[:10]}",
            content=content,
            content_type="history",
        )

        # Q&A for each new rpcid
        for rpcid in new_rpcids:
            self.store_qa(
                f"What is the unknown rpcid {rpcid} found in {target} HAR?",
                f"rpcid `{rpcid}` was found in the {target} HAR replay on {_now()[:10]}. "
                f"Purpose unknown — requires further investigation with ARGUS crawlers.",
            )

        if new_rpcids:
            self.store_qa(
                f"What new {target} rpcids did ARGUS find in the HAR replay?",
                f"ARGUS HAR replay of {target} found {len(new_rpcids)} new rpcids: "
                f"{', '.join(new_rpcids)}. These are not in the known baseline and need investigation.",
            )

    def store_override_candidates(
        self,
        target: str,
        candidates: Dict[str, List[Any]],
    ) -> None:
        """Store client-side override candidates found in HAR payloads.

        Args:
            target: ARGUS target name.
            candidates: Dict of field_name → [observed_values].
        """
        if not candidates:
            return

        lines = [
            f"# Client-side Override Candidates — {target} — {_now()[:10]}\n\n",
            "Fields found in batchexecute/gRPC payloads that may be overridable client-side:\n\n",
        ]
        for field_name, values in sorted(candidates.items()):
            lines.append(f"## `{field_name}`\n")
            lines.append(f"Observed values: `{values}`\n\n")

        self.store(
            title=f"ARGUS Override Candidates: {target}",
            content="".join(lines),
            content_type="note",
        )

        model_fields = {k: v for k, v in candidates.items() if "model" in k.lower()}
        if model_fields:
            self.store_qa(
                f"Can the model be overridden client-side in {target}?",
                f"Yes — model fields found in {target} payloads: {model_fields}. "
                f"These can potentially be modified in batchexecute requests to select different models.",
            )

        quota_fields = {k: v for k, v in candidates.items() if any(
            q in k.lower() for q in ("quota", "limit", "remaining", "count")
        )}
        if quota_fields:
            self.store_qa(
                f"Are quotas enforced client-side in {target}?",
                f"Quota-related fields found in {target} page state/payloads: {quota_fields}. "
                f"These may be client-side counters that can be reset or bypassed.",
            )

    def store_bulk(self, entries: List[Dict[str, str]]) -> int:
        """Store multiple entries. Returns count stored."""
        count = 0
        for entry in entries:
            if self.store(
                title=entry.get("title", "ARGUS entry"),
                content=entry.get("content", ""),
                content_type=entry.get("content_type", "note"),
            ):
                count += 1
        return count


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ──── Module-level singleton ────

_sink: Optional[ArgusNexusSink] = None


def get_sink() -> ArgusNexusSink:
    global _sink
    if _sink is None:
        _sink = ArgusNexusSink()
    return _sink
