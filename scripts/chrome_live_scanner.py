"""Chrome Live Process Memory Scanner.

Implements the V8MapScan MetaMap-detection algorithm (Wang et al., 2022) adapted
for live Windows process memory via ctypes ReadProcessMemory + Windows VirtualQueryEx.

Algorithm (from "Juicing V8: A primary account for the memory forensics of the V8
JavaScript engine"):
  1. Scan Chrome process memory for MetaMap signature: FF 03 (20|40) 00 00 00 00 00
  2. Walk back 18 bytes from each hit to find the self-referencing MetaMap pointer
  3. Scan for pointers to MetaMap+1 to find all object maps
  4. Scan for pointers to each map+1 to find all objects of that type
  5. Apply 70+ credential regex patterns to extracted strings

Also performs a broad string scan (regex over readable memory regions) as a fast
credential harvest without requiring MetaMap discovery.

Usage:
    python scripts/chrome_live_scanner.py
    python scripts/chrome_live_scanner.py --pid 1234
    python scripts/chrome_live_scanner.py --string-scan-only
    python scripts/chrome_live_scanner.py --metamap
    python scripts/chrome_live_scanner.py --nexus

Reference:
    https://github.com/unhcfreg/V8-Memory-Forensics-Plugins
    https://doi.org/10.1016/j.fsidi.2022.301389
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import logging
import os
import re
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

import psutil

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ──── Windows API constants ────
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100
PAGE_READWRITE = 0x04
PAGE_READONLY = 0x02
PAGE_EXECUTE_READ = 0x20
PAGE_EXECUTE_READWRITE = 0x40
PAGE_EXECUTE_WRITECOPY = 0x80
PAGE_WRITECOPY = 0x08

READABLE_PAGES = {
    PAGE_READWRITE, PAGE_READONLY,
    PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE,
    PAGE_EXECUTE_WRITECOPY, PAGE_WRITECOPY,
}

# ──── V8 MetaMap magic bytes (from V8MapScan.py paper) ────
# FF 03 20 00 00 00 00 00  (Node v12-v15, 32-bit instance type)
# FF 03 40 00 00 00 00 00  (alternative)
METAMAP_SIGS = [
    b"\xff\x03\x20\x00\x00\x00\x00\x00",
    b"\xff\x03\x40\x00\x00\x00\x00\x00",
]
METAMAP_BACK_OFFSET = 18  # bytes before signature → pointer to MetaMap

WORD_SIZE = 8  # 64-bit
READ_CHUNK = 4 * 1024 * 1024  # 4MB chunks

# ──── Chrome process name patterns ────
CHROME_PROCESS_NAMES = {"chrome.exe", "chromium.exe", "msedge.exe"}
CHROME_NETWORK_CMDLINE = "network.mojom.NetworkService"
CHROME_RENDERER_CMDLINE = "renderer"

OUT_BASE = Path("data/heap_output")

# ──── Credential patterns (mirrors heap_deep_parser.py) ────
CRED_PATTERNS: Dict[str, re.Pattern] = {
    # Google session cookies
    "SAPISID":           re.compile(r'\bSAPISID=[A-Za-z0-9_/\-]{20,60}\b'),
    "APISID":            re.compile(r'\bAPISID=[A-Za-z0-9_/\-]{20,60}\b'),
    "SID":               re.compile(r'\bSID=[A-Za-z0-9_/\-]{50,200}\b'),
    "SSID":              re.compile(r'\bSSID=[A-Za-z0-9_/\-]{20,60}\b'),
    "HSID":              re.compile(r'\bHSID=[A-Za-z0-9_/\-]{20,60}\b'),
    "PSID":              re.compile(r'\b__Secure-[13]PSID=[A-Za-z0-9_/\-]{50,200}\b'),
    "NID":               re.compile(r'\bNID=[A-Za-z0-9_=+/\-]{20,200}\b'),
    "GAPS":              re.compile(r'\bGAPS=[A-Za-z0-9_:]{20,60}\b'),

    # Auth tokens
    "bearer_token":      re.compile(r'Bearer\s+[A-Za-z0-9\-_]{20,500}', re.IGNORECASE),
    "oauth_token":       re.compile(r'"access_token"\s*:\s*"([^"]{20,500})"'),
    "oauth_token2":      re.compile(r'ya29\.[A-Za-z0-9\-_]{60,200}'),
    "refresh_token":     re.compile(r'"refresh_token"\s*:\s*"([^"]{20,200})"'),

    # JWT tokens
    "jwt":               re.compile(r'eyJ[A-Za-z0-9\-_]{10,200}\.eyJ[A-Za-z0-9\-_]{10,500}\.[A-Za-z0-9\-_]{20,200}'),

    # Google API keys
    "goog_api_key":      re.compile(r'AIza[0-9A-Za-z\-_]{35}'),

    # GitHub tokens
    "github_token":      re.compile(r'gh[pousr]_[A-Za-z0-9]{36,}'),
    "github_classic":    re.compile(r'ghp_[A-Za-z0-9]{36}'),

    # SAPISIDHASH (NLM auth pattern)
    "sapisidhash":       re.compile(r'SAPISIDHASH\s+\d+_[A-Fa-f0-9]{40}'),

    # f.sid (NLM session)
    "f_sid":             re.compile(r'"f\.sid"\s*:\s*"(-?\d{15,20})"'),
    "f_sid2":            re.compile(r'f\.sid=(-?\d{15,20})'),

    # NLM notebook UUIDs
    "nlm_notebook":      re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'),

    # HPKE public keys (NLM per-notebook encryption)
    "hpke_key":          re.compile(r'"hpkePublicKey"\s*:\s*\{[^}]{50,500}\}'),

    # Colab/gRPC session
    "colab_xsrf":        re.compile(r'"colab\.research\.google\.com.*?xsrf[^"]{10,80}"', re.DOTALL),
    "drive_token":       re.compile(r'TE9[A-Za-z0-9+/]{20,80}={0,2}'),

    # OAuth client IDs
    "oauth_client":      re.compile(r'[0-9]{10,14}-[a-z0-9]{32}\.apps\.googleusercontent\.com'),

    # URLs with auth
    "authed_url":        re.compile(r'https://[^"\'<\s]*(?:token|key|auth|sid|session)[^"\'<\s]*', re.IGNORECASE),

    # Email addresses
    "email":             re.compile(r'\b[A-Za-z0-9._%+\-]{3,30}@(gmail|googlemail|google)\.com\b'),
    "github_email":      re.compile(r'\b[A-Za-z0-9._%+\-]{3,30}@users\.noreply\.github\.com\b'),

    # Colab tunnel JWTs
    "tunnel_jwt":        re.compile(r'm-s-[a-z0-9]{10,20}'),
    "tunnel_url":        re.compile(r'https://colab\.research\.google\.com/tun/m/[a-z0-9\-]+'),

    # gRPC endpoints
    "grpc_endpoint":     re.compile(r'colab(?:\.research)?\.google\.com/\$rpc/[A-Za-z.]+/[A-Za-z]+'),

    # Drive file IDs
    "drive_file":        re.compile(r'[0-9A-Za-z_\-]{28,44}(?=.*drive|.*google)', re.IGNORECASE),
}


# ──── WinAPI wrappers ────
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress",       ctypes.c_void_p),
        ("AllocationBase",    ctypes.c_void_p),
        ("AllocationProtect", wt.DWORD),
        ("RegionSize",        ctypes.c_size_t),
        ("State",             wt.DWORD),
        ("Protect",           wt.DWORD),
        ("Type",              wt.DWORD),
    ]

def open_process(pid: int) -> Optional[int]:
    """Open Chrome process for reading."""
    handle = kernel32.OpenProcess(
        PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid
    )
    if not handle:
        err = ctypes.get_last_error()
        logger.error("OpenProcess(%d) failed: error %d", pid, err)
        return None
    return handle


def close_process(handle: int) -> None:
    kernel32.CloseHandle(handle)


def read_memory(handle: int, address: int, size: int) -> Optional[bytes]:
    """Read `size` bytes from process memory at `address`."""
    buf = ctypes.create_string_buffer(size)
    bytes_read = ctypes.c_size_t(0)
    ok = kernel32.ReadProcessMemory(
        handle, ctypes.c_void_p(address), buf, size, ctypes.byref(bytes_read)
    )
    if not ok:
        return None
    return buf.raw[:bytes_read.value]


def iter_readable_regions(handle: int) -> Generator[Tuple[int, int], None, None]:
    """Yield (base_address, size) for all readable committed memory regions."""
    mbi = MEMORY_BASIC_INFORMATION()
    address = 0

    while True:
        size_mbi = ctypes.sizeof(mbi)
        ret = kernel32.VirtualQueryEx(handle, ctypes.c_void_p(address), ctypes.byref(mbi), size_mbi)
        if ret == 0:
            break

        region_end = address + mbi.RegionSize
        if (mbi.State == MEM_COMMIT
                and mbi.Protect in READABLE_PAGES
                and (mbi.Protect & PAGE_GUARD) == 0
                and (mbi.Protect & PAGE_NOACCESS) == 0
                and mbi.RegionSize > 0):
            yield (address, mbi.RegionSize)

        address = region_end
        if address >= 0x7FFFFFFFFFFF:  # 48-bit user space limit
            break


# ──── Chrome process discovery ────
def find_chrome_pids(prefer_network: bool = True) -> List[Tuple[int, str]]:
    """Return list of (pid, description) for Chrome processes.

    Prefers NetworkService subprocess which holds session cookies.

    Args:
        prefer_network: If True, prioritize the network utility process.

    Returns:
        List of (pid, description) tuples, best candidates first.
    """
    candidates: List[Tuple[int, str, int]] = []  # (pid, desc, priority)

    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info["name"] or "").lower()
            cmdline = " ".join(proc.info.get("cmdline") or [])

            if name not in CHROME_PROCESS_NAMES:
                continue

            if CHROME_NETWORK_CMDLINE in cmdline:
                priority = 0
                desc = "NetworkService (has live cookies)"
            elif "gpu-process" in cmdline:
                priority = 5
                desc = "GPU process"
            elif "utility" in cmdline:
                priority = 2
                desc = "Utility"
            elif len(cmdline) < 200:  # Main process (short cmdline)
                priority = 1
                desc = "Main process"
            else:
                priority = 3
                desc = "Renderer/other"

            candidates.append((proc.info["pid"], desc, priority))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    candidates.sort(key=lambda x: x[2])
    return [(pid, desc) for pid, desc, _ in candidates]


# ──── MetaMap detection (V8MapScan algorithm) ────
def find_metamap_in_region(data: bytes, region_base: int) -> Optional[int]:
    """Search a memory region for the MetaMap signature.

    From V8MapScan: scan for `FF 03 (20|40) 00 00 00 00 00`, then read
    pointer 18 bytes before the hit. Find the most common repeated pointer
    — that is the MetaMap address.

    Args:
        data: Raw bytes of the memory region.
        region_base: Base virtual address of the region.

    Returns:
        MetaMap address + 1 (as stored in V8 tagged pointers), or None.
    """
    candidates: List[int] = []

    for sig in METAMAP_SIGS:
        offset = 0
        while True:
            idx = data.find(sig, offset)
            if idx == -1:
                break
            offset = idx + 1

            # Read pointer 18 bytes before the signature
            ptr_offset = idx - METAMAP_BACK_OFFSET
            if ptr_offset < 0 or ptr_offset + 8 > len(data):
                continue

            raw_ptr = data[ptr_offset:ptr_offset + 8]
            try:
                ptr_value = struct.unpack("<Q", raw_ptr)[0]
            except struct.error:
                continue

            if ptr_value > 0x1000:  # Basic sanity check — not zero/null
                candidates.append(ptr_value)

    if not candidates:
        return None

    # Most common pointer is the MetaMap address (from paper's deduplication logic)
    from collections import Counter
    most_common = Counter(candidates).most_common(1)
    if most_common:
        metamap_ptr = most_common[0][0]
        # V8 uses tagged pointers (address + 1), so actual address = ptr - 1
        metamap_addr = (metamap_ptr & ~0xFFFF) - 1
        if metamap_addr > 0:
            return metamap_addr + 1  # Return tagged pointer form
    return None


def scan_for_maps(handle: int, metamap_tagged: int, all_regions: List[Tuple[int, bytes]]) -> List[int]:
    """Find all object maps by scanning for pointers to metamap_tagged.

    Args:
        handle: Process handle.
        metamap_tagged: MetaMap address + 1 (tagged pointer).
        all_regions: Pre-read list of (base_address, data) tuples.

    Returns:
        List of map addresses (untagged).
    """
    target = struct.pack("<Q", metamap_tagged)
    maps: List[int] = []
    seen: set = set()

    for base, data in all_regions:
        offset = 0
        while True:
            idx = data.find(target, offset)
            if idx == -1:
                break
            offset = idx + 1
            map_addr = base + idx - 1  # Untagged (pointer to map is stored as addr+1)
            if map_addr not in seen and map_addr > 0x1000:
                seen.add(map_addr)
                maps.append(map_addr)

    return maps


def extract_strings_from_map(handle: int, map_addr: int, all_regions: List[Tuple[int, bytes]]) -> List[str]:
    """Extract V8 strings for all objects belonging to a given map.

    Args:
        handle: Process handle.
        map_addr: Object map address (untagged).
        all_regions: Pre-read memory regions.

    Returns:
        List of extracted string values.
    """
    # Tagged pointer form = map_addr + 1
    target = struct.pack("<Q", map_addr + 1)
    strings: List[str] = []

    for base, data in all_regions:
        offset = 0
        while True:
            idx = data.find(target, offset)
            if idx == -1:
                break
            offset = idx + 1
            obj_addr = base + idx - 1  # Object lives at address before the map pointer

            # V8 SeqOneByteString layout:
            # [0x00] map pointer (8 bytes)
            # [0x08] hash + length (4+4 bytes, length in upper 32)
            # [0x10] character data (length bytes)
            str_len_offset = obj_addr + 0x0C
            if str_len_offset + 4 > base + len(data):
                continue

            local_offset = str_len_offset - base
            if local_offset < 0 or local_offset + 4 > len(data):
                continue

            try:
                raw_len = struct.unpack("<I", data[local_offset:local_offset + 4])[0]
                length = raw_len  # Already the length in newer V8
                if length <= 0 or length > 2048:
                    continue
            except struct.error:
                continue

            chars_offset = obj_addr + 0x10
            chars_local = chars_offset - base
            if chars_local < 0 or chars_local + length > len(data):
                continue

            try:
                chars = data[chars_local:chars_local + length]
                text = chars.decode("utf-8", errors="replace")
                text = text.strip()
                if len(text) >= 4 and text.isprintable():
                    strings.append(text)
            except Exception:
                continue

    return strings


# ──── Fast pre-filter keyword list ────
# These bytes appear in all high-value credentials. We byte-search first,
# then only decode+regex the 512-byte context window around each hit.
# This reduces the decoded text from 367 MB to a few KB per process.
_PREFILTER_KEYWORDS: List[bytes] = [
    b"SAPISID=", b"APISID=", b"__Secure-1PSID=", b"__Secure-3PSID=",
    b"SSID=", b"HSID=", b"NID=", b"GAPS=",
    b"Bearer ", b"bearer ", b"ya29.", b"access_token",
    b"refresh_token", b"eyJhbGciOi", b"eyJhbGc",
    b"AIza", b"ghp_", b"gho_", b"ghu_", b"ghs_",
    b"SAPISIDHASH", b"f.sid", b"hpkePublicKey",
    b"@gmail.com", b"@googlemail.com",
    b"colab.research.google.com",
    b"notebooklm.google.com",
    b"m-s-", b"drive.google.com",
    b"SID=A", b"SID=g", b"SID=e",
    b"github.com/login",
]
_CONTEXT_WINDOW = 512  # bytes around each keyword hit to decode+regex


def scan_region_for_credentials(
    data: bytes,
    region_base: int,
    results: Dict[str, List[str]],
    min_string_len: int = 8,
) -> None:
    """Apply credential regex patterns to a raw memory region.

    Fast two-pass approach:
    1. Byte-search for known credential keywords (microseconds per region)
    2. Only decode+regex a small context window around each hit

    Args:
        data: Raw bytes of the region.
        region_base: Virtual base address (for context).
        results: Dict accumulating findings by pattern name.
        min_string_len: Minimum printable string length to record.
    """
    # Collect candidate windows via fast byte search
    hit_positions: set = set()
    for keyword in _PREFILTER_KEYWORDS:
        pos = 0
        while True:
            idx = data.find(keyword, pos)
            if idx == -1:
                break
            # Add the window start (clamped)
            win_start = max(0, idx - 64)
            hit_positions.add(win_start)
            pos = idx + 1

    if not hit_positions:
        return  # No credentials in this region

    # Decode only the context windows and apply all regex patterns
    decoded_windows: List[str] = []
    for win_start in sorted(hit_positions):
        win_end = min(len(data), win_start + _CONTEXT_WINDOW)
        chunk = data[win_start:win_end]
        try:
            decoded_windows.append(chunk.decode("latin-1"))
        except Exception:
            pass

    if not decoded_windows:
        return

    # Combine small windows for a single regex pass per pattern
    text = " ".join(decoded_windows)
    for name, pattern in CRED_PATTERNS.items():
        for match in pattern.finditer(text):
            hit = match.group(0).strip()
            if len(hit) >= 8:
                results.setdefault(name, [])
                if hit not in results[name]:
                    results[name].append(hit)


# ──── Main scanner class ────
class ChromeLiveScanner:
    """Orchestrates live Chrome process memory scanning."""

    def __init__(self, output_dir: Path = OUT_BASE):
        self.output_dir = output_dir
        self.ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.scan_dir = output_dir / f"live_scan_{self.ts}"
        self.scan_dir.mkdir(parents=True, exist_ok=True)
        self.findings: Dict[str, Any] = {
            "scan_time": datetime.now(timezone.utc).isoformat(),
            "processes": [],
            "credentials": {},
            "metamap_found": False,
            "total_bytes_read": 0,
            "total_regions": 0,
        }

    def scan_pid(
        self,
        pid: int,
        desc: str = "",
        metamap_mode: bool = False,
        string_scan: bool = True,
    ) -> Dict[str, Any]:
        """Scan a single Chrome process.

        Args:
            pid: Process ID.
            desc: Human-readable description.
            metamap_mode: If True, perform MetaMap-based V8 object extraction.
            string_scan: If True, perform broad credential regex scan.

        Returns:
            Per-process findings dict.
        """
        logger.info("Opening process PID %d (%s)", pid, desc)
        handle = open_process(pid)
        if not handle:
            return {"pid": pid, "error": "could not open process"}

        proc_results: Dict[str, Any] = {
            "pid": pid,
            "desc": desc,
            "regions_scanned": 0,
            "bytes_read": 0,
            "credentials": {},
            "metamap_address": None,
            "strings_from_v8": [],
        }

        # Max region size to read for credential scanning (large regions are
        # mapped DLLs/executables which never contain live cookies or tokens)
        MAX_REGION_BYTES = 16 * 1024 * 1024  # 16 MB

        try:
            # ── Phase 1: enumerate + read all readable regions ──
            logger.info("Enumerating memory regions for PID %d…", pid)
            all_regions: List[Tuple[int, bytes]] = []
            region_count = 0
            skipped_large = 0

            for base, size in iter_readable_regions(handle):
                if size > MAX_REGION_BYTES:
                    skipped_large += 1
                    continue

                # Read in chunks to handle large regions
                full_data = b""
                remaining = size
                addr = base
                while remaining > 0:
                    chunk_size = min(remaining, READ_CHUNK)
                    chunk = read_memory(handle, addr, chunk_size)
                    if chunk is None:
                        break
                    full_data += chunk
                    addr += chunk_size
                    remaining -= chunk_size

                if full_data:
                    all_regions.append((base, full_data))
                    proc_results["bytes_read"] += len(full_data)
                    region_count += 1

            proc_results["regions_scanned"] = region_count
            logger.info("PID %d: read %d regions, %.1f MB (skipped %d large regions)",
                        pid, region_count, proc_results["bytes_read"] / 1e6, skipped_large)

            # ── Phase 2: Broad credential string scan ──
            if string_scan:
                logger.info("Running credential pattern scan on PID %d…", pid)
                cred_results: Dict[str, List[str]] = {}
                for base, data in all_regions:
                    scan_region_for_credentials(data, base, cred_results)
                proc_results["credentials"] = cred_results
                total_creds = sum(len(v) for v in cred_results.values())
                logger.info("PID %d: found %d credential hits across %d pattern types",
                            pid, total_creds, len(cred_results))

            # ── Phase 3: MetaMap-based V8 string extraction ──
            if metamap_mode:
                logger.info("Searching for V8 MetaMap in PID %d…", pid)
                metamap_tagged = None
                for base, data in all_regions:
                    metamap_tagged = find_metamap_in_region(data, base)
                    if metamap_tagged:
                        proc_results["metamap_address"] = hex(metamap_tagged)
                        logger.info("MetaMap found at tagged address: %s", hex(metamap_tagged))
                        self.findings["metamap_found"] = True
                        break

                if metamap_tagged:
                    logger.info("Scanning for object maps…")
                    maps = scan_for_maps(handle, metamap_tagged, all_regions)
                    logger.info("Found %d object maps", len(maps))
                    proc_results["map_count"] = len(maps)

                    # Extract strings from first 100 maps (avoid timeout)
                    all_strings: List[str] = []
                    for map_addr in maps[:100]:
                        strings = extract_strings_from_map(handle, map_addr, all_regions)
                        all_strings.extend(strings)

                    # Deduplicate and filter
                    unique_strings = list(dict.fromkeys(all_strings))
                    # Apply credential scan to extracted strings too
                    v8_text = "\n".join(unique_strings)
                    for name, pattern in CRED_PATTERNS.items():
                        for match in pattern.finditer(v8_text):
                            hit = match.group(0).strip()
                            if len(hit) >= 8:
                                proc_results["credentials"].setdefault(name, [])
                                if hit not in proc_results["credentials"][name]:
                                    proc_results["credentials"][name].append(hit)

                    proc_results["strings_from_v8"] = unique_strings[:500]  # Top 500
                    logger.info("Extracted %d unique V8 strings", len(unique_strings))

        finally:
            close_process(handle)

        return proc_results

    def scan(
        self,
        pids: Optional[List[int]] = None,
        metamap_mode: bool = False,
        string_scan: bool = True,
    ) -> Dict[str, Any]:
        """Run the full scan.

        Args:
            pids: Specific PIDs to scan. If None, auto-discovers Chrome processes.
            metamap_mode: Enable MetaMap V8 extraction.
            string_scan: Enable broad credential regex scan.

        Returns:
            Full findings dict.
        """
        if pids:
            targets = [(pid, "user-specified") for pid in pids]
        else:
            targets = find_chrome_pids()
            if not targets:
                logger.error("No Chrome processes found")
                return self.findings

        logger.info("Scanning %d Chrome process(es)", len(targets))

        # Merge credentials across all processes
        merged_creds: Dict[str, List[str]] = {}

        for pid, desc in targets:
            proc_result = self.scan_pid(
                pid, desc,
                metamap_mode=metamap_mode,
                string_scan=string_scan,
            )
            self.findings["processes"].append(proc_result)
            self.findings["total_bytes_read"] += proc_result.get("bytes_read", 0)
            self.findings["total_regions"] += proc_result.get("regions_scanned", 0)

            for cred_type, values in proc_result.get("credentials", {}).items():
                merged_creds.setdefault(cred_type, [])
                for v in values:
                    if v not in merged_creds[cred_type]:
                        merged_creds[cred_type].append(v)

        self.findings["credentials"] = merged_creds
        self._save_results()
        return self.findings

    def _save_results(self) -> None:
        """Save findings to disk."""
        # Full JSON report
        report_path = self.scan_dir / "live_scan_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(self.findings, f, indent=2)

        # Human-readable credentials file
        creds_path = self.scan_dir / "credentials.txt"
        with open(creds_path, "w", encoding="utf-8") as f:
            f.write(f"Chrome Live Memory Scan — {self.findings['scan_time']}\n")
            f.write(f"Total bytes read: {self.findings['total_bytes_read']:,}\n")
            f.write(f"Processes scanned: {len(self.findings['processes'])}\n")
            f.write("=" * 70 + "\n\n")

            creds = self.findings.get("credentials", {})
            if not creds:
                f.write("No credentials found\n")
            else:
                for cred_type, values in sorted(creds.items()):
                    f.write(f"[{cred_type}] ({len(values)} unique)\n")
                    for v in values[:20]:  # Cap at 20 per type
                        f.write(f"  {v[:200]}\n")
                    f.write("\n")

        # Cookies specifically (for account pool update)
        cookie_names = {
            "SAPISID", "APISID", "SID", "SSID", "HSID",
            "PSID", "NID", "GAPS",
            "bearer_token", "oauth_token2",
        }
        cookie_data = {k: v for k, v in self.findings.get("credentials", {}).items()
                       if k in cookie_names and v}
        if cookie_data:
            cookies_path = self.scan_dir / "cookies_extracted.json"
            with open(cookies_path, "w", encoding="utf-8") as f:
                json.dump(cookie_data, f, indent=2)

        logger.info("Results saved to: %s", self.scan_dir)
        logger.info("  Full report: %s", report_path)
        logger.info("  Credentials: %s", creds_path)


def print_summary(findings: Dict[str, Any]) -> None:
    """Print human-readable summary."""
    creds = findings.get("credentials", {})
    procs = findings.get("processes", [])
    total_mb = findings.get("total_bytes_read", 0) / 1e6

    print(f"\n{'═' * 65}")
    print(f"  Chrome Live Memory Scan")
    print(f"  Processes: {len(procs)}  |  Memory read: {total_mb:.1f} MB")
    print(f"  MetaMap found: {findings.get('metamap_found', False)}")
    print(f"{'═' * 65}")

    if not creds:
        print("  No credentials found")
    else:
        # Sort by priority
        priority_order = [
            "SAPISID", "SID", "PSID", "SSID", "HSID", "APISID", "NID", "GAPS",
            "oauth_token2", "bearer_token", "jwt", "goog_api_key",
            "github_token", "github_classic", "sapisidhash", "f_sid",
            "nlm_notebook", "tunnel_jwt", "tunnel_url", "oauth_client",
            "email", "github_email",
        ]
        all_types = priority_order + [k for k in creds if k not in priority_order]

        for cred_type in all_types:
            values = creds.get(cred_type, [])
            if not values:
                continue
            print(f"\n  [{cred_type}] — {len(values)} unique:")
            for v in values[:5]:
                print(f"    {v[:100]}")
            if len(values) > 5:
                print(f"    … and {len(values) - 5} more")

    print(f"\n{'═' * 65}\n")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Scan live Chrome process memory for credentials and V8 strings",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--pid", type=int, nargs="*", help="Specific PIDs to scan (default: auto-discover)")
    parser.add_argument("--list-pids", action="store_true", help="List Chrome processes and exit")
    parser.add_argument("--metamap", action="store_true", help="Enable MetaMap-based V8 string extraction")
    parser.add_argument("--string-scan-only", action="store_true", help="Broad string scan only (no MetaMap)")
    parser.add_argument("--nexus", action="store_true", help="Store findings in Nexus knowledge base")
    parser.add_argument("--max-procs", type=int, default=3, help="Maximum processes to scan (default: 3)")
    args = parser.parse_args()

    if args.list_pids:
        pids = find_chrome_pids()
        if not pids:
            print("No Chrome processes found")
        else:
            print(f"Chrome processes ({len(pids)}):")
            for pid, desc in pids:
                print(f"  PID {pid:6d}  {desc}")
        return

    scanner = ChromeLiveScanner()

    # Determine targets
    pids = args.pid if args.pid else None
    if pids is None:
        discovered = find_chrome_pids()
        if not discovered:
            logger.error("No Chrome processes found — is Chrome running?")
            sys.exit(1)
        # Limit to best candidates
        pids = [p for p, _ in discovered[:args.max_procs]]
        logger.info("Auto-discovered PIDs: %s", pids)

    use_metamap = args.metamap and not args.string_scan_only
    findings = scanner.scan(
        pids=pids,
        metamap_mode=use_metamap,
        string_scan=True,
    )

    print_summary(findings)

    if args.nexus:
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            creds = findings.get("credentials", {})
            summary = (
                f"Live Chrome memory scan — {len(creds)} credential types found, "
                f"{findings['total_bytes_read'] // 1024 // 1024}MB read from "
                f"{len(findings['processes'])} processes"
            )
            client.add_entry(
                f"Chrome Live Scan {findings['scan_time'][:10]}",
                json.dumps({"summary": summary, "credential_types": list(creds.keys()),
                            "counts": {k: len(v) for k, v in creds.items()}}, indent=2),
                content_type="memory",
                category="debugging",
            )
            logger.info("Findings stored in Nexus")
        except Exception as e:
            logger.warning("Nexus store failed: %s", e)

    print(f"Results saved to: {scanner.scan_dir}")


if __name__ == "__main__":
    main()
