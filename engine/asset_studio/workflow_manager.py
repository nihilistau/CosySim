"""ComfyUI Workflow Manager — thread-safe singleton for submitting and polling jobs.

Provides the WorkflowManager class that handles all ComfyUI API interaction:
node discovery, model enumeration, workflow queuing, completion polling,
and output collection.  All methods return gracefully when ComfyUI is offline.
"""
from __future__ import annotations

import base64
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Node cache TTL in seconds.
_NODE_CACHE_TTL = 300.0

# ──── Model priority lists ─────────────────────────────────────────────────────

_VIDEO_T2V_MODELS: List[str] = [
    "wan22EnhancedNSFWSVICamera_nsfwFASTMOVEV2Q4KMH.gguf",
    "wan22EnhancedNSFWSVICamera_nsfwFASTMOVEV2Q4KML.gguf",
    "wan2.2_t2v_high_noise_14B_Q4_K_M.gguf",
    "smoothMixWan22I2VT2V_t2vHighV20_Q4_K_M.gguf",
]

_VIDEO_I2V_MODELS: List[str] = [
    "wan22EnhancedNSFWSVICamera_nsfwFASTMOVEV2Q4KMH.gguf",
    "wan22EnhancedNSFWSVICamera_nsfwFASTMOVEV2Q4KML.gguf",
    "smoothMixWan22I2VV20_highQ4KM.gguf",
    "wan2.1-i2v-14b-480p-Q4_0.gguf",
]

_VIDEO_CLIP_MODELS: List[str] = [
    "nsfwWanUMT5XXLGGUF_q5AndQ4KM.gguf",
    "umt5-xxl-encoder-Q8_0.gguf",
]

_VIDEO_VAE: List[str] = [
    "wan_2.1_vae.safetensors",
    "wan2.2_vae.safetensors",
    "Wan2_1_VAE_fp32.safetensors",
]

_VIDEO_TEXT_ENCODER: List[str] = [
    "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    "umt5-xxl-encoder-Q8_0.gguf",
]

_SDXL_SPEED_LORAS: List[str] = [
    "dmd2_sdxl_4step_lora_fp16.safetensors",
    "dmd2_sdxl_4step_lora.safetensors",
]

_WAN_T2V_SPEED_LORAS: List[str] = [
    "wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors",
    "lightx2v_T2V_14B_cfg_step_distill_v2_lora_rank128_bf16.safetensors",
]

_manager_instance: Optional["WorkflowManager"] = None
_manager_lock = threading.Lock()


