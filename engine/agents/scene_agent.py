"""
SceneAgent — Lightweight one-shot task agent

Used for utility LLM calls that don't need the full character persona:
- Generating a title for a video/voice message
- Summarizing a conversation
- Routing / classification

``SceneAgent`` is intentionally stateless: each ``run()`` call is independent.
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


class SceneAgent:
    """
    Minimal LMStudio agent for one-shot utility tasks.

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
    ) -> str:
        """
        Run a one-shot task via VirtualAgentManager and return the LLM output.

        Uses the centralised inference router for consistent model control.

        Args:
            task:       Instruction / prompt for the task.
            tools:      Ignored — expose tools via CosySim MCP server instead.
            max_tokens: Soft token cap for the response.

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

    # ────────────────────────────────── convenience helpers ──────────

    def generate_title(self, content: str, max_words: int = 6) -> str:
        """
        Generate a short descriptive title for media content.

        Args:
            content:   Text / transcript to summarise as a title.
            max_words: Approximate max title length in words.

        Returns:
            Title string (may be empty on LLM failure).
        """
        task = (
            f"Write a title of {max_words} words or fewer for this message transcript. "
            f"Reply with only the title, no quotes or punctuation:\n\n{content[:600]}"
        )
        return self.run(task, max_tokens=40)

    def summarize(self, text: str, max_sentences: int = 3) -> str:
        """
        Summarize *text* into at most *max_sentences* sentences.

        Args:
            text:          The text to summarize.
            max_sentences: Target summary length.

        Returns:
            Summary string.
        """
        task = (
            f"Summarise the following text in {max_sentences} sentences or fewer. "
            f"Be concise and factual:\n\n{text[:2000]}"
        )
        return self.run(task, max_tokens=200)

    def classify(self, text: str, labels: List[str]) -> str:
        """
        Classify *text* into one of the provided *labels*.

        Args:
            text:   The text to classify.
            labels: Possible category labels.

        Returns:
            The best-matching label string, or empty string on failure.
        """
        labels_str = ", ".join(f'"{lb}"' for lb in labels)
        task = (
            f"Classify the following text into exactly one of these categories: {labels_str}. "
            f"Reply with only the category name:\n\n{text[:800]}"
        )
        result = self.run(task, max_tokens=20)
        # Normalise to closest label
        result_lower = result.lower()
        for lb in labels:
            if lb.lower() in result_lower:
                return lb
        return result  # Return raw if no match


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
