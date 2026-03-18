"""ARGUS gRPC-web decoder — parse AI Studio's gRPC-web binary frames.

AI Studio (MakerSuiteService) uses gRPC-web:
    POST https://alkalimakersuite-pa.clients6.google.com/$rpc/.../MakerSuiteService/{Method}
    Content-Type: application/json   (JSON mode, not binary proto)
    Authorization: SAPISIDHASH {ts}_{sha1}

Response may be:
    - Plain JSON (simple methods)
    - gRPC-web binary frames (streaming methods):
        [0x00][4-byte length][proto bytes]  — data frame
        [0x80][4-byte length][trailer bytes] — trailer frame

This decoder handles both JSON and binary frame modes, plus extracts
proto field shapes from binary payloads for proto reconstruction.
"""
from __future__ import annotations

import json
import logging
import re
import struct
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class GrpcFrame:
    """A single gRPC-web frame (data or trailer)."""

    frame_type: int          # 0x00 = data, 0x80 = trailer
    length: int
    payload: bytes
    is_trailer: bool = False
    fields: List[ProtoField] = field(default_factory=list)

    @property
    def payload_text(self) -> str:
        try:
            return self.payload.decode("utf-8", errors="replace")
        except Exception:
            return repr(self.payload)


@dataclass
class GrpcWebResponse:
    """A decoded gRPC-web response."""

    method: str
    service: str
    frames: List[GrpcFrame] = field(default_factory=list)
    json_data: Optional[Dict] = None       # if response was plain JSON
    proto_fields: Dict[int, Any] = field(default_factory=dict)  # field_num -> value
    raw_body: Optional[str] = None
    status_code: int = 200
    url: str = ""

    @property
    def is_streaming(self) -> bool:
        return len(self.frames) > 0

    @property
    def data_frames(self) -> List[GrpcFrame]:
        return [f for f in self.frames if not f.is_trailer]

    @property
    def trailer_frames(self) -> List[GrpcFrame]:
        return [f for f in self.frames if f.is_trailer]


@dataclass
class ProtoField:
    """A proto3 field extracted from binary payload."""

    field_number: int
    wire_type: int        # 0=varint, 1=64bit, 2=length-delimited, 5=32bit
    value_raw: Any
    value_decoded: Any = None   # string if wire_type==2 and valid UTF-8

    WIRE_NAMES = {0: "varint", 1: "fixed64", 2: "bytes/str", 5: "fixed32"}

    @property
    def wire_name(self) -> str:
        return self.WIRE_NAMES.get(self.wire_type, f"unknown({self.wire_type})")


