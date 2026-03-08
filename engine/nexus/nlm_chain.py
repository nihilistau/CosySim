"""NLM Chain-Prompting Engine.

Orchestrates multi-step NotebookLM operations using the RPC registry,
notebook fleet config, and Nexus knowledge backbone. Supports
double-prompt artifact generation, batch distillation, and
progressive research chains.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml

logger = logging.getLogger(__name__)

# ──── Data Classes ────────────────────────────────────────────

@dataclass
class ChainStep:
    """A single step in a chain-prompting pipeline."""
    name: str
    prompt_template: str
    output_as_source: bool = False
    result: Optional[str] = None
    elapsed_ms: float = 0.0


@dataclass
class ChainResult:
    """Result of a complete chain execution."""
    chain_name: str
    notebook_id: Optional[str] = None
    steps: List[ChainStep] = field(default_factory=list)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    total_elapsed_ms: float = 0.0
    success: bool = False
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_name": self.chain_name,
            "notebook_id": self.notebook_id,
            "steps": [
                {
                    "name": s.name,
                    "prompt": s.prompt_template[:200],
                    "result_length": len(s.result) if s.result else 0,
                    "elapsed_ms": s.elapsed_ms,
                }
                for s in self.steps
            ],
            "artifact_count": len(self.artifacts),
            "total_elapsed_ms": self.total_elapsed_ms,
            "success": self.success,
            "error": self.error,
        }


@dataclass
class NotebookSpec:
    """Specification for a purpose-built notebook."""
    key: str
    name: str
    purpose: str
    url: Optional[str] = None
    refresh_interval_hours: int = 168
    sources: List[Dict[str, Any]] = field(default_factory=list)
    distillation_questions: List[str] = field(default_factory=list)


# ──── Fleet Configuration ─────────────────────────────────────

_fleet_config: Optional[Dict[str, Any]] = None


def _load_fleet_config() -> Dict[str, Any]:
    """Load the notebook fleet configuration from YAML."""
    global _fleet_config
    if _fleet_config is not None:
        return _fleet_config

    config_path = Path(__file__).parent.parent.parent / "config" / "nlm_notebooks.yaml"
    if not config_path.exists():
        logger.warning("nlm_notebooks.yaml not found at %s", config_path)
        _fleet_config = {"fleet": {"defaults": {}, "notebooks": {}, "chains": {}, "batches": {}}}
        return _fleet_config

    with open(config_path, "r", encoding="utf-8") as f:
        _fleet_config = yaml.safe_load(f) or {}

    logger.info("Loaded NLM fleet config: %d notebooks, %d chains",
                len(_fleet_config.get("fleet", {}).get("notebooks", {})),
                len(_fleet_config.get("fleet", {}).get("chains", {})))
    return _fleet_config


def reset_fleet_config() -> None:
    """Reset cached fleet config (for testing)."""
    global _fleet_config
    _fleet_config = None


def get_fleet_defaults() -> Dict[str, Any]:
    """Get global fleet defaults."""
    config = _load_fleet_config()
    return config.get("fleet", {}).get("defaults", {})


def get_notebook_spec(key: str) -> Optional[NotebookSpec]:
    """Get a notebook specification by key."""
    config = _load_fleet_config()
    notebooks = config.get("fleet", {}).get("notebooks", {})
    nb = notebooks.get(key)
    if not nb:
        return None
    return NotebookSpec(
        key=key,
        name=nb.get("name", f"cosysim-{key}"),
        purpose=nb.get("purpose", ""),
        url=nb.get("url"),
        refresh_interval_hours=nb.get("refresh_interval_hours", 168),
        sources=nb.get("sources", []),
        distillation_questions=nb.get("distillation_questions", []),
    )


def get_all_notebook_specs() -> List[NotebookSpec]:
    """Get all configured notebook specifications."""
    config = _load_fleet_config()
    notebooks = config.get("fleet", {}).get("notebooks", {})
    return [get_notebook_spec(k) for k in notebooks if get_notebook_spec(k)]


def get_chain_config(chain_name: str) -> Optional[Dict[str, Any]]:
    """Get a chain-prompting strategy configuration."""
    config = _load_fleet_config()
    chains = config.get("fleet", {}).get("chains", {})
    return chains.get(chain_name)


def get_batch_config(batch_name: str) -> Optional[Dict[str, Any]]:
    """Get a batch operation configuration."""
    config = _load_fleet_config()
    batches = config.get("fleet", {}).get("batches", {})
    return batches.get(batch_name)


# ──── Chain Execution Engine ──────────────────────────────────

class NLMChainEngine:
    """Executes multi-step chain-prompting pipelines against NLM notebooks.

    The engine supports:
    - Double-prompt artifact generation (generate → refine)
    - Progressive research chains (overview → details → examples → gaps)
    - Knowledge distillation (extract → Q&A → gap analysis)
    - Task decomposition (understand → decompose → manifest)
    - Batch operations across multiple notebooks
    """

    def __init__(self, nlm_client: Any = None, nexus_client: Any = None) -> None:
        self._nlm_client = nlm_client
        self._nexus_client = nexus_client
        self._defaults = get_fleet_defaults()

    def _get_nlm_client(self) -> Any:
        """Lazy-load the NLM client."""
        if self._nlm_client is None:
            try:
                from engine.integrations.nlm_direct_client import NLMDirectClient
                self._nlm_client = NLMDirectClient()
            except Exception as e:
                logger.error("Failed to initialize NLMDirectClient: %s", e)
                raise
        return self._nlm_client

    def _get_nexus_client(self) -> Any:
        """Lazy-load the Nexus client."""
        if self._nexus_client is None:
            try:
                from engine.nexus.client import get_nexus_client
                self._nexus_client = get_nexus_client()
            except Exception as e:
                logger.error("Failed to initialize NexusClient: %s", e)
                raise
        return self._nexus_client

    def _ask_notebook(self, notebook_id: str, question: str) -> str:
        """Ask a question to a notebook and return the answer."""
        client = self._get_nlm_client()
        try:
            result = client.ask_notebook(notebook_id, question)
            if isinstance(result, dict):
                return result.get("answer", result.get("text", str(result)))
            return str(result) if result else ""
        except Exception as e:
            logger.error("NLM ask failed for notebook %s: %s", notebook_id, e)
            return f"[ERROR: {e}]"

    def _store_in_nexus(
        self, title: str, content: str,
        content_type: str = "note",
        category: str = "nlm-chain",
        tags: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Store a chain result in Nexus."""
        try:
            client = self._get_nexus_client()
            result = client.add_entry(
                title=title,
                content=content,
                content_type=content_type,
                category=category,
                tags=tags or ["nlm-chain", "auto-generated"],
            )
            entry_id = result.get("id") if isinstance(result, dict) else str(result)
            logger.info("Stored chain result in Nexus: %s (%s)", title, entry_id)
            return entry_id
        except Exception as e:
            logger.error("Failed to store in Nexus: %s", e)
            return None

    def _store_qa_in_nexus(
        self, question: str, answer: str,
        category: str = "nlm-chain",
    ) -> Optional[str]:
        """Store a Q&A pair in Nexus from chain output."""
        try:
            client = self._get_nexus_client()
            result = client.add_qa(question, answer, category=category)
            qa_id = result.get("id") if isinstance(result, dict) else str(result)
            return qa_id
        except Exception as e:
            logger.error("Failed to store Q&A in Nexus: %s", e)
            return None

    def execute_chain(
        self,
        chain_name: str,
        notebook_id: str,
        variables: Optional[Dict[str, str]] = None,
        store_results: bool = True,
    ) -> ChainResult:
        """Execute a named chain-prompting strategy against a notebook.

        Args:
            chain_name: Name of the chain from config (e.g., 'double_prompt')
            notebook_id: NLM notebook ID to query
            variables: Template variables to substitute in prompts
            store_results: Whether to store results in Nexus

        Returns:
            ChainResult with all step outputs and artifacts
        """
        chain_config = get_chain_config(chain_name)
        if not chain_config:
            return ChainResult(
                chain_name=chain_name,
                error=f"Chain '{chain_name}' not found in config",
            )

        result = ChainResult(chain_name=chain_name, notebook_id=notebook_id)
        variables = variables or {}
        start_time = time.time()

        steps_config = chain_config.get("steps", [])
        previous_output = ""

        for step_cfg in steps_config:
            step = ChainStep(
                name=step_cfg.get("name", "unnamed"),
                prompt_template=step_cfg.get("prompt_template", ""),
                output_as_source=step_cfg.get("output_as_source", False),
            )

            prompt = step.prompt_template.format(
                previous_output=previous_output,
                **variables,
            )

            step_start = time.time()
            answer = self._ask_notebook(notebook_id, prompt)
            step.elapsed_ms = (time.time() - step_start) * 1000
            step.result = answer
            previous_output = answer

            result.steps.append(step)
            logger.info("Chain step '%s' completed in %.0fms (%d chars)",
                        step.name, step.elapsed_ms, len(answer))

            if step.output_as_source and answer and not answer.startswith("[ERROR"):
                result.artifacts.append({
                    "step": step.name,
                    "content": answer,
                    "type": "intermediate_artifact",
                })

            batch_delay = self._defaults.get("batch_delay_ms", 500)
            time.sleep(batch_delay / 1000.0)

        result.total_elapsed_ms = (time.time() - start_time) * 1000
        result.success = all(
            s.result and not s.result.startswith("[ERROR") for s in result.steps
        )

        if store_results and result.success:
            final_output = result.steps[-1].result if result.steps else ""
            self._store_in_nexus(
                title=f"NLM Chain: {chain_name}",
                content=final_output,
                category="nlm-chain",
                tags=["nlm-chain", chain_name, *list(variables.keys())[:3]],
            )

            for step in result.steps:
                if step.result and len(step.result) > 50:
                    prompt_summary = step.prompt_template[:100].format(**variables)
                    self._store_qa_in_nexus(
                        question=prompt_summary,
                        answer=step.result[:2000],
                        category="nlm-chain",
                    )

        return result

    def distill_notebook(
        self,
        notebook_key: str,
        questions: Optional[List[str]] = None,
        store_results: bool = True,
    ) -> List[Dict[str, Any]]:
        """Run distillation questions against a fleet notebook.

        Args:
            notebook_key: Key from config (e.g., 'control', 'coding')
            questions: Override questions (uses config defaults if None)
            store_results: Whether to store results in Nexus

        Returns:
            List of {question, answer, qa_id} dicts
        """
        spec = get_notebook_spec(notebook_key)
        if not spec:
            logger.error("Notebook spec '%s' not found", notebook_key)
            return []

        if not spec.url:
            logger.error("Notebook '%s' has no URL configured", notebook_key)
            return []

        notebook_id = spec.url.rstrip("/").split("/")[-1]
        distill_questions = questions or spec.distillation_questions

        results = []
        for question in distill_questions:
            answer = self._ask_notebook(notebook_id, question)
            entry = {"question": question, "answer": answer, "qa_id": None}

            if store_results and answer and not answer.startswith("[ERROR"):
                qa_id = self._store_qa_in_nexus(
                    question=question,
                    answer=answer,
                    category=f"nlm-distill-{notebook_key}",
                )
                entry["qa_id"] = qa_id

            results.append(entry)

            batch_delay = self._defaults.get("batch_delay_ms", 500)
            time.sleep(batch_delay / 1000.0)

        logger.info("Distilled %d questions from '%s': %d successful",
                    len(distill_questions), notebook_key,
                    sum(1 for r in results if r["answer"] and not r["answer"].startswith("[ERROR")))
        return results

    def run_batch(
        self,
        batch_name: str,
        chain_override: Optional[str] = None,
        variables: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Run a named batch operation across multiple notebooks.

        Args:
            batch_name: Batch config name (e.g., 'daily_refresh', 'weekly_deep')
            chain_override: Override the chain strategy
            variables: Template variables for chain prompts

        Returns:
            Batch results summary
        """
        batch_config = get_batch_config(batch_name)
        if not batch_config:
            return {"error": f"Batch '{batch_name}' not found", "success": False}

        notebook_keys = batch_config.get("notebooks", [])
        chain_name = chain_override or batch_config.get("chain")
        store = batch_config.get("store_in_nexus", True)

        results = {}
        for key in notebook_keys:
            spec = get_notebook_spec(key)
            if not spec or not spec.url:
                results[key] = {"error": f"No URL for notebook '{key}'", "success": False}
                continue

            notebook_id = spec.url.rstrip("/").split("/")[-1]

            if chain_name:
                chain_result = self.execute_chain(
                    chain_name=chain_name,
                    notebook_id=notebook_id,
                    variables=variables or {},
                    store_results=store,
                )
                results[key] = chain_result.to_dict()
            else:
                distill_results = self.distill_notebook(
                    notebook_key=key,
                    store_results=store,
                )
                results[key] = {
                    "questions_asked": len(distill_results),
                    "successful": sum(1 for r in distill_results
                                     if r["answer"] and not r["answer"].startswith("[ERROR")),
                    "success": True,
                }

        return {
            "batch_name": batch_name,
            "notebooks_processed": len(results),
            "results": results,
            "success": all(
                r.get("success", False) for r in results.values()
            ),
        }

    def generate_action_manifest(
        self,
        task_description: str,
        notebook_key: str = "planning",
        store_result: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Generate an Action Manifest from a task description.

        Uses the task_decompose chain to break a complex task into
        agent-executable steps with validation gates.

        Args:
            task_description: The task to decompose
            notebook_key: Notebook to use for context
            store_result: Whether to store in Nexus

        Returns:
            Action manifest dict or None on failure
        """
        spec = get_notebook_spec(notebook_key)
        if not spec or not spec.url:
            logger.error("No URL for notebook '%s'", notebook_key)
            return None

        notebook_id = spec.url.rstrip("/").split("/")[-1]
        result = self.execute_chain(
            chain_name="task_decompose",
            notebook_id=notebook_id,
            variables={"task_description": task_description},
            store_results=store_result,
        )

        if not result.success:
            logger.error("Action manifest generation failed: %s", result.error)
            return None

        final_step = result.steps[-1] if result.steps else None
        if not final_step or not final_step.result:
            return None

        try:
            manifest = json.loads(final_step.result)
            return manifest
        except json.JSONDecodeError:
            return {
                "raw_output": final_step.result,
                "parsed": False,
                "task": task_description,
            }


# ──── Singleton ───────────────────────────────────────────────

_engine_instance: Optional[NLMChainEngine] = None


def get_chain_engine() -> NLMChainEngine:
    """Get or create the singleton chain engine."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = NLMChainEngine()
    return _engine_instance


def reset_chain_engine() -> None:
    """Reset the singleton (for testing)."""
    global _engine_instance
    _engine_instance = None
