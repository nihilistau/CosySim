"""Agent workflow orchestration for CosySim."""
from __future__ import annotations

from engine.workflows.agent_workflows import (
    WORKFLOWS,
    WorkflowResult,
    dataset_curate,
    knowledge_distill,
    metrics_extract,
    quality_audit,
    research_pipeline,
    run_all,
)

__all__ = [
    "WORKFLOWS",
    "WorkflowResult",
    "dataset_curate",
    "knowledge_distill",
    "metrics_extract",
    "quality_audit",
    "research_pipeline",
    "run_all",
]
