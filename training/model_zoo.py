"""Central ModelSpec registry — single source of truth for all trainable model types."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ModelSpec:
    """Specification for a trainable model type."""

    id: str
    display_name: str
    description: str
    base_model_alias: str        # "qwen-270m", "qwen-1.7b", "llama-3b", "piper", "qwen3-tts", "orpheus"
    task_type: str               # "classification","structured_output","generation","detection","scoring","voice_piper","voice_qwen3","voice_orpheus","conversation"
    instruction: str             # Alpaca instruction string
    dataset_key: str             # prefix for {key}_train.jsonl
    train_threshold: int         # min collected examples before auto-train fires
    benchmark_instruction: str   # instruction used during eval
    auto_promote: bool = True
    priority: int = 5            # 1=highest
    lora_overrides: Dict[str, Any] = field(default_factory=dict)
    collect_from: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    enabled: bool = True
    voice_backend: Optional[str] = None  # "piper","qwen3","orpheus" for voice types
    character_ids: List[str] = field(default_factory=list)


MODEL_ZOO: Dict[str, ModelSpec] = {
    "qa_evaluator": ModelSpec(
        id="qa_evaluator",
        display_name="QA Evaluator",
        description="Evaluates question-answer pair quality and correctness.",
        base_model_alias="qwen-270m",
        task_type="classification",
        instruction="Evaluate the quality of this question-answer pair. Respond: GOOD or BAD with brief reason.",
        dataset_key="qa_evaluator",
        train_threshold=200,
        benchmark_instruction="Evaluate this Q&A pair quality:",
        priority=3,
        collect_from=["qa_feedback", "nexus_ratings"],
        tags=["evaluation", "qa", "classification"],
    ),
    "conversation_analyzer": ModelSpec(
        id="conversation_analyzer",
        display_name="Conversation Analyzer",
        description="Analyzes conversation quality, detects issues, and suggests improvements.",
        base_model_alias="qwen-270m",
        task_type="classification",
        instruction="Analyze this conversation and identify any issues or quality problems. Respond: ISSUE: description or OK.",
        dataset_key="conversation_analyzer",
        train_threshold=150,
        benchmark_instruction="Analyze this conversation for issues:",
        priority=4,
        collect_from=["dialog_ratings", "conversation_feedback"],
        tags=["conversation", "analysis", "quality"],
    ),
    "syntax_fixer": ModelSpec(
        id="syntax_fixer",
        display_name="Syntax Fixer",
        description="Detects and fixes syntax errors in code and structured data.",
        base_model_alias="qwen-270m",
        task_type="generation",
        instruction="Fix any syntax errors in the following code or text. Return the corrected version.",
        dataset_key="syntax_fixer",
        train_threshold=200,
        benchmark_instruction="Fix syntax errors in:",
        priority=3,
        collect_from=["syntax_corrections"],
        tags=["syntax", "fixing", "code"],
    ),
    "router_v2": ModelSpec(
        id="router_v2",
        display_name="Agent Router v2",
        description="Routes agent requests to the appropriate handler or model.",
        base_model_alias="qwen-270m",
        task_type="classification",
        instruction="Classify this request and route it to the correct handler. Respond with the handler name.",
        dataset_key="router_v2",
        train_threshold=300,
        benchmark_instruction="Route this request:",
        priority=2,
        collect_from=["agent_routing_events"],
        tags=["routing", "classification", "agent"],
    ),
    "router_v3": ModelSpec(
        id="router_v3",
        display_name="Agent Router v3",
        description="Enhanced router with intent detection and multi-label classification.",
        base_model_alias="qwen-270m",
        task_type="classification",
        instruction='Classify the intent and route this request. Respond with JSON: {"intent": "...", "handler": "..."}',
        dataset_key="router_v3",
        train_threshold=500,
        benchmark_instruction="Classify and route:",
        priority=2,
        collect_from=["agent_routing_events", "intent_labels"],
        tags=["routing", "intent", "classification"],
    ),
    "knowledge_synthesizer": ModelSpec(
        id="knowledge_synthesizer",
        display_name="Knowledge Synthesizer",
        description="Synthesizes knowledge from multiple sources into coherent summaries.",
        base_model_alias="qwen-1.7b",
        task_type="generation",
        instruction="Synthesize the following knowledge fragments into a coherent, comprehensive answer.",
        dataset_key="knowledge_synthesizer",
        train_threshold=200,
        benchmark_instruction="Synthesize these knowledge fragments:",
        priority=4,
        collect_from=["nexus_synthesis_feedback"],
        tags=["synthesis", "knowledge", "summarization"],
    ),
    "tool_dispatch": ModelSpec(
        id="tool_dispatch",
        display_name="Tool Dispatcher",
        description="Routes user instructions to the correct skill/MCP tool with parameter extraction.",
        base_model_alias="qwen-270m",
        task_type="structured_output",
        instruction='Route this instruction to the correct tool. Respond with JSON: {"tool": "skill_name", "args": {...}}',
        dataset_key="tool_dispatch",
        train_threshold=200,
        benchmark_instruction='Route this instruction to the correct tool. Respond with JSON: {"tool": "skill_name", "args": {...}}',
        priority=2,
        collect_from=["skill_calls", "mcp_tool_calls"],
        tags=["tool_calling", "routing", "skills", "mcp"],
    ),
    "grammar_scanner": ModelSpec(
        id="grammar_scanner",
        display_name="Grammar Scanner",
        description="Detects grammar errors, missing brackets, unclosed strings, malformed JSON/YAML/Python.",
        base_model_alias="qwen-270m",
        task_type="detection",
        instruction="Scan this text for grammar errors and missing symbols. List all issues or respond 'OK' if clean.",
        dataset_key="grammar_scanner",
        train_threshold=200,
        benchmark_instruction="Scan this text for grammar errors. List issues or respond 'OK':",
        priority=3,
        collect_from=["grammar_corrections"],
        tags=["grammar", "syntax", "validation"],
    ),
    "output_evaluator": ModelSpec(
        id="output_evaluator",
        display_name="Output Evaluator",
        description="Scores LLM output quality on 1-5 scale with brief reason.",
        base_model_alias="qwen-270m",
        task_type="scoring",
        instruction="Score the quality of this LLM output from 1 (bad) to 5 (excellent). Respond: SCORE: N\nREASON: brief explanation",
        dataset_key="output_evaluator",
        train_threshold=150,
        benchmark_instruction="Score this output 1-5. Respond: SCORE: N\nREASON:",
        priority=3,
        collect_from=["news_ratings", "output_feedback"],
        tags=["evaluation", "quality", "scoring"],
    ),
    "conversational": ModelSpec(
        id="conversational",
        display_name="Conversational",
        description="Per-character dialog model trained on actual scene conversations.",
        base_model_alias="qwen-1.7b",
        task_type="conversation",
        instruction="Continue this conversation naturally, in character.",
        dataset_key="conversational",
        train_threshold=300,
        benchmark_instruction="Continue the conversation:",
        priority=4,
        lora_overrides={"lora_r": 16, "num_epochs": 2, "batch_size": 4, "max_seq_length": 1024},
        collect_from=["scene_dialogs", "agent_conversations", "dialog_ratings"],
        tags=["conversation", "dialog", "character", "generation"],
    ),
    "coder": ModelSpec(
        id="coder",
        display_name="CosySim Coder",
        description="Code generation/completion model trained on CosySim codebase.",
        base_model_alias="llama-3b",
        task_type="generation",
        instruction="Complete or generate the requested code following CosySim conventions.",
        dataset_key="coder",
        train_threshold=500,
        benchmark_instruction="Complete the code:",
        priority=4,
        lora_overrides={"lora_r": 16, "num_epochs": 2, "batch_size": 2, "gradient_accumulation": 8, "max_seq_length": 2048},
        collect_from=["coding_sessions", "nexus_code_qa"],
        tags=["code", "generation", "python", "cosysim"],
    ),
    "voice_piper": ModelSpec(
        id="voice_piper",
        display_name="Voice Piper VITS",
        description="Piper VITS fine-tune: trains encoder/duration-predictor/flow-decoder/HiFi-GAN vocoder.",
        base_model_alias="piper",
        task_type="voice_piper",
        instruction="",
        dataset_key="voice_piper",
        train_threshold=50,
        benchmark_instruction="",
        priority=5,
        collect_from=["tts_audio_rated"],
        tags=["voice", "piper", "vits", "acoustic"],
        character_ids=["aria", "lola", "viktor", "frankie", "mira"],
        voice_backend="piper",
    ),
    "voice_qwen3": ModelSpec(
        id="voice_qwen3",
        display_name="Voice Qwen3-TTS LoRA",
        description="Qwen3-TTS LoRA: fine-tunes LLM backbone + flow-matching decoder.",
        base_model_alias="qwen3-tts",
        task_type="voice_qwen3",
        instruction="",
        dataset_key="voice_qwen3",
        train_threshold=30,
        benchmark_instruction="",
        priority=5,
        collect_from=["tts_audio_rated"],
        tags=["voice", "qwen3", "flow-matching", "acoustic"],
        character_ids=["aria", "lola", "viktor", "frankie", "mira"],
        voice_backend="qwen3",
    ),
    "voice_orpheus": ModelSpec(
        id="voice_orpheus",
        display_name="Voice Orpheus LoRA",
        description="Orpheus Llama-3B LoRA: fine-tunes the backbone on character dialog + emotion audio.",
        base_model_alias="orpheus",
        task_type="voice_orpheus",
        instruction="",
        dataset_key="voice_orpheus",
        train_threshold=40,
        benchmark_instruction="",
        priority=5,
        collect_from=["tts_audio_rated"],
        tags=["voice", "orpheus", "llama", "acoustic"],
        character_ids=["aria", "lola", "viktor", "frankie", "mira"],
        voice_backend="orpheus",
    ),
}


def get_spec(model_type: str) -> ModelSpec:
    """Get a ModelSpec by model type ID.

    Args:
        model_type: The model type identifier.

    Returns:
        ModelSpec for the given type.

    Raises:
        KeyError: If model_type not found in MODEL_ZOO.
    """
    if model_type not in MODEL_ZOO:
        raise KeyError(f"Model type '{model_type}' not found in MODEL_ZOO. Available: {list(MODEL_ZOO.keys())}")
    return MODEL_ZOO[model_type]


def list_specs(task_type: Optional[str] = None, enabled: bool = True) -> List[ModelSpec]:
    """List ModelSpecs with optional filtering.

    Args:
        task_type: Optional task type filter.
        enabled: If True, only return enabled specs.

    Returns:
        List of matching ModelSpec instances.
    """
    specs = list(MODEL_ZOO.values())
    if enabled:
        specs = [s for s in specs if s.enabled]
    if task_type:
        specs = [s for s in specs if s.task_type == task_type]
    return sorted(specs, key=lambda s: s.priority)


def get_nlp_specs(enabled: bool = True) -> List[ModelSpec]:
    """Get all non-voice NLP model specs.

    Args:
        enabled: If True, only return enabled specs.

    Returns:
        List of NLP ModelSpec instances (excludes voice types).
    """
    voice_types = {"voice_piper", "voice_qwen3", "voice_orpheus"}
    specs = list(MODEL_ZOO.values())
    if enabled:
        specs = [s for s in specs if s.enabled]
    return [s for s in specs if s.task_type not in voice_types]


def get_voice_specs(enabled: bool = True) -> List[ModelSpec]:
    """Get all voice model specs.

    Args:
        enabled: If True, only return enabled specs.

    Returns:
        List of voice ModelSpec instances.
    """
    voice_types = {"voice_piper", "voice_qwen3", "voice_orpheus"}
    specs = list(MODEL_ZOO.values())
    if enabled:
        specs = [s for s in specs if s.enabled]
    return [s for s in specs if s.task_type in voice_types]


def get_conversation_specs(enabled: bool = True) -> List[ModelSpec]:
    """Get all conversational model specs.

    Args:
        enabled: If True, only return enabled specs.

    Returns:
        List of conversational ModelSpec instances.
    """
    specs = list(MODEL_ZOO.values())
    if enabled:
        specs = [s for s in specs if s.enabled]
    return [s for s in specs if s.task_type == "conversation"]
