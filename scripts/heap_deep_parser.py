"""
Heap Deep Parser  —  scripts/heap_deep_parser.py
=================================================
Full structural parse of V8 heap snapshots produced by Chrome DevTools.
Unlike heap_miner.py (regex on the string tail), this walks the ENTIRE
node/edge graph to reconstruct objects, extract all script source code,
recover DOM content, and catalog the full internal API surface.

Node types parsed:   hidden, array, string, object, code, closure, regexp,
                     number, native, synthetic, concatenated string, sliced
                     string, symbol, bigint, object shape
Edge types parsed:   context, element, property, internal, hidden, shortcut, weak

Outputs (in data/heap_output/<stem>_deep/):
  strings_all.txt          - ALL unique strings, longest first (goldmine)
  strings_large.txt        - Strings >2 KB (source code, configs, chat history)
  strings_credentials.txt  - Strings matching credential patterns
  scripts.js               - Every JS function/script source found in the heap
  objects.json             - Reconstructed interesting JS objects (credentials etc.)
  api_surface.txt          - All unique function names + constructor names
  dom_content.txt          - DOM node values: inputs, textareas, forms
  findings.json            - Structured credential findings (compat with heap_miner)
  report.txt               - Human-readable summary report

Usage:
    python scripts/heap_deep_parser.py data/har_files/Heap.heapsnapshot
    python scripts/heap_deep_parser.py data/har_files/*.heapsnapshot --nexus
    python scripts/heap_deep_parser.py --all           # scan data/har_files/
    python scripts/heap_deep_parser.py --strings-only  # faster: skip graph walk
"""
from __future__ import annotations

import argparse
import array as _array
import json
import logging
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import ijson

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ──── Directories ──────────────────────────────────────────────────────────────
HAR_DIR   = Path("data/har_files")
OUT_BASE  = Path("data/heap_output")

# ──── Thresholds ──────────────────────────────────────────────────────────────
LARGE_STRING_BYTES   = 400          # >400 chars → save to strings_large.txt
HUGE_STRING_BYTES    = 50_000        # >50 KB → likely source code
MAX_STRINGS_ALL      = 5_000_000     # safety cap on string table size
MAX_OBJECT_PROPS     = 200           # max properties per reconstructed object
SNIPPET_CONTEXT      = 120           # chars either side of credential match

# ──── Node type indices (from Chrome snapshot meta) ───────────────────────────
NT_HIDDEN = 0; NT_ARRAY = 1; NT_STRING = 2; NT_OBJECT = 3; NT_CODE = 4
NT_CLOSURE = 5; NT_REGEXP = 6; NT_NUMBER = 7; NT_NATIVE = 8; NT_SYNTHETIC = 9
NT_CONCAT_STR = 10; NT_SLICED_STR = 11; NT_SYMBOL = 12; NT_BIGINT = 13
NT_OBJECT_SHAPE = 14

# ──── Edge type indices ───────────────────────────────────────────────────────
ET_CONTEXT = 0; ET_ELEMENT = 1; ET_PROPERTY = 2; ET_INTERNAL = 3
ET_HIDDEN = 4; ET_SHORTCUT = 5; ET_WEAK = 6

