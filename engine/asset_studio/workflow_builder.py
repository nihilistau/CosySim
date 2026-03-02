"""ComfyUI Workflow Builder — dynamic workflow construction for Asset Studio.

Builds ComfyUI API-format prompt dicts for 11 professional workflow types.
All builders expose every configurable parameter and use helper chains for
LoRA stacking. Video builders use the correct Wan 2.2 dual-model architecture
(UnetLoaderGGUF + KSamplerAdvanced two-stage pipeline).
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

# ──── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_IMAGE_MODEL: str = "gonzalomoXLFluxPony_v60PhotoXLDMD.safetensors"
_DEFAULT_UNET_HIGH: str = "wan22EnhancedNSFWSVICamera_nsfwFASTMOVEV2Q4KMH.gguf"
_DEFAULT_UNET_LOW: str = "wan22EnhancedNSFWSVICamera_nsfwFASTMOVEV2Q4KML.gguf"
_DEFAULT_CLIP_MODEL: str = "nsfwWanUMT5XXLGGUF_q5AndQ4KM.gguf"
_DEFAULT_VAE_WAN: str = "wan_2.1_vae.safetensors"
_DEFAULT_LORAS_HIGH: List[Dict[str, Any]] = [
    {
        "name": "lightx2v_I2V_14B_480p_cfg_step_distill_rank128_bf16.safetensors",
        "strength_model": 3.0,
        "enabled": True,
    }
]
_DEFAULT_LORAS_LOW: List[Dict[str, Any]] = [
    {
        "name": "SVI_Wan2.2-I2V-A14B_lora_LOW_v2.0_rank_128_fp16.safetensors",
        "strength_model": 1.5,
        "enabled": True,
    }
]
_DEFAULT_SAMPLER: str = "lcm"
_DEFAULT_SCHEDULER: str = "exponential"
_DEFAULT_CFG: float = 1.5
_DEFAULT_STEPS: int = 20
# Pony SDXL tuned negative — matches generate_Image.json
_DEFAULT_NEGATIVE: str = (
    "ugly, deformed, blurry, bad anatomy, worst quality, low quality, "
    "watermark, text, signature, censored, jpeg artifacts, mutation"
)


# ──── Seed helper ──────────────────────────────────────────────────────────────


def _seed(s: int) -> int:
    """Return s if >= 0 else a random uint32.

    Args:
        s: Input seed value.

    Returns:
        s when s >= 0, otherwise a random integer in [0, 2^32 - 1].
    """
    return s if s >= 0 else random.randint(0, 2 ** 32 - 1)


# ──── LoRA chain helpers ───────────────────────────────────────────────────────


def _build_lora_chain(
    loras: List[Dict[str, Any]],
    model_ref: List,
    clip_ref: List,
    start_id: int = 20,
) -> Tuple[Dict[str, Any], List, List]:
    """Build LoraLoader chain for image models (updates both model and CLIP).

    Args:
        loras: List of LoRA dicts with keys name, strength_model, strength_clip,
            and enabled (optional, defaults True).
        model_ref: Starting model node reference [node_id, output_index].
        clip_ref: Starting CLIP node reference [node_id, output_index].
        start_id: First integer node ID to assign.

    Returns:
        Tuple of (nodes_dict, final_model_ref, final_clip_ref).
    """
    nodes: Dict[str, Any] = {}
    cur_model: List = list(model_ref)
    cur_clip: List = list(clip_ref)
    nid = start_id
    for lora in loras:
        if not lora.get("enabled", True):
            continue
        node_id = str(nid)
        nodes[node_id] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": cur_model,
                "clip": cur_clip,
                "lora_name": lora["name"],
                "strength_model": lora.get("strength_model", 1.0),
                "strength_clip": lora.get("strength_clip", 1.0),
            },
        }
        cur_model = [node_id, 0]
        cur_clip = [node_id, 1]
        nid += 1
    return nodes, cur_model, cur_clip


def _build_video_lora_chain(
    loras: List[Dict[str, Any]],
    model_ref: List,
    start_id: int = 20,
) -> Tuple[Dict[str, Any], List]:
    """Build LoraLoaderModelOnly chain for video models (model only, no CLIP).

    Args:
        loras: List of LoRA dicts with keys name, strength_model, and enabled
            (optional, defaults True).
        model_ref: Starting model node reference [node_id, output_index].
        start_id: First integer node ID to assign.

    Returns:
        Tuple of (nodes_dict, final_model_ref).
    """
    nodes: Dict[str, Any] = {}
    cur_model: List = list(model_ref)
    nid = start_id
    for lora in loras:
        if not lora.get("enabled", True):
            continue
        node_id = str(nid)
        nodes[node_id] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": cur_model,
                "lora_name": lora["name"],
                "strength_model": lora.get("strength_model", 1.0),
            },
        }
        cur_model = [node_id, 0]
        nid += 1
    return nodes, cur_model


# ──── Internal image workflow helper ──────────────────────────────────────────


def _build_image_workflow(
    positive: str,
    negative: str,
    seed: int,
    model: str,
    vae: Optional[str],
    steps: int,
    cfg: float,
    width: int,
    height: int,
    batch_size: int,
    sampler_name: str,
    scheduler: str,
    denoise: float,
    loras: Optional[List[Dict[str, Any]]],
    filename_prefix: str,
    rmbg: bool = False,
    face_detailer_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble a standard image-generation workflow dict.

    Node layout:
        "1"        CheckpointLoaderSimple
        "2"        VAELoader (only when vae is explicitly set)
        "20"–"29"  LoRA chain (LoraLoader, if loras provided)
        "50"       CLIPTextEncode (positive)
        "51"       CLIPTextEncode (negative)
        "55"       EmptyLatentImage
        "60"       KSampler
        "65"       VAEDecode
        "70"       SaveImage
        "71"       UltralyticsDetectorProvider (portrait_hires only)
        "72"       FaceDetailer (portrait_hires only)
        "75"       RMBG (item/ui icons only)

    Args:
        positive: Positive prompt text.
        negative: Negative prompt text.
        seed: RNG seed (-1 for random).
        model: Checkpoint filename.
        vae: Explicit VAE filename; if None, uses checkpoint output ["1", 2].
        steps: KSampler steps.
        cfg: Guidance scale.
        width: Image width.
        height: Image height.
        batch_size: Batch size.
        sampler_name: KSampler sampler name.
        scheduler: KSampler scheduler.
        denoise: Denoising strength.
        loras: LoRA list, each with name/strength_model/strength_clip/enabled.
        filename_prefix: Prefix string for SaveImage node.
        rmbg: Insert RMBG background-removal node before SaveImage.
        face_detailer_params: Dict with detect_model/face_steps/face_cfg/
            face_denoise; enables FaceDetailer pass when set.

    Returns:
        ComfyUI API-format workflow dict.
    """
    s = _seed(seed)
    nodes: Dict[str, Any] = {}

    # Loaders
    nodes["1"] = {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": model}}
    if vae:
        nodes["2"] = {"class_type": "VAELoader", "inputs": {"vae_name": vae}}
        vae_ref: List = ["2", 0]
    else:
        vae_ref = ["1", 2]

    # LoRA chain (nodes 20–29)
    model_ref: List = ["1", 0]
    clip_ref: List = ["1", 1]
    if loras:
        lora_nodes, model_ref, clip_ref = _build_lora_chain(
            loras, model_ref, clip_ref, start_id=20
        )
        nodes.update(lora_nodes)

    # Main pipeline (nodes 50–70)
    nodes["50"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": clip_ref, "text": positive}}
    nodes["51"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": clip_ref, "text": negative}}
    nodes["55"] = {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": width, "height": height, "batch_size": batch_size},
    }
    nodes["60"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": model_ref,
            "positive": ["50", 0],
            "negative": ["51", 0],
            "latent_image": ["55", 0],
            "seed": s,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": sampler_name,
            "scheduler": scheduler,
            "denoise": denoise,
        },
    }
    nodes["65"] = {"class_type": "VAEDecode", "inputs": {"samples": ["60", 0], "vae": vae_ref}}

    # Output stage
    decode_out: List = ["65", 0]
    if rmbg:
        nodes["75"] = {"class_type": "RMBG", "inputs": {"image": decode_out}}
        save_input: List = ["75", 0]
    elif face_detailer_params:
        fd = face_detailer_params
        nodes["71"] = {
            "class_type": "UltralyticsDetectorProvider",
            "inputs": {"model_name": fd.get("detect_model", "bbox/face_yolov8s.pt")},
        }
        nodes["72"] = {
            "class_type": "FaceDetailer",
            "inputs": {
                "image": decode_out,
                "model": model_ref,
                "clip": clip_ref,
                "vae": vae_ref,
                "positive": ["50", 0],
                "negative": ["51", 0],
                "bbox_detector": ["71", 0],
                "guide_size": 384,
                "guide_size_for": True,
                "max_size": 1024,
                "seed": s,
                "steps": fd.get("face_steps", 20),
                "cfg": fd.get("face_cfg", cfg),
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "denoise": fd.get("face_denoise", 0.45),
                "feather": 5,
                "noise_mask": True,
                "force_inpaint": True,
                "bbox_threshold": 0.5,
                "bbox_dilation": 10,
                "bbox_crop_factor": 3.0,
                "sam_detection_hint": "center-1",
                "sam_dilation": 0,
                "sam_threshold": 0.93,
                "sam_bbox_expansion": 0,
                "sam_mask_hint_threshold": 0.7,
                "sam_mask_hint_use_negative": "False",
                "wildcard": "",
                "cycle": 1,
                "inpaint_model": False,
                "noise_mask_feather": 20,
            },
        }
        save_input = ["72", 0]
    else:
        save_input = decode_out

    nodes["70"] = {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": filename_prefix, "images": save_input},
    }
    return nodes


# ──── Image builders ───────────────────────────────────────────────────────────


def build_portrait_hires(
    positive: str = "masterpiece, best quality, highly detailed portrait photograph",
    negative: str = _DEFAULT_NEGATIVE,
    seed: int = -1,
    model: str = _DEFAULT_IMAGE_MODEL,
    vae: Optional[str] = None,
    steps: int = 20,
    cfg: float = 1.5,
    width: int = 896,
    height: int = 1152,
    batch_size: int = 1,
    sampler_name: str = "lcm",
    scheduler: str = "exponential",
    denoise: float = 1.0,
    loras: Optional[List[Dict[str, Any]]] = None,
    face_detect_model: str = "bbox/face_yolov8s.pt",
    face_steps: int = 12,
    face_cfg: float = 1.0,
    face_denoise: float = 0.4,
) -> Dict[str, Any]:
    """Build portrait_hires workflow: SDXL + FaceDetailer refinement pass.

    Args:
        positive: Positive prompt text.
        negative: Negative prompt text.
        seed: RNG seed (-1 for random).
        model: Checkpoint filename.
        vae: Explicit VAE filename; None uses checkpoint's baked VAE.
        steps: KSampler steps.
        cfg: Guidance scale.
        width: Image width.
        height: Image height.
        batch_size: Images per batch.
        sampler_name: KSampler sampler name.
        scheduler: KSampler scheduler.
        denoise: Denoising strength.
        loras: Optional LoRA list (name/strength_model/strength_clip/enabled).
        face_detect_model: YOLO model path for UltralyticsDetectorProvider.
        face_steps: FaceDetailer KSampler steps.
        face_cfg: FaceDetailer guidance scale.
        face_denoise: FaceDetailer denoising strength.

    Returns:
        ComfyUI API-format workflow dict.
    """
    return _build_image_workflow(
        positive=positive,
        negative=negative,
        seed=seed,
        model=model,
        vae=vae,
        steps=steps,
        cfg=cfg,
        width=width,
        height=height,
        batch_size=batch_size,
        sampler_name=sampler_name,
        scheduler=scheduler,
        denoise=denoise,
        loras=loras,
        filename_prefix="portrait_hires",
        rmbg=False,
        face_detailer_params={
            "detect_model": face_detect_model,
            "face_steps": face_steps,
            "face_cfg": face_cfg,
            "face_denoise": face_denoise,
        },
    )


def build_portrait_fast(
    positive: str = "masterpiece, best quality, portrait photograph",
    negative: str = "ugly, deformed, blurry, low quality",
    seed: int = -1,
    model: str = _DEFAULT_IMAGE_MODEL,
    vae: Optional[str] = None,
    steps: int = 20,
    cfg: float = 1.5,
    width: int = 896,
    height: int = 1152,
    batch_size: int = 1,
    sampler_name: str = "lcm",
    scheduler: str = "exponential",
    denoise: float = 1.0,
    loras: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build portrait_fast workflow using Lightning 8-step LoRA.

    Args:
        positive: Positive prompt text.
        negative: Negative prompt text.
        seed: RNG seed (-1 for random).
        model: Checkpoint filename.
        vae: Explicit VAE filename; None uses checkpoint's baked VAE.
        steps: KSampler steps.
        cfg: Guidance scale.
        width: Image width.
        height: Image height.
        batch_size: Images per batch.
        sampler_name: KSampler sampler name.
        scheduler: KSampler scheduler.
        denoise: Denoising strength.
        loras: Optional LoRA list; defaults to sdxl_lightning_8step.

    Returns:
        ComfyUI API-format workflow dict.
    """
    effective_loras = loras if loras is not None else [
        {
            "name": "sdxl_lightning_8step_lora.safetensors",
            "strength_model": 1.0,
            "strength_clip": 1.0,
            "enabled": True,
        }
    ]
    return _build_image_workflow(
        positive=positive,
        negative=negative,
        seed=seed,
        model=model,
        vae=vae,
        steps=steps,
        cfg=cfg,
        width=width,
        height=height,
        batch_size=batch_size,
        sampler_name=sampler_name,
        scheduler=scheduler,
        denoise=denoise,
        loras=effective_loras,
        filename_prefix="portrait_fast",
    )


def build_character_card(
    positive: str = "masterpiece, full body portrait, cinematic lighting, detailed",
    negative: str = "ugly, deformed, blurry, cropped, worst quality",
    seed: int = -1,
    model: str = _DEFAULT_IMAGE_MODEL,
    vae: Optional[str] = None,
    steps: int = 20,
    cfg: float = 1.5,
    width: int = 832,
    height: int = 1216,
    batch_size: int = 1,
    sampler_name: str = "lcm",
    scheduler: str = "exponential",
    denoise: float = 1.0,
    loras: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build character_card workflow — full body cinematic portrait.

    Args:
        positive: Positive prompt text.
        negative: Negative prompt text.
        seed: RNG seed (-1 for random).
        model: Checkpoint filename.
        vae: Explicit VAE filename; None uses checkpoint's baked VAE.
        steps: KSampler steps.
        cfg: Guidance scale.
        width: Image width.
        height: Image height.
        batch_size: Images per batch.
        sampler_name: KSampler sampler name.
        scheduler: KSampler scheduler.
        denoise: Denoising strength.
        loras: Optional LoRA list.

    Returns:
        ComfyUI API-format workflow dict.
    """
    return _build_image_workflow(
        positive=positive,
        negative=negative,
        seed=seed,
        model=model,
        vae=vae,
        steps=steps,
        cfg=cfg,
        width=width,
        height=height,
        batch_size=batch_size,
        sampler_name=sampler_name,
        scheduler=scheduler,
        denoise=denoise,
        loras=loras,
        filename_prefix="character_card",
    )


def build_game_item_icon(
    positive: str = "game item icon, isolated on white background, detailed craftsmanship",
    negative: str = "ugly, deformed, blurry, background, people, text, watermark",
    seed: int = -1,
    model: str = _DEFAULT_IMAGE_MODEL,
    vae: Optional[str] = None,
    steps: int = 20,
    cfg: float = 1.5,
    width: int = 512,
    height: int = 512,
    batch_size: int = 1,
    sampler_name: str = "lcm",
    scheduler: str = "exponential",
    denoise: float = 1.0,
    loras: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build game_item_icon workflow with RMBG background removal.

    Args:
        positive: Positive prompt text.
        negative: Negative prompt text.
        seed: RNG seed (-1 for random).
        model: Checkpoint filename.
        vae: Explicit VAE filename; None uses checkpoint's baked VAE.
        steps: KSampler steps.
        cfg: Guidance scale.
        width: Image width.
        height: Image height.
        batch_size: Images per batch.
        sampler_name: KSampler sampler name.
        scheduler: KSampler scheduler.
        denoise: Denoising strength.
        loras: Optional LoRA list.

    Returns:
        ComfyUI API-format workflow dict.
    """
    return _build_image_workflow(
        positive=positive,
        negative=negative,
        seed=seed,
        model=model,
        vae=vae,
        steps=steps,
        cfg=cfg,
        width=width,
        height=height,
        batch_size=batch_size,
        sampler_name=sampler_name,
        scheduler=scheduler,
        denoise=denoise,
        loras=loras,
        filename_prefix="item_icon",
        rmbg=True,
    )


def build_scene_background(
    positive: str = "cinematic background, wide shot, detailed environment, atmospheric lighting",
    negative: str = "ugly, deformed, blurry, text, watermark, people",
    seed: int = -1,
    model: str = _DEFAULT_IMAGE_MODEL,
    vae: Optional[str] = None,
    steps: int = 20,
    cfg: float = 1.5,
    width: int = 1024,
    height: int = 576,
    batch_size: int = 1,
    sampler_name: str = "lcm",
    scheduler: str = "exponential",
    denoise: float = 1.0,
    loras: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build scene_background workflow — widescreen cinematic environment.

    Args:
        positive: Positive prompt text.
        negative: Negative prompt text.
        seed: RNG seed (-1 for random).
        model: Checkpoint filename.
        vae: Explicit VAE filename; None uses checkpoint's baked VAE.
        steps: KSampler steps.
        cfg: Guidance scale.
        width: Image width.
        height: Image height.
        batch_size: Images per batch.
        sampler_name: KSampler sampler name.
        scheduler: KSampler scheduler.
        denoise: Denoising strength.
        loras: Optional LoRA list.

    Returns:
        ComfyUI API-format workflow dict.
    """
    return _build_image_workflow(
        positive=positive,
        negative=negative,
        seed=seed,
        model=model,
        vae=vae,
        steps=steps,
        cfg=cfg,
        width=width,
        height=height,
        batch_size=batch_size,
        sampler_name=sampler_name,
        scheduler=scheduler,
        denoise=denoise,
        loras=loras,
        filename_prefix="scene_bg",
    )


def build_action_card(
    positive: str = "dramatic cinematic scene, action, wide angle, storytelling, epic",
    negative: str = "ugly, deformed, blurry, text, watermark",
    seed: int = -1,
    model: str = _DEFAULT_IMAGE_MODEL,
    vae: Optional[str] = None,
    steps: int = 20,
    cfg: float = 1.5,
    width: int = 1216,
    height: int = 512,
    batch_size: int = 1,
    sampler_name: str = "lcm",
    scheduler: str = "exponential",
    denoise: float = 1.0,
    loras: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build action_card workflow — ultra-wide dramatic storytelling card.

    Args:
        positive: Positive prompt text.
        negative: Negative prompt text.
        seed: RNG seed (-1 for random).
        model: Checkpoint filename.
        vae: Explicit VAE filename; None uses checkpoint's baked VAE.
        steps: KSampler steps.
        cfg: Guidance scale.
        width: Image width.
        height: Image height.
        batch_size: Images per batch.
        sampler_name: KSampler sampler name.
        scheduler: KSampler scheduler.
        denoise: Denoising strength.
        loras: Optional LoRA list.

    Returns:
        ComfyUI API-format workflow dict.
    """
    return _build_image_workflow(
        positive=positive,
        negative=negative,
        seed=seed,
        model=model,
        vae=vae,
        steps=steps,
        cfg=cfg,
        width=width,
        height=height,
        batch_size=batch_size,
        sampler_name=sampler_name,
        scheduler=scheduler,
        denoise=denoise,
        loras=loras,
        filename_prefix="action_card",
    )


def build_ui_icon(
    positive: str = "clean UI icon, flat design, minimal, isolated element",
    negative: str = "ugly, deformed, blurry, photo, gradient, background noise",
    seed: int = -1,
    model: str = _DEFAULT_IMAGE_MODEL,
    vae: Optional[str] = None,
    steps: int = 20,
    cfg: float = 1.5,
    width: int = 512,
    height: int = 512,
    batch_size: int = 1,
    sampler_name: str = "lcm",
    scheduler: str = "exponential",
    denoise: float = 1.0,
    loras: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build ui_icon workflow with RMBG background removal.

    Args:
        positive: Positive prompt text.
        negative: Negative prompt text.
        seed: RNG seed (-1 for random).
        model: Checkpoint filename.
        vae: Explicit VAE filename; None uses checkpoint's baked VAE.
        steps: KSampler steps.
        cfg: Guidance scale.
        width: Image width.
        height: Image height.
        batch_size: Images per batch.
        sampler_name: KSampler sampler name.
        scheduler: KSampler scheduler.
        denoise: Denoising strength.
        loras: Optional LoRA list.

    Returns:
        ComfyUI API-format workflow dict.
    """
    return _build_image_workflow(
        positive=positive,
        negative=negative,
        seed=seed,
        model=model,
        vae=vae,
        steps=steps,
        cfg=cfg,
        width=width,
        height=height,
        batch_size=batch_size,
        sampler_name=sampler_name,
        scheduler=scheduler,
        denoise=denoise,
        loras=loras,
        filename_prefix="ui_icon",
        rmbg=True,
    )


def build_message_image(
    positive: str = "chat message image, vivid, detailed, cinematic",
    negative: str = "ugly, deformed, blurry, low quality",
    seed: int = -1,
    model: str = _DEFAULT_IMAGE_MODEL,
    vae: Optional[str] = None,
    steps: int = 8,
    cfg: float = 1.5,
    width: int = 768,
    height: int = 512,
    batch_size: int = 1,
    sampler_name: str = "lcm",
    scheduler: str = "exponential",
    denoise: float = 1.0,
    loras: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build message_image workflow using Lightning 8-step LoRA.

    Args:
        positive: Positive prompt text.
        negative: Negative prompt text.
        seed: RNG seed (-1 for random).
        model: Checkpoint filename.
        vae: Explicit VAE filename; None uses checkpoint's baked VAE.
        steps: KSampler steps.
        cfg: Guidance scale.
        width: Image width.
        height: Image height.
        batch_size: Images per batch.
        sampler_name: KSampler sampler name.
        scheduler: KSampler scheduler.
        denoise: Denoising strength.
        loras: Optional LoRA list; defaults to sdxl_lightning_8step.

    Returns:
        ComfyUI API-format workflow dict.
    """
    effective_loras = loras if loras is not None else [
        {
            "name": "sdxl_lightning_8step_lora.safetensors",
            "strength_model": 1.0,
            "strength_clip": 1.0,
            "enabled": True,
        }
    ]
    return _build_image_workflow(
        positive=positive,
        negative=negative,
        seed=seed,
        model=model,
        vae=vae,
        steps=steps,
        cfg=cfg,
        width=width,
        height=height,
        batch_size=batch_size,
        sampler_name=sampler_name,
        scheduler=scheduler,
        denoise=denoise,
        loras=effective_loras,
        filename_prefix="message_img",
    )


def build_upscale_enhance(
    positive: str = "masterpiece, highly detailed, sharp focus, high resolution, 8k",
    negative: str = "ugly, deformed, blurry, artifacts, noise, grain",
    seed: int = -1,
    model: str = _DEFAULT_IMAGE_MODEL,
    vae: str = "sdxl_vae.safetensors",
    image_path: str = "input.png",
    steps: int = 20,
    cfg: float = 6.0,
    upscale_model: str = "4x_NMKD-Superscale-SP_178000_G.pth",
    controlnet_name: str = "xinsircontrolnet-tile-sdxl-1.0.safetensors",
    target_width: int = 2048,
    target_height: int = 2048,
    denoise: float = 0.4,
    loras: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build upscale_enhance workflow — tile ControlNet + ESRGAN pixel upscale.

    Unique 14-node structure (img2img style, not EmptyLatentImage).

    Args:
        positive: Positive prompt text.
        negative: Negative prompt text.
        seed: RNG seed (-1 for random).
        model: Checkpoint filename.
        vae: Explicit VAE filename.
        image_path: Input image filename (ComfyUI input dir).
        steps: KSampler steps.
        cfg: Guidance scale.
        upscale_model: ESRGAN model filename.
        controlnet_name: Tile ControlNet filename.
        target_width: Intermediate upscale width.
        target_height: Intermediate upscale height.
        denoise: Denoising strength (keep low for img2img fidelity).
        loras: Optional LoRA list applied at nodes 20+.

    Returns:
        ComfyUI API-format workflow dict.
    """
    s = _seed(seed)
    nodes: Dict[str, Any] = {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_path, "upload": "image"}},
        "2": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": model}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
    }

    # LoRA chain (nodes 20+)
    model_ref: List = ["2", 0]
    clip_ref: List = ["2", 1]
    if loras:
        lora_nodes, model_ref, clip_ref = _build_lora_chain(
            loras, model_ref, clip_ref, start_id=20
        )
        nodes.update(lora_nodes)

    nodes.update({
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": clip_ref, "text": positive}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": clip_ref, "text": negative}},
        "6": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": controlnet_name}},
        "7": {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["1", 0],
                "upscale_method": "bicubic",
                "width": target_width,
                "height": target_height,
                "crop": "disabled",
            },
        },
        "8": {"class_type": "VAEEncode", "inputs": {"pixels": ["7", 0], "vae": ["3", 0]}},
        "9": {
            "class_type": "ControlNetApply",
            "inputs": {
                "conditioning": ["4", 0],
                "control_net": ["6", 0],
                "image": ["7", 0],
                "strength": 0.6,
            },
        },
        "10": {
            "class_type": "KSampler",
            "inputs": {
                "model": model_ref,
                "positive": ["9", 0],
                "negative": ["5", 0],
                "latent_image": ["8", 0],
                "seed": s,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "denoise": denoise,
            },
        },
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["3", 0]}},
        "12": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": upscale_model}},
        "13": {
            "class_type": "ImageUpscaleWithModel",
            "inputs": {"upscale_model": ["12", 0], "image": ["11", 0]},
        },
        "14": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "upscaled", "images": ["13", 0]},
        },
    })
    return nodes