class WorkflowManager:
    """Thread-safe manager for ComfyUI workflow submission and result collection.

    Caches node/model lists from ComfyUI's /object_info endpoint and provides
    a high-level generate() method that handles the full queue → poll → download
    lifecycle.
    """

    def __init__(self, base_url: str = "") -> None:
        """Initialise the WorkflowManager.

        Args:
            base_url: Base URL of the ComfyUI server. Resolved from port
                registry if empty.
        """
        if not base_url:
            try:
                from engine.port_registry import get_service_url
                base_url = get_service_url("comfyui")
            except Exception:
                base_url = "http://localhost:8188"
        self._base_url = base_url.rstrip("/")
        self._lock = threading.Lock()
        self._node_cache: Dict[str, Any] = {}
        self._node_cache_ts: float = 0.0
        self._client_id = "cosysim_studio"

    # ──── Availability ─────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return True if ComfyUI is reachable.

        Returns:
            bool: True when the /system_stats endpoint responds with HTTP 200.
        """
        try:
            import requests  # noqa: PLC0415
            resp = requests.get(f"{self._base_url}/system_stats", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    # ──── Node / model discovery ───────────────────────────────────────────────

    def get_available_nodes(self) -> Dict[str, Any]:
        """Return the cached object_info dict from ComfyUI.

        Results are cached for _NODE_CACHE_TTL seconds.  Returns an empty
        dict if ComfyUI is unreachable.

        Returns:
            Dict mapping node class_type names to their metadata.
        """
        with self._lock:
            now = time.monotonic()
            if self._node_cache and (now - self._node_cache_ts) < _NODE_CACHE_TTL:
                return self._node_cache
        try:
            import requests  # noqa: PLC0415
            resp = requests.get(f"{self._base_url}/object_info", timeout=10)
            resp.raise_for_status()
            data: Dict[str, Any] = resp.json()
            with self._lock:
                self._node_cache = data
                self._node_cache_ts = time.monotonic()
            return data
        except Exception as exc:
            logger.debug("Could not fetch ComfyUI object_info: %s", exc)
            return {}

    def has_node(self, class_type: str) -> bool:
        """Return True if class_type is available in the connected ComfyUI.

        Args:
            class_type: ComfyUI node class name (e.g. ``"FaceDetailer"``).

        Returns:
            bool: True when the node is registered in object_info.
        """
        return class_type in self.get_available_nodes()

    def get_models(self, category: str = "checkpoints") -> List[str]:
        """Return a list of model filenames for the given category.

        Args:
            category: One of ``"checkpoints"``, ``"loras"``, ``"vae"``,
                ``"upscale_models"``, ``"controlnet"``.

        Returns:
            List of filenames, empty list if ComfyUI is offline.
        """
        nodes = self.get_available_nodes()
        if not nodes:
            return []

        # Map category aliases to the canonical node/input used by ComfyUI.
        _category_map: Dict[str, tuple[str, str]] = {
            "checkpoints": ("CheckpointLoaderSimple", "ckpt_name"),
            "loras": ("LoraLoader", "lora_name"),
            "vae": ("VAELoader", "vae_name"),
            "upscale_models": ("UpscaleModelLoader", "model_name"),
            "controlnet": ("ControlNetLoader", "control_net_name"),
            "unet": ("UnetLoaderGGUF", "unet_name"),
            "clip_gguf": ("CLIPLoaderGGUF", "clip_name"),
            "text_encoders": ("WanVideoTextEncodeCached", "model_name"),
        }
        if category not in _category_map:
            return []

        node_name, input_key = _category_map[category]
        try:
            node_info = nodes.get(node_name, {})
            input_def = node_info.get("input", {}).get("required", {}).get(input_key, [])
            if isinstance(input_def, list) and input_def:
                options = input_def[0]
                if isinstance(options, list):
                    return options
        except Exception as exc:
            logger.debug("Could not parse model list for %s: %s", category, exc)
        return []

    def select_model(self, priority_list: List[str], category: str = "checkpoints") -> Optional[str]:
        """Return the first model from priority_list that exists in ComfyUI.

        Args:
            priority_list: Ordered list of model filenames to try.
            category: Model category to search (``"checkpoints"``, ``"unet"``,
                ``"vae"``, ``"loras"``, ``"text_encoders"``, etc.).

        Returns:
            First matching filename, or None if none are available.
        """
        available = set(self.get_models(category))
        if not available:
            return None
        for candidate in priority_list:
            if candidate in available:
                return candidate
        return None

    # ──── Workflow listing ─────────────────────────────────────────────────────

    def list_workflows(self) -> List[Dict[str, Any]]:
        """Return metadata for all registered workflows.

        Returns:
            List of dicts with keys: id, label, description, category,
            resolution, speed, requires_nodes, available.
        """
        from engine.asset_studio.workflow_builder import WORKFLOW_REGISTRY  # noqa: PLC0415
        result = []
        for wf_id, meta in WORKFLOW_REGISTRY.items():
            required = meta.get("requires_nodes", [])
            available = all(self.has_node(n) for n in required) if self.is_available() else True
            result.append({
                "id": wf_id,
                "label": meta["label"],
                "description": meta["description"],
                "category": meta["category"],
                "resolution": meta["resolution"],
                "speed": meta["speed"],
                "requires_nodes": required,
                "available": available,
            })
        return result

    def get_workflow_params(self, workflow_id: str) -> Dict[str, Any]:
        """Return the params metadata dict for a registered workflow.

        Args:
            workflow_id: Key from WORKFLOW_REGISTRY.

        Returns:
            Dict mapping parameter names to {type, default} dicts.

        Raises:
            KeyError: If workflow_id is not in WORKFLOW_REGISTRY.
        """
        from engine.asset_studio.workflow_builder import WORKFLOW_REGISTRY  # noqa: PLC0415
        return WORKFLOW_REGISTRY[workflow_id].get("params", {})

    # ──── Core submission pipeline ─────────────────────────────────────────────

    def build(self, workflow_id: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Build a ComfyUI prompt dict for the given workflow.

        Args:
            workflow_id: Key from WORKFLOW_REGISTRY (e.g. ``"portrait_hires"``).
            params: Override parameters passed as kwargs to the builder function.

        Returns:
            ComfyUI API-format prompt dict.

        Raises:
            KeyError: If workflow_id is not in WORKFLOW_REGISTRY.
        """
        from engine.asset_studio.workflow_builder import WORKFLOW_REGISTRY  # noqa: PLC0415
        meta = WORKFLOW_REGISTRY[workflow_id]
        builder_fn = meta["builder"]
        return builder_fn(**(params or {}))

    def queue(self, workflow_dict: Dict[str, Any]) -> Optional[str]:
        """POST a workflow to ComfyUI /prompt and return the prompt_id.

        Args:
            workflow_dict: ComfyUI API-format prompt dict.

        Returns:
            prompt_id string, or None on failure.
        """
        try:
            import requests  # noqa: PLC0415
            payload = {"prompt": workflow_dict, "client_id": self._client_id}
            resp = requests.post(f"{self._base_url}/prompt", json=payload, timeout=30)
            resp.raise_for_status()
            return resp.json().get("prompt_id")
        except Exception as exc:
            logger.warning("Failed to queue ComfyUI workflow: %s", exc)
            return None

    def wait_for_completion(
        self,
        prompt_id: str,
        timeout: float = 300.0,
        poll_interval: float = 2.0,
    ) -> Optional[Dict[str, Any]]:
        """Poll /history/{prompt_id} until outputs appear or timeout.

        Args:
            prompt_id: ComfyUI prompt ID returned by queue().
            timeout: Maximum seconds to wait.
            poll_interval: Seconds between polls.

        Returns:
            The outputs dict from the history entry, or None on timeout/error.
        """
        try:
            import requests  # noqa: PLC0415
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    resp = requests.get(
                        f"{self._base_url}/history/{prompt_id}", timeout=10
                    )
                    if resp.status_code == 200:
                        hist = resp.json()
                        if prompt_id in hist:
                            entry = hist[prompt_id]
                            outputs = entry.get("outputs", {})
                            if outputs:
                                return outputs
                except Exception as poll_exc:
                    logger.debug("Poll error for %s: %s", prompt_id, poll_exc)
                time.sleep(poll_interval)
            logger.warning("Timeout waiting for ComfyUI job %s", prompt_id)
            return None
        except Exception as exc:
            logger.warning("wait_for_completion error: %s", exc)
            return None

    def collect_outputs(
        self,
        outputs: Dict[str, Any],
        save_dir: Optional[Path] = None,
        filename_prefix: str = "output",
    ) -> List[str]:
        """Download output images/videos from ComfyUI and return local paths or URLs.

        Args:
            outputs: Outputs dict from wait_for_completion().
            save_dir: Directory to save downloaded files.  When None, returns
                ComfyUI view URLs directly.
            filename_prefix: Prefix for saved filenames.

        Returns:
            List of file paths (if save_dir given) or ComfyUI view URLs.
        """
        collected: List[str] = []
        try:
            import requests  # noqa: PLC0415
            for _node_id, node_out in outputs.items():
                for media_key in ("images", "gifs", "videos"):
                    for item in node_out.get(media_key, []):
                        fname = item.get("filename", "")
                        subfolder = item.get("subfolder", "")
                        ftype = item.get("type", "output")
                        view_url = (
                            f"{self._base_url}/view"
                            f"?filename={fname}&subfolder={subfolder}&type={ftype}"
                        )
                        if save_dir is not None:
                            try:
                                r = requests.get(view_url, timeout=60)
                                r.raise_for_status()
                                ext = Path(fname).suffix or ".png"
                                local_name = f"{filename_prefix}_{uuid.uuid4().hex[:8]}{ext}"
                                local_path = save_dir / local_name
                                local_path.write_bytes(r.content)
                                collected.append(str(local_path))
                            except Exception as dl_exc:
                                logger.warning("Download failed for %s: %s", fname, dl_exc)
                                collected.append(view_url)
                        else:
                            collected.append(view_url)
        except Exception as exc:
            logger.warning("collect_outputs error: %s", exc)
        return collected

    def check_image_quality(
        self,
        image_path: str,
        prompt_context: str = "",
        model: str = "qwen3-vl",
    ) -> Dict[str, Any]:
        """Run Qwen3 VL quality check on a generated image via LMStudio.

        Encodes the image to base64, sends to the currently loaded vision model,
        and returns a structured quality assessment. Returns gracefully when
        LMStudio is offline or no vision model is loaded.

        Args:
            image_path: Absolute or relative path to the image file.
            prompt_context: Optional generation prompt for context in the check.
            model: LMStudio model identifier to use for the check.

        Returns:
            Dict with keys: score (0-10 float), issues (list[str]),
            strengths (list[str]), suggestion (str), raw (str).
            On failure: {"score": -1, "error": str}.
        """
        try:
            path = Path(image_path)
            if not path.exists():
                return {"score": -1, "error": f"Image not found: {image_path}"}
            img_bytes = path.read_bytes()
            ext = path.suffix.lower().lstrip(".")
            mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
            b64 = base64.b64encode(img_bytes).decode()
            data_url = f"data:{mime};base64,{b64}"

            import requests  # noqa: PLC0415
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": data_url},
                            },
                            {
                                "type": "text",
                                "text": (
                                    "You are an AI image quality inspector. "
                                    "Evaluate this generated image professionally.\n"
                                    + (f"Generation prompt: {prompt_context}\n" if prompt_context else "")
                                    + "Respond in JSON: {\"score\": 0-10, \"issues\": [], \"strengths\": [], \"suggestion\": \"\"}"
                                ),
                            },
                        ],
                    }
                ],
                "max_tokens": 300,
                "temperature": 0.1,
            }
            resp = requests.post(
                "http://localhost:1234/v1/chat/completions",
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            # Parse JSON from the response
            import json as _json  # noqa: PLC0415
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = _json.loads(raw[start:end])
                parsed["raw"] = raw
                return parsed
            return {"score": -1, "error": "No JSON in response", "raw": raw}
        except Exception as exc:
            logger.warning("Image QC failed: %s", exc)
            return {"score": -1, "error": str(exc)}

    # ──── High-level end-to-end method ────────────────────────────────────────

    def generate(
        self,
        workflow_id: str,
        params: Optional[Dict[str, Any]] = None,
        save_dir: Optional[Path] = None,
        filename_prefix: str = "output",
        timeout: float = 300.0,
    ) -> Dict[str, Any]:
        """Build, queue, wait, and collect outputs for a workflow.

        Args:
            workflow_id: Key from WORKFLOW_REGISTRY.
            params: Override parameters for the builder function.
            save_dir: Directory to save output files.
            filename_prefix: Prefix for output filenames.
            timeout: Maximum seconds to wait for ComfyUI completion.

        Returns:
            Dict with keys: ``url`` (first output), ``urls`` (all outputs),
            ``duration_ms``, and optionally ``error``.
        """
        t_start = time.monotonic()
        if not self.is_available():
            return {
                "error": "ComfyUI is not available",
                "url": "",
                "urls": [],
                "duration_ms": 0,
            }
        try:
            workflow_dict = self.build(workflow_id, params)
        except Exception as exc:
            logger.warning("Workflow build error for %s: %s", workflow_id, exc)
            return {
                "error": f"Build failed: {exc}",
                "url": "",
                "urls": [],
                "duration_ms": int((time.monotonic() - t_start) * 1000),
            }

        prompt_id = self.queue(workflow_dict)
        if not prompt_id:
            return {
                "error": "Failed to queue workflow",
                "url": "",
                "urls": [],
                "duration_ms": int((time.monotonic() - t_start) * 1000),
            }

        outputs = self.wait_for_completion(prompt_id, timeout=timeout)
        if outputs is None:
            return {
                "error": f"Timeout waiting for job {prompt_id}",
                "url": "",
                "urls": [],
                "duration_ms": int((time.monotonic() - t_start) * 1000),
                "prompt_id": prompt_id,
            }

        paths = self.collect_outputs(outputs, save_dir=save_dir, filename_prefix=filename_prefix)
        duration_ms = int((time.monotonic() - t_start) * 1000)

        if not paths:
            return {
                "error": "No outputs collected",
                "url": "",
                "urls": [],
                "duration_ms": duration_ms,
                "prompt_id": prompt_id,
            }

        # Normalise local paths to web-accessible URLs if possible.
        first = paths[0]
        url = first if first.startswith("http") else f"/asset_studio/output/{Path(first).name}"

        return {
            "url": url,
            "urls": [
                p if p.startswith("http") else f"/asset_studio/output/{Path(p).name}"
                for p in paths
            ],
            "local_paths": paths,
            "duration_ms": duration_ms,
            "prompt_id": prompt_id,
            "workflow_id": workflow_id,
        }


# ──── Singleton factory ────────────────────────────────────────────────────────

def get_workflow_manager() -> WorkflowManager:
    """Return the process-wide WorkflowManager singleton.

    Reads ``art.comfyui_url`` from config on first call.

    Returns:
        The shared WorkflowManager instance.
    """
    global _manager_instance
    if _manager_instance is not None:
        return _manager_instance
    with _manager_lock:
        if _manager_instance is not None:
            return _manager_instance
        try:
            from engine.port_registry import get_service_url  # noqa: PLC0415
            base_url = get_service_url("comfyui")
        except Exception:
            try:
                from engine.config import get_config  # noqa: PLC0415
                base_url = get_config().get("art.comfyui_url", "http://localhost:8188")
            except Exception:
                base_url = "http://localhost:8188"
        _manager_instance = WorkflowManager(base_url=base_url)
    return _manager_instance