# ──── Credential patterns ─────────────────────────────────────────────────────
# (category, compiled_regex) — first group = value if present
CRED_PATTERNS: List[Tuple[str, re.Pattern]] = [
    # Google auth
    ("google_sapisid",    re.compile(r'\bSAPISID=([A-Za-z0-9_/]+)')),
    ("google_apisid",     re.compile(r'\bAPISID=([A-Za-z0-9_/]+)')),
    ("google_1psid",      re.compile(r'\b__Secure-1PSID=([A-Za-z0-9_/.-]+)')),
    ("google_3psid",      re.compile(r'\b__Secure-3PSID=([A-Za-z0-9_/.-]+)')),
    ("google_sid",        re.compile(r'\bSID=([A-Za-z0-9_/.-]{20,})')),
    ("google_hsid",       re.compile(r'\bHSID=([A-Za-z0-9_/.-]+)')),
    ("google_osid",       re.compile(r'\bOSID=([A-Za-z0-9_/.-]+)')),
    ("google_at_token",   re.compile(r'"at":?"?([A-Za-z0-9_/-]{20,}:[0-9]+)"?')),
    ("google_at_token2",  re.compile(r'\bat_token["\s:=]+([A-Za-z0-9_/+=-]{30,})')),
    ("google_fsid",       re.compile(r'f\.sid["\s:=]+(-?[0-9]{10,})')),
    ("google_bl",         re.compile(r'"bl":"([^"]{20,})"')),
    ("google_wiz",        re.compile(r'WIZ_global_data\s*=\s*(\{[^;]{100,})\s*;')),
    ("google_gaia",       re.compile(r'"DS:2"[^[]*\["(\d{15,21})"')),
    # OAuth / access tokens
    ("oauth_access_token",re.compile(r'\bya29\.[A-Za-z0-9_.-]{40,}')),
    ("oauth_refresh_token",re.compile(r'\b1//[A-Za-z0-9_.-]{40,}')),
    ("oauth_bearer",      re.compile(r'[Bb]earer ([A-Za-z0-9_.-]{40,})')),
    # GitHub
    ("github_pat",        re.compile(r'\bghp_[A-Za-z0-9]{36,}')),
    ("github_oauth",      re.compile(r'\bgho_[A-Za-z0-9]{36,}')),
    ("github_app_token",  re.compile(r'\bghs_[A-Za-z0-9]{36,}')),
    ("github_refresh",    re.compile(r'\bghr_[A-Za-z0-9]{36,}')),
    ("github_actions",    re.compile(r'\bGITHUB_TOKEN["\s:=]+([A-Za-z0-9_.-]{20,})')),
    # JWT
    ("jwt_token",         re.compile(r'\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}')),
    # API keys
    ("google_api_key",    re.compile(r'\bAIza[A-Za-z0-9_-]{35}')),
    ("generic_api_key",   re.compile(r'["\']?api[_-]?key["\']?\s*[:=]\s*["\']?([A-Za-z0-9_-]{20,})')),
    ("generic_secret",    re.compile(r'["\']?(?:secret|client_secret)["\']?\s*[:=]\s*["\']([A-Za-z0-9_-]{20,})')),
    # Colab / runtime
    ("colab_tunnel_url",  re.compile(r'https://colab\.research\.google\.com/tun/m/[A-Za-z0-9_-]+')),
    ("colab_runtime_url", re.compile(r'https://[a-z0-9-]+\.colab\.research\.google\.com')),
    ("colab_xsrf",        re.compile(r'_xsrf["\s:=]+([A-Za-z0-9_|-]{20,})')),
    ("colab_grpc",        re.compile(r'/\$rpc/google\.internal\.\S+/\S+')),
    # NLM
    ("nlm_rpcid",         re.compile(r'"([A-Za-z0-9]{5,8})"\s*,\s*null\s*,\s*\[\[(?:null,){0,3}\[.*?1\]')),
    ("nlm_notebook_id",   re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')),
    # OpenAI / Anthropic
    ("openai_key",        re.compile(r'\bsk-[A-Za-z0-9]{40,}')),
    ("anthropic_key",     re.compile(r'\bsk-ant-[A-Za-z0-9_-]{80,}')),
    # AWS
    ("aws_access_key",    re.compile(r'\bAKIA[0-9A-Z]{16}\b')),
    ("aws_secret_key",    re.compile(r'aws_secret[_a-z]*\s*=\s*([A-Za-z0-9/+]{40})')),
    # URLs with auth
    ("url_with_token",    re.compile(r'https?://[^\s"\'<>]{5,}\?[^\s"\'<>]*(?:token|key|auth|session)[^\s"\'<>]*=[A-Za-z0-9_.-]{10,}')),
    # Password fields
    ("password_field",    re.compile(r'["\']?password["\']?\s*[:=]\s*["\']([^"\']{8,})["\']')),
    # Email addresses
    ("email",             re.compile(r'\b[a-zA-Z0-9._%+-]{3,}@(?:gmail|googlemail|yahoo|outlook|hotmail)\.com\b')),
    # Drive file IDs
    ("drive_file_id",     re.compile(r'/(?:file/d|folders)/([A-Za-z0-9_-]{28,33})')),
    # Internal gRPC paths
    ("grpc_path",         re.compile(r'google\.[a-z]+\.[a-z]+\.[a-z]+\.[A-Za-z]+Service/[A-Z][A-Za-z]+')),
    # Client IDs
    ("oauth_client_id",   re.compile(r'\b([0-9]{10,20}-[a-z0-9]{30,}\.apps\.googleusercontent\.com)')),
    # Auth URLs
    ("auth_endpoint",     re.compile(r'https://accounts\.google\.com/[A-Za-z/]+\?[^\s"\'<>]{20,}')),
    # Internal config JSON keys
    ("config_blob",       re.compile(r'(?:WIZ|FE|ds\.ic)\s*=\s*(\{.{200,}?\})\s*;', re.DOTALL)),
    # Websocket URLs
    ("websocket_url",     re.compile(r'wss?://[^\s"\'<>]{10,}')),
    # XSRF / CSRF tokens
    ("xsrf_token",        re.compile(r'(?:xsrf|csrf)[-_]?token["\s:=]+([A-Za-z0-9_/+=-]{16,})')),
]

# ──── Property names to harvest from objects ──────────────────────────────────
INTERESTING_PROPS = frozenset([
    "token", "access_token", "refresh_token", "id_token", "auth_token",
    "api_key", "apiKey", "secret", "client_secret", "password", "credential",
    "SAPISID", "APISID", "SID", "HSID", "SSID", "cookie", "Cookie",
    "session_id", "sessionId", "session", "xsrf", "csrf", "nonce",
    "Authorization", "authorization", "bearer", "at", "at_token",
    "f.sid", "fsid", "bl", "rt", "expires", "expires_in",
    "email", "user", "username", "account", "sub", "aud", "iss",
    "url", "endpoint", "host", "baseURL", "origin",
    "notebook_id", "notebookId", "source_id", "document_id",
    "runtime_id", "runtimeId", "task_id", "taskId",
    "tunnel_url", "proxy_token", "jwt",
    "value",  # catch-all for form inputs
    "defaultValue", "textContent", "innerHTML", "innerText",
    "src", "href", "action",  # DOM attributes with URLs
    "localStorage", "sessionStorage",
    "_token", "_key", "_secret", "_session", "_cookie",
])

# ──── DOM node types to extract content from ──────────────────────────────────
DOM_CONTENT_NODES = frozenset([
    "HTMLInputElement", "HTMLTextAreaElement", "HTMLFormElement",
    "HTMLSelectElement", "HTMLButtonElement", "HTMLScriptElement",
])

# ──── Function name patterns indicating internal APIs ─────────────────────────
API_FUNC_PATTERNS = [
    re.compile(r'(?:generate|create|list|get|update|delete|fetch|request|send|post)\w+', re.I),
    re.compile(r'(?:auth|login|token|credential|session|cookie|user|account)\w+', re.I),
    re.compile(r'(?:rpc|grpc|service|client|api|endpoint)\w+', re.I),
    re.compile(r'[A-Z][a-z]+(?:[A-Z][a-z]+){2,}'),  # CamelCase multi-word = likely API method
]


# ──── Streaming snapshot parser ───────────────────────────────────────────────

class HeapSnapshot:
    """Parsed V8 heap snapshot with full string table + node/edge arrays."""

    def __init__(self) -> None:
        self.strings:     List[str] = []
        self.nodes:       "_array.array[int]" = _array.array("q")  # int64 (nodes can be large)
        self.edges:       "_array.array[l]" = _array.array("l")    # int32 sufficient for edges
        self.node_fields: int = 6    # fields per node (read from meta)
        self.edge_fields: int = 3    # fields per edge
        self.node_types:  List[str] = []
        self.edge_types:  List[str] = []
        self.meta:        Dict[str, Any] = {}
        self.parse_time_s: float = 0.0

    @classmethod
    def from_file(cls, path: Path, strings_only: bool = False) -> "HeapSnapshot":
        """Stream-parse a .heapsnapshot file.

        Args:
            path: Path to the .heapsnapshot file.
            strings_only: If True, skip nodes/edges (faster, less analysis).

        Returns:
            Populated HeapSnapshot instance.
        """
        import time
        snap = cls()
        t0 = time.time()
        file_size = path.stat().st_size
        log.info("Parsing %s (%.1f MB) …", path.name, file_size / 1_048_576)

        with open(path, "rb") as f:
            # ijson streaming parse
            for prefix, event, value in ijson.parse(f, use_float=True):
                # ── Metadata ──────────────────────────────────────────────────
                if prefix == "snapshot.meta.node_fields":
                    pass  # count populated below
                elif prefix == "snapshot.meta.node_fields.item":
                    pass  # we count dynamically
                elif prefix.startswith("snapshot.meta") and event in ("string", "number", "boolean"):
                    # collect raw meta
                    pass
                elif prefix == "snapshot.meta" and event == "map_key":
                    pass
                # node_types first array of arrays
                elif prefix == "snapshot.meta.node_types.item.item":
                    if isinstance(value, str):
                        snap.node_types.append(value)
                # edge types
                elif prefix == "snapshot.meta.edge_types.item.item":
                    if isinstance(value, str):
                        snap.edge_types.append(value)

                # ── Strings ───────────────────────────────────────────────────
                elif prefix == "strings.item":
                    if len(snap.strings) < MAX_STRINGS_ALL:
                        snap.strings.append(value if isinstance(value, str) else str(value))

                # ── Nodes ─────────────────────────────────────────────────────
                elif not strings_only and prefix == "nodes.item":
                    snap.nodes.append(int(value))

                # ── Edges ─────────────────────────────────────────────────────
                elif not strings_only and prefix == "edges.item":
                    snap.edges.append(int(value))

        # Determine field widths from meta (already known, but reconfirm)
        # For this snapshot format: node_fields=6, edge_fields=3
        snap.node_fields = 6
        snap.edge_fields = 3

        snap.parse_time_s = time.time() - t0
        log.info(
            "  Parsed in %.1fs: %d strings, %d node ints, %d edge ints",
            snap.parse_time_s,
            len(snap.strings),
            len(snap.nodes),
            len(snap.edges),
        )
        return snap

    # ──── String table helpers ─────────────────────────────────────────────────

    def str_at(self, idx: int) -> str:
        """Safely get string at index, returns '' on out-of-bounds."""
        if 0 <= idx < len(self.strings):
            return self.strings[idx]
        return ""

    # ──── Node accessors ───────────────────────────────────────────────────────
    # Node layout: [type, name_str_idx, id, self_size, edge_count, detachedness]

    def node_count(self) -> int:
        return len(self.nodes) // self.node_fields

    def node_type(self, n: int) -> int:
        return int(self.nodes[n * self.node_fields])

    def node_name_idx(self, n: int) -> int:
        return int(self.nodes[n * self.node_fields + 1])

    def node_name(self, n: int) -> str:
        return self.str_at(self.node_name_idx(n))

    def node_self_size(self, n: int) -> int:
        return int(self.nodes[n * self.node_fields + 3])

    def node_edge_count(self, n: int) -> int:
        return int(self.nodes[n * self.node_fields + 4])

    # ──── Edge accessors ───────────────────────────────────────────────────────
    # Edge layout: [type, name_or_index, to_node_offset]
    # to_node_offset is byte offset into nodes array / field_count → node index

    def edge_count_total(self) -> int:
        return len(self.edges) // self.edge_fields

    def edge_type(self, e: int) -> int:
        return int(self.edges[e * self.edge_fields])

    def edge_name_or_index(self, e: int) -> int:
        return int(self.edges[e * self.edge_fields + 1])

    def edge_to_node(self, e: int) -> int:
        """Returns node index of destination (to_node_offset / node_fields)."""
        raw = int(self.edges[e * self.edge_fields + 2])
        return raw // self.node_fields

    def edge_name(self, e: int) -> str:
        """Get the string name of a property/context edge."""
        et = self.edge_type(e)
        if et in (ET_PROPERTY, ET_CONTEXT, ET_INTERNAL, ET_HIDDEN, ET_SHORTCUT):
            return self.str_at(self.edge_name_or_index(e))
        elif et == ET_ELEMENT:
            return f"[{self.edge_name_or_index(e)}]"
        return ""

    # ──── Edge start index per node ───────────────────────────────────────────

    def build_edge_starts(self) -> "_array.array[int]":
        """Build an array mapping node_index → first edge index.

        Returns:
            Array of length node_count+1 where arr[n] = first edge for node n.
        """
        nc = self.node_count()
        starts = _array.array("l", [0] * (nc + 1))
        current_edge = 0
        for n in range(nc):
            starts[n] = current_edge
            current_edge += self.node_edge_count(n)
        starts[nc] = current_edge
        return starts


# ──── Analysis engine ─────────────────────────────────────────────────────────

class DeepAnalyzer:
    """Runs the full extraction pipeline on a parsed HeapSnapshot."""

    def __init__(self, snap: HeapSnapshot, out_dir: Path) -> None:
        self.snap = snap
        self.out_dir = out_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        # Results accumulators
        self.cred_findings: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.large_strings: List[Tuple[int, str]] = []   # (length, value)
        self.all_strings_unique: List[str] = []
        self.scripts: List[str] = []
        self.api_functions: List[str] = []
        self.objects: List[Dict[str, Any]] = []
        self.dom_content: List[Dict[str, str]] = []
        self.local_storage: Dict[str, str] = {}
        self.session_storage: Dict[str, str] = {}

    # ──── Pass 1: Process all strings ─────────────────────────────────────────

    def analyze_strings(self) -> None:
        """Run all credential patterns against every string in the table."""
        log.info("  Analyzing %d strings …", len(self.snap.strings))
        seen: set = set()
        total_large = 0

        for s in self.snap.strings:
            if not s or not isinstance(s, str):
                continue
            s_stripped = s.strip()
            if not s_stripped:
                continue

            # Dedup for all-strings output
            key = s_stripped[:200]
            if key not in seen:
                seen.add(key)
                self.all_strings_unique.append(s_stripped)

            # Large strings
            if len(s_stripped) >= LARGE_STRING_BYTES:
                total_large += 1
                if len(self.large_strings) < 50_000:
                    self.large_strings.append((len(s_stripped), s_stripped))

            # Credential patterns
            for cat, pat in CRED_PATTERNS:
                for m in pat.finditer(s_stripped):
                    val = m.group(1) if m.lastindex else m.group(0)
                    if len(val) < 6:
                        continue
                    # Build context snippet
                    start = max(0, m.start() - SNIPPET_CONTEXT)
                    end   = min(len(s_stripped), m.end() + SNIPPET_CONTEXT)
                    snippet = s_stripped[start:end]
                    finding = {
                        "value":   val,
                        "context": snippet,
                        "str_len": len(s_stripped),
                        "source":  "string_table",
                    }
                    # Dedup by value
                    existing = [f["value"] for f in self.cred_findings[cat]]
                    if val not in existing:
                        self.cred_findings[cat].append(finding)

        log.info(
            "  Strings analyzed: %d unique, %d large, %d credential categories",
            len(self.all_strings_unique),
            total_large,
            len(self.cred_findings),
        )

    # ──── Pass 2: Walk node graph ──────────────────────────────────────────────

    def analyze_graph(self) -> None:
        """Walk the node/edge graph to extract objects, scripts, and DOM."""
        if len(self.snap.nodes) == 0:
            log.info("  No node data (strings-only mode)")
            return

        log.info("  Building edge index for %d nodes …", self.snap.node_count())
        edge_starts = self.snap.build_edge_starts()
        nc = self.snap.node_count()
        log.info("  Walking %d nodes …", nc)

        code_seen:    set = set()
        func_seen:    set = set()
        obj_seen:     set = set()
        dom_seen:     set = set()

        for n in range(nc):
            ntype = self.snap.node_type(n)
            nname = self.snap.node_name(n)

            # ── Code / script nodes ──────────────────────────────────────────
            if ntype == NT_CODE:
                if nname and nname not in code_seen:
                    code_seen.add(nname)
                    # Is it a script source? Check self_size
                    sz = self.snap.node_self_size(n)
                    self.api_functions.append(nname)
                    if sz > 200:
                        self.scripts.append(f"/* function: {nname} (size={sz}) */")
                # Walk edges for source property
                self._extract_code_edges(n, edge_starts)

            # ── Object / closure nodes ────────────────────────────────────────
            elif ntype in (NT_OBJECT, NT_CLOSURE, NT_NATIVE):
                if nname in DOM_CONTENT_NODES:
                    self._extract_dom_node(n, edge_starts, nname, dom_seen)
                elif nname in ("Window", "NativeContext", "global"):
                    self._extract_global_node(n, edge_starts, nname)
                elif nname == "Script":
                    self._extract_script_node(n, edge_starts, code_seen)
                else:
                    self._extract_object_node(n, edge_starts, nname, obj_seen)

            # ── String nodes themselves ───────────────────────────────────────
            # (already handled in analyze_strings via the strings array)

        log.info(
            "  Graph walk done: %d scripts, %d api funcs, %d objects, %d dom nodes",
            len(self.scripts),
            len(self.api_functions),
            len(self.objects),
            len(self.dom_content),
        )

    def _get_property_edges(
        self, node_idx: int, edge_starts: "_array.array[int]"
    ) -> Iterator[Tuple[str, int]]:
        """Yield (prop_name, target_node_index) for all property edges of a node."""
        e_start = edge_starts[node_idx]
        e_end   = edge_starts[node_idx + 1]
        for e in range(e_start, e_end):
            if e >= self.snap.edge_count_total():
                break
            et = self.snap.edge_type(e)
            if et in (ET_PROPERTY, ET_INTERNAL, ET_CONTEXT):
                prop = self.snap.edge_name(e)
                target = self.snap.edge_to_node(e)
                if prop and 0 <= target < self.snap.node_count():
                    yield prop, target

    def _node_string_value(self, node_idx: int) -> Optional[str]:
        """If node is a string type, return its string content."""
        nt = self.snap.node_type(node_idx)
        if nt in (NT_STRING, NT_CONCAT_STR, NT_SLICED_STR):
            return self.snap.node_name(node_idx)
        return None

    def _extract_code_edges(
        self, node_idx: int, edge_starts: "_array.array[int]"
    ) -> None:
        """Extract 'source_url', 'script', and 'function_body' from code nodes."""
        for prop, target in self._get_property_edges(node_idx, edge_starts):
            if prop in ("source", "script_data", "source_url", "script"):
                val = self._node_string_value(target)
                if val and len(val) > 100:
                    header = f"/* source: {self.snap.node_name(node_idx)} */\n"
                    if header not in self.scripts:
                        self.scripts.append(header + val[:200_000])  # cap at 200K chars

    def _extract_script_node(
        self, node_idx: int, edge_starts: "_array.array[int]", seen: set
    ) -> None:
        """Extract source text from Script objects."""
        for prop, target in self._get_property_edges(node_idx, edge_starts):
            if prop in ("source", "sourceText"):
                val = self._node_string_value(target)
                if val and len(val) > 50 and val not in seen:
                    seen.add(val[:100])
                    self.scripts.append(f"/* Script node */\n{val[:200_000]}")

    def _extract_object_node(
        self,
        node_idx: int,
        edge_starts: "_array.array[int]",
        obj_name: str,
        seen: set,
    ) -> None:
        """Reconstruct a JS object's properties if they look interesting."""
        if len(self.objects) > 100_000:
            return
        props: Dict[str, str] = {}
        has_interesting = False

        for prop, target in self._get_property_edges(node_idx, edge_starts):
            if len(props) > MAX_OBJECT_PROPS:
                break
            is_interesting = prop in INTERESTING_PROPS
            val = self._node_string_value(target)
            if val is not None:
                props[prop] = val[:2000]  # cap
                if is_interesting:
                    has_interesting = True
            elif self.snap.node_type(target) == NT_NUMBER:
                props[prop] = f"(number:{self.snap.node_name(target)})"
                if is_interesting:
                    has_interesting = True

        if has_interesting and props:
            sig = f"{obj_name}:{','.join(sorted(props.keys())[:5])}"
            if sig not in seen:
                seen.add(sig)
                obj = {"_type": obj_name, "_node": node_idx, **props}
                self.objects.append(obj)
                # Also add credential findings from object properties
                for prop_name, val in props.items():
                    if not isinstance(val, str):
                        continue
                    for cat, pat in CRED_PATTERNS:
                        for m in pat.finditer(val):
                            v = m.group(1) if m.lastindex else m.group(0)
                            if len(v) >= 6:
                                existing = [f["value"] for f in self.cred_findings[cat]]
                                if v not in existing:
                                    self.cred_findings[cat].append({
                                        "value":   v,
                                        "context": f"object:{obj_name}.{prop_name}",
                                        "str_len": len(val),
                                        "source":  "graph_object",
                                    })

    def _extract_global_node(
        self, node_idx: int, edge_starts: "_array.array[int]", context_name: str
    ) -> None:
        """Extract global variables from Window / NativeContext."""
        for prop, target in self._get_property_edges(node_idx, edge_starts):
            if prop == "localStorage":
                self._extract_storage(target, edge_starts, self.local_storage)
            elif prop == "sessionStorage":
                self._extract_storage(target, edge_starts, self.session_storage)

    def _extract_storage(
        self,
        storage_node: int,
        edge_starts: "_array.array[int]",
        store: Dict[str, str],
    ) -> None:
        """Extract localStorage / sessionStorage key-value pairs."""
        for prop, target in self._get_property_edges(storage_node, edge_starts):
            val = self._node_string_value(target)
            if val is not None:
                store[prop] = val[:50_000]  # cap at 50KB per value

    def _extract_dom_node(
        self,
        node_idx: int,
        edge_starts: "_array.array[int]",
        node_name: str,
        seen: set,
    ) -> None:
        """Extract content/value from DOM element nodes."""
        content: Dict[str, str] = {"type": node_name}
        for prop, target in self._get_property_edges(node_idx, edge_starts):
            if prop in ("value", "defaultValue", "textContent", "innerHTML",
                        "innerText", "name", "id", "placeholder", "src", "href"):
                val = self._node_string_value(target)
                if val:
                    content[prop] = val[:5000]
        if len(content) > 1:
            sig = f"{node_name}:{content.get('name','')}:{content.get('id','')}"
            if sig not in seen and sig != f"{node_name}::":
                seen.add(sig)
                self.dom_content.append(content)

    # ──── Post-processing ──────────────────────────────────────────────────────

    def analyze_api_surface(self) -> None:
        """Catalog internal API function names from strings + code nodes."""
        api_candidates = set(self.api_functions)
        for s in self.snap.strings:
            if not isinstance(s, str) or len(s) < 5 or len(s) > 200:
                continue
            for pat in API_FUNC_PATTERNS:
                if pat.fullmatch(s.strip()):
                    api_candidates.add(s.strip())
                    break
        self.api_functions = sorted(api_candidates)

    def collect_large_strings(self) -> None:
        """Sort large strings by length (longest = most likely to be source/config)."""
        self.large_strings.sort(key=lambda x: x[0], reverse=True)

    # ──── Writers ──────────────────────────────────────────────────────────────

    def write_all_outputs(self) -> None:
        """Write all output files to self.out_dir."""
        log.info("  Writing outputs to %s …", self.out_dir)

        # 1. All unique strings (longest first for easy scanning)
        strings_sorted = sorted(self.all_strings_unique, key=len, reverse=True)
        (self.out_dir / "strings_all.txt").write_text(
            "\n".join(strings_sorted), encoding="utf-8", errors="replace"
        )
        log.info("    strings_all.txt: %d strings", len(strings_sorted))

        # 2. Large strings only
        self.collect_large_strings()
        large_lines = []
        for length, text in self.large_strings[:10_000]:
            large_lines.append(f"{'─'*60}")
            large_lines.append(f"[{length} chars]")
            large_lines.append(text[:100_000])  # cap display
        (self.out_dir / "strings_large.txt").write_text(
            "\n".join(large_lines), encoding="utf-8", errors="replace"
        )
        log.info("    strings_large.txt: %d large strings", len(self.large_strings))

        # 3. Credential strings (human-readable)
        cred_lines = []
        for cat in sorted(self.cred_findings.keys()):
            findings = self.cred_findings[cat]
            cred_lines.append(f"\n{'='*60}")
            cred_lines.append(f"  {cat.upper()}  ({len(findings)} findings)")
            cred_lines.append('='*60)
            for i, f in enumerate(findings[:50]):  # cap per category
                cred_lines.append(f"  [{i+1}] {f['value'][:200]}")
                ctx = f.get("context", "")
                if ctx and ctx != f["value"]:
                    cred_lines.append(f"      context: {ctx[:300]}")
                src = f.get("source", "")
                if src != "string_table":
                    cred_lines.append(f"      source: {src}")
        (self.out_dir / "strings_credentials.txt").write_text(
            "\n".join(cred_lines), encoding="utf-8", errors="replace"
        )

        # 4. JS scripts
        (self.out_dir / "scripts.js").write_text(
            "\n\n".join(self.scripts[:20_000]), encoding="utf-8", errors="replace"
        )
        log.info("    scripts.js: %d script/function entries", len(self.scripts))

        # 5. Reconstructed objects
        with open(self.out_dir / "objects.json", "w", encoding="utf-8") as fh:
            json.dump(self.objects[:20_000], fh, indent=2, default=str, ensure_ascii=False)
        log.info("    objects.json: %d objects", len(self.objects))

        # 6. API surface
        api_lines = [
            "# Internal API Surface — function names from heap",
            f"# Extracted: {len(self.api_functions)} names",
            "",
        ] + [f for f in self.api_functions if len(f) >= 5]
        (self.out_dir / "api_surface.txt").write_text(
            "\n".join(api_lines), encoding="utf-8", errors="replace"
        )
        log.info("    api_surface.txt: %d entries", len(self.api_functions))

        # 7. DOM content
        with open(self.out_dir / "dom_content.json", "w", encoding="utf-8") as fh:
            json.dump(self.dom_content, fh, indent=2, ensure_ascii=False)
        log.info("    dom_content.json: %d dom nodes", len(self.dom_content))

        # 8. Storage
        storage = {
            "localStorage":    self.local_storage,
            "sessionStorage":  self.session_storage,
        }
        with open(self.out_dir / "storage.json", "w", encoding="utf-8") as fh:
            json.dump(storage, fh, indent=2, ensure_ascii=False)
        log.info(
            "    storage.json: %d localStorage, %d sessionStorage keys",
            len(self.local_storage), len(self.session_storage)
        )

        # 9. Structured findings (compat with heap_miner format)
        findings_out: Dict[str, Any] = {
            "file":        str(self.out_dir.name),
            "generated":   datetime.utcnow().isoformat(),
            "string_count": len(self.snap.strings),
            "node_count":  self.snap.node_count(),
            "findings":    {cat: f for cat, f in self.cred_findings.items()},
            "summary": {
                "categories":     len(self.cred_findings),
                "total_findings": sum(len(v) for v in self.cred_findings.values()),
                "large_strings":  len(self.large_strings),
                "scripts":        len(self.scripts),
                "objects":        len(self.objects),
                "dom_nodes":      len(self.dom_content),
                "api_functions":  len(self.api_functions),
            },
        }
        with open(self.out_dir / "findings.json", "w", encoding="utf-8") as fh:
            json.dump(findings_out, fh, indent=2, default=str, ensure_ascii=False)

        # 10. Human-readable report
        self._write_report(findings_out)
        log.info("    All outputs written.")

    def _write_report(self, findings: Dict[str, Any]) -> None:
        summary = findings["summary"]
        lines = [
            "=" * 70,
            f"  HEAP DEEP PARSE REPORT",
            f"  {self.out_dir.parent.name}/{self.out_dir.name}",
            f"  Generated: {findings['generated']}",
            "=" * 70,
            "",
            "STATISTICS",
            f"  Strings in table:  {findings['string_count']:,}",
            f"  Node count:        {findings['node_count']:,}",
            f"  Large strings:     {summary['large_strings']:,}  (>{LARGE_STRING_BYTES} chars)",
            f"  Scripts extracted: {summary['scripts']:,}",
            f"  Objects found:     {summary['objects']:,}",
            f"  DOM nodes:         {summary['dom_nodes']:,}",
            f"  API functions:     {summary['api_functions']:,}",
            "",
            "CREDENTIAL FINDINGS",
        ]
        for cat in sorted(self.cred_findings.keys()):
            fs = self.cred_findings[cat]
            lines.append(f"  {cat:<35} {len(fs):>4} finding(s)")
            for f in fs[:5]:
                lines.append(f"    → {f['value'][:120]}")
        lines += [
            "",
            "TOP LARGE STRINGS (first 20)",
        ]
        for length, text in self.large_strings[:20]:
            preview = text[:200].replace("\n", " ")
            lines.append(f"  [{length:>7} chars] {preview}")
        lines += [
            "",
            "TOP API FUNCTIONS (first 50)",
        ]
        for fn in self.api_functions[:50]:
            lines.append(f"  {fn}")
        lines.append("")
        if self.local_storage:
            lines.append("LOCALSTORAGE KEYS")
            for k, v in list(self.local_storage.items())[:30]:
                lines.append(f"  {k}: {str(v)[:120]}")
            lines.append("")
        if self.session_storage:
            lines.append("SESSIONSTORAGE KEYS")
            for k, v in list(self.session_storage.items())[:30]:
                lines.append(f"  {k}: {str(v)[:120]}")
            lines.append("")

        (self.out_dir / "report.txt").write_text("\n".join(lines), encoding="utf-8")


# ──── Nexus integration ───────────────────────────────────────────────────────

def store_in_nexus(analyzer: DeepAnalyzer, stem: str) -> None:
    """Store key findings in the Nexus knowledge base."""
    try:
        import subprocess, sys
        title = f"Heap Deep Parse — {stem}"
        cred_summary = []
        for cat, findings in analyzer.cred_findings.items():
            if findings:
                cred_summary.append(f"## {cat} ({len(findings)})")
                for f in findings[:10]:
                    cred_summary.append(f"  - `{f['value'][:100]}`")
        api_sample = "\n".join(f"  - {fn}" for fn in analyzer.api_functions[:100])
        content = "\n".join([
            f"# {title}",
            f"Parse time: {analyzer.snap.parse_time_s:.1f}s",
            f"Strings: {len(analyzer.snap.strings):,}",
            f"Nodes: {analyzer.snap.node_count():,}",
            "",
            "## Credential Findings",
            "\n".join(cred_summary),
            "",
            "## API Surface Sample",
            api_sample,
        ])
        cmd = [
            sys.executable, "-m", "engine.nexus.bridge",
            "store", title, content,
            "--type", "note", "--category", "security",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            log.info("  Stored findings in Nexus.")
        else:
            log.warning("  Nexus store failed: %s", result.stderr[:200])
    except Exception as exc:
        log.warning("  Nexus integration error: %s", exc)


# ──── Entry point ─────────────────────────────────────────────────────────────

def collect_files(args: argparse.Namespace) -> List[Path]:
    """Resolve the list of snapshot files to process."""
    paths: List[Path] = []
    if args.all:
        paths = sorted(HAR_DIR.glob("**/*.heapsnapshot"))
    elif args.files:
        for f in args.files:
            p = Path(f)
            if p.is_file():
                paths.append(p)
            else:
                # Try glob
                paths.extend(sorted(Path(".").glob(f)))
    if not paths:
        paths = sorted(HAR_DIR.glob("**/*.heapsnapshot"))
    return paths


def process_file(path: Path, args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    """Parse and analyze a single heap snapshot."""
    stem = path.stem
    out_dir = OUT_BASE / f"{stem}_deep"

    try:
        snap = HeapSnapshot.from_file(path, strings_only=args.strings_only)
    except Exception as exc:
        log.error("Failed to parse %s: %s", path, exc)
        return None

    analyzer = DeepAnalyzer(snap, out_dir)

    log.info("  → String analysis …")
    analyzer.analyze_strings()

    if not args.strings_only:
        log.info("  → Graph walk …")
        analyzer.analyze_graph()
        log.info("  → API surface …")
        analyzer.analyze_api_surface()

    log.info("  → Writing outputs …")
    analyzer.write_all_outputs()

    if args.nexus:
        store_in_nexus(analyzer, stem)

    total = sum(len(v) for v in analyzer.cred_findings.values())
    log.info(
        "  ✓ %s done — %d credential findings, %d large strings, %d scripts",
        stem, total, len(analyzer.large_strings), len(analyzer.scripts)
    )
    return {
        "file":     str(path),
        "out_dir":  str(out_dir),
        "findings": total,
    }


def main() -> None:  # noqa: C901
    global OUT_BASE  # must be first use in function
    parser = argparse.ArgumentParser(
        description="Full V8 heap snapshot deep parser — walks node/edge graph, "
                    "extracts all strings, scripts, objects, DOM, localStorage."
    )
    parser.add_argument("files", nargs="*", help="Heap snapshot file(s) or globs")
    parser.add_argument("--all",          action="store_true", help="Process all .heapsnapshot files in data/har_files/")
    parser.add_argument("--strings-only", action="store_true", help="Skip graph walk (faster, strings+patterns only)")
    parser.add_argument("--nexus",        action="store_true", help="Store findings in Nexus")
    parser.add_argument("--out",          default=str(OUT_BASE), help="Output directory")
    args = parser.parse_args()

    out_base = Path(args.out)
    out_base.mkdir(parents=True, exist_ok=True)
    OUT_BASE = out_base

    paths = collect_files(args)
    if not paths:
        log.error("No .heapsnapshot files found.")
        sys.exit(1)

    log.info("Deep parsing %d file(s) …", len(paths))
    results = []
    for p in paths:
        log.info("\n%s\n  %s", "=" * 70, p)
        r = process_file(p, args)
        if r:
            results.append(r)

    # Write combined index
    index_path = OUT_BASE / "deep_index.json"
    with open(index_path, "w") as fh:
        json.dump({"runs": results, "generated": datetime.utcnow().isoformat()}, fh, indent=2)
    log.info("\nDone. Index written to %s", index_path)
    log.info("Outputs in %s/", OUT_BASE)


if __name__ == "__main__":
    main()