# ──── Internal Wan 2.2 video helper ───────────────────────────────────────────


def _build_wan_video(
    positive: str,
    negative: str,
    seed: int,
    start_image: str,
    width: int,
    height: int,
    length: int,
    batch_size: int,
    fps: int,
    steps: int,
    cfg: float,
    shift: float,
    sampler_name: str,
    scheduler: str,
    unet_high: str,
    unet_low: str,
    clip_model: str,
    vae: str,
    loras_high: List[Dict[str, Any]],
    loras_low: List[Dict[str, Any]],
    filename_prefix: str,
) -> Dict[str, Any]:
    """Build Wan 2.2 dual-model two-stage video workflow.

    Node layout:
        "1"        UnetLoaderGGUF  (high-noise model)
        "2"        UnetLoaderGGUF  (low-noise model)
        "20"–"29"  High-model LoRA chain (LoraLoaderModelOnly)
        "30"–"39"  Low-model LoRA chain  (LoraLoaderModelOnly)
        "5"        ModelSamplingSD3 on final high model
        "6"        ModelSamplingSD3 on final low model
        "7"        CLIPLoaderGGUF
        "8"        VAELoader
        "9"        CLIPTextEncode  (positive)
        "10"       CLIPTextEncode  (negative)
        "11"       LoadImage       (start_image)
        "12"       WanImageToVideo → [0]=pos_embed, [1]=neg_embed, [2]=latent
        "13"       KSamplerAdvanced stage 1 (add_noise=enable, 0→steps//2)
        "14"       KSamplerAdvanced stage 2 (add_noise=disable, steps//2→steps)
        "15"       VAEDecode
        "16"       CreateVideo
        "17"       SaveVideo

    Args:
        positive: Positive prompt text.
        negative: Negative prompt text.
        seed: RNG seed (-1 for random).
        start_image: Input image filename for WanImageToVideo; use "white.png" for T2V.
        width: Output video width.
        height: Output video height.
        length: Number of frames.
        batch_size: Batch size.
        fps: Output frames per second.
        steps: Total sampling steps (split evenly between stages).
        cfg: Guidance scale.
        shift: ModelSamplingSD3 shift value.
        sampler_name: KSamplerAdvanced sampler.
        scheduler: KSamplerAdvanced scheduler.
        unet_high: GGUF filename for high-noise stage model.
        unet_low: GGUF filename for low-noise stage model.
        clip_model: GGUF CLIP filename.
        vae: VAE filename.
        loras_high: LoRA list for high-noise model.
        loras_low: LoRA list for low-noise model.
        filename_prefix: Prefix for SaveVideo.

    Returns:
        ComfyUI API-format workflow dict.
    """
    s = _seed(seed)
    mid = steps // 2
    nodes: Dict[str, Any] = {}

    # Base model loaders
    nodes["1"] = {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": unet_high}}
    nodes["2"] = {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": unet_low}}

    # LoRA chains
    high_lora_nodes, final_high_ref = _build_video_lora_chain(loras_high, ["1", 0], start_id=20)
    nodes.update(high_lora_nodes)
    low_lora_nodes, final_low_ref = _build_video_lora_chain(loras_low, ["2", 0], start_id=30)
    nodes.update(low_lora_nodes)

    # ModelSamplingSD3 for shift
    nodes["5"] = {"class_type": "ModelSamplingSD3", "inputs": {"shift": shift, "model": final_high_ref}}
    nodes["6"] = {"class_type": "ModelSamplingSD3", "inputs": {"shift": shift, "model": final_low_ref}}

    # Shared encoders
    nodes["7"] = {"class_type": "CLIPLoaderGGUF", "inputs": {"clip_name": clip_model, "type": "wan"}}
    nodes["8"] = {"class_type": "VAELoader", "inputs": {"vae_name": vae}}

    # Conditioning
    nodes["9"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["7", 0], "text": positive}}
    nodes["10"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["7", 0], "text": negative}}
    nodes["11"] = {"class_type": "LoadImage", "inputs": {"image": start_image}}

    # WanImageToVideo: outputs [0]=pos_embed, [1]=neg_embed, [2]=latent
    nodes["12"] = {
        "class_type": "WanImageToVideo",
        "inputs": {
            "width": width,
            "height": height,
            "length": length,
            "batch_size": batch_size,
            "positive": ["9", 0],
            "negative": ["10", 0],
            "vae": ["8", 0],
            "start_image": ["11", 0],
        },
    }

    # Stage 1: high-noise model, first half
    nodes["13"] = {
        "class_type": "KSamplerAdvanced",
        "inputs": {
            "model": ["5", 0],
            "add_noise": "enable",
            "noise_seed": s,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": sampler_name,
            "scheduler": scheduler,
            "positive": ["12", 0],
            "negative": ["12", 1],
            "latent_image": ["12", 2],
            "start_at_step": 0,
            "end_at_step": mid,
            "return_with_leftover_noise": "enable",
        },
    }

    # Stage 2: low-noise model, second half
    nodes["14"] = {
        "class_type": "KSamplerAdvanced",
        "inputs": {
            "model": ["6", 0],
            "add_noise": "disable",
            "noise_seed": s,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": sampler_name,
            "scheduler": scheduler,
            "positive": ["12", 0],
            "negative": ["12", 1],
            "latent_image": ["13", 0],
            "start_at_step": mid,
            "end_at_step": steps,
            "return_with_leftover_noise": "disable",
        },
    }

    # Decode and output
    nodes["15"] = {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0], "vae": ["8", 0]}}
    nodes["16"] = {"class_type": "CreateVideo", "inputs": {"fps": fps, "images": ["15", 0]}}
    nodes["17"] = {
        "class_type": "SaveVideo",
        "inputs": {
            "filename_prefix": filename_prefix,
            "format": "auto",
            "codec": "auto",
            "video": ["16", 0],
        },
    }
    return nodes


