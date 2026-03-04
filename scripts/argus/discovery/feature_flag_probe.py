"""ARGUS feature flag prober — enumerates hidden feature flag IDs.

Uses the NLM GetFeatureFlags rpcid (``ozz5Z``) to probe flag IDs
in the range 300–1500 and logs which return non-empty responses.

Calling strategy:
    - Sends batches of 20 flag IDs per batchexecute call
    - Stores all live flag IDs + their responses in Nexus
    - Outputs a flag map to data/argus/feature_flags.json
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from scripts.argus.config import DATA_DIR, NLM_RPCIDS

logger = logging.getLogger(__name__)

FLAGS_PATH = DATA_DIR / "feature_flags.json"

# The NLM rpcid used to fetch feature flags
FEATURE_FLAGS_RPCID = "ozz5Z"  # GetFeatureFlags

# Target: notebooklm batchexecute endpoint
NLM_BATCHEXECUTE_URL = (
    "https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute"
    "?rpcids=ozz5Z&source-path=%2F&f.sid=-{sid}&bl={bl}&hl=en&_reqid={reqid}"
)

# Flag ID ranges to probe
PROBE_RANGES = [
    (300, 500),
    (500, 700),
    (700, 900),
    (900, 1100),
    (1100, 1300),
    (1300, 1500),
]
BATCH_SIZE = 20  # flag IDs per request


@dataclass
class FlagResult:
    """Result for a single flag ID probe."""
    flag_id: int
    raw_response: str
    data: Any = None  # parsed response if available
    is_active: bool = False

    def __post_init__(self) -> None:
        # A flag is "active" (live) if the response has non-trivial content
        self.is_active = bool(
            self.raw_response
            and self.raw_response.strip()
            and self.raw_response not in (",", "null", "[]")
        )


@dataclass
class FeatureFlagProber:
    """Probes NLM for unknown feature flag IDs using the batchexecute endpoint.

    Requires the NLM direct client (``engine.integrations.nlm_direct_client``)
    for authenticated calls.
    """

    _results: Dict[int, FlagResult] = field(default_factory=dict)

    async def probe_range(
        self,
        start: int,
        end: int,
        client: Optional[Any] = None,
    ) -> List[FlagResult]:
        """Probe all flag IDs in [start, end).

        Args:
            start: First flag ID to probe (inclusive).
            end:   Last flag ID to probe (exclusive).
            client: An NLM direct client instance with a ``batchexecute()`` method.
                    If None, builds a payload-only structure suitable for manual replay.

        Returns:
            List of FlagResult objects (all probed IDs, active or not).
        """
        results: List[FlagResult] = []
        flag_ids = list(range(start, end))

        for batch_start in range(0, len(flag_ids), BATCH_SIZE):
            batch = flag_ids[batch_start: batch_start + BATCH_SIZE]
            batch_results = await self._probe_batch(batch, client)
            results.extend(batch_results)
            # Throttle to avoid rate limiting
            await asyncio.sleep(0.5)

        return results

    async def probe_all(self, client: Optional[Any] = None) -> Dict[int, FlagResult]:
        """Probe all ranges defined in PROBE_RANGES."""
        all_results: List[FlagResult] = []
        for start, end in PROBE_RANGES:
            logger.info("FeatureFlagProber: probing flag IDs %d–%d", start, end)
            batch = await self.probe_range(start, end, client)
            all_results.extend(batch)
            # Brief pause between ranges
            await asyncio.sleep(1.0)

        for r in all_results:
            self._results[r.flag_id] = r

        active = [r for r in all_results if r.is_active]
        logger.info(
            "FeatureFlagProber: found %d active flags out of %d probed",
            len(active), len(all_results),
        )
        return self._results

    def save(self, path: Path = FLAGS_PATH) -> None:
        """Persist flag results to JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            str(fid): {
                "is_active": r.is_active,
                "raw_response": r.raw_response[:500] if r.raw_response else "",
            }
            for fid, r in self._results.items()
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info("FeatureFlagProber: saved %d results to %s", len(data), path)

    def get_active_flags(self) -> List[int]:
        """Return sorted list of active (live) flag IDs."""
        return sorted(fid for fid, r in self._results.items() if r.is_active)

    def to_nexus_entries(self) -> List[Dict[str, str]]:
        """Convert active flags to Nexus knowledge entries."""
        active = self.get_active_flags()
        if not active:
            return []
        return [
            {
                "title": "NLM Feature Flag Discovery",
                "content": (
                    f"Active flag IDs found by FeatureFlagProber:\n"
                    f"{active}\n\n"
                    f"Total probed: {len(self._results)}\n"
                    f"Total active: {len(active)}\n\n"
                    f"These flag IDs can be passed to GetFeatureFlags (rpcid: ozz5Z)\n"
                    f"to read feature configuration from the NLM backend."
                ),
                "content_type": "note",
                "category": "argus",
            }
        ]

    # ──── Internal ────

    async def _probe_batch(
        self, flag_ids: List[int], client: Optional[Any]
    ) -> List[FlagResult]:
        """Send a single batchexecute call for a batch of flag IDs."""
        results: List[FlagResult] = []

        if client is None:
            # No client — return empty results with the payload for manual replay
            logger.debug(
                "FeatureFlagProber: no client provided, skipping batch %d–%d",
                flag_ids[0], flag_ids[-1],
            )
            for fid in flag_ids:
                results.append(FlagResult(flag_id=fid, raw_response=""))
            return results

        # Build batchexecute f.req payload for GetFeatureFlags
        # Each call: ["ozz5Z", json.dumps([flag_id]), null, "1"]
        calls = [
            [FEATURE_FLAGS_RPCID, json.dumps([fid]), None, "1"]
            for fid in flag_ids
        ]
        payload = json.dumps([calls])

        try:
            response = await client.batchexecute(
                rpcid=FEATURE_FLAGS_RPCID,
                payload=payload,
                timeout=15,
            )
            # Parse response: each frame corresponds to one flag_id
            frames = _split_frames(response)
            for i, fid in enumerate(flag_ids):
                raw = frames[i] if i < len(frames) else ""
                results.append(FlagResult(flag_id=fid, raw_response=raw))
        except Exception as exc:
            logger.warning("FeatureFlagProber: batch error: %s", exc)
            for fid in flag_ids:
                results.append(FlagResult(flag_id=fid, raw_response=""))

        return results


def _split_frames(response: str) -> List[str]:
    """Split a batchexecute multi-frame response into individual frame strings."""
    # Responses look like: ")]}'\n123\n[...]\n456\n[...]..."
    lines = response.split("\n")
    frames: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.isdigit():
            # Next line(s) form the JSON frame
            i += 1
            if i < len(lines):
                frames.append(lines[i])
        i += 1
    return frames


# ──── Module-level singleton ────

_prober: Optional[FeatureFlagProber] = None


def get_prober() -> FeatureFlagProber:
    """Return shared FeatureFlagProber singleton."""
    global _prober
    if _prober is None:
        _prober = FeatureFlagProber()
    return _prober
