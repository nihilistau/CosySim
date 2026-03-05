"""Tests for engine.integrations.colab_gpu_manager.

Covers the GPUTier enum, GPU tier selection logic, model-size routing,
CU budget checks, usage recording, the usage summary, budget top-ups,
JSON persistence, and the singleton factory.  No HTTP calls are made —
this is pure logic tested in isolation.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.integrations.colab_gpu_manager import (
    GPU_SPECS,
    TASK_GPU_MAP,
    ColabGPUManager,
    GPUTier,
    _DEFAULT_BUDGET_CU,
    _EMERGENCY_RESERVE_CU,
    get_gpu_manager,
)


# ──── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def manager(tmp_path: Path) -> ColabGPUManager:
    """Fresh ColabGPUManager using a temp budget file (no disk side-effects)."""
    return ColabGPUManager(budget_path=tmp_path / "cu_budget.json")


# ──── Tests: GPUTier enum ─────────────────────────────────────────────────────

class TestGPUTierEnum:
    """Tests for the GPUTier enum values and coverage."""

    def test_has_t4(self) -> None:
        """GPUTier should expose a T4 member with string value 'T4'."""
        assert GPUTier.T4 == "T4"

    def test_has_l4(self) -> None:
        """GPUTier should expose an L4 member with string value 'L4'."""
        assert GPUTier.L4 == "L4"

    def test_has_a100(self) -> None:
        """GPUTier should expose an A100 member with string value 'A100'."""
        assert GPUTier.A100 == "A100"

    def test_has_h100(self) -> None:
        """GPUTier should expose an H100 member with string value 'H100'."""
        assert GPUTier.H100 == "H100"

    def test_has_free(self) -> None:
        """GPUTier should expose a FREE (CPU-only) member with string value 'FREE'."""
        assert GPUTier.FREE == "FREE"

    def test_all_tiers_have_specs(self) -> None:
        """Every GPUTier member must have a corresponding entry in GPU_SPECS."""
        for tier in GPUTier:
            assert tier in GPU_SPECS, f"{tier} missing from GPU_SPECS"

    def test_specs_have_required_keys(self) -> None:
        """Each GPU_SPECS entry must contain cu_per_hour and vram_gb keys."""
        for tier, spec in GPU_SPECS.items():
            assert "cu_per_hour" in spec, f"{tier} missing cu_per_hour"
            assert "vram_gb" in spec, f"{tier} missing vram_gb"

    def test_tier_order_cheapest_to_most_expensive(self) -> None:
        """T4 should cost fewer CU/hr than L4, which should cost fewer than A100."""
        assert GPU_SPECS[GPUTier.T4]["cu_per_hour"] < GPU_SPECS[GPUTier.L4]["cu_per_hour"]
        assert GPU_SPECS[GPUTier.L4]["cu_per_hour"] < GPU_SPECS[GPUTier.A100]["cu_per_hour"]


# ──── Tests: select_gpu ───────────────────────────────────────────────────────

class TestSelectGpu:
    """Tests for ColabGPUManager.select_gpu task-based routing."""

    def test_inference_maps_to_t4(self, manager: ColabGPUManager) -> None:
        """'inference' task should return GPUTier.T4 per TASK_GPU_MAP."""
        assert manager.select_gpu("inference") == GPUTier.T4

    def test_inference_large_maps_to_l4(self, manager: ColabGPUManager) -> None:
        """'inference_large' task should return GPUTier.L4."""
        assert manager.select_gpu("inference_large") == GPUTier.L4

    def test_finetune_small_maps_to_l4(self, manager: ColabGPUManager) -> None:
        """'finetune_small' task (3B–7B LoRA) should return GPUTier.L4."""
        assert manager.select_gpu("finetune_small") == GPUTier.L4

    def test_finetune_medium_maps_to_a100(self, manager: ColabGPUManager) -> None:
        """'finetune_medium' task (7B–34B LoRA) should return GPUTier.A100."""
        assert manager.select_gpu("finetune_medium") == GPUTier.A100

    def test_finetune_large_maps_to_h100(self, manager: ColabGPUManager) -> None:
        """'finetune_large' task (34B+ full fine-tune) should return GPUTier.H100."""
        assert manager.select_gpu("finetune_large") == GPUTier.H100

    def test_unknown_task_falls_back_to_t4(self, manager: ColabGPUManager) -> None:
        """An unrecognised task type should default to T4 as the safe fallback."""
        result = manager.select_gpu("completely_unknown_task_xyz_abc")
        assert result == GPUTier.T4

    def test_model_size_overrides_to_higher_tier(
        self, manager: ColabGPUManager
    ) -> None:
        """When model_size requires more VRAM than the task default, the higher tier wins."""
        # 'inference' defaults to T4, but 70b requires ~42 GB → A100/H100
        result = manager.select_gpu("inference", model_size="70b")
        assert result in (GPUTier.A100, GPUTier.H100)

    def test_model_size_does_not_downgrade_tier(
        self, manager: ColabGPUManager
    ) -> None:
        """When task tier is already higher than model needs, task tier is kept."""
        # 'finetune_large' → H100; 0.6b model only needs T4 → result stays H100
        result = manager.select_gpu("finetune_large", model_size="0.6b")
        assert result == GPUTier.H100

    def test_prefer_cheap_returns_budget_friendly_tier(
        self, manager: ColabGPUManager
    ) -> None:
        """prefer_cheap=True should return a tier affordable within the current budget."""
        result = manager.select_gpu("finetune_large", prefer_cheap=True)
        # With default 190 CU budget, at least T4 (min_cu=0.1) must be affordable
        assert result in list(GPUTier)
        assert result != GPUTier.FREE  # should not fall to CPU-only

    def test_comfyui_maps_to_t4(self, manager: ColabGPUManager) -> None:
        """'comfyui' image generation task should map to T4."""
        assert manager.select_gpu("comfyui") == GPUTier.T4

    def test_vllm_server_maps_to_l4(self, manager: ColabGPUManager) -> None:
        """'vllm_server' task should map to L4 for sufficient VRAM."""
        assert manager.select_gpu("vllm_server") == GPUTier.L4


# ──── Tests: gpu_for_model_size ───────────────────────────────────────────────

class TestGpuForModelSize:
    """Tests for ColabGPUManager.gpu_for_model_size VRAM routing."""

    def test_7b_fits_in_t4(self, manager: ColabGPUManager) -> None:
        """7B model (6.5 GB VRAM at 4-bit) fits within T4's 16 GB VRAM."""
        assert manager.gpu_for_model_size("7b") == GPUTier.T4

    def test_8b_fits_in_t4(self, manager: ColabGPUManager) -> None:
        """8B model (7 GB VRAM at 4-bit) fits within T4's 16 GB VRAM."""
        assert manager.gpu_for_model_size("8b") == GPUTier.T4

    def test_70b_requires_a100_or_h100(self, manager: ColabGPUManager) -> None:
        """70B model (42 GB VRAM) requires at least A100 (40 GB) or H100 (80 GB)."""
        result = manager.gpu_for_model_size("70b")
        assert result in (GPUTier.A100, GPUTier.H100)

    def test_34b_requires_at_least_a100(self, manager: ColabGPUManager) -> None:
        """34B model (24 GB VRAM) exceeds L4's 22.5 GB → A100 or H100."""
        result = manager.gpu_for_model_size("34b")
        assert result in (GPUTier.A100, GPUTier.H100)

    def test_uppercase_size_normalised(self, manager: ColabGPUManager) -> None:
        """Model size '7B' (uppercase) should be normalised and resolve to T4."""
        assert manager.gpu_for_model_size("7B") == GPUTier.T4

    def test_unknown_model_size_defaults_to_t4(self, manager: ColabGPUManager) -> None:
        """An unrecognised model size string should fall back to T4."""
        assert manager.gpu_for_model_size("999b_imaginary") == GPUTier.T4

    def test_small_model_fits_t4(self, manager: ColabGPUManager) -> None:
        """0.6B model (1.5 GB VRAM) should comfortably fit in T4."""
        assert manager.gpu_for_model_size("0.6b") == GPUTier.T4

    def test_3b_fits_in_t4_or_l4(self, manager: ColabGPUManager) -> None:
        """3B model (4.5 GB VRAM) should fit in T4 (16 GB)."""
        result = manager.gpu_for_model_size("3b")
        # T4 has 16 GB → more than enough for 3b
        assert result in (GPUTier.T4, GPUTier.L4)