# ──── Video builders ───────────────────────────────────────────────────────────


def build_video_wan_t2v(
    positive: str = "cinematic video, smooth motion, high quality, detailed",
    negative: str = "blurry, low quality, worst quality, watermark",
    seed: int = -1,
    width: int = 272,
    height: int = 352,
    length: int = 105,
    batch_size: int = 1,
    fps: int = 16,
    steps: int = 6,
    cfg: float = 1.0,
    shift: float = 5.0,
    sampler_name: str = "euler",
    scheduler: str = "simple",
    unet_high: str = _DEFAULT_UNET_HIGH,
    unet_low: str = _DEFAULT_UNET_LOW,
    clip_model: str = _DEFAULT_CLIP_MODEL,
    vae: str = _DEFAULT_VAE_WAN,
    loras_high: Optional[List[Dict[str, Any]]] = None,
    loras_low: Optional[List[Dict[str, Any]]] = None,
    filename_prefix: str = "wan_t2v",
) -> Dict[str, Any]:
    """Wan 2.2 text-to-video using dual-model KSamplerAdvanced pipeline.

    Uses a white placeholder image as start_image so WanImageToVideo acts as T2V.

    Args:
        positive: Positive prompt text.
        negative: Negative prompt text.
        seed: RNG seed (-1 for random).
        width: Output width.
        height: Output height.
        length: Number of frames.
        batch_size: Batch size.
        fps: Output video framerate.
        steps: Total sampling steps.
        cfg: Guidance scale.
        shift: ModelSamplingSD3 shift.
        sampler_name: KSamplerAdvanced sampler.
        scheduler: KSamplerAdvanced scheduler.
        unet_high: High-noise GGUF model filename.
        unet_low: Low-noise GGUF model filename.
        clip_model: CLIP GGUF filename.
        vae: VAE filename.
        loras_high: LoRAs for high-noise model; defaults to LightX2V.
        loras_low: LoRAs for low-noise model; defaults to SVI_LOW.
        filename_prefix: Prefix for SaveVideo.

    Returns:
        ComfyUI API-format workflow dict.
    """
    return _build_wan_video(
        positive=positive,
        negative=negative,
        seed=seed,
        start_image="white.png",
        width=width,
        height=height,
        length=length,
        batch_size=batch_size,
        fps=fps,
        steps=steps,
        cfg=cfg,
        shift=shift,
        sampler_name=sampler_name,
        scheduler=scheduler,
        unet_high=unet_high,
        unet_low=unet_low,
        clip_model=clip_model,
        vae=vae,
        loras_high=loras_high if loras_high is not None else list(_DEFAULT_LORAS_HIGH),
        loras_low=loras_low if loras_low is not None else list(_DEFAULT_LORAS_LOW),
        filename_prefix=filename_prefix,
    )


