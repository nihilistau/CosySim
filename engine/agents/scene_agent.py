"""
SceneAgent — Lightweight one-shot task agent

Used for utility LLM calls that don't need the full character persona:
- Generating a title for a video/voice message
- Summarizing a conversation
- Routing / classification
- Structured JSON output (game decisions, schema-enforced responses)

``SceneAgent`` is intentionally stateless: every call uses ``store=False``
so it never pollutes LMStudio's server conversation state.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SceneAgent:
    """
    Minimal LMStudio agent for one-shot utility tasks.

    All calls use ``store=False`` (stateless) by default. No conversation
    state is created or consumed — this is for fire-and-forget queries.

    Parameters
    ----------
    model : str, optional
        LMStudio model key.  Uses the currently loaded model if None.
    system_prompt : str, optional
        System prompt to prepend to every task.
    config : ConfigManager, optional
        Config override.  Uses global if None.
    """

    DEFAULT_SYSTEM = (
        "You are a helpful assistant that performs short, precise tasks. "
        "Reply with only the requested output — no extra commentary."
    )

    def __init__(
        self,
        model:         Optional[str] = None,
        system_prompt: Optional[str] = None,
        config=None,
        scene_id:      Optional[str] = None,
        character_id:  Optional[str] = None,
    ) -> None:
        self.model         = model
        self.system_prompt = system_prompt or self.DEFAULT_SYSTEM
        self.scene_id      = scene_id or "system"
        self.character_id  = character_id or "scene_agent"
        if config is None:
            from engine.config import get_config
            config = get_config()
        self.config = config

    # ──────────────────────────────────────────────────── public API ──

    def run(
        self,
        task: str,
        *,
        tools:      Optional[List] = None,
        max_tokens: int            = 256,
        store:      bool           = False,
    ) -> str:
        """
        Run a one-shot task via VirtualAgentManager and return the LLM output.

        Uses ``store=False`` by default — stateless, disposable query.

        Args:
            task:       Instruction / prompt for the task.
            tools:      Ignored — expose tools via CosySim MCP server instead.
            max_tokens: Soft token cap for the response.
            store:      Whether to store this in LMStudio state (default: False).

        Returns:
            Response text, or empty string on failure.
        """
        if tools:
            logger.debug(
                "SceneAgent.run: local tool callables are not supported; "
                "expose them via the CosySim MCP server and set lmstudio.cosysim_mcp_url"
            )
        try:
            from engine.agents.virtual_agent_manager import get_virtual_agent_manager
            from engine.agents.virtual_agent import InferenceRequest
            mgr = get_virtual_agent_manager()

            # Build MCP integrations if configured
            integrations = None
            mcp_url = self.config.get("lmstudio.cosysim_mcp_url", "")
            if mcp_url:
                integrations = [{"type": "ephemeral_mcp", "server_url": mcp_url}]

            request = InferenceRequest(
                agent_id=self.character_id,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": task},
                ],
                model=self.model,
                max_output_tokens=max_tokens,
                integrations=integrations,
                store=store,
                priority=4,
                metadata={"type": "scene_agent_task", "scene": self.scene_id},
            )
            response = mgr.infer(request)
            result = (response.content or "").strip()

            # ActivityBus: make utility calls visible in admin panel
            try:
                from engine.services.activity_bus import get_activity_bus
                get_activity_bus().publish(
                    activity_type="scene_agent_task",
                    description=f"SceneAgent task: {task[:80]}",
                    agent_id=self.character_id,
                    scene=self.scene_id,
                    data={"task_preview": task[:200], "result_preview": result[:200]},
                )
            except Exception:
                pass

            return result

        except Exception as exc:
            logger.error("SceneAgent.run failed: %s", exc)
            return ""

    def run_structured(
        self,
        task: str,
        schema: Dict[str, Any],
        *,
        schema_name: str = "output",
        max_tokens: int  = 512,
    ) -> Optional[Dict]:
        """
        Run a one-shot task with JSON schema enforcement.

        LMStudio v1 ``response_format.json_schema`` guarantees the response
        matches the provided schema. Uses ``store=False`` (stateless).

        Args:
            task:        Instruction / prompt.
            schema:      JSON Schema dict for the response format.
            schema_name: Name for the schema (for LMStudio).
            max_tokens:  Soft token cap.

        Returns:
            Parsed JSON dict, or None on failure.
        """
        try:
            from engine.agents.virtual_agent_manager import get_virtual_agent_manager
            from engine.agents.virtual_agent import InferenceRequest
            mgr = get_virtual_agent_manager()

            request = InferenceRequest(
                agent_id=self.character_id,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": task},
                ],
                model=self.model,
                max_output_tokens=max_tokens,
                store=False,
                structured_schema=schema,
                schema_name=schema_name,
                priority=4,
                metadata={"type": "scene_agent_structured", "scene": self.scene_id},
            )
            response = mgr.infer(request)
            raw = (response.content or "").strip()
            return json.loads(raw) if raw else None
        except json.JSONDecodeError as exc:
            logger.warning("SceneAgent structured parse failed: %s", exc)
            return None
        except Exception as exc:
            logger.error("SceneAgent.run_structured failed: %s", exc)
            return None

    def run_stream(
        self,
        task: str,
        *,
        max_tokens: int = 512,
        on_delta=None,
        on_tool_call=None,
        on_mood=None,
    ) -> "ProcessedResponse":
        """
        Run a one-shot task with streaming via StreamProcessor.

        Uses ``store=False`` (stateless). Returns a rich ProcessedResponse.

        Args:
            task:         Instruction / prompt.
            max_tokens:   Soft token cap.
            on_delta:     Callback for each content delta (for UI streaming).
            on_tool_call: Callback when a tool call completes.
            on_mood:      Callback when a mood tag is detected.

        Returns:
            ProcessedResponse with full metadata.
        """
        try:
            from engine.agents.virtual_agent_manager import get_virtual_agent_manager
            from engine.agents.virtual_agent import InferenceRequest
            mgr = get_virtual_agent_manager()

            request = InferenceRequest(
                agent_id=self.character_id,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": task},
                ],
                model=self.model,
                max_output_tokens=max_tokens,
                store=False,
                stream=True,
                priority=4,
                metadata={"type": "scene_agent_stream", "scene": self.scene_id},
            )
            return mgr.infer_processed(
                request,
                on_delta=on_delta,
                on_tool_call=on_tool_call,
                on_mood=on_mood,
            )
        except Exception as exc:
            logger.error("SceneAgent.run_stream failed: %s", exc)
            from engine.agents.stream_processor import ProcessedResponse
            return ProcessedResponse()

    # ────────────────────────────────── convenience helpers ──────────

    def generate_title(self, content: str, max_words: int = 6) -> str:
        """Generate a short descriptive title for media content."""
        task = (
            f"Write a title of {max_words} words or fewer for this message transcript. "
            f"Reply with only the title, no quotes or punctuation:\n\n{content[:600]}"
        )
        return self.run(task, max_tokens=40)

    def summarize(self, text: str, max_sentences: int = 3) -> str:
        """Summarize *text* into at most *max_sentences* sentences."""
        task = (
            f"Summarise the following text in {max_sentences} sentences or fewer. "
            f"Be concise and factual:\n\n{text[:2000]}"
        )
        return self.run(task, max_tokens=200)

    def classify(self, text: str, labels: List[str]) -> str:
        """Classify *text* into one of the provided *labels*."""
        labels_str = ", ".join(f'"{lb}"' for lb in labels)
        task = (
            f"Classify the following text into exactly one of these categories: {labels_str}. "
            f"Reply with only the category name:\n\n{text[:800]}"
        )
        result = self.run(task, max_tokens=20)
        result_lower = result.lower()
        for lb in labels:
            if lb.lower() in result_lower:
                return lb
        return result

    def decide(
        self,
        situation: str,
        options: List[str],
        criteria: str = "",
    ) -> Optional[Dict]:
        """
        Make a game/narrative decision using structured output.

        Returns dict with 'choice' (index), 'option' (text), 'reasoning'.
        """
        opts_str = "\n".join(f"{i+1}. {o}" for i, o in enumerate(options))
        task = (
            f"Situation: {situation}\n\nOptions:\n{opts_str}\n\n"
            f"{'Criteria: ' + criteria + chr(10) if criteria else ''}"
            f"Pick the best option."
        )
        schema = {
            "type": "object",
            "properties": {
                "choice": {"type": "integer", "description": "1-based option index"},
                "option": {"type": "string", "description": "The chosen option text"},
                "reasoning": {"type": "string", "description": "Brief reasoning"},
            },
            "required": ["choice", "option", "reasoning"],
        }
        return self.run_structured(task, schema, schema_name="decision")


# ──────────────────────────────────────────────────── singleton ──

_scene_agent_instance: Optional[SceneAgent] = None


def get_scene_agent(model: Optional[str] = None) -> SceneAgent:
    """
    Return the global ``SceneAgent`` singleton.

    A new instance is created if the requested model differs from the
    current singleton's model.
    """
    global _scene_agent_instance
    if _scene_agent_instance is None or (_scene_agent_instance.model != model and model):
        _scene_agent_instance = SceneAgent(model=model)
    return _scene_agent_instance
