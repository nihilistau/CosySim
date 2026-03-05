"""Artifact Bus — unified handoff layer between all Google services and CosySim.

Routes artifacts between: Colab, Drive, NotebookLM, Sheets, Nexus, and local filesystem.
Every service speaks to every other service through this bus.

The flow:
    Colab output  → Drive (persist) → NLM (analyse) → Nexus (store Q&A)
    NLM audio     → Drive → Colab (transcribe) → Sheets (data) → NLM (read back)
    Local model   → Drive → Colab (serve) → ngrok URL → CosySim router
    Colab chart   → NLM (visual analysis) → Nexus → Sheets (tracking)
"""
from __future__ import annotations

import json
import logging
import mimetypes
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ──── Artifact model ──────────────────────────────────────────────────────────

class ArtifactService(str, Enum):
    LOCAL = "local"
    DRIVE = "drive"
    COLAB = "colab"
    NLM = "nlm"
    SHEETS = "sheets"
    NEXUS = "nexus"


@dataclass
class Artifact:
    """A routable artifact with location, content type, and metadata.

    Attributes:
        service: Where this artifact currently lives.
        ref: Service-specific identifier (file_id, path, notebook_id, etc.)
        artifact_type: Content type hint (model, dataset, audio, image, chart,
                        text, code, json, notebook).
        local_path: Local file path if downloaded.
        url: Shareable URL if available.
        metadata: Arbitrary extra data (name, size, drive_id, etc.)
    """

    service: ArtifactService
    ref: str
    artifact_type: str = "file"
    local_path: Optional[str] = None
    url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def name(self) -> str:
        """Return a human-readable name for logging."""
        return self.metadata.get("name", self.ref[:16])


# ──── Bus ─────────────────────────────────────────────────────────────────────