def build_video_wan_i2v(
    positive: str = "cinematic video, smooth motion, high quality, detailed",
    negative: str = "blurry, low quality, worst quality, watermark",
    seed: int = -1,
    start_image: str = "input.png",
    width: int = 272,
    height: int = 352,
    length: int = 105,
    batch_size: int = 1,
    fps: int = 16,
    steps: int = 6,
    cfg: float = 1.0,
    shift: float = 5.0,
    sampler_name: str = "euler",
    scheduler: str = "simple",
    unet_high: str = _DEFAULT_UNET_HIGH,
    unet_low: str = _DEFAULT_UNET_LOW,
    clip_model: str = _DEFAULT_CLIP_MODEL,
    vae: str = _DEFAULT_VAE_WAN,
    loras_high: Optional[List[Dict[str, Any]]] = None,
    loras_low: Optional[List[Dict[str, Any]]] = None,
    filename_prefix: str = "wan_i2v",
) -> Dict[str, Any]:
    """Wan 2.2 image-to-video using dual-model KSamplerAdvanced pipeline.

    Args:
        positive: Positive prompt text.
        negative: Negative prompt text.
        seed: RNG seed (-1 for random).
        start_image: Input image filename (ComfyUI input dir).
        width: Output width.
        height: Output height.
        length: Number of frames.
        batch_size: Batch size.
        fps: Output video framerate.
        steps: Total sampling steps.
        cfg: Guidance scale.
        shift: ModelSamplingSD3 shift.
        sampler_name: KSamplerAdvanced sampler.
        scheduler: KSamplerAdvanced scheduler.
        unet_high: High-noise GGUF model filename.
        unet_low: Low-noise GGUF model filename.
        clip_model: CLIP GGUF filename.
        vae: VAE filename.
        loras_high: LoRAs for high-noise model; defaults to LightX2V.
        loras_low: LoRAs for low-noise model; defaults to SVI_LOW.
        filename_prefix: Prefix for SaveVideo.

    Returns:
        ComfyUI API-format workflow dict.
    """
    return _build_wan_video(
        positive=positive,
        negative=negative,
        seed=seed,
        start_image=start_image,
        width=width,
        height=height,
        length=length,
        batch_size=batch_size,
        fps=fps,
        steps=steps,
        cfg=cfg,
        shift=shift,
        sampler_name=sampler_name,
        scheduler=scheduler,
        unet_high=unet_high,
        unet_low=unet_low,
        clip_model=clip_model,
        vae=vae,
        loras_high=loras_high if loras_high is not None else list(_DEFAULT_LORAS_HIGH),
        loras_low=loras_low if loras_low is not None else list(_DEFAULT_LORAS_LOW),
        filename_prefix=filename_prefix,
    )


