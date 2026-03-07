"""Colab and NLM direct-access skill pack.

Exposes the Colab AI Agent and the direct NotebookLM private-RPC client as MCP
@skill tools. NotebookLM calls run without a browser in the request path, but
they still rely on browser-attached auth/session capture established elsewhere
in the stack.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


# ──── Colab AI Agent skills ───────────────────────────────────────────────────

@skill(
    pack="colab",
    description=(
        "Ask Gemini (via Colab AI agent) a question. "
        "Free access to Gemini 2.5 Flash/Pro via Colab's AI service. "
        "Provide an optional context string with notebook or code content."
    ),
    category="SYSTEM",
)
def colab_ask(prompt: str, context: str = "") -> str:
    """Send a prompt to the Colab AI agent and return the response.

    Args:
        prompt: The question or instruction to send to Gemini.
        context: Optional code or notebook context to include.

    Returns:
        Gemini's response text, or an error message.
    """
    from engine.integrations.colab_client import get_colab_client

    client = get_colab_client()
    if client is None:
        return (
            "No Colab account available. "
            "Import one with: pool.import_from_har(har_path, 'name', ['colab'])"
        )
    try:
        return client.ask(prompt, context=context)
    except TimeoutError:
        return "Colab AI agent timed out — the query may still be processing."
    except Exception as exc:
        logger.error("colab_ask failed: %s", exc)
        return f"Colab AI agent error: {exc}"


@skill(
    pack="colab",
    description=(
        "Execute Python code in a Colab kernel with GPU access. "
        "Requires an active Colab runtime (start one in the Colab UI). "
        "Returns stdout, stderr, and execution status."
    ),
    category="SYSTEM",
)
def colab_execute(code: str, description: str = "") -> str:
    """Execute Python code in the active Colab runtime.

    Args:
        code: Python source code to execute.
        description: Human-readable description of what the code does.

    Returns:
        JSON string with output, error, and status.
    """
    from engine.integrations.colab_client import get_colab_client

    if description:
        logger.info("Executing Colab code: %s", description)

    client = get_colab_client()
    if client is None:
        return json.dumps({
            "output": "",
            "error": "No Colab account available.",
            "status": "error",
        })
    try:
        result = client.run_python(code)
        return json.dumps(result, indent=2)
    except Exception as exc:
        logger.error("colab_execute failed: %s", exc)
        return json.dumps({"output": "", "error": str(exc), "status": "error"})


@skill(
    pack="colab",
    description=(
        "Get available Colab hardware and quota for the current account. "
        "Returns free tier GPUs (T4, V100), pro tier GPUs (A100, H100, L4), "
        "and compute unit balance."
    ),
    category="SYSTEM",
)
def colab_status() -> str:
    """Fetch Colab hardware tiers and compute quota.

    Returns:
        JSON string with hardware tiers, compute units, and account info.
    """
    from engine.integrations.colab_client import get_colab_client
    from engine.integrations.google_account_pool import get_account_pool

    pool = get_account_pool()
    accounts = pool.list_accounts()
    colab_accounts = [a for a in accounts if "colab" in a.get("services", [])]

    client = get_colab_client()
    if client is None:
        return json.dumps({
            "error": "No Colab account available",
            "accounts": colab_accounts,
        })

    try:
        info = client.get_user_info()
        runtimes = client.list_assignments()
        return json.dumps({
            "hardware": {
                "free_tiers": info.get("free_tiers", {}),
                "pro_tiers": info.get("pro_tiers", {}),
            },
            "compute_units": info.get("compute_units"),
            "expires_at": info.get("expires_at"),
            "active_runtimes": len(runtimes),
            "accounts": colab_accounts,
        }, indent=2)
    except Exception as exc:
        logger.error("colab_status failed: %s", exc)
        return json.dumps({"error": str(exc), "accounts": colab_accounts})


@skill(
    pack="colab",
    description=(
        "Get follow-up question suggestions from the Colab AI agent "
        "based on current notebook or conversation context."
    ),
    category="SYSTEM",
)
def colab_suggestions(context: str) -> str:
    """Get AI-suggested follow-up prompts for a given context.

    Args:
        context: Current notebook content or conversation context.

    Returns:
        Newline-separated list of suggestions, or an error message.
    """
    from engine.integrations.colab_client import get_colab_client

    client = get_colab_client()
    if client is None:
        return "No Colab account available."
    try:
        suggestions = client.get_suggestions(context)
        if not suggestions:
            return "No suggestions returned."
        return "\n".join(f"{i+1}. {s}" for i, s in enumerate(suggestions))
    except Exception as exc:
        logger.error("colab_suggestions failed: %s", exc)
        return f"Error getting suggestions: {exc}"


# ──── NLM direct client skills ────────────────────────────────────────────────

@skill(
    pack="colab",
    description=(
        "Ask NotebookLM directly via its private RPC surface using the browser-attached "
        "cookie/session pool. Fast once auth is refreshed from live Chrome or HAR recovery. "
        "Requires a notebook_id (UUID) and source_ids (comma-separated UUIDs). "
        "Returns grounded answers from your notebook sources."
    ),
    category="SYSTEM",
)
def nlm_direct_ask(notebook_id: str, source_ids: str, question: str) -> str:
    """Query NotebookLM directly through the stored browser-auth session.

    Args:
        notebook_id: NotebookLM notebook UUID.
        source_ids: Comma-separated list of source UUIDs to query against.
        question: The question to ask NotebookLM.

    Returns:
        NotebookLM's answer text, or an error message.
    """
    from engine.integrations.nlm_direct_client import get_nlm_direct_client

    client = get_nlm_direct_client()
    if client is None:
        return (
            "No NotebookLM account available. "
            "Refresh one with scripts\\har_capture.py --mode cdp or import a fresh HAR."
        )

    source_list = [s.strip() for s in source_ids.split(",") if s.strip()]
    if not source_list:
        return "No source_ids provided — supply comma-separated UUIDs."

    try:
        return client.ask(notebook_id, source_list, question)
    except Exception as exc:
        logger.error("nlm_direct_ask failed: %s", exc)
        return f"NLM direct query error: {exc}"


@skill(
    pack="colab",
    description=(
        "Get Colab AI agent suggestions for next steps based on context. "
        "Useful for exploring what questions to ask or actions to take."
    ),
    category="SYSTEM",
)
def colab_get_suggestions(context: str) -> str:
    """Alias for colab_suggestions — returns AI-generated follow-up prompts.

    Args:
        context: Current context or conversation content.

    Returns:
        Numbered list of suggestions.
    """
    return colab_suggestions(context)


# ──── Notebook builder skills ─────────────────────────────────────────────────

@skill(
    pack="colab",
    description=(
        "Build and run a Colab notebook from a task description. "
        "Gemini 3.1 Pro creates the cells, the Jupyter kernel executes them. "
        "Optionally chain follow-up cell prompts with semicolons. "
        "Returns execution summary and Drive URL."
    ),
    category="SYSTEM",
)
def colab_build_notebook(task: str, context: str = "", chain_prompts: str = "") -> str:
    """Build and execute a Colab notebook from a natural language task description.

    Args:
        task: Natural language description of the notebook task.
        context: Optional additional context for the AI agent.
        chain_prompts: Semicolon-separated list of follow-up cell prompts.

    Returns:
        Summary of execution including Drive URL if saved.
    """
    from engine.integrations.colab_notebook_builder import get_notebook_builder

    builder = get_notebook_builder()
    if builder is None:
        return "Colab not available: no account configured."

    prompts = [p.strip() for p in chain_prompts.split(";") if p.strip()]
    try:
        execution = builder.build_and_run(
            task_description=task,
            initial_context=context,
            chain_prompts=prompts if prompts else None,
        )
        lines = [
            f"Notebook ID: {execution.notebook_id}",
            f"Status: {execution.status}",
            f"Cells: {len(execution.cells)}",
        ]
        if execution.drive_url:
            lines.append(f"Drive: {execution.drive_url}")
        if execution.total_output:
            lines.append(f"\nOutput (truncated):\n{execution.total_output[:500]}")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("colab_build_notebook failed: %s", exc)
        return f"Notebook build error: {exc}"


@skill(
    pack="colab",
    description=(
        "Upload a file to Google Drive under CosySim/<subfolder>/. "
        "Returns the file_id and shareable URL."
    ),
    category="SYSTEM",
)
def drive_upload(name: str, content: str, subfolder: str = "nexus") -> str:
    """Upload text content to Google Drive in the CosySim folder.

    Args:
        name: File name (e.g. "report.txt").
        content: Text content to upload.
        subfolder: Subfolder inside CosySim (default: "nexus").

    Returns:
        JSON string with file_id and shareable_link.
    """
    from engine.integrations.google_drive_client import get_drive_client

    drive = get_drive_client()
    if drive is None:
        return "Drive not available: no account configured."
    try:
        meta = drive.upload_text_to_cosysim_folder(name, content, subfolder=subfolder)
        return json.dumps({
            "file_id": meta.get("id"),
            "name": meta.get("name"),
            "shareable_link": meta.get("shareable_link"),
        }, indent=2)
    except Exception as exc:
        logger.error("drive_upload failed: %s", exc)
        return f"Drive upload error: {exc}"


@skill(
    pack="colab",
    description=(
        "Download a file from Google Drive by file_id. "
        "Returns the file content as text."
    ),
    category="SYSTEM",
)
def drive_download(file_id: str) -> str:
    """Download a file from Google Drive.

    Args:
        file_id: The Drive file ID.

    Returns:
        File content as text, or an error message.
    """
    from engine.integrations.google_drive_client import get_drive_client

    drive = get_drive_client()
    if drive is None:
        return "Drive not available: no account configured."
    try:
        return drive.download_text(file_id)
    except Exception as exc:
        logger.error("drive_download failed: %s", exc)
        return f"Drive download error: {exc}"


@skill(
    pack="colab",
    description=(
        "List files in CosySim Drive folder. "
        "Optionally filter by subfolder name."
    ),
    category="SYSTEM",
)
def drive_list(subfolder: str = "") -> str:
    """List files in the CosySim Google Drive folder.

    Args:
        subfolder: Optional subfolder name to list within CosySim.

    Returns:
        JSON string listing files with id, name, mimeType.
    """
    from engine.integrations.google_drive_client import get_drive_client

    drive = get_drive_client()
    if drive is None:
        return "Drive not available: no account configured."
    try:
        root_id = drive.find_or_create_folder("CosySim")
        if subfolder:
            folder_id = drive.find_or_create_folder(subfolder, parent_id=root_id)
        else:
            folder_id = root_id
        files = drive.list_files(folder_id=folder_id)
        return json.dumps(files, indent=2)
    except Exception as exc:
        logger.error("drive_list failed: %s", exc)
        return f"Drive list error: {exc}"


@skill(
    pack="colab",
    description=(
        "Full pipeline: NLM research answer → Colab analysis notebook → Drive storage → Nexus update. "
        "Uploads the research text to Drive, builds Colab analysis cells, executes them, "
        "and stores results in Nexus."
    ),
    category="SYSTEM",
)
def nlm_to_colab_pipeline(nlm_answer: str, analysis_prompt: str = "") -> str:
    """Run the full NLM→Colab→Drive→Nexus pipeline.

    Args:
        nlm_answer: Research text from NotebookLM.
        analysis_prompt: Optional custom analysis instruction.

    Returns:
        Execution summary with Drive URL.
    """
    from engine.integrations.colab_notebook_builder import get_notebook_builder

    builder = get_notebook_builder()
    if builder is None:
        return "Colab not available: no account configured."
    try:
        prompt = analysis_prompt or "Analyze this research and create visualization cells"
        execution = builder.research_to_notebook(nlm_answer, analysis_prompt=prompt)
        lines = [
            f"Notebook ID: {execution.notebook_id}",
            f"Status: {execution.status}",
            f"Cells executed: {len(execution.cells)}",
        ]
        if execution.drive_url:
            lines.append(f"Drive: {execution.drive_url}")
        if execution.total_output:
            lines.append(f"\nOutput:\n{execution.total_output[:400]}")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("nlm_to_colab_pipeline failed: %s", exc)
        return f"Pipeline error: {exc}"


# ──── Tunnel server skills ────────────────────────────────────────────────────

@skill(
    pack="colab",
    description="Deploy a persistent Colab GPU server with tunnel. Returns tunnel URL for direct inference calls.",
    category="SYSTEM",
)
def colab_deploy_server(account_name: str = "", tunnel_type: str = "cloudflare") -> str:
    """Deploy a FastAPI inference server on Colab with a public tunnel.

    Args:
        account_name: Google account to use (empty for default).
        tunnel_type: "cloudflare" (default) or "ngrok".

    Returns:
        Deployment summary with tunnel URL, hardware, and kernel ID.
    """
    try:
        from engine.integrations.colab_tunnel_server import get_tunnel_server
        server = get_tunnel_server()
        session = server.deploy(account_name=account_name or None)
        return (
            f"Tunnel deployed: {session.tunnel_url} | "
            f"Hardware: {session.hardware} | "
            f"Kernel: {session.kernel_id}"
        )
    except Exception as exc:
        return f"Deploy failed: {exc}"


@skill(
    pack="colab",
    description="Route an inference request to the best available backend (Colab tunnel > local LMStudio). Auto-selects model tier.",
    category="SYSTEM",
)
def compute_route(prompt: str, model: str = "auto", require_pro: bool = False) -> str:
    """Route a prompt to the best available compute backend.

    Args:
        prompt: Text prompt to send.
        model: Model identifier or "auto" for automatic selection.
        require_pro: If True, require a pro-tier account.

    Returns:
        Backend-tagged response string.
    """
    try:
        from engine.integrations.compute_router import get_compute_router
        router = get_compute_router()
        require_tier = "pro" if require_pro else None
        result = router.route_inference(
            prompt, model_preference=model, require_tier=require_tier
        )
        return f"[{result['backend']}:{result['model']}] {result['response']}"
    except Exception as exc:
        return f"Routing failed: {exc}"


@skill(
    pack="colab",
    description="Get status of all compute backends: active tunnels, account tiers, usage vs limits.",
    category="SYSTEM",
)
def compute_status() -> str:
    """Return a JSON snapshot of all compute backends and usage.

    Returns:
        JSON string with accounts, tunnels, and LMStudio info.
    """
    try:
        from engine.integrations.compute_router import get_compute_router
        status = get_compute_router().get_status()
        return json.dumps(status, indent=2)
    except Exception as exc:
        return f"Status check failed: {exc}"


@skill(
    pack="colab",
    description="Configure feature limits for a Google account. Set unlimited NLM queries, Pro models, etc.",
    category="SYSTEM",
)
def compute_configure(account_name: str, feature: str, value: str) -> str:
    """Configure a feature flag or usage limit for an account.

    Args:
        account_name: Google account to configure.
        feature: Feature name or service key (e.g. "nlm_queries_per_day").
        value: "unlimited", a number, or "true"/"false" for features.

    Returns:
        Confirmation string.
    """
    try:
        from engine.integrations.compute_router import get_compute_router
        router = get_compute_router()
        if (
            feature.endswith("_per_day")
            or feature.endswith("_gb")
            or feature.endswith("_hours")
        ):
            limit = float("inf") if value == "unlimited" else float(value)
            router.configure_limits(account_name, feature, limit)
            return f"Configured {account_name}.{feature} = {value}"
        else:
            enabled = value.lower() in ("true", "1", "yes", "enabled", "unlock")
            existing = router._feature_config.get(account_name, {}).get(
                "unlocked_features", []
            )
            if enabled and feature not in existing:
                existing.append(feature)
            elif not enabled and feature in existing:
                existing.remove(feature)
            router.set_feature_config(account_name, existing)
            return f"Feature {feature} {'enabled' if enabled else 'disabled'} for {account_name}"
    except Exception as exc:
        return f"Configure failed: {exc}"


@skill(
    pack="colab",
    description="List available Gemini models for current account tier (free/pro).",
    category="SYSTEM",
)
def compute_list_models(tier: str = "auto") -> str:
    """List available Gemini models for the given tier.

    Args:
        tier: "free", "pro", or "auto" to detect from active accounts.

    Returns:
        Formatted model list.
    """
    try:
        from engine.integrations.compute_router import get_compute_router, MODELS_FREE, MODELS_PRO
        if tier == "auto":
            router = get_compute_router()
            status = router.get_status()
            has_pro = any(a.get("tier") == "pro" for a in status.get("accounts", []))
            tier = "pro" if has_pro else "free"
        models = MODELS_PRO if tier == "pro" else MODELS_FREE
        return f"Models ({tier} tier):\n" + "\n".join(f"  - {m}" for m in models)
    except Exception as exc:
        return f"Model list failed: {exc}"


@skill(
    pack="colab",
    description=(
        "Offload a model fine-tuning job to Colab GPU. "
        "Uploads the dataset JSONL to Drive, builds unsloth LoRA training cells, "
        "executes them on the Colab runtime, and returns the Drive adapter URL."
    ),
    category="SYSTEM",
)
def colab_finetune(
    dataset_path: str,
    model_name: str = "unsloth/Qwen2.5-1.5B-Instruct",
    epochs: int = 2,
) -> str:
    """Fine-tune a model on Colab using unsloth LoRA.

    Args:
        dataset_path: Local path to the training JSONL file.
        model_name: HuggingFace model identifier.
        epochs: Number of training epochs.

    Returns:
        Execution summary with Drive adapter URL if training succeeded.
    """
    from engine.integrations.colab_notebook_builder import get_notebook_builder

    builder = get_notebook_builder()
    if builder is None:
        return "Colab not available: no account configured."
    try:
        execution = builder.training_notebook(
            dataset_jsonl_path=dataset_path,
            model_name=model_name,
            epochs=epochs,
        )
        lines = [
            f"Notebook ID: {execution.notebook_id}",
            f"Status: {execution.status}",
            f"Cells: {len(execution.cells)}",
        ]
        if execution.drive_url:
            lines.append(f"Notebook: {execution.drive_url}")
        if execution.total_output:
            lines.append(f"\nTraining output:\n{execution.total_output[:600]}")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("colab_finetune failed: %s", exc)
        return f"Fine-tune error: {exc}"