# ──── Tests: check_budget ─────────────────────────────────────────────────────

class TestCheckBudget:
    """Tests for ColabGPUManager.check_budget affordability gate."""

    def test_t4_short_session_is_affordable(self, manager: ColabGPUManager) -> None:
        """T4 × 10 hours = 5 CU; well within the 190 CU default budget."""
        assert manager.check_budget(GPUTier.T4, 10) is True

    def test_h100_100_hours_is_unaffordable(self, manager: ColabGPUManager) -> None:
        """H100 × 100 hours = 700 CU; exceeds 190 CU default budget."""
        assert manager.check_budget(GPUTier.H100, 100) is False

    def test_returns_false_at_emergency_reserve(
        self, manager: ColabGPUManager
    ) -> None:
        """check_budget should return False when remaining CU ≤ emergency reserve."""
        # Drive remaining balance to exactly the emergency reserve
        manager._budget = _EMERGENCY_RESERVE_CU
        manager._used = 0.0
        assert manager.check_budget(GPUTier.T4, 0.01) is False

    def test_returns_false_when_budget_exhausted(
        self, manager: ColabGPUManager
    ) -> None:
        """check_budget should return False when all CU have been used."""
        manager._used = manager._budget
        assert manager.check_budget(GPUTier.T4, 1.0) is False

    def test_exact_cost_equals_remaining_is_affordable(
        self, manager: ColabGPUManager
    ) -> None:
        """Session cost exactly equal to remaining CU should be considered affordable."""
        # Set budget to give us exactly 5 CU after the emergency reserve
        manager._budget = 5.0 + _EMERGENCY_RESERVE_CU + 0.1
        manager._used = _EMERGENCY_RESERVE_CU + 0.1
        # T4 × 10 hours = 5 CU = remaining
        assert manager.check_budget(GPUTier.T4, 10.0) is True

    def test_free_tier_always_affordable(self, manager: ColabGPUManager) -> None:
        """FREE tier costs 0 CU/hr, so it should always be affordable."""
        assert manager.check_budget(GPUTier.FREE, 1000) is True