def build_portrait_refiner(
    positive: str = "masterpiece, best quality, highly detailed portrait photograph, sharp focus",
    negative: str = _DEFAULT_NEGATIVE,
    positive_refiner: str = "highly detailed, intricate details, realistic skin texture, sharp focus",
    seed: int = -1,
    model: str = _DEFAULT_IMAGE_MODEL,
    vae: Optional[str] = None,
    steps: int = 20,
    cfg: float = 1.5,
    refiner_steps: int = 12,
    refiner_cfg: float = 1.0,
    refiner_denoise: float = 0.4,
    refiner_scale: float = 1.5,
    width: int = 896,
    height: int = 1152,
    batch_size: int = 1,
    sampler_name: str = "lcm",
    scheduler: str = "exponential",
    denoise: float = 1.0,
    loras: Optional[List[Dict[str, Any]]] = None,
    clip_layer: int = -2,
) -> Dict[str, Any]:
    """Build portrait_refiner workflow — base pass + upscale + img2img refiner.

    Matches the generate_Image.json dual-pass pattern:
    base (steps=20, cfg=1.5, denoise=1.0) → ImageScaleBy(1.5x) → refiner (steps=12, cfg=1.0, denoise=0.4).
    CLIPSetLastLayer (stop_at_clip_layer=-2) isolates refiner conditioning.

    Node layout:
        "1"        CheckpointLoaderSimple
        "2"        VAELoader (only when vae is explicitly set)
        "20"–"29"  LoRA chain
        "50"       CLIPTextEncode positive (base)
        "51"       CLIPTextEncode negative
        "52"       CLIPSetLastLayer (clip_layer, for refiner)
        "53"       CLIPTextEncode positive (refiner detail)
        "54"       ConditioningConcat (base pos + refiner pos)
        "55"       EmptyLatentImage (base resolution)
        "60"       KSampler base
        "65"       VAEDecode base → final base image
        "66"       ImageScaleBy (refiner_scale, lanczos)
        "67"       VAEEncode (back to latent)
        "70"       KSampler refiner
        "75"       VAEDecode refined
        "80"       SaveImage (refined output)
        "81"       SaveImage (base output for comparison)

    Args:
        positive: Base positive prompt text.
        negative: Negative prompt text.
        positive_refiner: Additional detail text appended in refiner pass (CLIPSetLastLayer).
        seed: RNG seed (-1 for random).
        model: Checkpoint filename.
        vae: Explicit VAE filename; None uses checkpoint's baked VAE.
        steps: Base KSampler steps.
        cfg: Base guidance scale.
        refiner_steps: Refiner KSampler steps.
        refiner_cfg: Refiner guidance scale.
        refiner_denoise: Refiner denoising strength (keep low, ~0.4).
        refiner_scale: Scale factor for upscaling base output before refiner.
        width: Base image width.
        height: Base image height.
        batch_size: Images per batch.
        sampler_name: KSampler sampler name (both passes).
        scheduler: KSampler scheduler (both passes).
        denoise: Base pass denoising strength.
        loras: Optional LoRA list.
        clip_layer: stop_at_clip_layer for CLIPSetLastLayer (-2 standard).

    Returns:
        ComfyUI API-format workflow dict.
    """
    s = _seed(seed)
    nodes: Dict[str, Any] = {}

    # Loaders
    nodes["1"] = {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": model}}
    if vae:
        nodes["2"] = {"class_type": "VAELoader", "inputs": {"vae_name": vae}}
        vae_ref: List = ["2", 0]
    else:
        vae_ref = ["1", 2]

    # LoRA chain (nodes 20–29)
    model_ref: List = ["1", 0]
    clip_ref: List = ["1", 1]
    if loras:
        lora_nodes, model_ref, clip_ref = _build_lora_chain(
            loras, model_ref, clip_ref, start_id=20
        )
        nodes.update(lora_nodes)

    # Conditioning — base pass
    nodes["50"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": clip_ref, "text": positive}}
    nodes["51"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": clip_ref, "text": negative}}

    # Conditioning — refiner pass (CLIPSetLastLayer isolates detail conditioning)
    nodes["52"] = {
        "class_type": "CLIPSetLastLayer",
        "inputs": {"clip": clip_ref, "stop_at_clip_layer": clip_layer},
    }
    nodes["53"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": ["52", 0], "text": positive_refiner},
    }
    nodes["54"] = {
        "class_type": "ConditioningConcat",
        "inputs": {"conditioning_to": ["50", 0], "conditioning_from": ["53", 0]},
    }

    # Base latent + sample
    nodes["55"] = {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": width, "height": height, "batch_size": batch_size},
    }
    nodes["60"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": model_ref,
            "positive": ["50", 0],
            "negative": ["51", 0],
            "latent_image": ["55", 0],
            "seed": s,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": sampler_name,
            "scheduler": scheduler,
            "denoise": denoise,
        },
    }
    nodes["65"] = {"class_type": "VAEDecode", "inputs": {"samples": ["60", 0], "vae": vae_ref}}
    nodes["81"] = {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "portrait_base", "images": ["65", 0]},
    }

    # Upscale for refiner
    nodes["66"] = {
        "class_type": "ImageScaleBy",
        "inputs": {
            "image": ["65", 0],
            "upscale_method": "lanczos",
            "scale_by": refiner_scale,
        },
    }
    nodes["67"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["66", 0], "vae": vae_ref}}

    # Refiner pass (img2img on upscaled latent, low denoise)
    nodes["70"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": model_ref,
            "positive": ["54", 0],
            "negative": ["51", 0],
            "latent_image": ["67", 0],
            "seed": s,
            "steps": refiner_steps,
            "cfg": refiner_cfg,
            "sampler_name": sampler_name,
            "scheduler": scheduler,
            "denoise": refiner_denoise,
        },
    }
    nodes["75"] = {"class_type": "VAEDecode", "inputs": {"samples": ["70", 0], "vae": vae_ref}}
    nodes["80"] = {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "portrait_refined", "images": ["75", 0]},
    }
    return nodes


