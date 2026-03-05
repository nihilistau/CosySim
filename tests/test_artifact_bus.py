"""Tests for engine.integrations.artifact_bus — connector layer between Google services."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from engine.integrations.artifact_bus import (
    Artifact,
    ArtifactBus,
    ArtifactService,
    get_artifact_bus,
)


# ──── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_drive():
    """Mock GoogleDriveClient."""
    drive = MagicMock()
    drive.find_or_create_folder.return_value = "folder-123"
    drive.upload_file.return_value = {"id": "drive-file-id", "name": "test.txt"}
    drive.get_shareable_link.return_value = "https://drive.google.com/file/d/drive-file-id/view"
    drive.download_text.return_value = "sample file content"
    return drive


@pytest.fixture
def mock_nlm():
    """Mock NLMDirectClient."""
    nlm = MagicMock()
    nlm.add_source_url.return_value = "source-id-abc"
    nlm.generate_flashcards.return_value = [
        ["What is CosySim?", "A local AI companion system."],
        ["What does NLM stand for?", "NotebookLM."],
    ]
    return nlm


@pytest.fixture
def mock_nexus():
    """Mock NexusClient."""
    nexus = MagicMock()
    nexus.add_entry.return_value = True
    nexus.add_qa.return_value = True
    return nexus


@pytest.fixture
def mock_sheets():
    """Mock GoogleSheetsClient."""
    sheets = MagicMock()
    sheets.create_sheet.return_value = {"id": "sheet-id-xyz", "url": "https://docs.google.com/spreadsheets/d/sheet-id-xyz"}
    sheets.append_rows.return_value = True
    sheets.read_rows.return_value = [{"col1": "val1"}, {"col1": "val2"}]
    return sheets


@pytest.fixture
def bus(mock_drive, mock_nlm, mock_nexus, mock_sheets):
    """ArtifactBus with all mock service clients."""
    return ArtifactBus(
        drive_client=mock_drive,
        nlm_client=mock_nlm,
        colab_client=None,
        sheets_client=mock_sheets,
        nexus_client=mock_nexus,
    )


@pytest.fixture
def local_artifact(tmp_path):
    """A LOCAL artifact backed by a real temp file."""
    p = tmp_path / "note.txt"
    p.write_text("hello from local artifact")
    return Artifact(
        service=ArtifactService.LOCAL,
        ref=str(p),
        artifact_type="text",
        local_path=str(p),
        metadata={"name": "note.txt"},
    )


@pytest.fixture
def drive_artifact():
    """A DRIVE artifact."""
    return Artifact(
        service=ArtifactService.DRIVE,
        ref="drive-file-id",
        artifact_type="text",
        url="https://drive.google.com/file/d/drive-file-id/view",
        metadata={"name": "report.txt"},
    )


@pytest.fixture
def nlm_artifact():
    """An NLM artifact."""
    return Artifact(
        service=ArtifactService.NLM,
        ref="nb-id-123",
        artifact_type="notebook",
        metadata={"notebook_id": "nb-id-123", "name": "Research NB"},
    )


# ──── Dataclass tests ─────────────────────────────────────────────────────────

class TestArtifactDataclass:
    """Tests for the Artifact dataclass."""

    def test_artifact_has_required_fields(self):
        """Artifact stores service, ref, artifact_type, and metadata."""
        art = Artifact(
            service=ArtifactService.LOCAL,
            ref="/tmp/file.txt",
            artifact_type="text",
            metadata={"size": 1234},
        )
        assert art.service == ArtifactService.LOCAL
        assert art.ref == "/tmp/file.txt"
        assert art.artifact_type == "text"
        assert art.metadata["size"] == 1234

    def test_artifact_content_defaults_to_empty_metadata(self):
        """Artifact metadata defaults to empty dict, optional fields default to None."""
        art = Artifact(service=ArtifactService.DRIVE, ref="some-id")
        assert art.metadata == {}
        assert art.local_path is None
        assert art.url is None

    def test_artifact_name_uses_metadata_name(self):
        """name() returns metadata['name'] when present."""
        art = Artifact(
            service=ArtifactService.NLM,
            ref="long-ref-string",
            metadata={"name": "My Notebook"},
        )
        assert art.name() == "My Notebook"

    def test_artifact_name_falls_back_to_ref(self):
        """name() truncates ref to 16 chars when no metadata name."""
        art = Artifact(service=ArtifactService.NEXUS, ref="abcdefghijklmnopqrstuvwxyz")
        assert art.name() == "abcdefghijklmnop"


class TestArtifactServiceEnum:
    """Tests for the ArtifactService enum values."""

    def test_all_expected_services_exist(self):
        """ArtifactService enum has all six expected service values."""
        expected = {"local", "drive", "colab", "nlm", "sheets", "nexus"}
        actual = {s.value for s in ArtifactService}
        assert expected == actual

    def test_service_values_are_strings(self):
        """ArtifactService inherits from str — values are usable as strings."""
        assert ArtifactService.LOCAL == "local"
        assert ArtifactService.NEXUS == "nexus"

    def test_enum_members_accessible_by_name(self):
        """All six enum members are accessible by name."""
        assert ArtifactService.LOCAL
        assert ArtifactService.DRIVE
        assert ArtifactService.COLAB
        assert ArtifactService.NLM
        assert ArtifactService.SHEETS
        assert ArtifactService.NEXUS


# ──── handoff() tests ─────────────────────────────────────────────────────────

class TestHandoff:
    """Tests for ArtifactBus.handoff()."""

    def test_handoff_to_nexus_calls_nexus_add_entry(self, bus, local_artifact, mock_nexus):
        """handoff() to NEXUS calls nexus.add_entry with artifact content."""
        result = bus.handoff(local_artifact, ArtifactService.NEXUS)
        assert mock_nexus.add_entry.called
        assert result.service == ArtifactService.NEXUS

    def test_handoff_to_nexus_returns_nexus_artifact(self, bus, local_artifact):
        """handoff() to NEXUS returns an Artifact with service=NEXUS."""
        result = bus.handoff(local_artifact, ArtifactService.NEXUS, title="My Note")
        assert result.service == ArtifactService.NEXUS
        assert result.artifact_type == "text"

    def test_handoff_to_drive_calls_drive_upload(self, bus, local_artifact, mock_drive):
        """handoff() LOCAL→DRIVE calls drive.upload_file."""
        result = bus.handoff(local_artifact, ArtifactService.DRIVE)
        assert mock_drive.upload_file.called
        assert result.service == ArtifactService.DRIVE

    def test_handoff_to_drive_returns_artifact_with_url(self, bus, local_artifact, mock_drive):
        """handoff() LOCAL→DRIVE returns Artifact with a populated url field."""
        result = bus.handoff(local_artifact, ArtifactService.DRIVE)
        assert result.url is not None
        assert "drive.google.com" in result.url

    def test_handoff_drive_to_nexus_calls_drive_download_and_nexus_add(
        self, bus, drive_artifact, mock_drive, mock_nexus
    ):
        """handoff() DRIVE→NEXUS downloads Drive text and stores in Nexus."""
        result = bus.handoff(drive_artifact, ArtifactService.NEXUS, title="From Drive")
        mock_drive.download_text.assert_called_once_with("drive-file-id")
        assert mock_nexus.add_entry.called
        assert result.service == ArtifactService.NEXUS

    def test_handoff_drive_to_sheets_calls_sheets_create(
        self, bus, mock_drive, mock_sheets, tmp_path
    ):
        """handoff() DRIVE→SHEETS creates a new Sheet and appends rows."""
        mock_drive.download_text.return_value = '[{"col": "val"}]'
        drive_art = Artifact(
            service=ArtifactService.DRIVE,
            ref="json-file-id",
            artifact_type="json",
            metadata={"name": "data.json"},
        )
        result = bus.handoff(drive_art, ArtifactService.SHEETS)
        mock_sheets.create_sheet.assert_called_once()
        assert result.service == ArtifactService.SHEETS
        assert result.ref == "sheet-id-xyz"

    def test_handoff_nlm_to_nexus_stores_flashcards(self, bus, nlm_artifact, mock_nlm, mock_nexus):
        """handoff() NLM→NEXUS calls nlm.generate_flashcards and nexus.add_qa for each pair."""
        result = bus.handoff(nlm_artifact, ArtifactService.NEXUS, notebook_id="nb-id-123")
        mock_nlm.generate_flashcards.assert_called_once_with("nb-id-123")
        assert mock_nexus.add_qa.call_count == 2
        assert result.service == ArtifactService.NEXUS
        assert result.artifact_type == "qa"

    def test_handoff_returns_artifact_with_updated_metadata(self, bus, local_artifact, mock_drive):
        """handoff() returns a new Artifact instance with metadata reflecting the target service."""
        result = bus.handoff(local_artifact, ArtifactService.DRIVE)
        assert result is not local_artifact
        assert "name" in result.metadata

    def test_handoff_unsupported_route_raises_value_error(self, bus):
        """handoff() with an unsupported route raises ValueError."""
        sheets_art = Artifact(service=ArtifactService.SHEETS, ref="sheet-id")
        with pytest.raises(ValueError, match="No route defined"):
            bus.handoff(sheets_art, ArtifactService.COLAB)

    def test_handoff_local_to_nexus_with_temp_file(self, bus, tmp_path, mock_nexus):
        """LOCAL service handoff to NEXUS reads real temp file content."""
        f = tmp_path / "knowledge.txt"
        f.write_text("important knowledge content")
        art = Artifact(
            service=ArtifactService.LOCAL,
            ref=str(f),
            local_path=str(f),
            artifact_type="text",
        )
        result = bus.handoff(art, ArtifactService.NEXUS, title="Knowledge Entry")
        call_args = mock_nexus.add_entry.call_args
        assert "important knowledge content" in call_args.kwargs.get("content", call_args.args[1] if len(call_args.args) > 1 else "")
        assert result.service == ArtifactService.NEXUS


# ──── pipeline() tests ────────────────────────────────────────────────────────

class TestPipeline:
    """Tests for ArtifactBus.pipeline()."""

    def test_pipeline_chains_handoffs_in_order(self, bus, drive_artifact, mock_nlm, mock_nexus):
        """pipeline([NLM, NEXUS]) chains two handoffs and returns all intermediate artifacts."""
        # drive → nlm: needs notebook_id kwarg per hop
        kwargs_per_hop = [{"notebook_id": "nb-123"}, {"notebook_id": "nb-123"}]
        history = bus.pipeline(drive_artifact, [ArtifactService.NLM, ArtifactService.NEXUS], kwargs_per_hop)
        assert len(history) == 3   # original + 2 hops
        assert history[0].service == ArtifactService.DRIVE
        assert history[1].service == ArtifactService.NLM
        assert history[2].service == ArtifactService.NEXUS

    def test_pipeline_returns_list_including_original(self, bus, drive_artifact, mock_nexus):
        """pipeline() returns list where first element is the original artifact."""
        history = bus.pipeline(drive_artifact, [ArtifactService.NEXUS], [{"title": "T"}])
        assert history[0] is drive_artifact

    def test_pipeline_single_hop_equivalent_to_handoff(self, bus, drive_artifact, mock_nexus, mock_drive):
        """Single-hop pipeline produces same result as direct handoff."""
        direct = bus.handoff(drive_artifact, ArtifactService.NEXUS, title="T")
        # Reset mocks to get clean call counts
        mock_nexus.reset_mock()
        mock_drive.reset_mock()
        history = bus.pipeline(drive_artifact, [ArtifactService.NEXUS], [{"title": "T"}])
        assert history[-1].service == direct.service


# ──── full_knowledge_loop() tests ─────────────────────────────────────────────

class TestFullKnowledgeLoop:
    """Tests for ArtifactBus.full_knowledge_loop()."""

    def test_full_knowledge_loop_returns_results_dict(self, bus, mock_nlm, mock_nexus):
        """full_knowledge_loop() returns a dict with 'steps' and 'nexus_ref' keys."""
        result = bus.full_knowledge_loop(notebook_id="nb-loop-123")
        assert "steps" in result
        assert "nexus_ref" in result

    def test_full_knowledge_loop_stores_qa_in_nexus(self, bus, mock_nlm, mock_nexus):
        """full_knowledge_loop() calls generate_flashcards and nexus.add_qa."""
        bus.full_knowledge_loop(notebook_id="nb-loop-123")
        mock_nlm.generate_flashcards.assert_called_once_with("nb-loop-123")
        assert mock_nexus.add_qa.call_count == 2  # 2 flashcard pairs

    def test_full_knowledge_loop_steps_include_nlm_to_nexus(self, bus, mock_nlm, mock_nexus):
        """full_knowledge_loop() records nlm→nexus step in results."""
        result = bus.full_knowledge_loop(notebook_id="nb-loop-123")
        step_names = [s["step"] for s in result["steps"]]
        assert "nlm→nexus" in step_names


# ──── get_artifact_bus() factory tests ────────────────────────────────────────

class TestGetArtifactBus:
    """Tests for the get_artifact_bus() factory function.

    get_artifact_bus() uses local imports inside the function body, so we patch
    the source modules (not artifact_bus attributes) via sys.modules.
    """

    def _make_module_mocks(self, account_name: str = "testaccount"):
        """Return a sys.modules patch dict and the mock pool for assertions."""
        mock_account = MagicMock()
        mock_pool = MagicMock()
        mock_pool.get_account.return_value = mock_account

        modules = {
            "engine.integrations.google_account_pool": MagicMock(
                get_account_pool=MagicMock(return_value=mock_pool),
                GoogleAccount=MagicMock,
            ),
            "engine.integrations.google_drive_client": MagicMock(
                get_drive_client=MagicMock(return_value=MagicMock())
            ),
            "engine.integrations.nlm_direct_client": MagicMock(
                get_nlm_direct_client=MagicMock(return_value=MagicMock())
            ),
            "engine.integrations.colab_client": MagicMock(
                get_colab_client=MagicMock(return_value=MagicMock())
            ),
            "engine.integrations.gsheets_client": MagicMock(
                get_sheets_client=MagicMock(return_value=None)
            ),
            "engine.nexus.client": MagicMock(
                get_nexus_client=MagicMock(return_value=None)
            ),
        }
        return modules, mock_pool

    def test_get_artifact_bus_returns_artifact_bus_instance(self):
        """get_artifact_bus() returns an ArtifactBus instance."""
        modules, _ = self._make_module_mocks()
        with patch.dict("sys.modules", modules):
            bus = get_artifact_bus("testaccount")
        assert isinstance(bus, ArtifactBus)

    def test_get_artifact_bus_uses_named_account(self):
        """get_artifact_bus(account_name) calls pool.get_account with the given name."""
        modules, mock_pool = self._make_module_mocks()
        with patch.dict("sys.modules", modules):
            get_artifact_bus("special-account")
        mock_pool.get_account.assert_called_with("special-account")


# ──── Error handling tests ─────────────────────────────────────────────────────

class TestErrorHandling:
    """Tests for error resilience in ArtifactBus."""

    def test_handoff_to_nexus_without_nexus_client_raises(self, mock_drive, mock_nlm):
        """handoff() to NEXUS without nexus_client raises RuntimeError."""
        bus_no_nexus = ArtifactBus(drive_client=mock_drive, nlm_client=mock_nlm)
        drive_art = Artifact(service=ArtifactService.DRIVE, ref="file-id", metadata={"name": "f.txt"})
        with pytest.raises(RuntimeError, match="No Nexus client"):
            bus_no_nexus.handoff(drive_art, ArtifactService.NEXUS)

    def test_handoff_local_to_drive_missing_file_raises(self, bus):
        """handoff() LOCAL→DRIVE with non-existent file raises FileNotFoundError."""
        ghost_art = Artifact(
            service=ArtifactService.LOCAL,
            ref="/does/not/exist/ghost.txt",
            local_path="/does/not/exist/ghost.txt",
        )
        with pytest.raises(FileNotFoundError):
            bus.handoff(ghost_art, ArtifactService.DRIVE)

    def test_nlm_to_nexus_falls_back_when_flashcards_fail(
        self, bus, mock_nlm, mock_nexus, nlm_artifact
    ):
        """handoff() NLM→NEXUS falls back to add_entry when generate_flashcards raises."""
        mock_nlm.generate_flashcards.side_effect = RuntimeError("NLM timeout")
        result = bus.handoff(nlm_artifact, ArtifactService.NEXUS, notebook_id="nb-id-123")
        # Should fall back to add_entry instead of raising
        assert mock_nexus.add_entry.called
        assert result.service == ArtifactService.NEXUS
