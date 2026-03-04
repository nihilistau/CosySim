"""ARGUS proto reconstructor — generates .proto stubs from captured gRPC-web traffic.

Combines two signal sources:
    1. Binary gRPC-web frames decoded by ``grpc_web.py`` (field numbers + wire types)
    2. JS bundle field maps extracted from the SPA bundle (field names matched to numbers)

Output: ``.proto`` files in ``data/argus/protos/`` + a combined ``argus_registry.proto``.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from scripts.argus.config import DATA_DIR

logger = logging.getLogger(__name__)

PROTOS_DIR = DATA_DIR / "protos"

# Wire type → proto scalar type mapping
_WIRE_TYPE_SCALARS = {
    0: ["int32", "int64", "uint32", "uint64", "sint32", "sint64", "bool", "enum"],
    1: ["fixed64", "sfixed64", "double"],
    2: ["string", "bytes", "embedded message", "packed repeated"],
    5: ["fixed32", "sfixed32", "float"],
}

# Known service → method → message name patterns extracted from heap/bundle analysis
_KNOWN_SERVICES = {
    "LabsTailwindUiService": {  # NLM
        "GenerateFreeFormStreamed": ("GenerateFreeFormRequest", "GenerateFreeFormResponse"),
        "GetNotebook": ("GetNotebookRequest", "GetNotebookResponse"),
        "CreateNotebook": ("CreateNotebookRequest", "CreateNotebookResponse"),
        "UpdateNotebook": ("UpdateNotebookRequest", "UpdateNotebookResponse"),
        "DeleteNotebook": ("DeleteNotebookRequest", "DeleteNotebookResponse"),
        "ListNotebooks": ("ListNotebooksRequest", "ListNotebooksResponse"),
        "AddSource": ("AddSourceRequest", "AddSourceResponse"),
        "RemoveSource": ("RemoveSourceRequest", "RemoveSourceResponse"),
        "ListSources": ("ListSourcesRequest", "ListSourcesResponse"),
        "GenerateGuide": ("GenerateGuideRequest", "GenerateGuideResponse"),
        "GenerateAudio": ("GenerateAudioRequest", "GenerateAudioResponse"),
        "GetAudioStatus": ("GetAudioStatusRequest", "GetAudioStatusResponse"),
    },
    "MakerSuiteService": {  # AI Studio
        "StreamGenerateContent": ("GenerateContentRequest", "GenerateContentResponse"),
        "GetModel": ("GetModelRequest", "Model"),
        "ListModels": ("ListModelsRequest", "ListModelsResponse"),
        "ListPrompts": ("ListPromptsRequest", "ListPromptsResponse"),
        "GetPrompt": ("GetPromptRequest", "Prompt"),
        "CreatePrompt": ("CreatePromptRequest", "Prompt"),
        "UpdatePrompt": ("UpdatePromptRequest", "Prompt"),
        "DeletePrompt": ("DeletePromptRequest", "google.protobuf.Empty"),
        "ListFiles": ("ListFilesRequest", "ListFilesResponse"),
        "CreateFile": ("CreateFileRequest", "File"),
        "DeleteFile": ("DeleteFileRequest", "google.protobuf.Empty"),
        "ListTunedModels": ("ListTunedModelsRequest", "ListTunedModelsResponse"),
        "ListCachedContents": ("ListCachedContentsRequest", "ListCachedContentsResponse"),
        "ListApplets": ("ListAppletsRequest", "ListAppletsResponse"),
        "GetApplet": ("GetAppletRequest", "Applet"),
    },
}


@dataclass
class ProtoField:
    """A single field in a reconstructed proto message."""
    number: int
    wire_type: int
    name: str = ""  # may be empty if unknown
    proto_type: str = ""  # e.g. "string", "int32", "bytes"
    repeated: bool = False

    def proto_line(self) -> str:
        field_name = self.name or f"field_{self.number}"
        proto_type = self.proto_type or _guess_type(self.wire_type)
        repeated_str = "repeated " if self.repeated else ""
        return f"  {repeated_str}{proto_type} {field_name} = {self.number};"


@dataclass
class ProtoMessage:
    """A reconstructed proto message."""
    name: str
    fields: List[ProtoField] = field(default_factory=list)
    service: str = ""
    method: str = ""
    direction: str = ""  # "request" | "response"

    def to_proto_string(self) -> str:
        lines = [f"message {self.name} {{"]
        for f_ in sorted(self.fields, key=lambda x: x.number):
            lines.append(f_.proto_line())
        lines.append("}")
        return "\n".join(lines)


@dataclass
class ProtoReconstructor:
    """Builds .proto stubs from captured gRPC-web binary frames and bundle field maps."""

    _messages: Dict[str, ProtoMessage] = field(default_factory=dict)
    _field_name_map: Dict[str, Dict[int, str]] = field(default_factory=dict)

    def ingest_grpc_frame(
        self,
        method: str,
        service: str,
        direction: str,
        raw_fields: List[Tuple[int, int, bytes]],
    ) -> None:
        """Ingest proto fields from a decoded gRPC-web binary frame.

        Args:
            method:     gRPC method name, e.g. "StreamGenerateContent".
            service:    gRPC service name, e.g. "MakerSuiteService".
            direction:  "request" or "response".
            raw_fields: List of (field_number, wire_type, raw_bytes) tuples.
        """
        # Determine message name from known service map or generate one
        msg_name = self._get_message_name(service, method, direction)
        if msg_name not in self._messages:
            self._messages[msg_name] = ProtoMessage(
                name=msg_name, service=service, method=method, direction=direction
            )
        msg = self._messages[msg_name]

        name_map = self._field_name_map.get(msg_name, {})
        existing_numbers = {f_.number for f_ in msg.fields}

        for field_num, wire_type, _raw in raw_fields:
            if field_num in existing_numbers:
                continue
            name = name_map.get(field_num, "")
            proto_type = _guess_type(wire_type)
            msg.fields.append(
                ProtoField(
                    number=field_num,
                    wire_type=wire_type,
                    name=name,
                    proto_type=proto_type,
                )
            )
            existing_numbers.add(field_num)

    def ingest_bundle_field_map(
        self, message_name: str, field_map: Dict[int, str]
    ) -> None:
        """Provide field name→number mapping extracted from a JS bundle.

        Args:
            message_name: Proto message name, e.g. "GenerateContentRequest".
            field_map:    Dict mapping field numbers to field names.
        """
        self._field_name_map[message_name] = field_map

        # Back-fill names into any already-ingested fields
        if message_name in self._messages:
            msg = self._messages[message_name]
            for f_ in msg.fields:
                if not f_.name and f_.number in field_map:
                    f_.name = field_map[f_.number]

    def extract_bundle_field_maps(self, bundle_text: str) -> int:
        """Scan a JS bundle for proto field name→number mappings.

        Looks for patterns like: ``{fieldNumber: 1, name: 'model'}``
        and the closure-compiler ``proto.Field`` patterns.

        Returns:
            Number of field mappings found.
        """
        count = 0
        # Pattern: proto2.FIELD_TYPE_BOOL = 8, fieldName: 'safe_output'
        # Approximation — real extraction needs AST
        field_patterns = [
            re.compile(r'"(\w+)":\s*\{\s*"field_number"\s*:\s*(\d+)'),
            re.compile(r'fieldNumber\s*:\s*(\d+),\s*name\s*:\s*["\'](\w+)["\']'),
            re.compile(r'["\'](\w+)["\'],\s*null,\s*(\d+),'),  # closure pattern
        ]
        for pat in field_patterns:
            for m in pat.finditer(bundle_text):
                groups = m.groups()
                if len(groups) == 2:
                    try:
                        name, num = groups[0], int(groups[1])
                        if len(name) > 1 and not name.isdigit():
                            # Use message name "unknown" until we can classify
                            if "unknown" not in self._field_name_map:
                                self._field_name_map["unknown"] = {}
                            self._field_name_map["unknown"][num] = name
                            count += 1
                    except ValueError:
                        pass
        logger.debug("ProtoReconstructor: extracted %d field mappings from bundle", count)
        return count

    # ──── Output ────

    def generate_proto_file(self, service: str) -> str:
        """Generate a complete .proto file for a service."""
        messages = [
            m for m in self._messages.values()
            if m.service == service or not m.service
        ]
        if not messages:
            return ""

        known = _KNOWN_SERVICES.get(service, {})
        lines = [
            'syntax = "proto3";',
            "",
            f'package argus.{service.lower().replace("service", "")};',
            "",
            f"// AUTO-GENERATED by ARGUS ProtoReconstructor",
            f"// Service: {service}",
            f"// Messages: {len(messages)}",
            "",
        ]

        # Service definition
        lines.append(f"service {service} {{")
        for method, (req_name, resp_name) in known.items():
            client_stream = "stream " if "List" not in method else ""
            server_stream = "stream " if "Stream" in method or "Generate" in method else ""
            lines.append(f"  rpc {method}({client_stream}{req_name})")
            lines.append(f"      returns ({server_stream}{resp_name});")
        lines.append("}")
        lines.append("")

        # Message definitions
        for msg in sorted(messages, key=lambda m: m.name):
            lines.append(msg.to_proto_string())
            lines.append("")

        return "\n".join(lines)

    def save_all(self, output_dir: Path = PROTOS_DIR) -> List[Path]:
        """Write one .proto file per service to output_dir."""
        output_dir.mkdir(parents=True, exist_ok=True)
        services = {m.service for m in self._messages.values() if m.service}
        written: List[Path] = []
        for service in services:
            proto_text = self.generate_proto_file(service)
            if proto_text:
                out = output_dir / f"{service.lower()}.proto"
                out.write_text(proto_text, encoding="utf-8")
                written.append(out)
                logger.info("ProtoReconstructor: wrote %s", out)
        return written

    def _get_message_name(self, service: str, method: str, direction: str) -> str:
        """Look up or generate a message name."""
        known = _KNOWN_SERVICES.get(service, {})
        if method in known:
            req_name, resp_name = known[method]
            return req_name if direction == "request" else resp_name
        suffix = "Request" if direction == "request" else "Response"
        return f"{method}{suffix}"


# ──── Helpers ────

def _guess_type(wire_type: int) -> str:
    options = _WIRE_TYPE_SCALARS.get(wire_type, ["bytes"])
    return options[0]


# ──── Module-level singleton ────

_reconstructor: Optional[ProtoReconstructor] = None


def get_reconstructor() -> ProtoReconstructor:
    global _reconstructor
    if _reconstructor is None:
        _reconstructor = ProtoReconstructor()
    return _reconstructor
