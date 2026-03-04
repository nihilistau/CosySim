"""ARGUS tshark integration — TLS-decrypted packet capture for gRPC binary extraction.

Flow:
    1. Chrome must be launched with SSLKEYLOGFILE env var pointing to sslkeys.log
    2. tshark captures packets on the active interface, writing a .pcapng file
    3. Post-process: tshark reads the pcap with TLS keys, outputs HTTP/2 frames as JSON
    4. gRPC binary payloads extracted from DATA frames
    5. Cross-reference with proto reconstructor for field map generation

Key constraint: tshark only works for connections Chrome makes AFTER the SSLKEYLOGFILE
is set. Use it for targeted proto capture sessions, not ambient monitoring
(CDP network monitoring handles ambient traffic without TLS key setup).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from scripts.argus.config import DATA_DIR, TSHARK_PATH

logger = logging.getLogger(__name__)

SSL_KEYLOG = DATA_DIR / "sslkeys.log"
PCAP_DIR = DATA_DIR / "pcap"


@dataclass
class GrpcPayload:
    """A decoded gRPC payload from a tshark capture."""
    stream_id: int
    method: str
    service: str
    direction: str  # "request" | "response"
    data_hex: str
    data_bytes: bytes = field(default_factory=bytes)

    def __post_init__(self) -> None:
        if self.data_hex and not self.data_bytes:
            try:
                self.data_bytes = bytes.fromhex(self.data_hex.replace(":", "").replace(" ", ""))
            except ValueError:
                pass


class TsharkCapture:
    """Manages a tshark capture process + post-processing pipeline."""

    def __init__(self, interface: Optional[str] = None) -> None:
        self._interface = interface  # None = auto-detect
        self._process: Optional[subprocess.Popen] = None
        self._pcap_path: Optional[Path] = None

    # ──── Capture control ────

    def start(self, output_name: str = "argus_capture") -> Path:
        """Start a tshark capture, writing to data/argus/pcap/<output_name>.pcapng.

        Returns the path to the output pcapng file.
        """
        PCAP_DIR.mkdir(parents=True, exist_ok=True)
        self._pcap_path = PCAP_DIR / f"{output_name}.pcapng"

        if not Path(TSHARK_PATH).exists():
            raise FileNotFoundError(
                f"tshark not found at {TSHARK_PATH}. "
                "Install Wireshark from https://wireshark.org"
            )

        iface_args = ["-i", self._interface] if self._interface else ["-i", "1"]
        ssl_args = [
            "-o", f"tls.keylog_file:{SSL_KEYLOG}",
            "-o", "tls.debug_file:-",
        ]

        cmd = [
            TSHARK_PATH,
            *iface_args,
            *ssl_args,
            "-w", str(self._pcap_path),
            "-f", "tcp port 443",  # HTTPS only
            "-q",
        ]

        logger.info("TsharkCapture: starting capture → %s", self._pcap_path)
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return self._pcap_path

    def stop(self) -> Optional[Path]:
        """Stop the capture and return the pcapng path."""
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
            logger.info("TsharkCapture: capture stopped → %s", self._pcap_path)
        return self._pcap_path

    # ──── Post-processing ────

    def decode_pcap(self, pcap_path: Optional[Path] = None) -> List[Dict[str, Any]]:
        """Decode a pcapng file to HTTP/2 JSON frames.

        Args:
            pcap_path: Path to .pcapng file. Defaults to the last captured file.

        Returns:
            List of decoded HTTP/2 frame dicts.
        """
        path = pcap_path or self._pcap_path
        if not path or not path.exists():
            logger.warning("TsharkCapture: no pcap to decode")
            return []

        cmd = [
            TSHARK_PATH,
            "-r", str(path),
            "-o", f"tls.keylog_file:{SSL_KEYLOG}",
            "-Y", "http2",
            "-T", "json",
            "-e", "http2.stream_id",
            "-e", "http2.header.name",
            "-e", "http2.header.value",
            "-e", "http2.data.data",
            "-e", "ip.dst",
            "-e", "ip.src",
            "-e", "tcp.dstport",
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                logger.error("TsharkCapture: decode failed: %s", result.stderr[:500])
                return []
            return json.loads(result.stdout) if result.stdout.strip() else []
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            logger.error("TsharkCapture: decode error: %s", exc)
            return []

    def extract_grpc_payloads(
        self, frames: List[Dict[str, Any]]
    ) -> List[GrpcPayload]:
        """Extract gRPC binary payloads from HTTP/2 DATA frames.

        Args:
            frames: JSON frame list from ``decode_pcap()``.

        Returns:
            List of GrpcPayload objects ready for proto reconstruction.
        """
        payloads: List[GrpcPayload] = []
        stream_methods: Dict[int, Dict[str, str]] = {}

        for frame in frames:
            layers = frame.get("_source", {}).get("layers", {})

            stream_ids = layers.get("http2.stream_id", [])
            if not stream_ids:
                continue
            stream_id = int(stream_ids[0]) if isinstance(stream_ids, list) else int(stream_ids)

            # HEADERS frame: extract :path and :method
            header_names = layers.get("http2.header.name", [])
            header_values = layers.get("http2.header.value", [])
            if isinstance(header_names, list) and isinstance(header_values, list):
                headers = dict(zip(header_names, header_values))
                path = headers.get(":path", "")
                if "/" in path and stream_id not in stream_methods:
                    parts = path.rstrip("/").split("/")
                    stream_methods[stream_id] = {
                        "service": parts[-2] if len(parts) >= 2 else "",
                        "method": parts[-1] if parts else "",
                    }

            # DATA frame: extract binary payload
            data_hex = layers.get("http2.data.data", "")
            if data_hex:
                info = stream_methods.get(stream_id, {})
                payloads.append(
                    GrpcPayload(
                        stream_id=stream_id,
                        method=info.get("method", "unknown"),
                        service=info.get("service", "unknown"),
                        direction="request" if (stream_id % 2 == 1) else "response",
                        data_hex=data_hex if isinstance(data_hex, str) else data_hex[0],
                    )
                )

        logger.info("TsharkCapture: extracted %d gRPC payloads", len(payloads))
        return payloads

    # ──── Async context manager ────

    async def __aenter__(self) -> "TsharkCapture":
        return self

    async def __aexit__(self, *_: Any) -> None:
        self.stop()

    # ──── Utility ────

    @staticmethod
    def detect_interfaces() -> List[str]:
        """Return list of available network interface names."""
        try:
            result = subprocess.run(
                [TSHARK_PATH, "-D"],
                capture_output=True, text=True, timeout=10
            )
            lines = result.stdout.strip().split("\n")
            return [line.split(" ", 1)[1] if " " in line else line for line in lines]
        except Exception:
            return []

    @staticmethod
    def setup_sslkeylog_env() -> str:
        """Return the environment variable instructions for SSLKEYLOGFILE setup.

        Chrome must be launched with SSLKEYLOGFILE set for TLS decryption to work.
        """
        keylog = str(SSL_KEYLOG.absolute())
        return (
            f"To enable TLS key logging in Chrome:\n\n"
            f"PowerShell:\n"
            f'  $env:SSLKEYLOGFILE = "{keylog}"\n'
            f'  Start-Process "chrome.exe"\n\n'
            f"Or set SSLKEYLOGFILE as a permanent system env var and restart Chrome."
        )
