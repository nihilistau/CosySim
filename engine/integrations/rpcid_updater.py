"""
RPC ID Auto-Updater — Bridge between ARGUS discovery and NLM registry
=====================================================================

Processes HAR files and heap snapshots to extract fresh rpcids and method
names, then updates config/nlm_rpcids.yaml and data/nlm_rpc_registry.json.

When Google deploys a new NLM frontend build, rpcids can rotate.  This
module lets us re-discover them from fresh browser captures (HAR traffic
or V8 heap snapshots) and push the updates into both the YAML source of
truth (config/nlm_rpcids.yaml) and the JSON runtime cache
(data/nlm_rpc_registry.json) so all live operations pick up the new
values at call time.

Version: v1.57.2 [2026-03-26]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-26] — Initial creation: HAR mining, heap mining,
                            dual-registry update (YAML + JSON), diff reporting
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote

import yaml

logger = logging.getLogger(__name__)

# ──── Path Constants ──────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_YAML_REGISTRY = _PROJECT_ROOT / "config" / "nlm_rpcids.yaml"
_JSON_CACHE = _PROJECT_ROOT / "data" / "nlm_rpc_registry.json"

# ──── HAR Parsing Constants ──────────────────────────────────────────────
_NLM_BATCH_PATH = "notebooklm.google.com/_/LabsTailwindUi/data/batchexecute"
_NLM_BUILD_LABEL_PREFIX = "boq_labs-tailwind-frontend_"

# Regex to extract rpcids from the f.req batchexecute envelope.
# The wire format is: [[[rpcid, json_payload, null, "generic"]]]
# The rpcid is a short alphanumeric string (3-10 chars).
_RPCID_PATTERN = re.compile(r'\[\["(\w{2,12})"')

# gRPC method patterns from V8 heap snapshots.
# These are LabsTailwindOrchestrationService method names.
_GRPC_METHOD_PATTERN = re.compile(
    r"LabsTailwindOrchestrationService[./](\w+)"
)


# ──── Data Classes ────────────────────────────────────────────────────────

@dataclass
class UpdateResult:
    """Result of an rpcid update operation.

    Attributes:
        added:       New rpcids not previously in the registry.
        changed:     Rpcids whose value changed (operation stayed the same).
        confirmed:   Rpcids that match the registry (still active).
        new_methods: New gRPC method names discovered from heap mining.
        build_label: Build label extracted from the HAR (if found).
        source:      Path to the source file that was processed.
    """

    added: List[str] = field(default_factory=list)
    changed: List[str] = field(default_factory=list)
    confirmed: List[str] = field(default_factory=list)
    new_methods: List[str] = field(default_factory=list)
    build_label: Optional[str] = None
    source: Optional[str] = None

    def summary(self) -> str:
        """Return a human-readable summary of the update."""
        lines = []
        if self.source:
            lines.append(f"Source: {self.source}")
        if self.build_label:
            lines.append(f"Build label: {self.build_label}")
        lines.append(f"Added:     {len(self.added)}")
        lines.append(f"Changed:   {len(self.changed)}")
        lines.append(f"Confirmed: {len(self.confirmed)}")
        if self.new_methods:
            lines.append(f"New gRPC methods: {len(self.new_methods)}")
        if self.added:
            lines.append("  New rpcids:")
            for item in self.added:
                lines.append(f"    + {item}")
        if self.changed:
            lines.append("  Changed rpcids:")
            for item in self.changed:
                lines.append(f"    ~ {item}")
        return "\n".join(lines)


# ──── RPC ID Updater ─────────────────────────────────────────────────────

# v1.57.2 [2026-03-26] — Bridge between ARGUS discovery and NLM registry
class RpcidUpdater:
    """Auto-updater for NLM rpcid registries.

    Parses HAR files and V8 heap snapshots to extract fresh rpcids,
    compares them against the current YAML/JSON registries, and writes
    updates back to both stores.

    Usage::

        updater = RpcidUpdater()
        result = updater.update_from_har("data/har_files/latest.har")
        print(result.summary())

    CONNECTS: nlm_rpc_registry.py (YAML), nlm_rpc_mapper.py (JSON), HARExtractor
    CALLED BY: scheduler task, CLI pipeline, ARGUS auto-analyze
    EMITS: writes config/nlm_rpcids.yaml + data/nlm_rpc_registry.json
    """

    def __init__(
        self,
        yaml_path: Optional[Path] = None,
        json_path: Optional[Path] = None,
    ) -> None:
        self._yaml_path = yaml_path or _YAML_REGISTRY
        self._json_path = json_path or _JSON_CACHE

    # ──── Public API ──────────────────────────────────────────────────────

    def update_from_har(self, har_path: str) -> UpdateResult:
        """Mine HAR for batchexecute rpcids and update registries.

        Parses all batchexecute POST entries in the HAR, extracts rpcids
        from the ``f.req`` parameter, compares against the current YAML
        registry, and writes updates to both YAML and JSON caches.

        Args:
            har_path: Path to a .har file (exported from Chrome DevTools).

        Returns:
            UpdateResult with added/changed/confirmed rpcid lists.
        """
        result = UpdateResult(source=har_path)

        # 1. Parse HAR for batchexecute calls
        har_rpcids = self._parse_har_batchexecute(har_path)
        if not har_rpcids:
            logger.warning(
                "[RpcidUpdater] No batchexecute calls found in %s "
                "(operation=update_from_har)",
                har_path,
            )
            return result

        # Extract build label from any batchexecute URL
        result.build_label = self._extract_build_label(har_path)

        # 2. Load current registries for comparison
        yaml_rpcids = self._load_yaml_rpcids()
        json_rpcids = self._load_json_rpcids()

        # Build reverse map: rpcid → operation name(s) from YAML
        yaml_rpcid_to_op = self._build_reverse_map(yaml_rpcids)
        json_rpcid_to_op = self._build_json_reverse_map(json_rpcids)

        # 3. Compare HAR rpcids against registry
        updates_for_json: Dict[str, str] = {}
        seen_rpcids = set()

        for rpcid, context in har_rpcids.items():
            if rpcid in seen_rpcids:
                continue
            seen_rpcids.add(rpcid)

            # Check if this rpcid is already known in YAML
            yaml_op = yaml_rpcid_to_op.get(rpcid)
            json_op = json_rpcid_to_op.get(rpcid)

            if yaml_op:
                # Known rpcid — confirmed still active
                result.confirmed.append(f"{yaml_op} = {rpcid}")
                # Ensure JSON cache has it too
                updates_for_json[self._op_to_json_key(yaml_op)] = rpcid
            elif json_op:
                # Known in JSON but not YAML — confirmed
                result.confirmed.append(f"{json_op} = {rpcid}")
            else:
                # Unknown rpcid — try to infer operation from context
                inferred_op = self._infer_operation(rpcid, context)
                if inferred_op:
                    # Check if this operation already has a DIFFERENT rpcid
                    existing_rpcid = yaml_rpcids.get(inferred_op)
                    if existing_rpcid and existing_rpcid != rpcid:
                        result.changed.append(
                            f"{inferred_op}: {existing_rpcid} -> {rpcid}"
                        )
                        updates_for_json[self._op_to_json_key(inferred_op)] = rpcid
                    else:
                        result.added.append(f"{inferred_op} = {rpcid}")
                        updates_for_json[self._op_to_json_key(inferred_op)] = rpcid
                else:
                    # Completely unknown — add with UNKNOWN_ prefix
                    result.added.append(f"UNKNOWN_{rpcid} = {rpcid}")
                    updates_for_json[f"UNKNOWN_{rpcid}"] = rpcid

        # 4. Update JSON cache
        if updates_for_json:
            self._update_json_cache(updates_for_json, result.build_label)

        logger.info(
            "[RpcidUpdater] HAR update complete: added=%d, changed=%d, "
            "confirmed=%d (operation=update_from_har, source=%s)",
            len(result.added), len(result.changed), len(result.confirmed),
            har_path,
        )
        return result

    def update_from_heap(self, heap_path: str) -> UpdateResult:
        """Mine V8 heap snapshot for gRPC method names and update registry.

        Scans the heap snapshot text for LabsTailwindOrchestrationService
        method names and adds any new ones to the JSON cache.

        Args:
            heap_path: Path to a .heapsnapshot file.

        Returns:
            UpdateResult with new_methods populated.
        """
        result = UpdateResult(source=heap_path)

        # 1. Read heap and extract method names
        try:
            with open(heap_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as exc:
            logger.error(
                "[RpcidUpdater] Failed to read heap snapshot "
                "(operation=update_from_heap): %s",
                exc,
            )
            return result

        methods = set(_GRPC_METHOD_PATTERN.findall(content))
        if not methods:
            logger.info(
                "[RpcidUpdater] No gRPC methods found in heap "
                "(operation=update_from_heap, source=%s)",
                heap_path,
            )
            return result

        # 2. Compare against known methods in JSON cache
        json_data = self._load_json_raw()
        existing_notes = json_data.get("_notes", {})
        # Extract existing method references from the notes
        existing_methods: set[str] = set()
        for note_text in existing_notes.values():
            if isinstance(note_text, str):
                for m in re.findall(r"LabsTailwindOrchestrationService\.(\w+)", note_text):
                    existing_methods.add(m)

        # Also check rpc_ids keys for gRPC-style operations
        rpc_ids = json_data.get("rpc_ids", {})
        for key, val in rpc_ids.items():
            if isinstance(val, str) and val in methods:
                existing_methods.add(val)

        new_methods = methods - existing_methods
        result.new_methods = sorted(new_methods)

        # 3. Map method names to operations where possible and update cache
        if new_methods:
            updates: Dict[str, str] = {}
            for method in new_methods:
                # Convert CamelCase to UPPER_SNAKE for JSON key
                op_key = self._method_to_op_key(method)
                updates[op_key] = method
            self._update_json_cache(updates)

        logger.info(
            "[RpcidUpdater] Heap update complete: %d total methods, "
            "%d new (operation=update_from_heap, source=%s)",
            len(methods), len(new_methods), heap_path,
        )
        return result

    # ──── HAR Parsing ─────────────────────────────────────────────────────

    def _parse_har_batchexecute(self, har_path: str) -> Dict[str, Dict]:
        """Parse HAR file for all batchexecute calls.

        Extracts rpcids from the f.req POST parameter in each
        batchexecute request.  The f.req value is URL-encoded and contains
        the wire format: [[[rpcid, json_payload, null, "generic"]]]

        Args:
            har_path: Path to the .har file.

        Returns:
            Dict of rpcid -> context dict with keys:
                url, payload_preview, notebook_id, timestamp.
        """
        rpcids: Dict[str, Dict] = {}

        try:
            with open(har_path, "r", encoding="utf-8") as f:
                har_data = json.load(f)
        except Exception as exc:
            logger.error(
                "[RpcidUpdater] Failed to load HAR file "
                "(operation=parse_har): %s",
                exc,
            )
            return rpcids

        entries = har_data.get("log", {}).get("entries", [])

        for entry in entries:
            request = entry.get("request", {})
            url = request.get("url", "")

            # Only process batchexecute calls to NLM
            if _NLM_BATCH_PATH not in url:
                continue

            # Extract notebook_id from source-path URL param
            notebook_id = None
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                params = parse_qs(parsed.query)
                source_path = params.get("source-path", [None])[0]
                if source_path:
                    nb_match = re.search(
                        r"/notebook/([a-f0-9-]{36})",
                        unquote(source_path),
                    )
                    if nb_match:
                        notebook_id = nb_match.group(1)
            except Exception:
                pass

            # Get timestamp
            timestamp = entry.get("startedDateTime", "")

            # Extract f.req from POST data
            post_data = request.get("postData", {})
            post_text = post_data.get("text", "")
            if not post_text:
                continue

            # Parse form-encoded body for f.req parameter
            f_req = self._extract_f_req(post_text)
            if not f_req:
                continue

            # Extract rpcids from the f.req value
            # Format: [[["rpcid","payload",null,"generic"]]]
            # or multi-RPC: [[["rpc1","p1",null,"generic"],["rpc2","p2",null,"generic"]]]
            extracted = self._extract_rpcids_from_freq(f_req)
            for rpcid, payload_preview in extracted:
                if rpcid not in rpcids:
                    rpcids[rpcid] = {
                        "url": url,
                        "payload_preview": payload_preview[:200],
                        "notebook_id": notebook_id,
                        "timestamp": timestamp,
                    }

        logger.debug(
            "[RpcidUpdater] Parsed %d batchexecute entries, found %d "
            "unique rpcids (operation=parse_har, source=%s)",
            len(entries), len(rpcids), har_path,
        )
        return rpcids

    def _extract_f_req(self, post_text: str) -> Optional[str]:
        """Extract the f.req parameter from URL-encoded POST body.

        Args:
            post_text: Raw form-encoded POST body text.

        Returns:
            Decoded f.req value, or None if not found.
        """
        try:
            params = parse_qs(post_text, keep_blank_values=True)
            freq_values = params.get("f.req")
            if freq_values:
                return freq_values[0]
        except Exception:
            pass

        # Fallback: manual extraction for malformed bodies
        for part in post_text.split("&"):
            if part.startswith("f.req="):
                return unquote(part[6:])

        return None

    def _extract_rpcids_from_freq(
        self, f_req: str
    ) -> List[tuple[str, str]]:
        """Extract rpcid(s) and payload previews from f.req value.

        The f.req wire format is a nested JSON array:
          [[[rpcid, payload_json, null, "generic"]]]

        For multi-RPC batches:
          [[[rpc1, p1, null, "generic"], [rpc2, p2, null, "generic"]]]

        Args:
            f_req: Decoded f.req parameter value.

        Returns:
            List of (rpcid, payload_preview) tuples.
        """
        results: List[tuple[str, str]] = []

        try:
            # The f.req is a JSON array — parse it
            parsed = json.loads(f_req)
            if not isinstance(parsed, list) or not parsed:
                return results

            # Navigate the nested structure
            # Outer: [[inner_array]]
            # inner_array = [rpc_call_1, rpc_call_2, ...]
            # rpc_call = [rpcid, payload_str, null, "generic"]
            outer = parsed[0]
            if not isinstance(outer, list):
                return results

            for item in outer:
                if not isinstance(item, list) or len(item) < 2:
                    continue
                rpcid = item[0]
                payload = item[1] if len(item) > 1 else ""
                if isinstance(rpcid, str) and len(rpcid) >= 2:
                    results.append((rpcid, str(payload)[:200]))
        except (json.JSONDecodeError, TypeError, IndexError):
            # Fallback: regex extraction for malformed JSON
            for match in _RPCID_PATTERN.finditer(f_req):
                rpcid = match.group(1)
                if rpcid and len(rpcid) >= 2:
                    results.append((rpcid, ""))

        return results

    # ──── Build Label Extraction ──────────────────────────────────────────

    def _extract_build_label(self, har_path: str) -> Optional[str]:
        """Extract the NLM build label from batchexecute URL params.

        Args:
            har_path: Path to the .har file.

        Returns:
            Build label string or None.
        """
        try:
            with open(har_path, "r", encoding="utf-8") as f:
                har_data = json.load(f)
        except Exception:
            return None

        for entry in har_data.get("log", {}).get("entries", []):
            url = entry.get("request", {}).get("url", "")
            if _NLM_BATCH_PATH not in url:
                continue
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                params = parse_qs(parsed.query)
                bl = params.get("bl", [None])[0]
                if bl and bl.startswith(_NLM_BUILD_LABEL_PREFIX):
                    return bl
            except Exception:
                continue
        return None

    # ──── Registry Loading ────────────────────────────────────────────────

    def _load_yaml_rpcids(self) -> Dict[str, str]:
        """Load operation -> rpcid mapping from the YAML registry.

        Returns:
            Dict of operation_name -> rpcid string.
        """
        if not self._yaml_path.exists():
            return {}
        try:
            with open(self._yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            ops = data.get("operations", {})
            result: Dict[str, str] = {}
            for name, op_data in ops.items():
                if isinstance(op_data, dict) and op_data.get("rpcid"):
                    result[name] = op_data["rpcid"]
            return result
        except Exception as exc:
            logger.warning(
                "[RpcidUpdater] Failed to load YAML registry "
                "(operation=load_yaml): %s",
                exc,
            )
            return {}

    def _load_json_rpcids(self) -> Dict[str, str]:
        """Load operation -> rpcid mapping from the JSON cache.

        Returns:
            Dict of OPERATION_NAME -> rpcid string.
        """
        data = self._load_json_raw()
        return data.get("rpc_ids", {})

    def _load_json_raw(self) -> Dict[str, Any]:
        """Load the raw JSON cache data.

        Returns:
            Full JSON dict, or empty dict on failure.
        """
        if not self._json_path.exists():
            return {}
        try:
            with open(self._json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning(
                "[RpcidUpdater] Failed to load JSON cache "
                "(operation=load_json): %s",
                exc,
            )
            return {}

    # ──── Reverse Maps ────────────────────────────────────────────────────

    def _build_reverse_map(
        self, yaml_rpcids: Dict[str, str]
    ) -> Dict[str, str]:
        """Build rpcid -> operation_name map from YAML entries.

        Args:
            yaml_rpcids: operation_name -> rpcid dict.

        Returns:
            rpcid -> operation_name dict.
        """
        return {rpcid: op for op, rpcid in yaml_rpcids.items() if rpcid}

    def _build_json_reverse_map(
        self, json_rpcids: Dict[str, str]
    ) -> Dict[str, str]:
        """Build rpcid -> operation_name map from JSON cache entries.

        Args:
            json_rpcids: OPERATION_NAME -> rpcid dict.

        Returns:
            rpcid -> OPERATION_NAME dict.
        """
        return {rpcid: op for op, rpcid in json_rpcids.items() if rpcid}

    # ──── Operation Inference ─────────────────────────────────────────────

    def _infer_operation(
        self, rpcid: str, context: Dict
    ) -> Optional[str]:
        """Try to infer the operation name for an unknown rpcid.

        Uses payload structure heuristics and notebook context to guess
        what operation a batchexecute call corresponds to.

        Args:
            rpcid:   The unknown rpcid string.
            context: Dict with url, payload_preview, notebook_id, timestamp.

        Returns:
            Inferred operation name or None if no match.
        """
        payload = context.get("payload_preview", "")

        # Heuristic: check payload patterns against known structures
        # These are the distinctive payload shapes from confirmed RPCs:
        #   create_note:  [nb_id, question_text]  — short, 2-element
        #   add_source:   [[source_obj], nb_id, [2], config]  — has [2]
        #   rename:       [nb_id, [[null,null,null,[null,name]]]]  — nested nulls
        #   delete_source: [[[source_id]], [2]]  — triple-nested then [2]
        #   register_files: [[[fn]], nb_id, [2], config]  — filenames

        # For now, return None — the rpcid gets logged as UNKNOWN_ and
        # the operator can manually assign it in the YAML registry.
        # Future: build a payload classifier from confirmed HAR examples.
        return None

    # ──── Key Conversion ──────────────────────────────────────────────────

    @staticmethod
    def _op_to_json_key(yaml_op: str) -> str:
        """Convert YAML operation name to JSON cache key format.

        YAML uses snake_case (e.g. "create_note").
        JSON cache uses UPPER_SNAKE (e.g. "CREATE_NOTE").

        Args:
            yaml_op: YAML operation name.

        Returns:
            UPPER_SNAKE key for the JSON cache.
        """
        return yaml_op.upper()

    @staticmethod
    def _method_to_op_key(method: str) -> str:
        """Convert a CamelCase gRPC method name to UPPER_SNAKE key.

        Example: "GenerateFreeFormStreamed" -> "GENERATE_FREE_FORM_STREAMED"

        Args:
            method: CamelCase method name.

        Returns:
            UPPER_SNAKE operation key.
        """
        # Insert underscore before uppercase letters preceded by lowercase
        s1 = re.sub(r"([a-z])([A-Z])", r"\1_\2", method)
        # Insert underscore before uppercase letters followed by lowercase
        # (handles sequences like "HTMLParser" -> "HTML_Parser")
        s2 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s1)
        return s2.upper()

    # ──── JSON Cache Update ───────────────────────────────────────────────

    # v1.57.2 [2026-03-26] — Atomic JSON cache update with merge semantics
    def _update_json_cache(
        self,
        updates: Dict[str, str],
        build_label: Optional[str] = None,
    ) -> None:
        """Update data/nlm_rpc_registry.json with new rpcid mappings.

        Merges new entries into the existing JSON cache.  Does NOT remove
        existing entries — this is additive only to avoid breaking lookups
        for operations not present in the current HAR capture.

        Args:
            updates:     Dict of OPERATION_KEY -> rpcid_or_method.
            build_label: New build label to record (if available).
        """
        data = self._load_json_raw()

        # Ensure rpc_ids section exists
        rpc_ids = data.setdefault("rpc_ids", {})
        changed = 0

        for key, value in updates.items():
            if rpc_ids.get(key) != value:
                old = rpc_ids.get(key, "(new)")
                rpc_ids[key] = value
                changed += 1
                logger.debug(
                    "[RpcidUpdater] JSON cache: %s = %s (was %s)",
                    key, value, old,
                )

        # Update metadata
        data["updated_at"] = datetime.now().isoformat()
        if build_label:
            data["bl"] = build_label
        data["_version"] = data.get("_version", "5.0")

        # v1.58.0 [2026-06-11] — Now actually atomic (tmp + os.replace); the
        # old comment said "atomically" but used a plain truncating write,
        # which corrupted the cache for concurrent readers ("Extra data").
        try:
            from engine.utils import atomic_write_json
            atomic_write_json(self._json_path, data)
            logger.info(
                "[RpcidUpdater] JSON cache updated: %d entries changed "
                "(operation=update_json_cache)",
                changed,
            )
        except Exception as exc:
            logger.error(
                "[RpcidUpdater] Failed to write JSON cache "
                "(operation=update_json_cache): %s",
                exc,
            )


# ──── Module-level Convenience ────────────────────────────────────────────

def update_from_har(har_path: str) -> UpdateResult:
    """Convenience: run HAR update with default paths.

    Args:
        har_path: Path to .har file.

    Returns:
        UpdateResult.
    """
    return RpcidUpdater().update_from_har(har_path)


def update_from_heap(heap_path: str) -> UpdateResult:
    """Convenience: run heap update with default paths.

    Args:
        heap_path: Path to .heapsnapshot file.

    Returns:
        UpdateResult.
    """
    return RpcidUpdater().update_from_heap(heap_path)