class ArtifactBus:
    """Routes artifacts between all services in the CosySim ecosystem.

    Args:
        drive_client: GoogleDriveClient instance.
        nlm_client: NLMDirectClient instance.
        colab_client: ColabClient instance (for executing code cells).
        sheets_client: Optional GoogleSheetsClient instance.
        nexus_client: Optional NexusClient instance.
        account_name: Account name used to look up clients from pool.
    """

    def __init__(
        self,
        drive_client: Any,
        nlm_client: Any,
        colab_client: Optional[Any] = None,
        sheets_client: Optional[Any] = None,
        nexus_client: Optional[Any] = None,
    ) -> None:
        self._drive = drive_client
        self._nlm = nlm_client
        self._colab = colab_client
        self._sheets = sheets_client
        self._nexus = nexus_client

    # ──── Primary handoff entry point ─────────────────────────────────────────

    def handoff(
        self,
        artifact: Artifact,
        to_service: ArtifactService,
        **kwargs: Any,
    ) -> Artifact:
        """Move an artifact from its current service to a target service.

        Automatically determines and executes the correct transport path.
        Returns a new Artifact representing the artifact in the target service.

        Args:
            artifact: Source artifact to hand off.
            to_service: Destination service.
            **kwargs: Route-specific options (see individual _route_* methods).

        Returns:
            New Artifact located in the target service.

        Raises:
            ValueError: If the route is not supported.
        """
        route = (artifact.service, to_service)
        logger.info(
            "Handoff: %s [%s] → %s", artifact.name(), artifact.service.value, to_service.value
        )

        # ── Local ──────────────────────────────────────────────────────────────
        if route == (ArtifactService.LOCAL, ArtifactService.DRIVE):
            return self._local_to_drive(artifact, **kwargs)

        if route == (ArtifactService.LOCAL, ArtifactService.NLM):
            return self._local_to_nlm(artifact, **kwargs)

        if route == (ArtifactService.LOCAL, ArtifactService.NEXUS):
            return self._local_to_nexus(artifact, **kwargs)

        # ── Drive ──────────────────────────────────────────────────────────────
        if route == (ArtifactService.DRIVE, ArtifactService.NLM):
            return self._drive_to_nlm(artifact, **kwargs)

        if route == (ArtifactService.DRIVE, ArtifactService.COLAB):
            return self._drive_to_colab(artifact, **kwargs)

        if route == (ArtifactService.DRIVE, ArtifactService.NEXUS):
            return self._drive_to_nexus(artifact, **kwargs)

        if route == (ArtifactService.DRIVE, ArtifactService.SHEETS):
            return self._drive_to_sheets(artifact, **kwargs)

        # ── Colab ──────────────────────────────────────────────────────────────
        if route == (ArtifactService.COLAB, ArtifactService.DRIVE):
            return self._colab_to_drive(artifact, **kwargs)

        if route == (ArtifactService.COLAB, ArtifactService.NLM):
            return self._colab_to_nlm(artifact, **kwargs)

        if route == (ArtifactService.COLAB, ArtifactService.SHEETS):
            return self._colab_to_sheets(artifact, **kwargs)

        if route == (ArtifactService.COLAB, ArtifactService.NEXUS):
            return self._colab_to_nexus(artifact, **kwargs)

        # ── NLM ────────────────────────────────────────────────────────────────
        if route == (ArtifactService.NLM, ArtifactService.COLAB):
            return self._nlm_to_colab(artifact, **kwargs)

        if route == (ArtifactService.NLM, ArtifactService.DRIVE):
            return self._nlm_to_drive(artifact, **kwargs)

        if route == (ArtifactService.NLM, ArtifactService.NEXUS):
            return self._nlm_to_nexus(artifact, **kwargs)

        # ── Sheets ─────────────────────────────────────────────────────────────
        if route == (ArtifactService.SHEETS, ArtifactService.NLM):
            return self._sheets_to_nlm(artifact, **kwargs)

        if route == (ArtifactService.SHEETS, ArtifactService.NEXUS):
            return self._sheets_to_nexus(artifact, **kwargs)

        raise ValueError(
            f"No route defined: {artifact.service.value} → {to_service.value}"
        )

    # ──── Multi-hop helper ────────────────────────────────────────────────────

    def pipeline(
        self,
        artifact: Artifact,
        route: List[ArtifactService],
        kwargs_per_hop: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Artifact]:
        """Execute a multi-hop pipeline, collecting each intermediate artifact.

        Args:
            artifact: Starting artifact.
            route: Ordered list of destination services.
            kwargs_per_hop: Optional per-hop kwargs aligned to route.

        Returns:
            List of artifacts at each hop including the original.

        Example::

            bus.pipeline(local_mp3, [DRIVE, NLM, NEXUS])
            # → upload to drive, add as NLM source, store Q&A in Nexus
        """
        history: List[Artifact] = [artifact]
        current = artifact
        for i, dst in enumerate(route):
            kw = (kwargs_per_hop or [{}] * len(route))[i] or {}
            current = self.handoff(current, dst, **kw)
            history.append(current)
        return history

    # ──── Local routes ────────────────────────────────────────────────────────

    def _local_to_drive(self, artifact: Artifact, **kwargs: Any) -> Artifact:
        """Upload local file to Google Drive.

        kwargs:
            folder_id: Drive folder ID (default: CosySim/artifacts)
            subfolder: CosySim subfolder name
            make_public: Set reader permission for NLM (default: False)
        """
        path = Path(artifact.local_path or artifact.ref)
        if not path.exists():
            raise FileNotFoundError(f"Local artifact not found: {path}")

        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        content = path.read_bytes()

        folder_id = kwargs.get("folder_id")
        if not folder_id:
            subfolder = kwargs.get("subfolder", "artifacts")
            root_id = self._drive.find_or_create_folder("CosySim")
            folder_id = self._drive.find_or_create_folder(subfolder, parent_id=root_id)

        result = self._drive.upload_file(
            name=path.name,
            content=content,
            mime_type=mime,
            folder_id=folder_id,
        )

        if kwargs.get("make_public", False):
            self._drive.make_file_accessible_to_notebooklm(result["id"])

        url = self._drive.get_shareable_link(result["id"])
        logger.info("Uploaded %s → Drive: %s", path.name, result["id"])
        return Artifact(
            service=ArtifactService.DRIVE,
            ref=result["id"],
            artifact_type=artifact.artifact_type,
            url=url,
            metadata={"name": path.name, "mime": mime, **result},
        )

    def _local_to_nlm(self, artifact: Artifact, **kwargs: Any) -> Artifact:
        """Upload local file directly to a NotebookLM notebook as a source.

        kwargs:
            notebook_id: Target NLM notebook ID (required)
        """
        nb_id = kwargs["notebook_id"]
        path = Path(artifact.local_path or artifact.ref)

        # Route via Drive so NLM can access it
        drive_artifact = self._local_to_drive(artifact, make_public=True, **{
            k: v for k, v in kwargs.items() if k != "notebook_id"
        })
        return self._drive_to_nlm(drive_artifact, notebook_id=nb_id)

    def _local_to_nexus(self, artifact: Artifact, **kwargs: Any) -> Artifact:
        """Store local file content in Nexus knowledge base.

        kwargs:
            title: Nexus entry title
            category: Nexus category (default: artifacts)
            content_type: Nexus content type (default: note)
        """
        if not self._nexus:
            raise RuntimeError("No Nexus client configured")
        path = Path(artifact.local_path or artifact.ref)
        content = path.read_text(encoding="utf-8", errors="replace")
        title = kwargs.get("title", path.name)
        self._nexus.add_entry(
            title=title,
            content=content,
            content_type=kwargs.get("content_type", "note"),
            category=kwargs.get("category", "artifacts"),
        )
        return Artifact(
            service=ArtifactService.NEXUS,
            ref=title,
            artifact_type="text",
            metadata={"name": title, "source_path": str(path)},
        )

    # ──── Drive routes ────────────────────────────────────────────────────────

    def _drive_to_nlm(self, artifact: Artifact, **kwargs: Any) -> Artifact:
        """Add a Drive file as a source in a NotebookLM notebook.

        kwargs:
            notebook_id: Target NLM notebook ID (required)
            make_public: Ensure file is publicly readable (default: True)
        """
        nb_id = kwargs["notebook_id"]
        if kwargs.get("make_public", True):
            self._drive.make_file_accessible_to_notebooklm(artifact.ref)

        # Use the Drive shareable URL as NLM source
        url = artifact.url or self._drive.get_shareable_link(artifact.ref)
        source_id = self._nlm.add_source_url(nb_id, url)

        logger.info("Added Drive file %s as NLM source %s", artifact.ref, source_id)
        return Artifact(
            service=ArtifactService.NLM,
            ref=source_id,
            artifact_type=artifact.artifact_type,
            url=url,
            metadata={"notebook_id": nb_id, "drive_id": artifact.ref, **artifact.metadata},
        )

    def _drive_to_colab(self, artifact: Artifact, **kwargs: Any) -> Artifact:
        """Download a Drive file and make it available in a Colab runtime.

        Generates a setup cell that mounts Drive and copies the file to /content/.

        kwargs:
            runtime_url: Colab runtime URL
            kernel_id: Jupyter kernel ID
            proxy_token: Runtime proxy token
            local_name: Filename to use in /content/ (default: original name)
        """
        if not self._colab:
            raise RuntimeError("No Colab client configured")

        file_name = kwargs.get("local_name") or artifact.metadata.get("name", artifact.ref)
        file_id = artifact.ref

        # Generate a cell that mounts Drive and loads the file
        cell_code = f"""# Load artifact from Drive
from google.colab import drive
drive.mount('/content/drive')
import shutil, os

# Copy from Drive to /content/ for fast local access
src = None
for root, dirs, files in os.walk('/content/drive/MyDrive'):
    for fname in files:
        if fname == {repr(file_name)}:
            src = os.path.join(root, fname)
            break
    if src:
        break

if src:
    shutil.copy(src, f'/content/{repr(file_name)}')
    print(f'Loaded: /content/{repr(file_name)}')
else:
    # Fallback: direct Drive API download cell marker
    print(f'File not found in Drive. Drive ID: {repr(file_id)}')
"""

        runtime_url = kwargs.get("runtime_url")
        kernel_id = kwargs.get("kernel_id")
        proxy_token = kwargs.get("proxy_token")

        if runtime_url and kernel_id and proxy_token:
            result = self._colab.execute_code(
                runtime_url=runtime_url,
                kernel_id=kernel_id,
                proxy_token=proxy_token,
                code=cell_code,
            )
            logger.info("Drive→Colab cell output: %s", result.get("output", "")[:200])

        return Artifact(
            service=ArtifactService.COLAB,
            ref=f"/content/{file_name}",
            artifact_type=artifact.artifact_type,
            metadata={"name": file_name, "drive_id": file_id},
        )

    def _drive_to_nexus(self, artifact: Artifact, **kwargs: Any) -> Artifact:
        """Download a Drive text file and store its content in Nexus.

        kwargs:
            title: Nexus entry title
            category: Nexus category
        """
        if not self._nexus:
            raise RuntimeError("No Nexus client configured")
        content = self._drive.download_text(artifact.ref)
        title = kwargs.get("title") or artifact.metadata.get("name", artifact.ref)
        self._nexus.add_entry(
            title=title,
            content=content,
            content_type=kwargs.get("content_type", "note"),
            category=kwargs.get("category", "artifacts"),
        )
        return Artifact(
            service=ArtifactService.NEXUS,
            ref=title,
            artifact_type="text",
            metadata={"drive_id": artifact.ref, "name": title},
        )

    def _drive_to_sheets(self, artifact: Artifact, **kwargs: Any) -> Artifact:
        """Import a Drive JSON/CSV file into a new Google Sheet.

        kwargs:
            sheet_title: Title for the new sheet
        """
        if not self._sheets:
            raise RuntimeError("No Sheets client configured")
        content = self._drive.download_text(artifact.ref)
        name = artifact.metadata.get("name", "")
        title = kwargs.get("sheet_title", name.replace(".json", "").replace(".csv", ""))

        if name.endswith(".json"):
            rows = json.loads(content)
        else:
            import csv, io
            rows = list(csv.DictReader(io.StringIO(content)))

        sheet = self._sheets.create_sheet(title)
        if rows:
            self._sheets.append_rows(sheet["id"], rows)

        logger.info("Imported Drive file %s → Sheet %s", artifact.ref, sheet["id"])
        return Artifact(
            service=ArtifactService.SHEETS,
            ref=sheet["id"],
            artifact_type="table",
            url=sheet.get("url"),
            metadata={"title": title, "drive_id": artifact.ref},
        )

    # ──── Colab routes ────────────────────────────────────────────────────────

    def _colab_to_drive(self, artifact: Artifact, **kwargs: Any) -> Artifact:
        """Upload a Colab output file to Google Drive.

        artifact.ref should be the /content/ path of the output file.

        kwargs:
            runtime_url, kernel_id, proxy_token: Colab runtime credentials
            subfolder: Drive subfolder (default: colab_outputs)
            make_public: Set public reader permission (default: False)
        """
        if not self._colab:
            raise RuntimeError("No Colab client configured")

        runtime_url = kwargs.get("runtime_url")
        kernel_id = kwargs.get("kernel_id")
        proxy_token = kwargs.get("proxy_token")
        file_path = artifact.ref  # e.g. /content/output.json

        # Read file from Colab runtime via kernel
        read_code = f"""
import base64, json
with open({repr(file_path)}, 'rb') as f:
    data = base64.b64encode(f.read()).decode()
print('__ARTIFACT_B64__:' + data)
"""
        content_bytes = b""
        if runtime_url and kernel_id and proxy_token:
            result = self._colab.execute_code(
                runtime_url=runtime_url,
                kernel_id=kernel_id,
                proxy_token=proxy_token,
                code=read_code,
            )
            output = result.get("output", "")
            if "__ARTIFACT_B64__:" in output:
                import base64
                b64 = output.split("__ARTIFACT_B64__:")[1].strip()
                content_bytes = base64.b64decode(b64)

        if not content_bytes:
            logger.warning("Could not read Colab file %s — runtime unavailable", file_path)
            content_bytes = f"# Could not read {file_path}".encode()

        file_name = Path(file_path).name
        mime = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        subfolder = kwargs.get("subfolder", "colab_outputs")
        root_id = self._drive.find_or_create_folder("CosySim")
        folder_id = self._drive.find_or_create_folder(subfolder, parent_id=root_id)

        result = self._drive.upload_file(
            name=file_name,
            content=content_bytes,
            mime_type=mime,
            folder_id=folder_id,
        )

        if kwargs.get("make_public", False):
            self._drive.make_file_accessible_to_notebooklm(result["id"])

        url = self._drive.get_shareable_link(result["id"])
        logger.info("Colab %s → Drive: %s", file_path, result["id"])
        return Artifact(
            service=ArtifactService.DRIVE,
            ref=result["id"],
            artifact_type=artifact.artifact_type,
            url=url,
            metadata={"name": file_name, "source_colab_path": file_path},
        )

    def _colab_to_nlm(self, artifact: Artifact, **kwargs: Any) -> Artifact:
        """Route a Colab output to NLM via Drive as intermediary.

        kwargs:
            notebook_id: NLM notebook ID (required)
            runtime_url, kernel_id, proxy_token: Colab runtime credentials
        """
        nb_id = kwargs["notebook_id"]
        drive_artifact = self._colab_to_drive(artifact, make_public=True, **{
            k: v for k, v in kwargs.items() if k != "notebook_id"
        })
        return self._drive_to_nlm(drive_artifact, notebook_id=nb_id)

    def _colab_to_sheets(self, artifact: Artifact, **kwargs: Any) -> Artifact:
        """Write Colab JSON output to a Google Sheet.

        artifact.ref should be a /content/ path to a JSON file (list of dicts).

        kwargs:
            sheet_title: Sheet title
            runtime_url, kernel_id, proxy_token: Colab runtime credentials
        """
        if not self._sheets:
            raise RuntimeError("No Sheets client configured")

        # First bring to Drive as text
        drive_artifact = self._colab_to_drive(artifact, subfolder="sheets_export", **kwargs)
        return self._drive_to_sheets(drive_artifact, sheet_title=kwargs.get("sheet_title", ""))

    def _colab_to_nexus(self, artifact: Artifact, **kwargs: Any) -> Artifact:
        """Store Colab text output in Nexus.

        kwargs:
            runtime_url, kernel_id, proxy_token: Colab runtime credentials
            title: Nexus entry title
            category: Nexus category
        """
        if not self._nexus:
            raise RuntimeError("No Nexus client configured")
        if not self._colab:
            raise RuntimeError("No Colab client configured")

        runtime_url = kwargs.get("runtime_url")
        kernel_id = kwargs.get("kernel_id")
        proxy_token = kwargs.get("proxy_token")
        file_path = artifact.ref

        read_code = f"""
with open({repr(file_path)}, 'r', encoding='utf-8', errors='replace') as f:
    print('__ARTIFACT_TEXT__:' + f.read())
"""
        content = f"# Could not read {file_path}"
        if runtime_url and kernel_id and proxy_token:
            result = self._colab.execute_code(
                runtime_url=runtime_url,
                kernel_id=kernel_id,
                proxy_token=proxy_token,
                code=read_code,
            )
            output = result.get("output", "")
            if "__ARTIFACT_TEXT__:" in output:
                content = output.split("__ARTIFACT_TEXT__:")[1]

        title = kwargs.get("title", Path(file_path).name)
        self._nexus.add_entry(
            title=title,
            content=content,
            content_type=kwargs.get("content_type", "note"),
            category=kwargs.get("category", "colab_outputs"),
        )
        return Artifact(
            service=ArtifactService.NEXUS,
            ref=title,
            artifact_type="text",
            metadata={"source_colab_path": file_path},
        )

    # ──── NLM routes ──────────────────────────────────────────────────────────

    def _nlm_to_colab(self, artifact: Artifact, **kwargs: Any) -> Artifact:
        """Inject NLM-generated content into a Colab runtime as a Python variable.

        For flashcard artifacts (list of [q, a] pairs), injects as QA_PAIRS variable.
        For text artifacts (reports, notes), injects as CONTENT variable.

        kwargs:
            runtime_url, kernel_id, proxy_token: Colab runtime credentials
            variable_name: Python variable name (default: NLM_DATA)
            notebook_id: NLM notebook ID (for flashcard fetch)
        """
        if not self._colab:
            raise RuntimeError("No Colab client configured")

        runtime_url = kwargs.get("runtime_url")
        kernel_id = kwargs.get("kernel_id")
        proxy_token = kwargs.get("proxy_token")
        var_name = kwargs.get("variable_name", "NLM_DATA")
        content = artifact.metadata.get("content", "")

        if not content and kwargs.get("notebook_id"):
            # Fetch flashcards from NLM if content not in metadata
            try:
                pairs = self._nlm.generate_flashcards(kwargs["notebook_id"])
                content = json.dumps(pairs)
            except Exception as exc:
                logger.warning("Could not fetch NLM flashcards: %s", exc)

        inject_code = (
            f"import json\n"
            f"{var_name} = json.loads({repr(content)})\n"
            f"print(f'Injected {var_name}: {{len({var_name}) if isinstance({var_name}, list) else \"dict\"}}')\n"
        )

        if runtime_url and kernel_id and proxy_token:
            result = self._colab.execute_code(
                runtime_url=runtime_url,
                kernel_id=kernel_id,
                proxy_token=proxy_token,
                code=inject_code,
            )
            logger.info("NLM→Colab inject output: %s", result.get("output", "")[:100])

        return Artifact(
            service=ArtifactService.COLAB,
            ref=f"variable:{var_name}",
            artifact_type="json",
            metadata={"variable_name": var_name, "source_nlm_ref": artifact.ref},
        )

    def _nlm_to_drive(self, artifact: Artifact, **kwargs: Any) -> Artifact:
        """Download NLM audio artifact to Drive.

        kwargs:
            local_download_path: Local temp path for audio download
            subfolder: Drive subfolder (default: nlm_audio)
        """
        content = artifact.metadata.get("content") or artifact.local_path
        if not content:
            raise ValueError("NLM artifact has no local_path or content for Drive upload")

        path = Path(content)
        if not path.exists():
            raise FileNotFoundError(f"NLM audio not found locally: {path}")

        return self._local_to_drive(
            Artifact(
                service=ArtifactService.LOCAL,
                ref=str(path),
                artifact_type=artifact.artifact_type,
                local_path=str(path),
                metadata={"name": path.name},
            ),
            subfolder=kwargs.get("subfolder", "nlm_audio"),
            make_public=kwargs.get("make_public", False),
        )

    def _nlm_to_nexus(self, artifact: Artifact, **kwargs: Any) -> Artifact:
        """Store NLM flashcard pairs or report content in Nexus.

        kwargs:
            notebook_id: NLM notebook to fetch flashcards from
            title: Nexus entry title
            category: Nexus category
        """
        if not self._nexus:
            raise RuntimeError("No Nexus client configured")

        nb_id = kwargs.get("notebook_id") or artifact.metadata.get("notebook_id")
        title = kwargs.get("title", "NLM Distillation")
        category = kwargs.get("category", "knowledge")

        # Try flashcards first — they're the richest Q&A source
        if nb_id:
            try:
                pairs = self._nlm.generate_flashcards(nb_id)
                for pair in pairs:
                    if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                        self._nexus.add_qa(str(pair[0]), str(pair[1]), category=category)
                logger.info("Stored %d NLM Q&A pairs in Nexus", len(pairs))
                return Artifact(
                    service=ArtifactService.NEXUS,
                    ref=title,
                    artifact_type="qa",
                    metadata={"qa_count": len(pairs), "notebook_id": nb_id},
                )
            except Exception as exc:
                logger.warning("Flashcard fetch failed, storing content: %s", exc)

        content = artifact.metadata.get("content", str(artifact.ref))
        self._nexus.add_entry(title=title, content=content, category=category)
        return Artifact(
            service=ArtifactService.NEXUS,
            ref=title,
            artifact_type="text",
            metadata={"notebook_id": nb_id},
        )

    # ──── Sheets routes ───────────────────────────────────────────────────────

    def _sheets_to_nlm(self, artifact: Artifact, **kwargs: Any) -> Artifact:
        """Add a Google Sheet URL as an NLM source.

        Gemini reads the spreadsheet directly from the URL.

        kwargs:
            notebook_id: Target NLM notebook ID (required)
        """
        nb_id = kwargs["notebook_id"]
        url = artifact.url or f"https://docs.google.com/spreadsheets/d/{artifact.ref}"
        source_id = self._nlm.add_source_url(nb_id, url)
        logger.info("Added Sheet %s as NLM source %s", artifact.ref, source_id)
        return Artifact(
            service=ArtifactService.NLM,
            ref=source_id,
            artifact_type="table",
            url=url,
            metadata={"notebook_id": nb_id, "sheet_id": artifact.ref},
        )

    def _sheets_to_nexus(self, artifact: Artifact, **kwargs: Any) -> Artifact:
        """Download Sheet rows and store as JSON in Nexus.

        kwargs:
            title: Nexus entry title
            category: Nexus category
        """
        if not self._sheets or not self._nexus:
            raise RuntimeError("Sheets and Nexus clients both required")

        rows = self._sheets.read_rows(artifact.ref)
        title = kwargs.get("title", artifact.metadata.get("title", "Sheet Data"))
        content = json.dumps(rows, indent=2)
        self._nexus.add_entry(
            title=title,
            content=content,
            content_type="note",
            category=kwargs.get("category", "data"),
        )
        return Artifact(
            service=ArtifactService.NEXUS,
            ref=title,
            artifact_type="json",
            metadata={"sheet_id": artifact.ref, "row_count": len(rows)},
        )

    # ──── Compound workflows ──────────────────────────────────────────────────

    def colab_output_to_nlm_and_nexus(
        self,
        file_path: str,
        notebook_id: str,
        nexus_title: str,
        runtime_url: str,
        kernel_id: str,
        proxy_token: str,
        artifact_type: str = "json",
    ) -> Tuple[Artifact, Artifact]:
        """One call to move a Colab output to both NLM and Nexus.

        Returns:
            Tuple of (nlm_artifact, nexus_artifact).
        """
        colab_artifact = Artifact(
            service=ArtifactService.COLAB,
            ref=file_path,
            artifact_type=artifact_type,
            metadata={"name": Path(file_path).name},
        )
        rt_kwargs = {
            "runtime_url": runtime_url,
            "kernel_id": kernel_id,
            "proxy_token": proxy_token,
        }
        # Drive is the intermediary for NLM
        drive_artifact = self._colab_to_drive(colab_artifact, make_public=True, **rt_kwargs)
        nlm_artifact = self._drive_to_nlm(drive_artifact, notebook_id=notebook_id)

        # Nexus directly from Colab text
        nexus_artifact = self._colab_to_nexus(
            colab_artifact, title=nexus_title, **rt_kwargs
        )
        return nlm_artifact, nexus_artifact

    def full_knowledge_loop(
        self,
        notebook_id: str,
        colab_output_path: Optional[str] = None,
        runtime_url: Optional[str] = None,
        kernel_id: Optional[str] = None,
        proxy_token: Optional[str] = None,
        nexus_category: str = "knowledge",
    ) -> Dict[str, Any]:
        """The complete self-improving knowledge loop.

        Colab output → Drive → NLM source → NLM flashcards → Nexus Q&A

        Returns:
            Summary dict with all artifact references.
        """
        results: Dict[str, Any] = {"steps": []}

        if colab_output_path and runtime_url:
            colab_art = Artifact(
                service=ArtifactService.COLAB,
                ref=colab_output_path,
                artifact_type="text",
                metadata={"name": Path(colab_output_path).name},
            )
            rt = {"runtime_url": runtime_url, "kernel_id": kernel_id, "proxy_token": proxy_token}
            drive_art = self._colab_to_drive(colab_art, make_public=True, **rt)
            self._drive_to_nlm(drive_art, notebook_id=notebook_id)
            results["steps"].append({"step": "colab→drive→nlm", "drive_id": drive_art.ref})

        # Distill flashcards from NLM → Nexus Q&A
        nlm_art = Artifact(
            service=ArtifactService.NLM,
            ref="flashcards",
            metadata={"notebook_id": notebook_id},
        )
        nexus_art = self._nlm_to_nexus(
            nlm_art, notebook_id=notebook_id, category=nexus_category
        )
        results["steps"].append({
            "step": "nlm→nexus",
            "qa_count": nexus_art.metadata.get("qa_count", 0),
        })
        results["nexus_ref"] = nexus_art.ref
        return results


# ──── Factory ─────────────────────────────────────────────────────────────────

def get_artifact_bus(account_name: str = "nihilistcod") -> ArtifactBus:
    """Get a configured ArtifactBus using the named Google account.

    Args:
        account_name: Account name from the pool (default: nihilistcod).

    Returns:
        Configured ArtifactBus instance.
    """
    from engine.integrations.google_account_pool import get_account_pool
    from engine.integrations.google_drive_client import get_drive_client
    from engine.integrations.nlm_direct_client import get_nlm_direct_client
    from engine.integrations.colab_client import get_colab_client

    pool = get_account_pool()
    account = pool.get_account(account_name)

    drive = get_drive_client(account_name)
    nlm = get_nlm_direct_client(account)
    colab = get_colab_client(account_name)

    sheets = None
    try:
        from engine.integrations.gsheets_client import get_sheets_client
        sheets = get_sheets_client(account_name)
    except ImportError:
        pass

    nexus = None
    try:
        from engine.nexus.client import get_nexus_client
        nexus = get_nexus_client()
    except ImportError:
        pass

    return ArtifactBus(
        drive_client=drive,
        nlm_client=nlm,
        colab_client=colab,
        sheets_client=sheets,
        nexus_client=nexus,
    )
