"""ARGUS batchexecute decoder — parse Google's internal batchexecute protocol.

Used by NotebookLM (LabsTailwindUi) and Gemini (BardChatUi).

Request format:
    POST /_/{service}/data/batchexecute
    Body: f.req=%5B%5B%5B%22{rpcid}%22%2C%22{payload}%22%2Cnull%2C%22generic%22%5D%5D%5D

    Decoded: f.req=[[["rpcid","json_payload",null,"generic"]]]

Response format:
    Starts with: )]}'\n
    Then one or more wrb.fr frames:
    [[["wrb.fr","rpcid","{json_response}",null,null,null,"generic"],...],...]
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Response prefix that must be stripped
_RESPONSE_PREFIX = ")]}'\n"


@dataclass
class BatchRequest:
    """A decoded batchexecute request."""

    rpcid: str
    payload_raw: str
    payload: Any = None          # decoded JSON payload (if valid JSON)
    service: str = ""            # LabsTailwindUi | BardChatUi
    url: str = ""
    extra_params: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.payload_raw:
            try:
                self.payload = json.loads(self.payload_raw)
            except json.JSONDecodeError:
                self.payload = self.payload_raw


@dataclass
class BatchFrame:
    """A single wrb.fr frame from a batchexecute response."""

    rpcid: str
    data_raw: str
    data: Any = None             # decoded JSON data
    frame_type: str = "wrb.fr"
    sequence: int = 0

    def __post_init__(self) -> None:
        if self.data_raw:
            try:
                self.data = json.loads(self.data_raw)
            except json.JSONDecodeError:
                self.data = self.data_raw


@dataclass
class BatchResponse:
    """A decoded batchexecute response, containing one or more frames."""

    frames: List[BatchFrame] = field(default_factory=list)
    raw: str = ""

    @property
    def rpcids(self) -> List[str]:
        return [f.rpcid for f in self.frames]

    def frame_for(self, rpcid: str) -> Optional[BatchFrame]:
        for f in self.frames:
            if f.rpcid == rpcid:
                return f
        return None


class BatchExecuteDecoder:
    """Decode Google batchexecute request/response pairs."""

    # ──── Request decoding ────

    def decode_request(self, post_body: str, url: str = "") -> List[BatchRequest]:
        """Decode a batchexecute POST body into a list of BatchRequest objects.

        Args:
            post_body: Raw POST body (URL-encoded or already decoded).
            url: The request URL (used to infer service name).

        Returns:
            List of decoded BatchRequest objects (usually 1).
        """
        # URL-decode if needed
        if "f.req=" in post_body:
            body = urllib.parse.unquote_plus(post_body)
            # Extract f.req value
            match = re.search(r'f\.req=(\[.*)', body, re.DOTALL)
            if match:
                freq_raw = match.group(1)
                # Strip trailing query params
                freq_raw = re.split(r'&[a-z]', freq_raw)[0]
            else:
                return []
        else:
            freq_raw = post_body

        service = self._extract_service(url)

        try:
            outer = json.loads(freq_raw)
        except json.JSONDecodeError as exc:
            logger.debug("batchexecute request parse error: %s", exc)
            return []

        results: List[BatchRequest] = []
        # outer = [[["rpcid", "payload", null, "generic"], ...], ...]
        for group in outer:
            if not isinstance(group, list):
                continue
            for call in group:
                if isinstance(call, list) and len(call) >= 2:
                    rpcid = call[0] if isinstance(call[0], str) else ""
                    payload_raw = call[1] if isinstance(call[1], str) else json.dumps(call[1])
                    if rpcid:
                        results.append(BatchRequest(
                            rpcid=rpcid,
                            payload_raw=payload_raw,
                            service=service,
                            url=url,
                        ))
        return results

    # ──── Response decoding ────

    def decode_response(self, body: str) -> BatchResponse:
        """Decode a batchexecute response body into frames.

        Args:
            body: Raw response body (may start with )]}'\n).

        Returns:
            BatchResponse with all decoded frames.
        """
        if not body:
            return BatchResponse()

        # Strip the security prefix
        clean = body.lstrip()
        if clean.startswith(_RESPONSE_PREFIX.strip()):
            clean = clean[len(_RESPONSE_PREFIX.strip()):]
        clean = clean.strip()

        frames: List[BatchFrame] = []
        seq = 0

        # Split into individual JSON arrays (each response chunk is a separate array)
        for chunk in self._split_response_chunks(clean):
            try:
                parsed = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed, list):
                continue
            for item in parsed:
                if not isinstance(item, list) or not item:
                    continue
                # wrb.fr frame: [["wrb.fr", "rpcid", "json_data", null, null, null, "generic"]]
                inner = item[0] if isinstance(item[0], list) else item
                if isinstance(inner, list) and len(inner) >= 3:
                    frame_type = inner[0] if isinstance(inner[0], str) else ""
                    if frame_type == "wrb.fr":
                        rpcid = inner[1] if isinstance(inner[1], str) else ""
                        data_raw = inner[2] if isinstance(inner[2], str) else json.dumps(inner[2])
                        if rpcid:
                            frames.append(BatchFrame(
                                rpcid=rpcid,
                                data_raw=data_raw,
                                frame_type=frame_type,
                                sequence=seq,
                            ))
                            seq += 1

        return BatchResponse(frames=frames, raw=body)

    # ──── Helpers ────

    @staticmethod
    def _extract_service(url: str) -> str:
        """Extract service name from batchexecute URL."""
        match = re.search(r'/_/([^/]+)/data/batchexecute', url)
        return match.group(1) if match else ""

    @staticmethod
    def _split_response_chunks(text: str) -> List[str]:
        """Split a streaming batchexecute response into individual JSON chunks.

        The response may contain multiple length-prefixed JSON arrays
        (server-sent chunked format).
        """
        chunks: List[str] = []
        i = 0
        while i < len(text):
            # Look for a digit (chunk length prefix) or a direct array
            if text[i] == '[':
                # Try to find the matching bracket
                try:
                    depth = 0
                    j = i
                    while j < len(text):
                        if text[j] == '[':
                            depth += 1
                        elif text[j] == ']':
                            depth -= 1
                            if depth == 0:
                                chunks.append(text[i:j + 1])
                                i = j + 1
                                break
                        j += 1
                    else:
                        break
                except Exception:
                    break
            elif text[i].isdigit():
                # Length-prefixed chunk: "123\n[...]"
                nl = text.find('\n', i)
                if nl == -1:
                    break
                try:
                    length = int(text[i:nl])
                    start = nl + 1
                    chunks.append(text[start:start + length])
                    i = start + length
                except ValueError:
                    i += 1
            else:
                i += 1
        return chunks

    def describe(self, req: BatchRequest, known_rpcids: Optional[Dict[str, str]] = None) -> str:
        """Human-readable description of a decoded request."""
        name = (known_rpcids or {}).get(req.rpcid, "UNKNOWN")
        return f"[{req.service}] {req.rpcid} ({name}) — payload: {str(req.payload)[:120]}"


# ──── Module-level singleton ────
_decoder: Optional[BatchExecuteDecoder] = None


def get_decoder() -> BatchExecuteDecoder:
    global _decoder
    if _decoder is None:
        _decoder = BatchExecuteDecoder()
    return _decoder
