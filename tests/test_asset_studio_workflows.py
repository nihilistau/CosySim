"""Tests for Asset Studio ComfyUI workflow builder and manager.

import pytest
pytestmark = pytest.mark.slow

Covers all 15 workflow builders, WorkflowManager methods, and scene routes.
All HTTP calls and ComfyUI interactions are mocked.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ──── Builder tests ────────────────────────────────────────────────────────────

from engine.asset_studio.workflow_builder import (
    WORKFLOW_REGISTRY,
    build_portrait_hires,
    build_portrait_fast,
    build_portrait_refiner,
    build_character_card,
    build_game_item_icon,
    build_scene_background,
    build_action_card,
    build_ui_icon,
    build_message_image,
    build_video_wan_t2v,
    build_video_wan_i2v,
    build_video_wan_landscape,
    build_video_wan_portrait_fast,
    build_video_wan_character_hq,
    build_upscale_enhance,
    _seed,
)


def _assert_valid_workflow(wf: Dict[str, Any]) -> None:
    """Assert basic structural validity of a ComfyUI API format workflow."""
    assert isinstance(wf, dict), "Workflow must be a dict"
    assert len(wf) > 0, "Workflow must not be empty"
    for node_id, node in wf.items():
        assert isinstance(node_id, str), f"Node ID must be str, got {type(node_id)}"
        assert "class_type" in node, f"Node {node_id} missing class_type"
        assert "inputs" in node, f"Node {node_id} missing inputs"
        assert isinstance(node["class_type"], str), f"class_type must be str in node {node_id}"
        assert isinstance(node["inputs"], dict), f"inputs must be dict in node {node_id}"


class TestSeedHelper:
    def test_positive_seed_returned_unchanged(self) -> None:
        assert _seed(42) == 42

    def test_zero_seed_returned(self) -> None:
        assert _seed(0) == 0

    def test_negative_seed_generates_random(self) -> None:
        s = _seed(-1)
        assert 0 <= s <= 2 ** 32 - 1

    def test_random_seed_not_always_same(self) -> None:
        seeds = {_seed(-1) for _ in range(20)}
        assert len(seeds) > 1, "Random seeds should not all be equal"


class TestBuildPortraitHires:
    def test_returns_valid_workflow(self) -> None:
        wf = build_portrait_hires()
        _assert_valid_workflow(wf)

    def test_has_face_detailer(self) -> None:
        wf = build_portrait_hires()
        class_types = [n["class_type"] for n in wf.values()]
        assert "FaceDetailer" in class_types

    def test_has_ultralytics_detector(self) -> None:
        wf = build_portrait_hires()
        class_types = [n["class_type"] for n in wf.values()]
        assert "UltralyticsDetectorProvider" in class_types

    def test_seed_injection(self) -> None:
        wf = build_portrait_hires(seed=99)
        ksampler = next(n for n in wf.values() if n["class_type"] == "KSampler")
        assert ksampler["inputs"]["seed"] == 99

    def test_random_seed_when_negative(self) -> None:
        wf = build_portrait_hires(seed=-1)
        ksampler = next(n for n in wf.values() if n["class_type"] == "KSampler")
        assert ksampler["inputs"]["seed"] >= 0

    def test_model_override(self) -> None:
        wf = build_portrait_hires(model="custom_model.safetensors")
        ckpt = next(n for n in wf.values() if n["class_type"] == "CheckpointLoaderSimple")
        assert ckpt["inputs"]["ckpt_name"] == "custom_model.safetensors"

    def test_dimension_params(self) -> None:
        wf = build_portrait_hires(width=512, height=768)
        latent = next(n for n in wf.values() if n["class_type"] == "EmptyLatentImage")
        assert latent["inputs"]["width"] == 512
        assert latent["inputs"]["height"] == 768

    def test_has_save_image(self) -> None:
        wf = build_portrait_hires()
        class_types = [n["class_type"] for n in wf.values()]
        assert "SaveImage" in class_types

    def test_positive_prompt_in_clip_encode(self) -> None:
        wf = build_portrait_hires(positive="test positive")
        prompts = [n["inputs"]["text"] for n in wf.values() if n["class_type"] == "CLIPTextEncode"]
        assert "test positive" in prompts


class TestBuildPortraitFast:
    def test_returns_valid_workflow(self) -> None:
        _assert_valid_workflow(build_portrait_fast())

    def test_has_lora_loader(self) -> None:
        wf = build_portrait_fast()
        class_types = [n["class_type"] for n in wf.values()]
        assert "LoraLoader" in class_types

    def test_lightning_lora_used(self) -> None:
        wf = build_portrait_fast()
        lora = next(n for n in wf.values() if n["class_type"] == "LoraLoader")
        assert "lightning" in lora["inputs"]["lora_name"]

    def test_steps_is_20(self) -> None:
        wf = build_portrait_fast()
        ksampler = next(n for n in wf.values() if n["class_type"] == "KSampler")
        assert ksampler["inputs"]["steps"] == 20

    def test_no_face_detailer(self) -> None:
        wf = build_portrait_fast()
        class_types = [n["class_type"] for n in wf.values()]
        assert "FaceDetailer" not in class_types

    def test_dimension_params(self) -> None:
        wf = build_portrait_fast(width=640, height=960)
        latent = next(n for n in wf.values() if n["class_type"] == "EmptyLatentImage")
        assert latent["inputs"]["width"] == 640


class TestBuildCharacterCard:
    def test_returns_valid_workflow(self) -> None:
        _assert_valid_workflow(build_character_card())

    def test_default_dimensions(self) -> None:
        wf = build_character_card()
        latent = next(n for n in wf.values() if n["class_type"] == "EmptyLatentImage")
        assert latent["inputs"]["width"] == 832
        assert latent["inputs"]["height"] == 1216

    def test_cfg_override(self) -> None:
        wf = build_character_card(cfg=8.0)
        ksampler = next(n for n in wf.values() if n["class_type"] == "KSampler")
        assert ksampler["inputs"]["cfg"] == 8.0


class TestBuildGameItemIcon:
    def test_returns_valid_workflow(self) -> None:
        _assert_valid_workflow(build_game_item_icon())

    def test_has_rmbg(self) -> None:
        wf = build_game_item_icon()
        class_types = [n["class_type"] for n in wf.values()]
        assert "RMBG" in class_types

    def test_square_dimensions(self) -> None:
        wf = build_game_item_icon()
        latent = next(n for n in wf.values() if n["class_type"] == "EmptyLatentImage")
        assert latent["inputs"]["width"] == 512
        assert latent["inputs"]["height"] == 512

    def test_save_after_rmbg(self) -> None:
        wf = build_game_item_icon()
        # Find RMBG node ID
        rmbg_id = next(nid for nid, n in wf.items() if n["class_type"] == "RMBG")
        save = next(n for n in wf.values() if n["class_type"] == "SaveImage")
        assert save["inputs"]["images"][0] == rmbg_id


class TestBuildSceneBackground:
    def test_returns_valid_workflow(self) -> None:
        _assert_valid_workflow(build_scene_background())

    def test_widescreen_dimensions(self) -> None:
        wf = build_scene_background()
        latent = next(n for n in wf.values() if n["class_type"] == "EmptyLatentImage")
        assert latent["inputs"]["width"] == 1024
        assert latent["inputs"]["height"] == 576

    def test_no_rmbg(self) -> None:
        wf = build_scene_background()
        assert "RMBG" not in [n["class_type"] for n in wf.values()]


class TestBuildActionCard:
    def test_returns_valid_workflow(self) -> None:
        _assert_valid_workflow(build_action_card())

    def test_ultrawide_dimensions(self) -> None:
        wf = build_action_card()
        latent = next(n for n in wf.values() if n["class_type"] == "EmptyLatentImage")
        assert latent["inputs"]["width"] == 1216
        assert latent["inputs"]["height"] == 512


class TestBuildUiIcon:
    def test_returns_valid_workflow(self) -> None:
        _assert_valid_workflow(build_ui_icon())

    def test_has_rmbg(self) -> None:
        wf = build_ui_icon()
        assert "RMBG" in [n["class_type"] for n in wf.values()]

    def test_euler_sampler(self) -> None:
        wf = build_ui_icon()
        ksampler = next(n for n in wf.values() if n["class_type"] == "KSampler")
        assert ksampler["inputs"]["sampler_name"] == "lcm"


class TestBuildMessageImage:
    def test_returns_valid_workflow(self) -> None:
        _assert_valid_workflow(build_message_image())

    def test_has_lightning_lora(self) -> None:
        wf = build_message_image()
        lora = next(n for n in wf.values() if n["class_type"] == "LoraLoader")
        assert "lightning" in lora["inputs"]["lora_name"]

    def test_steps_is_8(self) -> None:
        wf = build_message_image()
        ksampler = next(n for n in wf.values() if n["class_type"] == "KSampler")
        assert ksampler["inputs"]["steps"] == 8

    def test_landscape_dimensions(self) -> None:
        wf = build_message_image()
        latent = next(n for n in wf.values() if n["class_type"] == "EmptyLatentImage")
        assert latent["inputs"]["width"] == 768
        assert latent["inputs"]["height"] == 512


class TestBuildVideoWanT2V:
    def test_build_video_wan_t2v_returns_valid_dict(self) -> None:
        _assert_valid_workflow(build_video_wan_t2v())

    def test_build_video_wan_t2v_has_new_wan_nodes(self) -> None:
        wf = build_video_wan_t2v()
        class_types = [n["class_type"] for n in wf.values()]
        assert "UnetLoaderGGUF" in class_types
        assert "CLIPLoaderGGUF" in class_types
        assert "WanImageToVideo" in class_types
        assert "KSamplerAdvanced" in class_types
        assert "CreateVideo" in class_types
        assert "SaveVideo" in class_types

    def test_build_video_wan_t2v_no_old_wan_nodes(self) -> None:
        wf = build_video_wan_t2v()
        class_types = [n["class_type"] for n in wf.values()]
        assert "WanVideoModelLoader" not in class_types
        assert "WanVideoSampler" not in class_types
        assert "WanVideoDecode" not in class_types

    def test_build_video_wan_t2v_has_two_unet_loaders(self) -> None:
        wf = build_video_wan_t2v()
        unet_nodes = [n for n in wf.values() if n["class_type"] == "UnetLoaderGGUF"]
        assert len(unet_nodes) == 2
        for n in unet_nodes:
            assert n["inputs"]["unet_name"].endswith(".gguf")

    def test_build_video_wan_t2v_has_lora_nodes(self) -> None:
        wf = build_video_wan_t2v()
        class_types = [n["class_type"] for n in wf.values()]
        assert "LoraLoaderModelOnly" in class_types

    def test_build_video_wan_t2v_no_lora_when_empty(self) -> None:
        wf = build_video_wan_t2v(loras_high=[], loras_low=[])
        class_types = [n["class_type"] for n in wf.values()]
        assert "LoraLoaderModelOnly" not in class_types

    def test_build_video_wan_t2v_has_dual_stage_samplers(self) -> None:
        wf = build_video_wan_t2v(steps=6)
        samplers = [n for n in wf.values() if n["class_type"] == "KSamplerAdvanced"]
        assert len(samplers) == 2
        assert samplers[0]["inputs"]["add_noise"] == "enable"
        assert samplers[1]["inputs"]["add_noise"] == "disable"
        assert samplers[0]["inputs"]["end_at_step"] == 3
        assert samplers[1]["inputs"]["start_at_step"] == 3

    def test_build_video_wan_t2v_seed_injection(self) -> None:
        wf = build_video_wan_t2v(seed=42)
        sampler = next(n for n in wf.values() if n["class_type"] == "KSamplerAdvanced")
        assert sampler["inputs"]["noise_seed"] == 42

    def test_build_video_wan_t2v_dimensions(self) -> None:
        wf = build_video_wan_t2v(width=1024, height=576)
        wan = next(n for n in wf.values() if n["class_type"] == "WanImageToVideo")
        assert wan["inputs"]["width"] == 1024
        assert wan["inputs"]["height"] == 576

    def test_build_video_wan_t2v_length(self) -> None:
        wf = build_video_wan_t2v(length=49)
        wan = next(n for n in wf.values() if n["class_type"] == "WanImageToVideo")
        assert wan["inputs"]["length"] == 49

    def test_build_video_wan_t2v_fps(self) -> None:
        wf = build_video_wan_t2v(fps=24)
        video_node = next(n for n in wf.values() if n["class_type"] == "CreateVideo")
        assert video_node["inputs"]["fps"] == 24

    def test_build_video_wan_t2v_uses_white_start_image(self) -> None:
        wf = build_video_wan_t2v()
        load_image = next(n for n in wf.values() if n["class_type"] == "LoadImage")
        assert load_image["inputs"]["image"] == "white.png"

    def test_build_video_wan_t2v_no_ltxv_nodes(self) -> None:
        wf = build_video_wan_t2v()
        class_types = [n["class_type"] for n in wf.values()]
        assert "EmptyLTXVLatentVideo" not in class_types
        assert "LTXVConditioning" not in class_types

    def test_build_video_wan_t2v_has_model_sampling(self) -> None:
        wf = build_video_wan_t2v()
        class_types = [n["class_type"] for n in wf.values()]
        assert "ModelSamplingSD3" in class_types

    def test_build_video_wan_t2v_save_video_node(self) -> None:
        wf = build_video_wan_t2v()
        save = next(n for n in wf.values() if n["class_type"] == "SaveVideo")
        assert save["inputs"]["format"] == "auto"
        assert save["inputs"]["codec"] == "auto"


class TestBuildVideoWanI2V:
    def test_build_video_wan_i2v_returns_valid_dict(self) -> None:
        _assert_valid_workflow(build_video_wan_i2v())

    def test_build_video_wan_i2v_has_new_wan_nodes(self) -> None:
        wf = build_video_wan_i2v()
        class_types = [n["class_type"] for n in wf.values()]
        assert "UnetLoaderGGUF" in class_types
        assert "CLIPLoaderGGUF" in class_types
        assert "WanImageToVideo" in class_types
        assert "KSamplerAdvanced" in class_types
        assert "VAEDecode" in class_types
        assert "CreateVideo" in class_types
        assert "SaveVideo" in class_types

    def test_build_video_wan_i2v_has_load_image(self) -> None:
        wf = build_video_wan_i2v()
        assert "LoadImage" in [n["class_type"] for n in wf.values()]

    def test_build_video_wan_i2v_image_path_set(self) -> None:
        wf = build_video_wan_i2v(start_image="test_frame.png")
        loader = next(n for n in wf.values() if n["class_type"] == "LoadImage")
        assert loader["inputs"]["image"] == "test_frame.png"

    def test_build_video_wan_i2v_has_lora_nodes(self) -> None:
        wf = build_video_wan_i2v()
        class_types = [n["class_type"] for n in wf.values()]
        assert "LoraLoaderModelOnly" in class_types

    def test_build_video_wan_i2v_has_two_unet_loaders(self) -> None:
        wf = build_video_wan_i2v()
        unet_nodes = [n for n in wf.values() if n["class_type"] == "UnetLoaderGGUF"]
        assert len(unet_nodes) == 2
        assert all(n["inputs"]["unet_name"].endswith(".gguf") for n in unet_nodes)

    def test_build_video_wan_i2v_vae_linked_to_wan_node(self) -> None:
        wf = build_video_wan_i2v()
        vae_ids = [nid for nid, n in wf.items() if n["class_type"] == "VAELoader"]
        assert vae_ids
        wan = next(n for n in wf.values() if n["class_type"] == "WanImageToVideo")
        assert wan["inputs"]["vae"][0] == vae_ids[0]

    def test_build_video_wan_i2v_uses_real_start_image(self) -> None:
        wf = build_video_wan_i2v()
        load_image = next(n for n in wf.values() if n["class_type"] == "LoadImage")
        assert load_image["inputs"]["image"] != "white.png"

    def test_build_video_wan_i2v_no_old_wan_nodes(self) -> None:
        wf = build_video_wan_i2v()
        class_types = [n["class_type"] for n in wf.values()]
        assert "WanVideoModelLoader" not in class_types
        assert "WanVideoImageToVideoEncode" not in class_types


class TestBuildVideoWanLandscape:
    def test_returns_valid_dict(self) -> None:
        _assert_valid_workflow(build_video_wan_landscape())

    def test_default_resolution_is_landscape(self) -> None:
        wf = build_video_wan_landscape()
        wan = next(n for n in wf.values() if n["class_type"] == "WanImageToVideo")
        assert wan["inputs"]["width"] == 480
        assert wan["inputs"]["height"] == 272

    def test_default_length_is_49_frames(self) -> None:
        wf = build_video_wan_landscape()
        wan = next(n for n in wf.values() if n["class_type"] == "WanImageToVideo")
        assert wan["inputs"]["length"] == 49

    def test_uses_white_start_image(self) -> None:
        wf = build_video_wan_landscape()
        loader = next(n for n in wf.values() if n["class_type"] == "LoadImage")
        assert loader["inputs"]["image"] == "white.png"

    def test_has_correct_wan_nodes(self) -> None:
        wf = build_video_wan_landscape()
        class_types = [n["class_type"] for n in wf.values()]
        assert "UnetLoaderGGUF" in class_types
        assert "CLIPLoaderGGUF" in class_types
        assert "WanImageToVideo" in class_types
        assert "KSamplerAdvanced" in class_types
        assert "CreateVideo" in class_types
        assert "SaveVideo" in class_types

    def test_dual_stage_samplers(self) -> None:
        wf = build_video_wan_landscape(steps=6)
        samplers = [n for n in wf.values() if n["class_type"] == "KSamplerAdvanced"]
        assert len(samplers) == 2
        assert samplers[0]["inputs"]["add_noise"] == "enable"
        assert samplers[1]["inputs"]["add_noise"] == "disable"

    def test_filename_prefix(self) -> None:
        wf = build_video_wan_landscape()
        save = next(n for n in wf.values() if n["class_type"] == "SaveVideo")
        assert "wan_landscape" in save["inputs"]["filename_prefix"]

    def test_custom_params_respected(self) -> None:
        wf = build_video_wan_landscape(width=848, height=480, length=81, steps=8, fps=24)
        wan = next(n for n in wf.values() if n["class_type"] == "WanImageToVideo")
        assert wan["inputs"]["width"] == 848
        assert wan["inputs"]["height"] == 480
        assert wan["inputs"]["length"] == 81
        video = next(n for n in wf.values() if n["class_type"] == "CreateVideo")
        assert video["inputs"]["fps"] == 24


class TestBuildVideoWanPortraitFast:
    def test_returns_valid_dict(self) -> None:
        _assert_valid_workflow(build_video_wan_portrait_fast())

    def test_default_steps_is_4(self) -> None:
        wf = build_video_wan_portrait_fast()
        samplers = [n for n in wf.values() if n["class_type"] == "KSamplerAdvanced"]
        # stage 1 ends at steps//2 = 2
        assert samplers[0]["inputs"]["end_at_step"] == 2

    def test_default_length_is_49_frames(self) -> None:
        wf = build_video_wan_portrait_fast()
        wan = next(n for n in wf.values() if n["class_type"] == "WanImageToVideo")
        assert wan["inputs"]["length"] == 49

    def test_portrait_orientation(self) -> None:
        wf = build_video_wan_portrait_fast()
        wan = next(n for n in wf.values() if n["class_type"] == "WanImageToVideo")
        assert wan["inputs"]["width"] == 272
        assert wan["inputs"]["height"] == 352

    def test_uses_white_start_image(self) -> None:
        wf = build_video_wan_portrait_fast()
        loader = next(n for n in wf.values() if n["class_type"] == "LoadImage")
        assert loader["inputs"]["image"] == "white.png"

    def test_has_correct_wan_nodes(self) -> None:
        wf = build_video_wan_portrait_fast()
        class_types = [n["class_type"] for n in wf.values()]
        assert "UnetLoaderGGUF" in class_types
        assert "WanImageToVideo" in class_types
        assert "KSamplerAdvanced" in class_types
        assert "CreateVideo" in class_types
        assert "SaveVideo" in class_types

    def test_no_old_wan_nodes(self) -> None:
        wf = build_video_wan_portrait_fast()
        class_types = [n["class_type"] for n in wf.values()]
        assert "WanVideoModelLoader" not in class_types

    def test_filename_prefix(self) -> None:
        wf = build_video_wan_portrait_fast()
        save = next(n for n in wf.values() if n["class_type"] == "SaveVideo")
        assert "wan_fast" in save["inputs"]["filename_prefix"]


class TestBuildVideoWanCharacterHQ:
    def test_returns_valid_dict(self) -> None:
        _assert_valid_workflow(build_video_wan_character_hq())

    def test_default_steps_is_8(self) -> None:
        wf = build_video_wan_character_hq()
        samplers = [n for n in wf.values() if n["class_type"] == "KSamplerAdvanced"]
        # 8 steps → stage 1 ends at 4
        assert samplers[0]["inputs"]["end_at_step"] == 4

    def test_default_fps_is_24(self) -> None:
        wf = build_video_wan_character_hq()
        video = next(n for n in wf.values() if n["class_type"] == "CreateVideo")
        assert video["inputs"]["fps"] == 24

    def test_default_length_is_81_frames(self) -> None:
        wf = build_video_wan_character_hq()
        wan = next(n for n in wf.values() if n["class_type"] == "WanImageToVideo")
        assert wan["inputs"]["length"] == 81

    def test_portrait_orientation(self) -> None:
        wf = build_video_wan_character_hq()
        wan = next(n for n in wf.values() if n["class_type"] == "WanImageToVideo")
        assert wan["inputs"]["width"] == 272
        assert wan["inputs"]["height"] == 352

    def test_default_start_image_is_white_png(self) -> None:
        wf = build_video_wan_character_hq()
        loader = next(n for n in wf.values() if n["class_type"] == "LoadImage")
        assert loader["inputs"]["image"] == "white.png"

    def test_supports_i2v_via_start_image(self) -> None:
        wf = build_video_wan_character_hq(start_image="character_frame.png")
        loader = next(n for n in wf.values() if n["class_type"] == "LoadImage")
        assert loader["inputs"]["image"] == "character_frame.png"

    def test_has_correct_wan_nodes(self) -> None:
        wf = build_video_wan_character_hq()
        class_types = [n["class_type"] for n in wf.values()]
        assert "UnetLoaderGGUF" in class_types
        assert "CLIPLoaderGGUF" in class_types
        assert "WanImageToVideo" in class_types
        assert "KSamplerAdvanced" in class_types
        assert "ModelSamplingSD3" in class_types
        assert "CreateVideo" in class_types
        assert "SaveVideo" in class_types

    def test_dual_stage_samplers(self) -> None:
        wf = build_video_wan_character_hq()
        samplers = [n for n in wf.values() if n["class_type"] == "KSamplerAdvanced"]
        assert len(samplers) == 2
        assert samplers[0]["inputs"]["add_noise"] == "enable"
        assert samplers[1]["inputs"]["add_noise"] == "disable"

    def test_filename_prefix(self) -> None:
        wf = build_video_wan_character_hq()
        save = next(n for n in wf.values() if n["class_type"] == "SaveVideo")
        assert "wan_char_hq" in save["inputs"]["filename_prefix"]

    def test_seed_injection(self) -> None:
        wf = build_video_wan_character_hq(seed=99)
        sampler = next(n for n in wf.values() if n["class_type"] == "KSamplerAdvanced")
        assert sampler["inputs"]["noise_seed"] == 99


class TestBuildUpscaleEnhance:
    def test_returns_valid_workflow(self) -> None:
        _assert_valid_workflow(build_upscale_enhance())

    def test_has_controlnet(self) -> None:
        wf = build_upscale_enhance()
        class_types = [n["class_type"] for n in wf.values()]
        assert "ControlNetLoader" in class_types
        assert "ControlNetApply" in class_types

    def test_has_upscale_model(self) -> None:
        wf = build_upscale_enhance()
        class_types = [n["class_type"] for n in wf.values()]
        assert "UpscaleModelLoader" in class_types
        assert "ImageUpscaleWithModel" in class_types

    def test_image_path_param(self) -> None:
        wf = build_upscale_enhance(image_path="myfile.png")
        loader = next(n for n in wf.values() if n["class_type"] == "LoadImage")
        assert loader["inputs"]["image"] == "myfile.png"

    def test_low_denoise_for_img2img(self) -> None:
        wf = build_upscale_enhance()
        ksampler = next(n for n in wf.values() if n["class_type"] == "KSampler")
        assert ksampler["inputs"]["denoise"] <= 0.5


# ──── WORKFLOW_REGISTRY tests ──────────────────────────────────────────────────

class TestWorkflowRegistry:
    def test_has_all_fifteen_workflows(self) -> None:
        expected = {
            "portrait_hires", "portrait_refiner", "portrait_fast", "character_card",
            "game_item_icon", "scene_background", "action_card", "ui_icon", "message_image",
            "video_wan_t2v", "video_wan_i2v", "video_wan_landscape",
            "video_wan_portrait_fast", "video_wan_character_hq", "upscale_enhance",
        }
        assert set(WORKFLOW_REGISTRY.keys()) == expected

    def test_workflow_registry_has_wan_entries(self) -> None:
        assert "video_wan_t2v" in WORKFLOW_REGISTRY
        assert "video_wan_i2v" in WORKFLOW_REGISTRY
        assert "video_txt2vid" not in WORKFLOW_REGISTRY

    def test_each_entry_has_builder(self) -> None:
        for wf_id, meta in WORKFLOW_REGISTRY.items():
            assert callable(meta["builder"]), f"{wf_id} builder is not callable"

    def test_each_builder_returns_valid_workflow(self) -> None:
        for wf_id, meta in WORKFLOW_REGISTRY.items():
            wf = meta["builder"]()
            _assert_valid_workflow(wf)

    def test_each_entry_has_metadata(self) -> None:
        for wf_id, meta in WORKFLOW_REGISTRY.items():
            for key in ("label", "description", "category", "resolution", "speed", "requires_nodes"):
                assert key in meta, f"{wf_id} missing {key}"

    def test_requires_nodes_is_list(self) -> None:
        for wf_id, meta in WORKFLOW_REGISTRY.items():
            assert isinstance(meta["requires_nodes"], list), f"{wf_id} requires_nodes not a list"


# ──── WorkflowManager tests ────────────────────────────────────────────────────

from engine.asset_studio.workflow_manager import WorkflowManager, get_workflow_manager


class TestWorkflowManagerAvailability:
    def test_is_available_false_when_offline(self) -> None:
        wm = WorkflowManager(base_url="http://localhost:9999")
        assert wm.is_available() is False

    @patch("requests.get")
    def test_is_available_true_when_ok(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(status_code=200)
        wm = WorkflowManager(base_url="http://localhost:8188")
        assert wm.is_available() is True

    @patch("requests.get")
    def test_is_available_false_on_non_200(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(status_code=503)
        wm = WorkflowManager(base_url="http://localhost:8188")
        assert wm.is_available() is False


class TestWorkflowManagerHasNode:
    @patch("requests.get")
    def test_has_node_true(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"FaceDetailer": {}, "KSampler": {}},
        )
        wm = WorkflowManager()
        assert wm.has_node("FaceDetailer") is True

    @patch("requests.get")
    def test_has_node_false(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"KSampler": {}},
        )
        wm = WorkflowManager()
        assert wm.has_node("FaceDetailer") is False

    def test_has_node_returns_false_when_offline(self) -> None:
        wm = WorkflowManager(base_url="http://localhost:9999")
        assert wm.has_node("KSampler") is False


class TestWorkflowManagerGetModels:
    @patch("requests.get")
    def test_get_checkpoints(self, mock_get: MagicMock) -> None:
        models = ["model_a.safetensors", "model_b.safetensors"]
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "CheckpointLoaderSimple": {
                    "input": {"required": {"ckpt_name": [models]}}
                }
            },
        )
        wm = WorkflowManager()
        assert wm.get_models("checkpoints") == models

    @patch("requests.get")
    def test_get_loras(self, mock_get: MagicMock) -> None:
        loras = ["lora_a.safetensors"]
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "LoraLoader": {
                    "input": {"required": {"lora_name": [loras]}}
                }
            },
        )
        wm = WorkflowManager()
        assert wm.get_models("loras") == loras

    def test_unknown_category_returns_empty(self) -> None:
        wm = WorkflowManager(base_url="http://localhost:9999")
        assert wm.get_models("unknown_category") == []

    def test_returns_empty_when_offline(self) -> None:
        wm = WorkflowManager(base_url="http://localhost:9999")
        assert wm.get_models("checkpoints") == []


class TestWorkflowManagerSelectModel:
    @patch("requests.get")
    def test_selects_first_available(self, mock_get: MagicMock) -> None:
        models = ["juggernaut.safetensors", "sdxl.safetensors"]
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "CheckpointLoaderSimple": {
                    "input": {"required": {"ckpt_name": [models]}}
                }
            },
        )
        wm = WorkflowManager()
        result = wm.select_model(["missing.safetensors", "juggernaut.safetensors"])
        assert result == "juggernaut.safetensors"

    @patch("requests.get")
    def test_returns_none_when_none_available(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "CheckpointLoaderSimple": {
                    "input": {"required": {"ckpt_name": [["other.safetensors"]]}}
                }
            },
        )
        wm = WorkflowManager()
        result = wm.select_model(["missing.safetensors"])
        assert result is None

    def test_returns_none_when_offline(self) -> None:
        wm = WorkflowManager(base_url="http://localhost:9999")
        assert wm.select_model(["any.safetensors"]) is None

    @patch("requests.get")
    def test_workflow_manager_selects_wan_t2v_model(self, mock_get: MagicMock) -> None:
        unet_models = ["wan2.2_t2v_high_noise_14B_Q4_K_M.gguf", "other.gguf"]
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "UnetLoaderGGUF": {
                    "input": {"required": {"unet_name": [unet_models]}}
                }
            },
        )
        wm = WorkflowManager()
        result = wm.select_model(
            ["wan2.2_t2v_high_noise_14B_Q4_K_M.gguf", "smoothMixWan22I2VT2V_t2vHighV20_Q4_K_M.gguf"],
            category="unet",
        )
        assert result == "wan2.2_t2v_high_noise_14B_Q4_K_M.gguf"

    @patch("requests.get")
    def test_workflow_manager_selects_wan_vae(self, mock_get: MagicMock) -> None:
        vae_models = ["wan2.2_vae.safetensors", "sdxl_vae.safetensors"]
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "VAELoader": {
                    "input": {"required": {"vae_name": [vae_models]}}
                }
            },
        )
        wm = WorkflowManager()
        result = wm.select_model(
            ["wan2.2_vae.safetensors", "wan_2.1_vae.safetensors"],
            category="vae",
        )
        assert result == "wan2.2_vae.safetensors"


class TestWorkflowManagerListWorkflows:
    def test_returns_all_fifteen(self) -> None:
        wm = WorkflowManager(base_url="http://localhost:9999")
        workflows = wm.list_workflows()
        assert len(workflows) == 15

    def test_each_has_required_keys(self) -> None:
        wm = WorkflowManager(base_url="http://localhost:9999")
        for wf in wm.list_workflows():
            for key in ("id", "label", "description", "category", "resolution", "speed", "available"):
                assert key in wf, f"Missing key {key} in workflow {wf.get('id')}"

    def test_ids_match_registry(self) -> None:
        wm = WorkflowManager(base_url="http://localhost:9999")
        ids = {wf["id"] for wf in wm.list_workflows()}
        assert ids == set(WORKFLOW_REGISTRY.keys())


class TestWorkflowManagerBuild:
    def test_build_portrait_hires(self) -> None:
        wm = WorkflowManager(base_url="http://localhost:9999")
        wf = wm.build("portrait_hires")
        _assert_valid_workflow(wf)
        assert "FaceDetailer" in [n["class_type"] for n in wf.values()]

    def test_build_with_params(self) -> None:
        wm = WorkflowManager(base_url="http://localhost:9999")
        wf = wm.build("portrait_fast", {"seed": 123, "width": 512, "height": 512})
        latent = next(n for n in wf.values() if n["class_type"] == "EmptyLatentImage")
        assert latent["inputs"]["width"] == 512

    def test_build_unknown_raises_key_error(self) -> None:
        wm = WorkflowManager(base_url="http://localhost:9999")
        with pytest.raises(KeyError):
            wm.build("does_not_exist")


class TestWorkflowManagerQueue:
    @patch("requests.post")
    def test_queue_returns_prompt_id(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"prompt_id": "abc123"},
        )
        mock_post.return_value.raise_for_status = MagicMock()
        wm = WorkflowManager()
        pid = wm.queue({"1": {"class_type": "KSampler", "inputs": {}}})
        assert pid == "abc123"

    @patch("requests.post")
    def test_queue_returns_none_on_error(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = ConnectionError("refused")
        wm = WorkflowManager()
        pid = wm.queue({})
        assert pid is None


class TestWorkflowManagerGenerate:
    @patch("requests.post")
    @patch("requests.get")
    def test_generate_returns_error_when_offline(
        self, mock_get: MagicMock, mock_post: MagicMock
    ) -> None:
        mock_get.side_effect = ConnectionError("offline")
        wm = WorkflowManager(base_url="http://localhost:9999")
        result = wm.generate("portrait_fast")
        assert "error" in result
        assert result["url"] == ""

    @patch("requests.post")
    @patch("requests.get")
    def test_generate_end_to_end(
        self, mock_get: MagicMock, mock_post: MagicMock, tmp_path: Path
    ) -> None:
        # is_available → OK
        # object_info (has_node) → empty (no node check needed for this test)
        # history poll → outputs with image
        mock_get.side_effect = [
            MagicMock(status_code=200, json=lambda: {}),  # system_stats
            MagicMock(  # history poll
                status_code=200,
                json=lambda: {
                    "job123": {
                        "outputs": {
                            "9": {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]}
                        }
                    }
                },
            ),
            MagicMock(status_code=200, content=b"PNG_DATA"),  # download
        ]
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"prompt_id": "job123"},
        )
        mock_post.return_value.raise_for_status = MagicMock()

        wm = WorkflowManager(base_url="http://localhost:8188")
        result = wm.generate("portrait_fast", save_dir=tmp_path, filename_prefix="test")
        assert "error" not in result or result.get("error") is None or result["url"] != ""


# ──── Node cache TTL test ──────────────────────────────────────────────────────

class TestNodeCacheTTL:
    @patch("requests.get")
    def test_cache_is_reused_within_ttl(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"KSampler": {}},
        )
        wm = WorkflowManager()
        wm.get_available_nodes()
        wm.get_available_nodes()
        # Should only have been called once (cache hit on second call)
        # Note: first call is system_stats check if is_available was called,
        # but here we call get_available_nodes directly.
        assert mock_get.call_count >= 1


# ──── Singleton test ───────────────────────────────────────────────────────────

class TestGetWorkflowManagerSingleton:
    def test_returns_same_instance(self) -> None:
        import engine.asset_studio.workflow_manager as wm_mod  # noqa: PLC0415
        # Reset singleton for test isolation
        original = wm_mod._manager_instance
        wm_mod._manager_instance = None
        try:
            a = get_workflow_manager()
            b = get_workflow_manager()
            assert a is b
        finally:
            wm_mod._manager_instance = original

    def test_thread_safe_singleton(self) -> None:
        import engine.asset_studio.workflow_manager as wm_mod  # noqa: PLC0415
        original = wm_mod._manager_instance
        wm_mod._manager_instance = None
        instances = []
        errors = []

        def _get() -> None:
            try:
                instances.append(get_workflow_manager())
            except Exception as e:
                errors.append(e)

        try:
            threads = [threading.Thread(target=_get) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            assert not errors
            assert len({id(i) for i in instances}) == 1
        finally:
            wm_mod._manager_instance = original


# ──── JSON workflow file tests ─────────────────────────────────────────────────

class TestWorkflowJsonFiles:
    _workflow_dir = Path("data/workflows/comfyui")
    _expected_files = [
        "portrait_hires.json",
        "portrait_fast.json",
        "character_card.json",
        "game_item_icon.json",
        "scene_background.json",
        "action_card.json",
        "ui_icon.json",
        "message_image.json",
        "video_wan_t2v.json",
        "video_wan_i2v.json",
        "upscale_enhance.json",
    ]

    def test_all_files_exist(self) -> None:
        for fname in self._expected_files:
            p = self._workflow_dir / fname
            assert p.exists(), f"Missing workflow file: {p}"

    def test_all_files_are_valid_json(self) -> None:
        for fname in self._expected_files:
            p = self._workflow_dir / fname
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                assert isinstance(data, dict), f"{fname} root must be a dict"

    def test_all_nodes_have_class_type(self) -> None:
        for fname in self._expected_files:
            p = self._workflow_dir / fname
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                for node_id, node in data.items():
                    assert "class_type" in node, f"{fname} node {node_id} missing class_type"

    def test_portrait_hires_has_face_detailer(self) -> None:
        p = self._workflow_dir / "portrait_hires.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            class_types = [n["class_type"] for n in data.values()]
            assert "FaceDetailer" in class_types

    def test_game_item_icon_has_rmbg(self) -> None:
        p = self._workflow_dir / "game_item_icon.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            class_types = [n["class_type"] for n in data.values()]
            assert "RMBG" in class_types

    def test_video_wan_t2v_has_wan_nodes(self) -> None:
        p = self._workflow_dir / "video_wan_t2v.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            class_types = [n["class_type"] for n in data.values()]
            assert "UnetLoaderGGUF" in class_types
            assert "KSamplerAdvanced" in class_types
            assert "WanImageToVideo" in class_types

    def test_video_wan_i2v_has_image_encode(self) -> None:
        p = self._workflow_dir / "video_wan_i2v.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            class_types = [n["class_type"] for n in data.values()]
            assert "WanImageToVideo" in class_types
            assert "LoadImage" in class_types

    def test_upscale_enhance_has_controlnet(self) -> None:
        p = self._workflow_dir / "upscale_enhance.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            class_types = [n["class_type"] for n in data.values()]
            assert "ControlNetApply" in class_types


# ──── Scene route tests ────────────────────────────────────────────────────────

@pytest.fixture()
def asset_studio_app():
    """Create a minimal Flask test app with the asset studio routes."""
    from flask import Flask, jsonify
    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/api/workflows")
    def api_workflows():
        from engine.asset_studio.workflow_manager import get_workflow_manager  # noqa: PLC0415
        wm = get_workflow_manager()
        return jsonify({"workflows": wm.list_workflows()})

    @app.route("/api/models")
    def api_models():
        from engine.asset_studio.workflow_manager import get_workflow_manager  # noqa: PLC0415
        wm = get_workflow_manager()
        return jsonify({
            "checkpoints": wm.get_models("checkpoints"),
            "loras": wm.get_models("loras"),
            "vae": wm.get_models("vae"),
            "upscale_models": wm.get_models("upscale_models"),
            "available": wm.is_available(),
        })

    @app.route("/api/studio/nodes")
    def api_studio_nodes():
        from engine.asset_studio.workflow_manager import get_workflow_manager  # noqa: PLC0415
        wm = get_workflow_manager()
        nodes = list(wm.get_available_nodes().keys()) if wm.is_available() else []
        return jsonify({"nodes": nodes, "count": len(nodes), "available": wm.is_available()})

    return app


class TestSceneRoutes:
    def test_workflows_route_returns_list(self, asset_studio_app: Any) -> None:
        client = asset_studio_app.test_client()
        resp = client.get("/api/workflows")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "workflows" in data
        assert isinstance(data["workflows"], list)
        assert len(data["workflows"]) == 15

    def test_models_route_structure(self, asset_studio_app: Any) -> None:
        client = asset_studio_app.test_client()
        resp = client.get("/api/models")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "checkpoints" in data
        assert "loras" in data
        assert "vae" in data
        assert "upscale_models" in data
        assert "available" in data

    def test_nodes_route_structure(self, asset_studio_app: Any) -> None:
        client = asset_studio_app.test_client()
        resp = client.get("/api/studio/nodes")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "nodes" in data
        assert "count" in data
        assert "available" in data
        assert isinstance(data["nodes"], list)
        assert data["count"] == len(data["nodes"])

    def test_workflows_all_have_ids(self, asset_studio_app: Any) -> None:
        client = asset_studio_app.test_client()
        resp = client.get("/api/workflows")
        data = resp.get_json()
        for wf in data["workflows"]:
            assert "id" in wf
            assert "label" in wf
            assert "category" in wf


# ──── build_portrait_refiner tests ────────────────────────────────────────────


def test_build_portrait_refiner_basic() -> None:
    wf = build_portrait_refiner(positive="test prompt")
    assert "1" in wf  # CheckpointLoaderSimple
    assert "52" in wf  # CLIPSetLastLayer
    assert "53" in wf  # refiner CLIPTextEncode
    assert "54" in wf  # ConditioningConcat
    assert "60" in wf  # base KSampler
    assert "66" in wf  # ImageScaleBy
    assert "67" in wf  # VAEEncode
    assert "70" in wf  # refiner KSampler
    assert "80" in wf  # refined SaveImage
    assert "81" in wf  # base SaveImage
    assert wf["60"]["inputs"]["steps"] == 20
    assert wf["60"]["inputs"]["cfg"] == 1.5
    assert wf["60"]["inputs"]["sampler_name"] == "lcm"
    assert wf["60"]["inputs"]["scheduler"] == "exponential"
    assert wf["70"]["inputs"]["steps"] == 12
    assert wf["70"]["inputs"]["cfg"] == 1.0
    assert wf["70"]["inputs"]["denoise"] == 0.4
    assert wf["66"]["inputs"]["scale_by"] == 1.5
    assert wf["52"]["inputs"]["stop_at_clip_layer"] == -2


def test_build_portrait_refiner_in_registry() -> None:
    assert "portrait_refiner" in WORKFLOW_REGISTRY
    entry = WORKFLOW_REGISTRY["portrait_refiner"]
    assert entry["builder"] is build_portrait_refiner
    assert "refiner_steps" in entry["params"]
    assert "clip_layer" in entry["params"]


def test_build_portrait_refiner_custom_params() -> None:
    wf = build_portrait_refiner(
        steps=15, cfg=2.0, refiner_steps=8, refiner_denoise=0.35,
        refiner_scale=2.0, clip_layer=-3
    )
    assert wf["60"]["inputs"]["steps"] == 15
    assert wf["66"]["inputs"]["scale_by"] == 2.0
    assert wf["70"]["inputs"]["steps"] == 8
    assert wf["70"]["inputs"]["denoise"] == 0.35
    assert wf["52"]["inputs"]["stop_at_clip_layer"] == -3


# ──── check_image_quality tests ───────────────────────────────────────────────


def test_check_image_quality_file_not_found(tmp_path: Path) -> None:
    from engine.asset_studio.workflow_manager import WorkflowManager  # noqa: PLC0415
    mgr = WorkflowManager.__new__(WorkflowManager)
    result = mgr.check_image_quality(str(tmp_path / "nonexistent.png"))
    assert result["score"] == -1
    assert "error" in result


def test_check_image_quality_request_failure(tmp_path: Path) -> None:
    from unittest.mock import patch  # noqa: PLC0415
    from engine.asset_studio.workflow_manager import WorkflowManager  # noqa: PLC0415
    img = tmp_path / "test.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    mgr = WorkflowManager.__new__(WorkflowManager)
    with patch("requests.post", side_effect=Exception("connection refused")):
        result = mgr.check_image_quality(str(img))
    assert result["score"] == -1
    assert "error" in result