# ──── Tests: estimate_cost ────────────────────────────────────────────────────

class TestEstimateCost:
    """Tests for ColabGPUManager.estimate_cost calculation."""

    def test_t4_two_hours(self, manager: ColabGPUManager) -> None:
        """T4 at 0.5 CU/hr × 2 hours should equal 1.0 CU."""
        assert abs(manager.estimate_cost(GPUTier.T4, 2.0) - 1.0) < 0.001

    def test_a100_one_hour(self, manager: ColabGPUManager) -> None:
        """A100 at 6.0 CU/hr × 1 hour should equal 6.0 CU."""
        assert abs(manager.estimate_cost(GPUTier.A100, 1.0) - 6.0) < 0.001

    def test_free_tier_zero_cost(self, manager: ColabGPUManager) -> None:
        """FREE tier should always estimate 0.0 CU regardless of hours."""
        assert manager.estimate_cost(GPUTier.FREE, 100.0) == 0.0


# ──── Tests: record_usage ─────────────────────────────────────────────────────

class TestRecordUsage:
    """Tests for ColabGPUManager.record_usage CU deduction and logging."""

    def test_deducts_correct_cu_amount(self, manager: ColabGPUManager) -> None:
        """record_usage should add tier_rate × hours to _used."""
        manager.record_usage(GPUTier.L4, 2.0)
        # L4 = 1.2 CU/hr × 2 hours = 2.4 CU
        assert abs(manager._used - 2.4) < 0.001

    def test_appends_entry_to_usage_log(self, manager: ColabGPUManager) -> None:
        """record_usage should append one entry to _usage_log."""
        manager.record_usage(GPUTier.T4, 1.0, "unit test job")
        assert len(manager._usage_log) == 1
        entry = manager._usage_log[0]
        assert entry["tier"] == "T4"
        assert entry["hours"] == 1.0
        assert entry["description"] == "unit test job"

    def test_remaining_cu_decreases_after_record(
        self, manager: ColabGPUManager
    ) -> None:
        """get_remaining_cu should report fewer CU after record_usage."""
        before = manager.get_remaining_cu()
        manager.record_usage(GPUTier.A100, 1.0)
        assert manager.get_remaining_cu() < before

    def test_multiple_records_accumulate(self, manager: ColabGPUManager) -> None:
        """Multiple record_usage calls should sum up in _used."""
        manager.record_usage(GPUTier.T4, 2.0)   # 1.0 CU
        manager.record_usage(GPUTier.L4, 1.0)   # 1.2 CU
        assert abs(manager._used - 2.2) < 0.001

    def test_log_entry_contains_timestamp(self, manager: ColabGPUManager) -> None:
        """Usage log entry should include an ISO-format timestamp."""
        manager.record_usage(GPUTier.T4, 0.5)
        ts = manager._usage_log[0]["timestamp"]
        assert "T" in ts  # ISO-8601 datetime contains 'T' separator