class GrpcWebDecoder:
    """Decode AI Studio gRPC-web requests and responses."""

    # ──── URL parsing ────

    @staticmethod
    def parse_url(url: str) -> Tuple[str, str]:
        """Extract (service, method) from a gRPC-web URL.

        e.g. 'alkalimakersuite-pa.clients6.google.com/$rpc/.../MakerSuiteService/GenerateContent'
        → ('MakerSuiteService', 'GenerateContent')
        """
        match = re.search(r'/\$rpc/[^/]+(?:/[^/]+)*/([^/]+)/([^/?]+)', url)
        if match:
            return match.group(1), match.group(2)
        # Fallback: last two path segments
        parts = url.rstrip("/").split("/")
        if len(parts) >= 2:
            return parts[-2], parts[-1]
        return "unknown", "unknown"

    # ──── Response decoding ────

    def decode_response(self, body: Optional[str], url: str = "",
                        status: int = 200) -> GrpcWebResponse:
        """Decode a gRPC-web response body.

        Args:
            body: Response body string (may be JSON or binary/escaped binary).
            url: The request URL (for service/method extraction).
            status: HTTP status code.

        Returns:
            GrpcWebResponse with frames and/or parsed JSON.
        """
        service, method = self.parse_url(url)
        resp = GrpcWebResponse(method=method, service=service,
                               raw_body=body, status_code=status, url=url)

        if not body:
            return resp

        # Try JSON first (most AI Studio responses in JSON mode)
        try:
            resp.json_data = json.loads(body)
            return resp
        except json.JSONDecodeError:
            pass

        # Try binary gRPC-web frames
        try:
            raw_bytes = body.encode("latin-1")
            frames = self._parse_grpc_frames(raw_bytes)
            resp.frames = frames
            # Extract proto fields from data frames
            for frame in resp.data_frames:
                parsed_fields = self._parse_proto_varint(frame.payload)
                frame.fields = parsed_fields
                resp.proto_fields.update({f.field_number: f.value_decoded or f.value_raw
                                           for f in parsed_fields})
        except Exception as exc:
            logger.debug("gRPC-web binary parse failed for %s/%s: %s", service, method, exc)

        return resp

    # ──── Binary frame parsing ────

    @staticmethod
    def _parse_grpc_frames(data: bytes) -> List[GrpcFrame]:
        """Parse gRPC-web binary framing: [flags(1)][length(4)][payload(N)]."""
        frames: List[GrpcFrame] = []
        i = 0
        while i + 5 <= len(data):
            flags = data[i]
            length = struct.unpack(">I", data[i + 1:i + 5])[0]
            payload = data[i + 5:i + 5 + length]
            frames.append(GrpcFrame(
                frame_type=flags,
                length=length,
                payload=payload,
                is_trailer=bool(flags & 0x80),
            ))
            i += 5 + length
        return frames

    # ──── Proto3 field extraction ────

    @staticmethod
    def _parse_proto_varint(data: bytes) -> List[ProtoField]:
        """Extract proto3 field tag+value pairs from binary payload.

        This is a best-effort parser — proto3 fields without a schema
        are ambiguous but we can extract field numbers and wire types.
        """
        fields: List[ProtoField] = []
        i = 0
        while i < len(data):
            try:
                # Read varint for tag
                tag, i = GrpcWebDecoder._read_varint(data, i)
                if tag == 0:
                    break
                field_number = tag >> 3
                wire_type = tag & 0x07

                if wire_type == 0:    # varint
                    value, i = GrpcWebDecoder._read_varint(data, i)
                    fields.append(ProtoField(field_number, wire_type, value, value))

                elif wire_type == 1:  # 64-bit fixed
                    if i + 8 > len(data):
                        break
                    value = struct.unpack("<Q", data[i:i + 8])[0]
                    i += 8
                    fields.append(ProtoField(field_number, wire_type, value, value))

                elif wire_type == 2:  # length-delimited (string/bytes/embedded msg)
                    length, i = GrpcWebDecoder._read_varint(data, i)
                    if i + length > len(data):
                        break
                    raw = data[i:i + length]
                    i += length
                    # Try to decode as UTF-8 string
                    try:
                        decoded: Any = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        decoded = raw.hex()
                    fields.append(ProtoField(field_number, wire_type, raw, decoded))

                elif wire_type == 5:  # 32-bit fixed
                    if i + 4 > len(data):
                        break
                    value = struct.unpack("<I", data[i:i + 4])[0]
                    i += 4
                    fields.append(ProtoField(field_number, wire_type, value, value))

                else:
                    # Unknown wire type — stop parsing this frame
                    break

            except Exception:
                break

        return fields

    @staticmethod
    def _read_varint(data: bytes, pos: int) -> Tuple[int, int]:
        """Read a protobuf varint from data at pos. Returns (value, new_pos)."""
        result = 0
        shift = 0
        while pos < len(data):
            byte = data[pos]
            pos += 1
            result |= (byte & 0x7F) << shift
            if not (byte & 0x80):
                break
            shift += 7
            if shift >= 64:
                raise ValueError("varint too long")
        return result, pos

    # ──── Request description ────

    @staticmethod
    def describe(url: str) -> str:
        service, method = GrpcWebDecoder.parse_url(url)
        return f"[gRPC-web] {service}/{method}"


# ──── Module-level singleton ────
_decoder: Optional[GrpcWebDecoder] = None


def get_decoder() -> GrpcWebDecoder:
    global _decoder
    if _decoder is None:
        _decoder = GrpcWebDecoder()
    return _decoder
