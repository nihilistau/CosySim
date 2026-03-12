"""Tests for WorkspacePipeline — cross-service orchestrator."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.workspace_pipeline import (
    PIPELINE_TEMPLATES,
    STAGE_REGISTRY,
    PipelineRun,
    PipelineStatus,
    StageResult,
    StageStatus,
    WorkspacePipeline,
    get_workspace_pipeline,
)


# ──── Data Model Tests ────────────────────────────────────────────────────────


class TestStageResult:
    """Tests for StageResult dataclass."""

    def test_default_status(self):
        """StageResult defaults to PENDING."""
        sr = StageResult(stage_name="test")
        assert sr.status == StageStatus.PENDING

    def test_stores_output(self):
        """StageResult stores output data."""
        sr = StageResult(stage_name="test", output={"key": "value"})
        assert sr.output["key"] == "value"

    def test_stores_error(self):
        """StageResult stores error string."""
        sr = StageResult(stage_name="test", error="something broke")
        assert sr.error == "something broke"


class TestPipelineRun:
    """Tests for PipelineRun dataclass."""

    def test_default_status(self):
        """PipelineRun defaults to PENDING."""
        run = PipelineRun(run_id="test1", pipeline_name="test_pipe")
        assert run.status == PipelineStatus.PENDING

    def test_duration_ms(self):
        """duration_ms returns positive value."""
        run = PipelineRun(run_id="test1", pipeline_name="test_pipe")
        assert run.duration_ms >= 0

    def test_current_stage_none_when_no_running(self):
        """current_stage is None when no stage is running."""
        run = PipelineRun(run_id="test1", pipeline_name="test_pipe")
        assert run.current_stage is None

    def test_current_stage_returns_running(self):
        """current_stage returns the name of the running stage."""
        run = PipelineRun(run_id="test1", pipeline_name="test_pipe")
        run.stages = [
            StageResult(stage_name="a", status=StageStatus.COMPLETED),
            StageResult(stage_name="b", status=StageStatus.RUNNING),
        ]
        assert run.current_stage == "b"

    def test_to_dict_includes_all_fields(self):
        """to_dict returns a complete dictionary."""
        run = PipelineRun(run_id="test1", pipeline_name="test_pipe")
        d = run.to_dict()
        assert d["run_id"] == "test1"
        assert d["pipeline_name"] == "test_pipe"
        assert d["status"] == "pending"
        assert "stages" in d
        assert "duration_ms" in d

    def test_to_dict_serialises_stages(self):
        """to_dict includes stage details."""
        run = PipelineRun(run_id="test1", pipeline_name="test_pipe")
        run.stages = [StageResult(stage_name="a", status=StageStatus.COMPLETED)]
        d = run.to_dict()
        assert len(d["stages"]) == 1
        assert d["stages"][0]["name"] == "a"
        assert d["stages"][0]["status"] == "completed"


# ──── Registry Tests ──────────────────────────────────────────────────────────


class TestStageRegistry:
    """Tests for the global stage registry."""

    def test_registry_has_core_stages(self):
        """STAGE_REGISTRY includes all expected stages."""
        expected = [
            "nlm_research", "create_doc", "create_sheet", "fill_sheet",
            "drive_search", "drive_ask", "drive_upload", "nexus_store",
            "columnsmith", "export_doc", "nlm_add_source",
            "workspace_generate", "fetch_news",
            "docs_to_sheets", "sheets_to_doc", "gemini_enrich", "prewarm",
            "drive_copy", "drive_export", "drive_permissions", "sheet_revisions",
            "colab_execute", "colab_ask", "colab_build",
        ]
        for name in expected:
            assert name in STAGE_REGISTRY, f"Missing stage: {name}"

    def test_all_stages_are_callable(self):
        """Every registered stage is a callable."""
        for name, func in STAGE_REGISTRY.items():
            assert callable(func), f"Stage {name} is not callable"

    def test_stage_count(self):
        """Registry has the expected number of stages."""
        assert len(STAGE_REGISTRY) == 24


class TestPipelineTemplates:
    """Tests for the predefined pipeline templates."""

    def test_templates_exist(self):
        """All expected templates are defined."""
        expected = [
            "research_and_distill", "create_knowledge_doc", "data_enrichment",
            "cross_source_synthesis", "news_pipeline", "doc_to_notebook",
            "sheet_to_knowledge", "generate_and_store", "news_to_knowledge",
            "docs_nlm_distill", "sheets_enrichment_cycle", "drive_nlm_nexus",
            "full_cross_service", "knowledge_distillation", "news_full_cycle",
            "doc_structure_extract", "sheet_knowledge_report",
            "drive_template_clone", "drive_export_and_distill",
            "drive_audit_permissions", "sheet_revision_audit",
            "research_and_compute", "data_analysis", "nlm_colab_loop",
            "colab_build_and_store",
        ]
        for name in expected:
            assert name in PIPELINE_TEMPLATES, f"Missing template: {name}"

    def test_template_count(self):
        """Correct number of templates are defined."""
        assert len(PIPELINE_TEMPLATES) == 25

    def test_templates_have_stages(self):
        """Every template has at least one stage."""
        for name, stages in PIPELINE_TEMPLATES.items():
            assert len(stages) > 0, f"Template {name} has no stages"

    def test_template_stages_are_valid(self):
        """Every stage in every template is in the registry."""
        for template_name, stages in PIPELINE_TEMPLATES.items():
            for stage_def in stages:
                stage_name = stage_def["stage"]
                assert stage_name in STAGE_REGISTRY, (
                    f"Template {template_name} references unknown stage: {stage_name}"
                )

    def test_research_and_distill_stages(self):
        """research_and_distill has correct stage sequence."""
        stages = [s["stage"] for s in PIPELINE_TEMPLATES["research_and_distill"]]
        assert stages[0] == "nlm_research"
        assert "nexus_store" in stages

    def test_all_templates_end_with_nexus_store(self):
        """All templates end with nexus_store (knowledge flows to Nexus)."""
        for name, stages in PIPELINE_TEMPLATES.items():
            last = stages[-1]["stage"]
            assert last == "nexus_store", (
                f"Template {name} doesn't end with nexus_store (ends with {last})"
            )


# ──── Pipeline Orchestrator Tests ─────────────────────────────────────────────


class TestWorkspacePipeline:
    """Tests for the WorkspacePipeline orchestrator."""

    def test_register_custom_stage(self):
        """Custom stages can be registered."""
        pipe = WorkspacePipeline()
        pipe.register_stage("custom_test", lambda p, c: {"done": True})
        assert pipe._get_executor("custom_test") is not None

    def test_get_executor_returns_registry_stage(self):
        """_get_executor returns registry stages."""
        pipe = WorkspacePipeline()
        assert pipe._get_executor("nexus_store") is not None

    def test_get_executor_returns_none_for_unknown(self):
        """_get_executor returns None for unknown stages."""
        pipe = WorkspacePipeline()
        assert pipe._get_executor("nonexistent_stage") is None

    def test_run_unknown_template_fails(self):
        """Running an unknown template returns a failed PipelineRun."""
        pipe = WorkspacePipeline()
        run = pipe.run("does_not_exist")
        assert run.status == PipelineStatus.FAILED
        assert "Unknown pipeline template" in run.error

    def test_run_with_custom_stages(self):
        """Running with custom stages works."""
        pipe = WorkspacePipeline()
        pipe.register_stage("mock_stage", lambda p, c: {"result": "ok"})

        run = pipe.run(
            "custom_pipeline",
            stages=[{"stage": "mock_stage", "params": {}}],
            topic="test",
        )
        assert run.status == PipelineStatus.COMPLETED
        assert len(run.stages) == 1
        assert run.stages[0].status == StageStatus.COMPLETED

    def test_run_multi_stage_pipeline(self):
        """Multi-stage pipeline executes in order."""
        pipe = WorkspacePipeline()
        pipe.register_stage("step1", lambda p, c: {"step": 1, "data": "from_1"})
        pipe.register_stage("step2", lambda p, c: {"step": 2, "received": c.get("data")})

        run = pipe.run(
            "multi",
            stages=[
                {"stage": "step1", "params": {}},
                {"stage": "step2", "params": {}},
            ],
        )
        assert run.status == PipelineStatus.COMPLETED
        assert len(run.stages) == 2
        assert run.final_output["step"] == 2
        assert run.final_output["received"] == "from_1"

    def test_run_stage_failure_stops_pipeline(self):
        """Pipeline stops when a required stage fails."""
        pipe = WorkspacePipeline()
        pipe.register_stage("good", lambda p, c: {"ok": True})
        pipe.register_stage("bad", lambda p, c: (_ for _ in ()).throw(ValueError("boom")))

        run = pipe.run(
            "fail_test",
            stages=[
                {"stage": "good", "params": {}},
                {"stage": "bad", "params": {}},
            ],
        )
        assert run.status == PipelineStatus.FAILED
        assert run.stages[0].status == StageStatus.COMPLETED
        assert run.stages[1].status == StageStatus.FAILED
        assert "boom" in run.error

    def test_optional_stage_failure_continues(self):
        """Optional stages are skipped on failure."""
        pipe = WorkspacePipeline()
        pipe.register_stage("good", lambda p, c: {"ok": True})
        pipe.register_stage("fragile", lambda p, c: (_ for _ in ()).throw(ValueError("oops")))
        pipe.register_stage("final", lambda p, c: {"done": True})

        run = pipe.run(
            "optional_test",
            stages=[
                {"stage": "good", "params": {}},
                {"stage": "fragile", "params": {}, "optional": True},
                {"stage": "final", "params": {}},
            ],
        )
        assert run.status == PipelineStatus.COMPLETED
        assert run.stages[1].status == StageStatus.SKIPPED

    def test_context_propagation(self):
        """Stage outputs are merged into context for subsequent stages."""
        pipe = WorkspacePipeline()
        pipe.register_stage("producer", lambda p, c: {"secret": 42})
        pipe.register_stage("consumer", lambda p, c: {"got_secret": c.get("secret")})

        run = pipe.run(
            "context_test",
            stages=[
                {"stage": "producer", "params": {}},
                {"stage": "consumer", "params": {}},
            ],
        )
        assert run.final_output["got_secret"] == 42

    def test_kwargs_in_context(self):
        """Pipeline kwargs appear in context."""
        pipe = WorkspacePipeline()
        pipe.register_stage("check", lambda p, c: {"topic": c.get("topic")})

        run = pipe.run(
            "kwargs_test",
            stages=[{"stage": "check", "params": {}}],
            topic="quantum",
        )
        assert run.final_output["topic"] == "quantum"


# ──── Run Management Tests ────────────────────────────────────────────────────


class TestRunManagement:
    """Tests for pipeline run tracking."""

    def test_get_run_by_id(self):
        """get_run returns the correct run."""
        pipe = WorkspacePipeline()
        pipe.register_stage("noop", lambda p, c: {})
        run = pipe.run("test", stages=[{"stage": "noop", "params": {}}])
        found = pipe.get_run(run.run_id)
        assert found is not None
        assert found.run_id == run.run_id

    def test_get_run_unknown_returns_none(self):
        """get_run returns None for unknown IDs."""
        pipe = WorkspacePipeline()
        assert pipe.get_run("nonexistent") is None

    def test_list_runs_returns_all(self):
        """list_runs returns all runs."""
        pipe = WorkspacePipeline()
        pipe.register_stage("noop", lambda p, c: {})
        pipe.run("test1", stages=[{"stage": "noop", "params": {}}])
        pipe.run("test2", stages=[{"stage": "noop", "params": {}}])
        runs = pipe.list_runs()
        assert len(runs) >= 2

    def test_list_runs_filter_by_status(self):
        """list_runs filters by status."""
        pipe = WorkspacePipeline()
        pipe.register_stage("noop", lambda p, c: {})
        pipe.register_stage("fail", lambda p, c: (_ for _ in ()).throw(ValueError("x")))

        pipe.run("ok", stages=[{"stage": "noop", "params": {}}])
        pipe.run("bad", stages=[{"stage": "fail", "params": {}}])

        completed = pipe.list_runs(status=PipelineStatus.COMPLETED)
        assert all(r.status == PipelineStatus.COMPLETED for r in completed)

        failed = pipe.list_runs(status=PipelineStatus.FAILED)
        assert all(r.status == PipelineStatus.FAILED for r in failed)

    def test_list_templates(self):
        """list_templates returns template names and stage lists."""
        pipe = WorkspacePipeline()
        templates = pipe.list_templates()
        assert "research_and_distill" in templates
        assert isinstance(templates["research_and_distill"], list)

    def test_clear_runs_respects_keep_last(self):
        """clear_runs removes old runs but keeps recent ones."""
        pipe = WorkspacePipeline()
        pipe.register_stage("noop", lambda p, c: {})
        for i in range(5):
            pipe.run(f"test{i}", stages=[{"stage": "noop", "params": {}}])

        removed = pipe.clear_runs(keep_last=2)
        assert removed == 3
        assert len(pipe.list_runs()) == 2


# ──── Convenience Method Tests ────────────────────────────────────────────────


class TestConvenienceMethods:
    """Tests for the shortcut pipeline methods."""

    def test_research_and_distill_calls_run(self):
        """research_and_distill delegates to run()."""
        pipe = WorkspacePipeline()
        with patch.object(pipe, "run", return_value=MagicMock()) as mock_run:
            pipe.research_and_distill("quantum computing")
            mock_run.assert_called_once()
            assert mock_run.call_args[0][0] == "research_and_distill"
            assert mock_run.call_args[1]["topic"] == "quantum computing"

    def test_create_knowledge_doc_sets_title(self):
        """create_knowledge_doc sets default title from topic."""
        pipe = WorkspacePipeline()
        with patch.object(pipe, "run", return_value=MagicMock()) as mock_run:
            pipe.create_knowledge_doc("AI safety")
            kwargs = mock_run.call_args[1]
            assert "AI safety" in kwargs.get("title", "")

    def test_cross_source_synthesis_calls_run(self):
        """cross_source_synthesis delegates to run()."""
        pipe = WorkspacePipeline()
        with patch.object(pipe, "run", return_value=MagicMock()) as mock_run:
            pipe.cross_source_synthesis("climate change")
            mock_run.assert_called_once()

    def test_news_digest_passes_sources(self):
        """news_digest passes sources list."""
        pipe = WorkspacePipeline()
        with patch.object(pipe, "run", return_value=MagicMock()) as mock_run:
            pipe.news_digest("tech news", sources=["https://example.com"])
            kwargs = mock_run.call_args[1]
            assert kwargs.get("sources") == ["https://example.com"]


# ──── Factory Tests ───────────────────────────────────────────────────────────


class TestPipelineFactory:
    """Tests for the singleton factory."""

    def test_get_workspace_pipeline_returns_instance(self):
        """get_workspace_pipeline returns a WorkspacePipeline."""
        pipe = get_workspace_pipeline()
        assert isinstance(pipe, WorkspacePipeline)

    def test_get_workspace_pipeline_is_singleton(self):
        """get_workspace_pipeline returns the same instance."""
        pipe1 = get_workspace_pipeline()
        pipe2 = get_workspace_pipeline()
        assert pipe1 is pipe2


# ──── Stage Executor Unit Tests ───────────────────────────────────────────────


class TestStageExecutors:
    """Tests for individual stage executor functions."""

    def test_nexus_store_stage_calls_client(self):
        """nexus_store stage calls the Nexus client."""
        with patch("engine.nexus.client.get_nexus_client") as mock_fn:
            mock_client = MagicMock()
            mock_client.add_qa.return_value = {"id": "qa1"}
            mock_client.add_entry.return_value = {"id": "entry1"}
            mock_fn.return_value = mock_client

            from engine.nexus.workspace_pipeline import _stage_nexus_store
            result = _stage_nexus_store(
                {"title": "Test", "category": "test"},
                {"answers": [{"question": "Q?", "answer": "A."}]},
            )
            assert result["entry_count"] >= 1

    def test_drive_upload_stage_uses_answers(self):
        """drive_upload stage builds content from answers."""
        with patch("engine.integrations.google_drive_client.get_drive_client") as mock_fn:
            mock_client = MagicMock()
            mock_client.upload_text_to_cosysim_folder.return_value = {"id": "file1"}
            mock_fn.return_value = mock_client

            from engine.nexus.workspace_pipeline import _stage_drive_upload
            result = _stage_drive_upload(
                {"name": "test.txt"},
                {"answers": [{"question": "Q?", "answer": "A."}]},
            )
            assert mock_client.upload_text_to_cosysim_folder.called

    def test_create_doc_stage_uses_prompt(self):
        """create_doc stage uses prompt parameter."""
        with patch("engine.integrations.google_docs_client.get_docs_client") as mock_fn:
            mock_client = MagicMock()
            mock_client.create_with_gemini.return_value = {"documentId": "doc1"}
            mock_fn.return_value = mock_client

            from engine.nexus.workspace_pipeline import _stage_create_doc
            result = _stage_create_doc(
                {"title": "Test", "prompt": "Write about AI"},
                {},
            )
            assert result["doc_id"] == "doc1"

    def test_create_sheet_stage_returns_sheet_id(self):
        """create_sheet stage returns sheet ID."""
        with patch("engine.integrations.gsheets_client.get_sheets_client") as mock_fn:
            mock_client = MagicMock()
            mock_client.build_with_gemini.return_value = {"spreadsheetId": "sheet1"}
            mock_fn.return_value = mock_client

            from engine.nexus.workspace_pipeline import _stage_create_sheet
            result = _stage_create_sheet(
                {"title": "Test", "prompt": "Budget tracker"},
                {},
            )
            assert result["sheet_id"] == "sheet1"

    def test_stage_raises_when_no_client(self):
        """Stages raise RuntimeError when no client available."""
        with patch("engine.integrations.google_docs_client.get_docs_client", return_value=None):
            from engine.nexus.workspace_pipeline import _stage_create_doc
            with pytest.raises(RuntimeError, match="No Google Docs"):
                _stage_create_doc({}, {})

        with patch("engine.integrations.gsheets_client.get_sheets_client", return_value=None):
            from engine.nexus.workspace_pipeline import _stage_create_sheet
            with pytest.raises(RuntimeError, match="No Google Sheets"):
                _stage_create_sheet({}, {})

        with patch("engine.integrations.google_drive_client.get_drive_client", return_value=None):
            from engine.nexus.workspace_pipeline import _stage_drive_search
            with pytest.raises(RuntimeError, match="No Google Drive"):
                _stage_drive_search({}, {})

    def test_workspace_generate_stage_calls_client(self):
        """workspace_generate stage calls WorkspaceGeminiClient.stream_generate."""
        with patch(
            "engine.integrations.workspace_gemini_client.get_workspace_gemini_client"
        ) as mock_fn:
            mock_client = MagicMock()
            mock_client.stream_generate.return_value = {
                "text": "Generated content",
                "model": "gemini-2.5-pro",
                "prompt_tokens": 10,
                "completion_tokens": 50,
            }
            mock_fn.return_value = mock_client

            from engine.nexus.workspace_pipeline import _stage_workspace_generate

            result = _stage_workspace_generate(
                {"prompt": "Write about AI safety"},
                {},
            )
            assert result["text"] == "Generated content"
            assert result["model"] == "gemini-2.5-pro"
            assert result["generated"] is True
            mock_client.stream_generate.assert_called_once()

    def test_workspace_generate_stage_falls_back_to_topic(self):
        """workspace_generate uses topic from context when no prompt given."""
        with patch(
            "engine.integrations.workspace_gemini_client.get_workspace_gemini_client"
        ) as mock_fn:
            mock_client = MagicMock()
            mock_client.stream_generate.return_value = {"text": "ok"}
            mock_fn.return_value = mock_client

            from engine.nexus.workspace_pipeline import _stage_workspace_generate

            _stage_workspace_generate({}, {"topic": "quantum computing"})
            call_args = mock_client.stream_generate.call_args
            assert call_args[0][0] == "quantum computing"

    def test_fetch_news_stage_returns_articles(self):
        """fetch_news stage fetches and returns article data."""
        mock_item = MagicMock()
        mock_item.title = "AI Breakthrough"
        mock_item.url = "https://example.com/article"
        mock_item.summary = "A major AI advance"
        mock_item.source = "TechNews"

        mock_digest = MagicMock()
        mock_digest.items = [mock_item]

        with patch(
            "engine.nexus.news.news_pipeline.get_news_pipeline"
        ) as mock_pipe_fn, patch(
            "engine.nexus.news_sources.get_questions",
            return_value=["What's new in AI?"],
        ):
            mock_pipeline = MagicMock()
            mock_pipeline.fetch_category.return_value = [mock_item]
            mock_pipeline.store_items_to_nexus.return_value = 1
            mock_pipeline.build_digest.return_value = mock_digest
            mock_pipe_fn.return_value = mock_pipeline

            from engine.nexus.workspace_pipeline import _stage_fetch_news

            result = _stage_fetch_news(
                {"category": "ai_research"},
                {},
            )
            assert result["total_fetched"] == 1
            assert result["total_stored"] == 1
            assert len(result["articles"]) == 1
            assert result["articles"][0]["title"] == "AI Breakthrough"
            assert "distillation_questions" in result
            assert len(result["distillation_questions"]) >= 1

    def test_fetch_news_stage_stores_by_default(self):
        """fetch_news stage stores items to Nexus by default."""
        with patch(
            "engine.nexus.news.news_pipeline.get_news_pipeline"
        ) as mock_pipe_fn, patch(
            "engine.nexus.news_sources.get_questions", return_value=[],
        ):
            mock_pipeline = MagicMock()
            mock_pipeline.fetch_category.return_value = [MagicMock(
                title="T", url="u", summary="s", source="S"
            )]
            mock_pipeline.store_items_to_nexus.return_value = 1
            mock_pipeline.build_digest.return_value = MagicMock(items=[])
            mock_pipe_fn.return_value = mock_pipeline

            from engine.nexus.workspace_pipeline import _stage_fetch_news

            _stage_fetch_news({"category": "tech"}, {})
            mock_pipeline.store_items_to_nexus.assert_called_once()

    def test_fetch_news_stage_skips_store_when_disabled(self):
        """fetch_news stage skips Nexus store when store=False."""
        with patch(
            "engine.nexus.news.news_pipeline.get_news_pipeline"
        ) as mock_pipe_fn, patch(
            "engine.nexus.news_sources.get_questions", return_value=[],
        ):
            mock_pipeline = MagicMock()
            mock_pipeline.fetch_category.return_value = []
            mock_pipeline.build_digest.return_value = MagicMock(items=[])
            mock_pipe_fn.return_value = mock_pipeline

            from engine.nexus.workspace_pipeline import _stage_fetch_news

            _stage_fetch_news({"category": "tech", "store": False}, {})
            mock_pipeline.store_items_to_nexus.assert_not_called()

    def test_news_pipeline_template_starts_with_fetch(self):
        """news_pipeline template starts with fetch_news stage."""
        stages = [s["stage"] for s in PIPELINE_TEMPLATES["news_pipeline"]]
        assert stages[0] == "fetch_news"

    def test_generate_and_store_template_stages(self):
        """generate_and_store template has correct stages."""
        stages = [s["stage"] for s in PIPELINE_TEMPLATES["generate_and_store"]]
        assert stages == ["workspace_generate", "nexus_store"]

    def test_news_to_knowledge_template_stages(self):
        """news_to_knowledge template has correct stage sequence."""
        stages = [s["stage"] for s in PIPELINE_TEMPLATES["news_to_knowledge"]]
        assert stages[0] == "fetch_news"
        assert "nlm_research" in stages
        assert "create_doc" in stages
        assert stages[-1] == "nexus_store"


# ──── Cross-Service Chain Template Tests ──────────────────────────────────────


class TestCrossServiceTemplates:
    """Tests for the v1.18c cross-service chain prompt templates."""

    def test_docs_nlm_distill_template(self):
        """docs_nlm_distill chains doc creation through NLM to Nexus."""
        stages = [s["stage"] for s in PIPELINE_TEMPLATES["docs_nlm_distill"]]
        assert stages[0] == "create_doc"
        assert "export_doc" in stages
        assert "nlm_add_source" in stages
        assert "nlm_research" in stages
        assert stages[-1] == "nexus_store"

    def test_sheets_enrichment_cycle_template(self):
        """sheets_enrichment_cycle chains sheet creation through enrichment."""
        stages = [s["stage"] for s in PIPELINE_TEMPLATES["sheets_enrichment_cycle"]]
        assert stages[0] == "create_sheet"
        assert "fill_sheet" in stages
        assert stages[-1] == "nexus_store"

    def test_drive_nlm_nexus_template(self):
        """drive_nlm_nexus chains Drive search through NLM to Nexus."""
        stages = [s["stage"] for s in PIPELINE_TEMPLATES["drive_nlm_nexus"]]
        assert stages[0] == "drive_search"
        assert "drive_ask" in stages
        assert "gemini_enrich" in stages
        assert stages[-1] == "nexus_store"

    def test_full_cross_service_template(self):
        """full_cross_service is the complete rotation pipeline."""
        stages = [s["stage"] for s in PIPELINE_TEMPLATES["full_cross_service"]]
        assert "drive_search" in stages
        assert "nlm_research" in stages
        assert "gemini_enrich" in stages
        assert "create_sheet" in stages
        assert "create_doc" in stages
        assert "drive_upload" in stages
        assert stages[-1] == "nexus_store"

    def test_knowledge_distillation_template(self):
        """knowledge_distillation chains generation through NLM research."""
        stages = [s["stage"] for s in PIPELINE_TEMPLATES["knowledge_distillation"]]
        assert stages[0] == "workspace_generate"
        assert "nlm_research" in stages
        assert stages[-1] == "nexus_store"

    def test_news_full_cycle_template(self):
        """news_full_cycle is the complete news→knowledge pipeline."""
        stages = [s["stage"] for s in PIPELINE_TEMPLATES["news_full_cycle"]]
        assert stages[0] == "fetch_news"
        assert "gemini_enrich" in stages
        assert stages[-1] == "nexus_store"

    def test_doc_structure_extract_template(self):
        """doc_structure_extract chains doc export through Gemini to sheets."""
        stages = [s["stage"] for s in PIPELINE_TEMPLATES["doc_structure_extract"]]
        assert stages[0] == "export_doc"
        assert "gemini_enrich" in stages
        assert "docs_to_sheets" in stages
        assert stages[-1] == "nexus_store"

    def test_sheet_knowledge_report_template(self):
        """sheet_knowledge_report chains sheet data through NLM research."""
        stages = [s["stage"] for s in PIPELINE_TEMPLATES["sheet_knowledge_report"]]
        assert stages[0] == "sheets_to_doc"
        assert "nlm_add_source" in stages
        assert "nlm_research" in stages
        assert stages[-1] == "nexus_store"

    def test_all_cross_service_templates_end_with_nexus_store(self):
        """All 8 new cross-service templates end with nexus_store."""
        new_templates = [
            "docs_nlm_distill", "sheets_enrichment_cycle", "drive_nlm_nexus",
            "full_cross_service", "knowledge_distillation", "news_full_cycle",
            "doc_structure_extract", "sheet_knowledge_report",
        ]
        for name in new_templates:
            stages = PIPELINE_TEMPLATES[name]
            assert stages[-1]["stage"] == "nexus_store", (
                f"Cross-service template {name} doesn't end with nexus_store"
            )

    def test_new_stages_are_callable(self):
        """All 4 new stages (docs_to_sheets, sheets_to_doc, gemini_enrich, prewarm) are callable."""
        new_stages = ["docs_to_sheets", "sheets_to_doc", "gemini_enrich", "prewarm"]
        for name in new_stages:
            assert name in STAGE_REGISTRY, f"Missing new stage: {name}"
            assert callable(STAGE_REGISTRY[name]), f"Stage {name} not callable"


# ──── v1.19b Stage & Template Tests ───────────────────────────────────────────


class TestV119bStages:
    """Tests for v1.19b Drive v2internal and Sheets extended stages."""

    def test_v19b_stages_registered(self):
        """All 4 v1.19b stages are in the STAGE_REGISTRY."""
        new_stages = ["drive_copy", "drive_export", "drive_permissions", "sheet_revisions"]
        for name in new_stages:
            assert name in STAGE_REGISTRY, f"Missing v1.19b stage: {name}"
            assert callable(STAGE_REGISTRY[name]), f"Stage {name} not callable"

    @patch("engine.integrations.google_drive_client.get_drive_client")
    def test_drive_copy_stage(self, mock_get):
        """drive_copy stage calls v2_copy_file and returns copy metadata."""
        mock_client = MagicMock()
        mock_client.v2_copy_file.return_value = {
            "id": "new123",
            "title": "Copy of Doc",
            "alternateLink": "https://docs.google.com/...",
        }
        mock_get.return_value = mock_client

        stage_fn = STAGE_REGISTRY["drive_copy"]
        params = {"file_id": "src123", "title": "My Copy"}
        result = stage_fn(params, {})

        mock_client.v2_copy_file.assert_called_once()
        assert result["id"] == "new123"
        assert result["title"] == "Copy of Doc"

    @patch("engine.integrations.google_drive_client.get_drive_client")
    def test_drive_export_stage(self, mock_get):
        """drive_export stage calls v2_export_file and returns content."""
        mock_client = MagicMock()
        mock_client.v2_export_file.return_value = b"exported content here"
        mock_get.return_value = mock_client

        stage_fn = STAGE_REGISTRY["drive_export"]
        params = {"file_id": "file456", "mime_type": "text"}
        result = stage_fn(params, {})

        mock_client.v2_export_file.assert_called_once_with("file456", "text")
        assert result["size"] == len(b"exported content here")
        assert "content" in result
        assert result["is_text"] is True

    @patch("engine.integrations.google_drive_client.get_drive_client")
    def test_drive_permissions_stage(self, mock_get):
        """drive_permissions stage handles list action."""
        mock_client = MagicMock()
        mock_client.v2_get_permissions.return_value = [
            {"id": "p1", "role": "owner"},
            {"id": "p2", "role": "reader"},
        ]
        mock_get.return_value = mock_client

        stage_fn = STAGE_REGISTRY["drive_permissions"]
        params = {"file_id": "file789", "action": "list"}
        result = stage_fn(params, {})

        mock_client.v2_get_permissions.assert_called_once_with("file789")
        assert result["count"] == 2
        assert result["action"] == "list"

    @patch("engine.integrations.google_drive_client.get_drive_client")
    def test_drive_permissions_set_stage(self, mock_get):
        """drive_permissions stage handles set action."""
        mock_client = MagicMock()
        mock_client.v2_insert_permission.return_value = {"id": "p3", "role": "writer"}
        mock_get.return_value = mock_client

        stage_fn = STAGE_REGISTRY["drive_permissions"]
        params = {"file_id": "file789", "action": "set", "role": "writer"}
        result = stage_fn(params, {})

        mock_client.v2_insert_permission.assert_called_once()
        assert result["action"] == "set"
        assert result["permission"]["role"] == "writer"

    @patch("engine.integrations.gsheets_client.get_sheets_client")
    def test_sheet_revisions_stage(self, mock_get):
        """sheet_revisions stage fetches revision history."""
        mock_client = MagicMock()
        mock_client.get_revision_history.return_value = [
            {"revisionId": "r1", "modifiedTime": "2025-01-01T00:00:00Z"},
            {"revisionId": "r2", "modifiedTime": "2025-01-02T00:00:00Z"},
        ]
        mock_get.return_value = mock_client

        stage_fn = STAGE_REGISTRY["sheet_revisions"]
        params = {"spreadsheet_id": "sheet_abc"}
        result = stage_fn(params, {})

        mock_client.get_revision_history.assert_called_once()
        assert result["count"] == 2
        assert len(result["revisions"]) == 2


class TestV119bTemplates:
    """Tests for v1.19b pipeline templates."""

    def test_drive_template_clone_stages(self):
        """drive_template_clone has correct stage sequence."""
        stages = [s["stage"] for s in PIPELINE_TEMPLATES["drive_template_clone"]]
        assert "drive_copy" in stages
        assert "nexus_store" in stages
        assert stages[-1] == "nexus_store"

    def test_drive_export_and_distill_stages(self):
        """drive_export_and_distill has correct stage sequence."""
        stages = [s["stage"] for s in PIPELINE_TEMPLATES["drive_export_and_distill"]]
        assert "drive_export" in stages
        assert "nlm_research" in stages
        assert stages[-1] == "nexus_store"

    def test_drive_audit_permissions_stages(self):
        """drive_audit_permissions has correct stage sequence."""
        stages = [s["stage"] for s in PIPELINE_TEMPLATES["drive_audit_permissions"]]
        assert "drive_permissions" in stages
        assert stages[-1] == "nexus_store"

    def test_sheet_revision_audit_stages(self):
        """sheet_revision_audit has correct stage sequence."""
        stages = [s["stage"] for s in PIPELINE_TEMPLATES["sheet_revision_audit"]]
        assert "sheet_revisions" in stages
        assert stages[-1] == "nexus_store"

    def test_v19b_templates_end_with_nexus_store(self):
        """All 4 v1.19b templates end with nexus_store."""
        new_templates = [
            "drive_template_clone", "drive_export_and_distill",
            "drive_audit_permissions", "sheet_revision_audit",
        ]
        for name in new_templates:
            stages = PIPELINE_TEMPLATES[name]
            assert stages[-1]["stage"] == "nexus_store", (
                f"v1.19b template {name} doesn't end with nexus_store"
            )


# ──── v1.19c Colab Stages ────────────────────────────────────────────────────


class TestV119cStages:
    """Tests for the three Colab pipeline stages added in v1.19c."""

    @patch("engine.integrations.colab_client.get_colab_client")
    def test_colab_execute_stage(self, mock_get):
        """colab_execute stage runs code via ColabClient."""
        mock_client = MagicMock()
        mock_client.run_python.return_value = {"output": "42\n", "success": True}
        mock_get.return_value = mock_client

        stage_fn = STAGE_REGISTRY["colab_execute"]
        params = {"code": "print(42)", "timeout": 60}
        ctx = {"pipeline_id": "test-c19c", "results": []}
        result = stage_fn(params, ctx)

        mock_client.run_python.assert_called_once_with("print(42)", timeout=60)
        assert result["output"] == "42\n"
        assert result["success"] is True

    @patch("engine.integrations.colab_client.get_colab_client")
    def test_colab_execute_default_timeout(self, mock_get):
        """colab_execute stage uses default timeout when not specified."""
        mock_client = MagicMock()
        mock_client.run_python.return_value = {"output": "ok"}
        mock_get.return_value = mock_client

        stage_fn = STAGE_REGISTRY["colab_execute"]
        result = stage_fn({"code": "pass"}, {"pipeline_id": "t", "results": []})

        mock_client.run_python.assert_called_once_with("pass", timeout=120)

    @patch("engine.integrations.colab_client.get_colab_client")
    def test_colab_execute_error(self, mock_get):
        """colab_execute stage returns error dict on failure."""
        mock_get.side_effect = RuntimeError("no GPU")

        stage_fn = STAGE_REGISTRY["colab_execute"]
        result = stage_fn({"code": "x"}, {"pipeline_id": "t", "results": []})

        assert "error" in result

    @patch("engine.integrations.colab_client.get_colab_client")
    def test_colab_ask_stage(self, mock_get):
        """colab_ask stage sends prompt to Gemini agent."""
        mock_client = MagicMock()
        mock_client.ask.return_value = "The answer is 42."
        mock_get.return_value = mock_client

        stage_fn = STAGE_REGISTRY["colab_ask"]
        params = {"prompt": "What is life?", "context_text": "biology"}
        result = stage_fn(params, {"pipeline_id": "t", "results": []})

        mock_client.ask.assert_called_once_with("What is life?", context="biology", timeout=120)
        assert result["answer"] == "The answer is 42."

    @patch("engine.integrations.colab_client.get_colab_client")
    def test_colab_ask_defaults(self, mock_get):
        """colab_ask stage uses empty context and default timeout."""
        mock_client = MagicMock()
        mock_client.ask.return_value = "ok"
        mock_get.return_value = mock_client

        stage_fn = STAGE_REGISTRY["colab_ask"]
        result = stage_fn({"prompt": "hi"}, {"pipeline_id": "t", "results": []})

        mock_client.ask.assert_called_once_with("hi", context="", timeout=120)

    @patch("engine.integrations.colab_client.get_colab_client")
    def test_colab_ask_error(self, mock_get):
        """colab_ask stage returns error dict on failure."""
        mock_get.side_effect = ConnectionError("offline")

        stage_fn = STAGE_REGISTRY["colab_ask"]
        result = stage_fn({"prompt": "x"}, {"pipeline_id": "t", "results": []})

        assert "error" in result

    @patch("engine.integrations.colab_client.get_colab_client")
    def test_colab_build_stage(self, mock_get):
        """colab_build stage creates and polls a task."""
        mock_client = MagicMock()
        mock_client.create_task.return_value = "task-123"
        mock_client.query_task.return_value = "# Notebook Content"
        mock_get.return_value = mock_client

        stage_fn = STAGE_REGISTRY["colab_build"]
        params = {"task_description": "Build ML pipeline", "timeout": 10}
        result = stage_fn(params, {"pipeline_id": "t", "results": []})

        mock_client.create_task.assert_called_once()
        mock_client.update_task.assert_called_once_with("task-123", "Build ML pipeline")
        assert result["task_id"] == "task-123"
        assert result["status"] == "complete"

    @patch("engine.integrations.colab_client.get_colab_client")
    def test_colab_build_error(self, mock_get):
        """colab_build stage returns error dict on failure."""
        mock_get.side_effect = Exception("auth")

        stage_fn = STAGE_REGISTRY["colab_build"]
        result = stage_fn({"task_description": "x"}, {"pipeline_id": "t", "results": []})

        assert "error" in result


class TestV119cTemplates:
    """Tests for the four Colab pipeline templates added in v1.19c."""

    def test_research_and_compute_template(self):
        """research_and_compute template has correct stages."""
        stages = [s["stage"] for s in PIPELINE_TEMPLATES["research_and_compute"]]
        assert "nlm_research" in stages
        assert "colab_execute" in stages
        assert stages[-1] == "nexus_store"

    def test_data_analysis_template(self):
        """data_analysis template has correct stages."""
        stages = [s["stage"] for s in PIPELINE_TEMPLATES["data_analysis"]]
        assert "drive_search" in stages
        assert "colab_execute" in stages or "colab_ask" in stages

    def test_nlm_colab_loop_template(self):
        """nlm_colab_loop template has correct stages."""
        stages = [s["stage"] for s in PIPELINE_TEMPLATES["nlm_colab_loop"]]
        assert "nlm_research" in stages
        assert "colab_ask" in stages
        assert stages[-1] == "nexus_store"

    def test_colab_build_and_store_template(self):
        """colab_build_and_store template has correct stages."""
        stages = [s["stage"] for s in PIPELINE_TEMPLATES["colab_build_and_store"]]
        assert "colab_build" in stages
        assert stages[-1] == "nexus_store"

    def test_v19c_templates_end_with_nexus_store(self):
        """All 4 v1.19c Colab templates end with nexus_store."""
        colab_templates = [
            "research_and_compute", "data_analysis",
            "nlm_colab_loop", "colab_build_and_store",
        ]
        for name in colab_templates:
            stages = PIPELINE_TEMPLATES[name]
            assert stages[-1]["stage"] == "nexus_store", (
                f"v1.19c template {name} doesn't end with nexus_store"
            )

    def test_v19c_template_stages_are_registered(self):
        """Every stage referenced in v1.19c templates exists in STAGE_REGISTRY."""
        colab_templates = [
            "research_and_compute", "data_analysis",
            "nlm_colab_loop", "colab_build_and_store",
        ]
        for tpl_name in colab_templates:
            for step in PIPELINE_TEMPLATES[tpl_name]:
                assert step["stage"] in STAGE_REGISTRY, (
                    f"Stage {step['stage']} in template {tpl_name} not in STAGE_REGISTRY"
                )