# ──── Tests: get_remaining_cu ─────────────────────────────────────────────────

class TestGetRemainingCu:
    """Tests for ColabGPUManager.get_remaining_cu floor behaviour."""

    def test_returns_budget_minus_used(self, manager: ColabGPUManager) -> None:
        """Remaining should equal budget - used when positive."""
        manager._budget = 100.0
        manager._used = 30.0
        assert abs(manager.get_remaining_cu() - 70.0) < 0.001

    def test_floors_at_zero(self, manager: ColabGPUManager) -> None:
        """Remaining CU should never go below zero."""
        manager._budget = 10.0
        manager._used = 20.0  # overspent
        assert manager.get_remaining_cu() == 0.0


# ──── Tests: get_usage_summary ────────────────────────────────────────────────

class TestGetUsageSummary:
    """Tests for ColabGPUManager.get_usage_summary reporting."""

    def test_returns_required_keys(self, manager: ColabGPUManager) -> None:
        """Summary dict must contain total_budget, used, remaining, and by_tier."""
        summary = manager.get_usage_summary()
        for key in ("total_budget", "used", "remaining", "by_tier"):
            assert key in summary, f"Missing key: {key}"

    def test_remaining_equals_budget_minus_used(
        self, manager: ColabGPUManager
    ) -> None:
        """Summary remaining should equal total_budget - used."""
        manager.record_usage(GPUTier.T4, 4.0)
        s = manager.get_usage_summary()
        assert abs(s["remaining"] - (s["total_budget"] - s["used"])) < 0.001

    def test_by_tier_tracks_multiple_tiers(self, manager: ColabGPUManager) -> None:
        """by_tier should have separate entries for each tier used."""
        manager.record_usage(GPUTier.T4, 2.0)
        manager.record_usage(GPUTier.L4, 1.0)
        by_tier = manager.get_usage_summary()["by_tier"]
        assert "T4" in by_tier
        assert "L4" in by_tier

    def test_by_tier_amounts_are_correct(self, manager: ColabGPUManager) -> None:
        """by_tier values should reflect actual CU spent per tier."""
        manager.record_usage(GPUTier.T4, 4.0)  # 4 × 0.5 = 2.0 CU
        by_tier = manager.get_usage_summary()["by_tier"]
        assert abs(by_tier["T4"] - 2.0) < 0.001

    def test_usage_log_in_summary(self, manager: ColabGPUManager) -> None:
        """Summary should include a usage_log list (possibly empty)."""
        summary = manager.get_usage_summary()
        assert isinstance(summary["usage_log"], list)


# ──── Tests: add_cu ───────────────────────────────────────────────────────────

class TestAddCu:
    """Tests for ColabGPUManager.add_cu top-up behaviour."""

    def test_increases_total_budget(self, manager: ColabGPUManager) -> None:
        """add_cu should increase _budget by the specified amount."""
        before = manager._budget
        manager.add_cu(50.0)
        assert manager._budget == pytest.approx(before + 50.0)

    def test_remaining_increases(self, manager: ColabGPUManager) -> None:
        """Remaining CU should grow after a top-up, even after prior spend."""
        manager.record_usage(GPUTier.A100, 5.0)  # spend 30 CU
        before = manager.get_remaining_cu()
        manager.add_cu(30.0)
        assert manager.get_remaining_cu() > before

    def test_fractional_top_up_accepted(self, manager: ColabGPUManager) -> None:
        """add_cu should accept fractional amounts without truncation."""
        manager.add_cu(0.75)
        assert manager._budget == pytest.approx(_DEFAULT_BUDGET_CU + 0.75)


# ──── Tests: persistence (save / load) ───────────────────────────────────────