# ──── Workflow Registry ────────────────────────────────────────────────────────

WORKFLOW_REGISTRY: Dict[str, Dict[str, Any]] = {
    "portrait_hires": {
        "builder": build_portrait_hires,
        "label": "Portrait — Hi-Res + Face Detail",
        "description": "SDXL portrait with FaceDetailer pass. Best quality for character portraits.",
        "category": "portrait",
        "resolution": "896x1152",
        "speed": "slow",
        "requires_nodes": ["FaceDetailer", "UltralyticsDetectorProvider"],
        "params": {
            "positive": {"type": "str", "default": "masterpiece, best quality, highly detailed portrait photograph"},
            "negative": {"type": "str", "default": "ugly, deformed, blurry, low quality, worst quality"},
            "seed": {"type": "int", "default": -1},
            "model": {"type": "str", "default": _DEFAULT_IMAGE_MODEL},
            "vae": {"type": "str", "default": None},
            "steps": {"type": "int", "default": 20},
            "cfg": {"type": "float", "default": 1.5},
            "width": {"type": "int", "default": 896},
            "height": {"type": "int", "default": 1152},
            "batch_size": {"type": "int", "default": 1},
            "sampler_name": {"type": "str", "default": "lcm"},
            "scheduler": {"type": "str", "default": "exponential"},
            "denoise": {"type": "float", "default": 1.0},
            "loras": {"type": "list", "default": None},
            "face_detect_model": {"type": "str", "default": "bbox/face_yolov8s.pt"},
            "face_steps": {"type": "int", "default": 12},
            "face_cfg": {"type": "float", "default": 1.0},
            "face_denoise": {"type": "float", "default": 0.4},
        },
    },
    "portrait_refiner": {
        "builder": build_portrait_refiner,
        "label": "Portrait — Base + Refiner (generate_Image style)",
        "description": (
            "Dual-pass: base (lcm/exp, steps=20, cfg=1.5) + 1.5x upscale + "
            "img2img refiner (steps=12, cfg=1.0, denoise=0.4). Matches tuned generate_Image.json workflow."
        ),
        "category": "portrait",
        "resolution": "896x1152 → 1344x1728",
        "speed": "medium",
        "requires_nodes": ["CLIPSetLastLayer", "ConditioningConcat", "ImageScaleBy", "VAEEncode"],
        "params": {
            "positive": {"type": "str", "default": "masterpiece, best quality, highly detailed portrait photograph, sharp focus"},
            "negative": {"type": "str", "default": _DEFAULT_NEGATIVE},
            "positive_refiner": {"type": "str", "default": "highly detailed, intricate details, realistic skin texture, sharp focus"},
            "seed": {"type": "int", "default": -1},
            "model": {"type": "str", "default": _DEFAULT_IMAGE_MODEL},
            "vae": {"type": "str", "default": None},
            "steps": {"type": "int", "default": 20},
            "cfg": {"type": "float", "default": 1.5},
            "refiner_steps": {"type": "int", "default": 12},
            "refiner_cfg": {"type": "float", "default": 1.0},
            "refiner_denoise": {"type": "float", "default": 0.4},
            "refiner_scale": {"type": "float", "default": 1.5},
            "width": {"type": "int", "default": 896},
            "height": {"type": "int", "default": 1152},
            "batch_size": {"type": "int", "default": 1},
            "sampler_name": {"type": "str", "default": "lcm"},
            "scheduler": {"type": "str", "default": "exponential"},
            "denoise": {"type": "float", "default": 1.0},
            "loras": {"type": "list", "default": None},
            "clip_layer": {"type": "int", "default": -2},
        },
    },
    "portrait_fast": {
        "builder": build_portrait_fast,
        "label": "Portrait — Fast (Lightning 8-step)",
        "description": "Lightning-accelerated portrait. ~3x faster than hi-res.",
        "category": "portrait",
        "resolution": "896x1152",
        "speed": "fast",
        "requires_nodes": [],
        "params": {
            "positive": {"type": "str", "default": "masterpiece, best quality, portrait photograph"},
            "negative": {"type": "str", "default": "ugly, deformed, blurry, low quality"},
            "seed": {"type": "int", "default": -1},
            "model": {"type": "str", "default": _DEFAULT_IMAGE_MODEL},
            "vae": {"type": "str", "default": None},
            "steps": {"type": "int", "default": 20},
            "cfg": {"type": "float", "default": 1.5},
            "width": {"type": "int", "default": 896},
            "height": {"type": "int", "default": 1152},
            "batch_size": {"type": "int", "default": 1},
            "sampler_name": {"type": "str", "default": "lcm"},
            "scheduler": {"type": "str", "default": "exponential"},
            "denoise": {"type": "float", "default": 1.0},
            "loras": {"type": "list", "default": None},
        },
    },
    "character_card": {
        "builder": build_character_card,
        "label": "Character Card — Full Body",
        "description": "Full-body character portrait with cinematic lighting.",
        "category": "portrait",
        "resolution": "832x1216",
        "speed": "medium",
        "requires_nodes": [],
        "params": {
            "positive": {"type": "str", "default": "masterpiece, full body portrait, cinematic lighting, detailed"},
            "negative": {"type": "str", "default": "ugly, deformed, blurry, cropped, worst quality"},
            "seed": {"type": "int", "default": -1},
            "model": {"type": "str", "default": _DEFAULT_IMAGE_MODEL},
            "vae": {"type": "str", "default": None},
            "steps": {"type": "int", "default": 20},
            "cfg": {"type": "float", "default": 1.5},
            "width": {"type": "int", "default": 832},
            "height": {"type": "int", "default": 1216},
            "batch_size": {"type": "int", "default": 1},
            "sampler_name": {"type": "str", "default": "lcm"},
            "scheduler": {"type": "str", "default": "exponential"},
            "denoise": {"type": "float", "default": 1.0},
            "loras": {"type": "list", "default": None},
        },
    },
    "game_item_icon": {
        "builder": build_game_item_icon,
        "label": "Game Item Icon (Transparent)",
        "description": "Game item rendered on transparent background via RMBG.",
        "category": "item",
        "resolution": "512x512",
        "speed": "fast",
        "requires_nodes": ["RMBG"],
        "params": {
            "positive": {"type": "str", "default": "game item icon, isolated on white background, detailed craftsmanship"},
            "negative": {"type": "str", "default": "ugly, deformed, blurry, background, people, text, watermark"},
            "seed": {"type": "int", "default": -1},
            "model": {"type": "str", "default": _DEFAULT_IMAGE_MODEL},
            "vae": {"type": "str", "default": None},
            "steps": {"type": "int", "default": 20},
            "cfg": {"type": "float", "default": 1.5},
            "width": {"type": "int", "default": 512},
            "height": {"type": "int", "default": 512},
            "batch_size": {"type": "int", "default": 1},
            "sampler_name": {"type": "str", "default": "lcm"},
            "scheduler": {"type": "str", "default": "exponential"},
            "denoise": {"type": "float", "default": 1.0},
            "loras": {"type": "list", "default": None},
        },
    },
    "scene_background": {
        "builder": build_scene_background,
        "label": "Scene Background — Widescreen",
        "description": "Cinematic widescreen background for scene environments.",
        "category": "background",
        "resolution": "1024x576",
        "speed": "medium",
        "requires_nodes": [],
        "params": {
            "positive": {"type": "str", "default": "cinematic background, wide shot, detailed environment, atmospheric lighting"},
            "negative": {"type": "str", "default": "ugly, deformed, blurry, text, watermark, people"},
            "seed": {"type": "int", "default": -1},
            "model": {"type": "str", "default": _DEFAULT_IMAGE_MODEL},
            "vae": {"type": "str", "default": None},
            "steps": {"type": "int", "default": 20},
            "cfg": {"type": "float", "default": 1.5},
            "width": {"type": "int", "default": 1024},
            "height": {"type": "int", "default": 576},
            "batch_size": {"type": "int", "default": 1},
            "sampler_name": {"type": "str", "default": "lcm"},
            "scheduler": {"type": "str", "default": "exponential"},
            "denoise": {"type": "float", "default": 1.0},
            "loras": {"type": "list", "default": None},
        },
    },
    "action_card": {
        "builder": build_action_card,
        "label": "Action Card — Cinematic",
        "description": "Ultra-wide dramatic action/story card.",
        "category": "background",
        "resolution": "1216x512",
        "speed": "medium",
        "requires_nodes": [],
        "params": {
            "positive": {"type": "str", "default": "dramatic cinematic scene, action, wide angle, storytelling, epic"},
            "negative": {"type": "str", "default": "ugly, deformed, blurry, text, watermark"},
            "seed": {"type": "int", "default": -1},
            "model": {"type": "str", "default": _DEFAULT_IMAGE_MODEL},
            "vae": {"type": "str", "default": None},
            "steps": {"type": "int", "default": 20},
            "cfg": {"type": "float", "default": 1.5},
            "width": {"type": "int", "default": 1216},
            "height": {"type": "int", "default": 512},
            "batch_size": {"type": "int", "default": 1},
            "sampler_name": {"type": "str", "default": "lcm"},
            "scheduler": {"type": "str", "default": "exponential"},
            "denoise": {"type": "float", "default": 1.0},
            "loras": {"type": "list", "default": None},
        },
    },
    "ui_icon": {
        "builder": build_ui_icon,
        "label": "UI Icon (Transparent)",
        "description": "Clean UI icon with background removed for overlay use.",
        "category": "ui",
        "resolution": "512x512",
        "speed": "fast",
        "requires_nodes": ["RMBG"],
        "params": {
            "positive": {"type": "str", "default": "clean UI icon, flat design, minimal, isolated element"},
            "negative": {"type": "str", "default": "ugly, deformed, blurry, photo, gradient, background noise"},
            "seed": {"type": "int", "default": -1},
            "model": {"type": "str", "default": _DEFAULT_IMAGE_MODEL},
            "vae": {"type": "str", "default": None},
            "steps": {"type": "int", "default": 20},
            "cfg": {"type": "float", "default": 1.5},
            "width": {"type": "int", "default": 512},
            "height": {"type": "int", "default": 512},
            "batch_size": {"type": "int", "default": 1},
            "sampler_name": {"type": "str", "default": "lcm"},
            "scheduler": {"type": "str", "default": "exponential"},
            "denoise": {"type": "float", "default": 1.0},
            "loras": {"type": "list", "default": None},
        },
    },
    "message_image": {
        "builder": build_message_image,
        "label": "Message Image — Lightning Fast",
        "description": "Lightning-accelerated image for chat messages and notifications.",
        "category": "message",
        "resolution": "768x512",
        "speed": "fast",
        "requires_nodes": [],
        "params": {
            "positive": {"type": "str", "default": "chat message image, vivid, detailed, cinematic"},
            "negative": {"type": "str", "default": "ugly, deformed, blurry, low quality"},
            "seed": {"type": "int", "default": -1},
            "model": {"type": "str", "default": _DEFAULT_IMAGE_MODEL},
            "vae": {"type": "str", "default": None},
            "steps": {"type": "int", "default": 8},
            "cfg": {"type": "float", "default": 1.5},
            "width": {"type": "int", "default": 768},
            "height": {"type": "int", "default": 512},
            "batch_size": {"type": "int", "default": 1},
            "sampler_name": {"type": "str", "default": "lcm"},
            "scheduler": {"type": "str", "default": "exponential"},
            "denoise": {"type": "float", "default": 1.0},
            "loras": {"type": "list", "default": None},
        },
    },
    "video_wan_t2v": {
        "builder": build_video_wan_t2v,
        "label": "Video — Wan 2.2 Text-to-Video",
        "description": (
            "Wan 2.2 14B GGUF dual-model T2V. 272x352, 105 frames (6.5s at 16fps). "
            "Dual KSamplerAdvanced with LightX2V + SVI_LOW LoRAs."
        ),
        "category": "video",
        "resolution": "272x352",
        "frames": 105,
        "fps": 16,
        "speed": "slow",
        "requires_nodes": [
            "UnetLoaderGGUF",
            "CLIPLoaderGGUF",
            "WanImageToVideo",
            "KSamplerAdvanced",
            "CreateVideo",
            "SaveVideo",
        ],
        "params": {
            "positive": {"type": "str", "default": "cinematic video, smooth motion, high quality, detailed"},
            "negative": {"type": "str", "default": "blurry, low quality, worst quality, watermark"},
            "seed": {"type": "int", "default": -1},
            "width": {"type": "int", "default": 272},
            "height": {"type": "int", "default": 352},
            "length": {"type": "int", "default": 105},
            "batch_size": {"type": "int", "default": 1},
            "fps": {"type": "int", "default": 16},
            "steps": {"type": "int", "default": 6},
            "cfg": {"type": "float", "default": 1.0},
            "shift": {"type": "float", "default": 5.0},
            "sampler_name": {"type": "str", "default": "euler"},
            "scheduler": {"type": "str", "default": "simple"},
            "unet_high": {"type": "str", "default": _DEFAULT_UNET_HIGH},
            "unet_low": {"type": "str", "default": _DEFAULT_UNET_LOW},
            "clip_model": {"type": "str", "default": _DEFAULT_CLIP_MODEL},
            "vae": {"type": "str", "default": _DEFAULT_VAE_WAN},
            "loras_high": {"type": "list", "default": None},
            "loras_low": {"type": "list", "default": None},
            "filename_prefix": {"type": "str", "default": "wan_t2v"},
        },
    },
    "video_wan_i2v": {
        "builder": build_video_wan_i2v,
        "label": "Video — Wan 2.2 Image-to-Video",
        "description": (
            "Wan 2.2 14B I2V GGUF dual-model. Animate a still image. 272x352, 105 frames."
        ),
        "category": "video",
        "resolution": "272x352",
        "frames": 105,
        "fps": 16,
        "speed": "slow",
        "requires_nodes": [
            "UnetLoaderGGUF",
            "CLIPLoaderGGUF",
            "WanImageToVideo",
            "KSamplerAdvanced",
            "CreateVideo",
            "SaveVideo",
        ],
        "params": {
            "positive": {"type": "str", "default": "cinematic video, smooth motion, high quality, detailed"},
            "negative": {"type": "str", "default": "blurry, low quality, worst quality, watermark"},
            "seed": {"type": "int", "default": -1},
            "start_image": {"type": "str", "default": "input.png"},
            "width": {"type": "int", "default": 272},
            "height": {"type": "int", "default": 352},
            "length": {"type": "int", "default": 105},
            "batch_size": {"type": "int", "default": 1},
            "fps": {"type": "int", "default": 16},
            "steps": {"type": "int", "default": 6},
            "cfg": {"type": "float", "default": 1.0},
            "shift": {"type": "float", "default": 5.0},
            "sampler_name": {"type": "str", "default": "euler"},
            "scheduler": {"type": "str", "default": "simple"},
            "unet_high": {"type": "str", "default": _DEFAULT_UNET_HIGH},
            "unet_low": {"type": "str", "default": _DEFAULT_UNET_LOW},
            "clip_model": {"type": "str", "default": _DEFAULT_CLIP_MODEL},
            "vae": {"type": "str", "default": _DEFAULT_VAE_WAN},
            "loras_high": {"type": "list", "default": None},
            "loras_low": {"type": "list", "default": None},
            "filename_prefix": {"type": "str", "default": "wan_i2v"},
        },
    },
    "upscale_enhance": {
        "builder": build_upscale_enhance,
        "label": "Upscale & Enhance (4x)",
        "description": "4x pixel upscale with tile ControlNet detail enhancement.",
        "category": "utility",
        "resolution": "variable",
        "speed": "medium",
        "requires_nodes": ["ControlNetApply", "UpscaleModelLoader", "ImageUpscaleWithModel"],
        "params": {
            "positive": {"type": "str", "default": "masterpiece, highly detailed, sharp focus, high resolution, 8k"},
            "negative": {"type": "str", "default": "ugly, deformed, blurry, artifacts, noise, grain"},
            "seed": {"type": "int", "default": -1},
            "model": {"type": "str", "default": _DEFAULT_IMAGE_MODEL},
            "vae": {"type": "str", "default": "sdxl_vae.safetensors"},
            "image_path": {"type": "str", "default": "input.png"},
            "steps": {"type": "int", "default": 20},
            "cfg": {"type": "float", "default": 6.0},
            "upscale_model": {"type": "str", "default": "4x_NMKD-Superscale-SP_178000_G.pth"},
            "controlnet_name": {"type": "str", "default": "xinsircontrolnet-tile-sdxl-1.0.safetensors"},
            "target_width": {"type": "int", "default": 2048},
            "target_height": {"type": "int", "default": 2048},
            "denoise": {"type": "float", "default": 0.4},
            "loras": {"type": "list", "default": None},
        },
    },
}