class TestPersistence:
    """Tests for ColabGPUManager.save and load JSON persistence."""

    def test_save_creates_json_file(self, tmp_path: Path) -> None:
        """save() must create the budget JSON file (creating parent dirs if needed)."""
        budget_file = tmp_path / "sub" / "cu_budget.json"
        mgr = ColabGPUManager(budget_path=budget_file)
        mgr.save()
        assert budget_file.exists()

    def test_save_load_roundtrip_preserves_used(self, tmp_path: Path) -> None:
        """_used value saved by one instance should be restored by a new instance."""
        budget_file = tmp_path / "cu_budget.json"
        mgr1 = ColabGPUManager(budget_path=budget_file)
        mgr1.record_usage(GPUTier.L4, 3.0)   # 3.6 CU
        saved_used = mgr1._used

        mgr2 = ColabGPUManager(budget_path=budget_file)
        assert abs(mgr2._used - saved_used) < 0.001

    def test_load_missing_file_uses_defaults(self, tmp_path: Path) -> None:
        """When the budget file does not exist, defaults are used silently."""
        mgr = ColabGPUManager(budget_path=tmp_path / "nonexistent.json")
        assert mgr._budget == _DEFAULT_BUDGET_CU
        assert mgr._used == 0.0

    def test_usage_log_persists_across_instances(self, tmp_path: Path) -> None:
        """Usage log entries should survive a save/load cycle intact."""
        budget_file = tmp_path / "cu_budget.json"
        mgr1 = ColabGPUManager(budget_path=budget_file)
        mgr1.record_usage(GPUTier.T4, 1.0, "persistent task")

        mgr2 = ColabGPUManager(budget_path=budget_file)
        assert len(mgr2._usage_log) == 1
        assert mgr2._usage_log[0]["description"] == "persistent task"

    def test_add_cu_persists(self, tmp_path: Path) -> None:
        """Budget additions should be visible after reloading from disk."""
        budget_file = tmp_path / "cu_budget.json"
        mgr1 = ColabGPUManager(budget_path=budget_file)
        mgr1.add_cu(75.0)

        mgr2 = ColabGPUManager(budget_path=budget_file)
        assert mgr2._budget == pytest.approx(_DEFAULT_BUDGET_CU + 75.0)

    def test_saved_json_is_valid(self, tmp_path: Path) -> None:
        """The saved file should be valid JSON with expected top-level keys."""
        budget_file = tmp_path / "cu_budget.json"
        mgr = ColabGPUManager(budget_path=budget_file)
        mgr.record_usage(GPUTier.T4, 1.0)

        data = json.loads(budget_file.read_text(encoding="utf-8"))
        for key in ("budget", "used", "usage_log", "last_updated"):
            assert key in data, f"Missing key in saved JSON: {key}"

    def test_corrupt_file_handled_gracefully(self, tmp_path: Path) -> None:
        """A corrupt budget file should not raise; defaults should be used instead."""
        budget_file = tmp_path / "cu_budget.json"
        budget_file.write_text("NOT JSON {{{", encoding="utf-8")
        mgr = ColabGPUManager(budget_path=budget_file)
        # Should fall back to defaults without raising
        assert mgr._budget == _DEFAULT_BUDGET_CU


# ──── Tests: get_gpu_manager singleton ───────────────────────────────────────

class TestGetGpuManager:
    """Tests for the get_gpu_manager singleton factory."""

    def test_returns_colab_gpu_manager_instance(self) -> None:
        """get_gpu_manager should return a ColabGPUManager."""
        import engine.integrations.colab_gpu_manager as _mod
        _mod._instance = None  # reset singleton state
        try:
            mgr = get_gpu_manager()
            assert isinstance(mgr, ColabGPUManager)
        finally:
            _mod._instance = None  # clean up after test

    def test_singleton_returns_same_object(self) -> None:
        """Two consecutive calls to get_gpu_manager should return the same object."""
        import engine.integrations.colab_gpu_manager as _mod
        _mod._instance = None
        try:
            mgr1 = get_gpu_manager()
            mgr2 = get_gpu_manager()
            assert mgr1 is mgr2
        finally:
            _mod._instance = None

    def test_singleton_reset_creates_new_instance(self) -> None:
        """After resetting _instance, get_gpu_manager should create a fresh object."""
        import engine.integrations.colab_gpu_manager as _mod
        _mod._instance = None
        mgr1 = get_gpu_manager()
        _mod._instance = None
        mgr2 = get_gpu_manager()
        assert mgr1 is not mgr2
        _mod._instance = None
