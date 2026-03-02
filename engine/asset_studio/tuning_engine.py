"""Asset Studio Tuning Engine — profile management, benchmark runs, auto-tune via Qwen VL.

Proven profiles encode the best-known settings for each workflow type, seeded from the
user's working generate_Image.json (lcm/exponential/cfg=1.5/steps=20).  Benchmark runs
generate N images with param variants, score each with Qwen VL, and persist all metrics
to a local SQLite database.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from itertools import product
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from engine.config import get_config

logger = logging.getLogger(__name__)

# ──── Proven profiles ──────────────────────────────────────────────────────────
# These are the tuned defaults from the user's working generate_Image.json.
# All SDXL/Pony DMD2-merge models respond best to these settings.

PROVEN_PROFILES: Dict[str, Dict[str, Any]] = {
    "proven_portrait_fast": {
        "label": "Proven — Portrait Fast (generate_Image.json)",
        "workflow": "portrait_fast",
        "description": (
            "Exact settings from the working generate_Image.json profile. "
            "lcm sampler + exponential scheduler, cfg=1.5, 20 steps, Lightning 8-step LoRA."
        ),
        "params": {
            "steps": 20,
            "cfg": 1.5,
            "sampler_name": "lcm",
            "scheduler": "exponential",
            "denoise": 1.0,
            "width": 896,
            "height": 1152,
            "loras": [
                {"name": "sdxl_lightning_8step_lora.safetensors", "strength_model": 1.0, "strength_clip": 1.0, "enabled": True}
            ],
        },
        "source": "generate_Image.json",
        "vl_score": None,
        "gen_time_ms": None,
        "builtin": True,
    },
    "proven_portrait_refiner": {
        "label": "Proven — Portrait Refiner (dual-pass)",
        "workflow": "portrait_refiner",
        "description": (
            "Base (steps=20, cfg=1.5, lcm, exponential) → 1.5x upscale → "
            "img2img refiner (steps=12, cfg=1.0, denoise=0.4). CLIPSetLastLayer=-2."
        ),
        "params": {
            "steps": 20,
            "cfg": 1.5,
            "refiner_steps": 12,
            "refiner_cfg": 1.0,
            "refiner_denoise": 0.4,
            "refiner_scale": 1.5,
            "sampler_name": "lcm",
            "scheduler": "exponential",
            "denoise": 1.0,
            "width": 896,
            "height": 1152,
            "clip_layer": -2,
        },
        "source": "generate_Image.json",
        "vl_score": None,
        "gen_time_ms": None,
        "builtin": True,
    },
    "proven_character_card": {
        "label": "Proven — Character Card Full Body",
        "workflow": "character_card",
        "description": "Full-body character card with tuned lcm settings. 832x1216 portrait.",
        "params": {
            "steps": 20,
            "cfg": 1.5,
            "sampler_name": "lcm",
            "scheduler": "exponential",
            "denoise": 1.0,
            "width": 832,
            "height": 1216,
        },
        "source": "system_tuning",
        "vl_score": None,
        "gen_time_ms": None,
        "builtin": True,
    },
    "proven_scene_background": {
        "label": "Proven — Scene Background Widescreen",
        "workflow": "scene_background",
        "description": "Widescreen cinematic background. lcm/exp, cfg=1.5, steps=20. 1024x576.",
        "params": {
            "steps": 20,
            "cfg": 1.5,
            "sampler_name": "lcm",
            "scheduler": "exponential",
            "denoise": 1.0,
            "width": 1024,
            "height": 576,
        },
        "source": "system_tuning",
        "vl_score": None,
        "gen_time_ms": None,
        "builtin": True,
    },
    "proven_video_wan_t2v": {
        "label": "Proven — Wan 2.2 T2V (SVI Camera tuned)",
        "workflow": "video_wan_t2v",
        "description": (
            "Wan 2.2 dual-model GGUF T2V. euler/simple, cfg=1.0, steps=6, shift=5.0. "
            "272x352 portrait, 105 frames @16fps (~6.5s). Tuned from working SVI workflow."
        ),
        "params": {
            "steps": 6,
            "cfg": 1.0,
            "shift": 5.0,
            "sampler_name": "euler",
            "scheduler": "simple",
            "width": 272,
            "height": 352,
            "length": 105,
            "fps": 16,
        },
        "source": "High-SVI-NSFW-CAM-FAST-SVII2V-L-_API_.json",
        "vl_score": None,
        "gen_time_ms": None,
        "builtin": True,
    },
    "proven_message_image": {
        "label": "Proven — Message Image (Lightning 8-step)",
        "workflow": "message_image",
        "description": "Super-fast message image. lcm/exp, cfg=1.5, steps=8, Lightning LoRA. 768x512.",
        "params": {
            "steps": 8,
            "cfg": 1.5,
            "sampler_name": "lcm",
            "scheduler": "exponential",
            "denoise": 1.0,
            "width": 768,
            "height": 512,
        },
        "source": "system_tuning",
        "vl_score": None,
        "gen_time_ms": None,
        "builtin": True,
    },
}

# ──── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass
class BenchmarkVariant:
    """One parameter variant in a benchmark run."""

    variant_id: str
    params: Dict[str, Any]
    prompt: str
    workflow_id: str
    status: str = "pending"       # pending | running | done | failed
    gen_time_ms: int = 0
    image_path: str = ""
    vl_score: float = -1.0
    vl_issues: List[str] = field(default_factory=list)
    vl_strengths: List[str] = field(default_factory=list)
    vl_suggestion: str = ""
    error: str = ""


@dataclass
class BenchmarkJob:
    """A full benchmark run containing N variants."""

    job_id: str
    workflow_id: str
    prompt: str
    variants: List[BenchmarkVariant]
    use_vl_qc: bool = True
    status: str = "pending"       # pending | running | done | cancelled | failed
    started_at: float = 0.0
    finished_at: float = 0.0
    current_variant: int = 0
    total_variants: int = 0
    best_variant_id: str = ""
    error: str = ""

    @property
    def elapsed_ms(self) -> int:
        """Elapsed ms since job started."""
        if self.started_at == 0:
            return 0
        end = self.finished_at if self.finished_at else time.time()
        return int((end - self.started_at) * 1000)

    @property
    def eta_ms(self) -> int:
        """Estimated ms remaining."""
        done = self.current_variant
        total = self.total_variants
        if done == 0 or total == 0:
            return 0
        avg = self.elapsed_ms / done
        remaining = total - done
        return int(avg * remaining)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to JSON-safe dict."""
        return {
            "job_id": self.job_id,
            "workflow_id": self.workflow_id,
            "prompt": self.prompt,
            "use_vl_qc": self.use_vl_qc,
            "status": self.status,
            "elapsed_ms": self.elapsed_ms,
            "eta_ms": self.eta_ms,
            "current_variant": self.current_variant,
            "total_variants": self.total_variants,
            "best_variant_id": self.best_variant_id,
            "error": self.error,
            "variants": [asdict(v) for v in self.variants],
        }


# ──── TuningEngine ─────────────────────────────────────────────────────────────


class TuningEngine:
    """Manages proven profiles, benchmark runs, auto-tune, and metrics persistence.

    Thread-safe singleton.  Benchmark jobs run in a background thread so the
    HTTP endpoint returns immediately.  Progress is pushed to callers via a
    callback (used to emit Socket.IO events) and also polled via get_job_status().
    """

    _instance: Optional["TuningEngine"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "TuningEngine":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        """Initialise DB, profiles, and job state."""
        cfg = get_config()
        db_path = Path(cfg.get("asset_studio.tuning_db", "data/asset_studio/tuning_metrics.db"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._init_db()
        self._custom_profiles: Dict[str, Dict[str, Any]] = self._load_custom_profiles()
        self._current_job: Optional[BenchmarkJob] = None
        self._job_lock = threading.Lock()

    def _init_db(self) -> None:
        """Create database tables if they don't exist."""
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS benchmark_runs (
                    run_id      TEXT PRIMARY KEY,
                    job_id      TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    variant_id  TEXT NOT NULL,
                    prompt      TEXT,
                    params_json TEXT,
                    status      TEXT,
                    gen_time_ms INTEGER,
                    image_path  TEXT,
                    vl_score    REAL,
                    vl_issues   TEXT,
                    vl_strengths TEXT,
                    vl_suggestion TEXT,
                    error       TEXT,
                    created_at  REAL DEFAULT (unixepoch('now'))
                );
                CREATE TABLE IF NOT EXISTS custom_profiles (
                    profile_id  TEXT PRIMARY KEY,
                    label       TEXT,
                    workflow_id TEXT,
                    description TEXT,
                    params_json TEXT,
                    vl_score    REAL,
                    gen_time_ms INTEGER,
                    created_at  REAL DEFAULT (unixepoch('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_runs_workflow ON benchmark_runs(workflow_id);
                CREATE INDEX IF NOT EXISTS idx_runs_score ON benchmark_runs(vl_score);
            """)

    def _load_custom_profiles(self) -> Dict[str, Dict[str, Any]]:
        """Load user-saved profiles from database."""
        profiles: Dict[str, Dict[str, Any]] = {}
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                for row in conn.execute("SELECT * FROM custom_profiles"):
                    p = dict(row)
                    p["params"] = json.loads(p.pop("params_json", "{}"))
                    p["builtin"] = False
                    profiles[p["profile_id"]] = p
        except Exception as exc:
            logger.warning("Could not load custom profiles: %s", exc)
        return profiles

    # ── Profile API ───────────────────────────────────────────────────────────

    def get_profiles(self) -> List[Dict[str, Any]]:
        """Return all profiles (builtin + custom), sorted builtin-first."""
        all_profiles = {**PROVEN_PROFILES, **self._custom_profiles}
        return sorted(all_profiles.values(), key=lambda p: (not p.get("builtin", False), p.get("label", "")))

    def get_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        """Return a single profile by ID."""
        return PROVEN_PROFILES.get(profile_id) or self._custom_profiles.get(profile_id)

    def save_profile(
        self,
        profile_id: str,
        label: str,
        workflow_id: str,
        description: str,
        params: Dict[str, Any],
        vl_score: Optional[float] = None,
        gen_time_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Save a custom profile to the database.

        Args:
            profile_id: Unique slug identifier.
            label: Human-readable name.
            workflow_id: Which workflow this applies to.
            description: Free text description.
            params: Settings dict.
            vl_score: Optional VL quality score.
            gen_time_ms: Optional generation time.

        Returns:
            The saved profile dict.
        """
        profile: Dict[str, Any] = {
            "profile_id": profile_id,
            "label": label,
            "workflow_id": workflow_id,
            "workflow": workflow_id,
            "description": description,
            "params": params,
            "vl_score": vl_score,
            "gen_time_ms": gen_time_ms,
            "builtin": False,
        }
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO custom_profiles
                (profile_id, label, workflow_id, description, params_json, vl_score, gen_time_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (profile_id, label, workflow_id, description, json.dumps(params), vl_score, gen_time_ms))
        self._custom_profiles[profile_id] = profile
        return profile

    def delete_profile(self, profile_id: str) -> bool:
        """Delete a custom profile. Builtin profiles cannot be deleted."""
        if profile_id in PROVEN_PROFILES:
            return False
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM custom_profiles WHERE profile_id = ?", (profile_id,))
        self._custom_profiles.pop(profile_id, None)
        return True

    # ── Benchmark API ─────────────────────────────────────────────────────────

    @staticmethod
    def build_variants(base_params: Dict[str, Any], sweep: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
        """Generate all combinations of sweep parameters.

        Args:
            base_params: Base parameter dict (applied to all variants).
            sweep: Dict of {param_name: [value1, value2, ...]} to sweep.

        Returns:
            List of full parameter dicts, one per combination.
        """
        if not sweep:
            return [dict(base_params)]
        keys = list(sweep.keys())
        value_lists = [sweep[k] for k in keys]
        variants = []
        for combo in product(*value_lists):
            v = dict(base_params)
            for k, val in zip(keys, combo):
                v[k] = val
            variants.append(v)
        return variants

    def submit_benchmark(
        self,
        workflow_id: str,
        prompt: str,
        base_params: Dict[str, Any],
        sweep: Dict[str, List[Any]],
        use_vl_qc: bool = True,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> str:
        """Submit a benchmark job (runs in background thread).

        Args:
            workflow_id: Workflow to benchmark.
            prompt: Positive prompt to use for all variants.
            base_params: Base parameters (applied to all variants).
            sweep: Dict of {param: [values]} to sweep over.
            use_vl_qc: Whether to score outputs with Qwen VL.
            progress_callback: Called with job.to_dict() after each variant.

        Returns:
            job_id string.
        """
        variants_params = self.build_variants(base_params, sweep)
        variants = [
            BenchmarkVariant(
                variant_id=f"v{i:03d}",
                params=p,
                prompt=prompt,
                workflow_id=workflow_id,
            )
            for i, p in enumerate(variants_params)
        ]
        job = BenchmarkJob(
            job_id=str(uuid.uuid4())[:8],
            workflow_id=workflow_id,
            prompt=prompt,
            variants=variants,
            use_vl_qc=use_vl_qc,
            total_variants=len(variants),
        )
        with self._job_lock:
            self._current_job = job
        thread = threading.Thread(
            target=self._run_benchmark_job,
            args=(job, progress_callback),
            daemon=True,
        )
        thread.start()
        return job.job_id

    def _run_benchmark_job(
        self,
        job: BenchmarkJob,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
    ) -> None:
        """Execute benchmark job in background thread."""
        job.status = "running"
        job.started_at = time.time()
        if progress_callback:
            progress_callback(job.to_dict())

        try:
            from engine.asset_studio.workflow_manager import get_workflow_manager  # noqa: PLC0415
            wm = get_workflow_manager()
            save_dir = Path(get_config().get("art.output_dir", "data/art/output"))
            save_dir.mkdir(parents=True, exist_ok=True)

            for i, variant in enumerate(job.variants):
                if job.status == "cancelled":
                    break
                job.current_variant = i
                variant.status = "running"
                if progress_callback:
                    progress_callback(job.to_dict())

                t0 = time.time()
                try:
                    gen_result = wm.generate(
                        job.workflow_id,
                        {"positive": variant.prompt, **variant.params},
                        save_dir=save_dir,
                        filename_prefix=f"bench_{job.job_id}_{variant.variant_id}",
                    )
                    variant.gen_time_ms = int((time.time() - t0) * 1000)

                    if gen_result.get("error"):
                        variant.status = "failed"
                        variant.error = gen_result["error"]
                    else:
                        variant.image_path = gen_result.get("path", "") or gen_result.get("url", "")
                        variant.status = "done"

                        # VL quality check
                        if job.use_vl_qc and variant.image_path:
                            actual_path = variant.image_path
                            # Convert URL to filesystem path if needed
                            if actual_path.startswith("/art/"):
                                actual_path = str(save_dir.parent / actual_path.lstrip("/"))
                            qc = wm.check_image_quality(actual_path, prompt_context=variant.prompt)
                            variant.vl_score = float(qc.get("score", -1))
                            variant.vl_issues = qc.get("issues", [])
                            variant.vl_strengths = qc.get("strengths", [])
                            variant.vl_suggestion = qc.get("suggestion", "")

                except Exception as exc:
                    variant.status = "failed"
                    variant.error = str(exc)
                    variant.gen_time_ms = int((time.time() - t0) * 1000)
                    logger.warning("Benchmark variant %s failed: %s", variant.variant_id, exc)

                # Persist to DB
                self._persist_variant(job, variant)
                job.current_variant = i + 1
                if progress_callback:
                    progress_callback(job.to_dict())

        except Exception as exc:
            job.error = str(exc)
            job.status = "failed"
            logger.exception("Benchmark job %s failed: %s", job.job_id, exc)
        else:
            if job.status != "cancelled":
                job.status = "done"
                # Find best variant by VL score, fallback to fastest
                scored = [v for v in job.variants if v.vl_score >= 0]
                if scored:
                    job.best_variant_id = max(scored, key=lambda v: v.vl_score).variant_id
                else:
                    fast = [v for v in job.variants if v.status == "done" and v.gen_time_ms > 0]
                    if fast:
                        job.best_variant_id = min(fast, key=lambda v: v.gen_time_ms).variant_id
        finally:
            job.finished_at = time.time()
            if progress_callback:
                progress_callback(job.to_dict())

    def _persist_variant(self, job: BenchmarkJob, v: BenchmarkVariant) -> None:
        """Write one variant result to the metrics database."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO benchmark_runs
                    (run_id, job_id, workflow_id, variant_id, prompt, params_json,
                     status, gen_time_ms, image_path, vl_score, vl_issues,
                     vl_strengths, vl_suggestion, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    f"{job.job_id}_{v.variant_id}",
                    job.job_id,
                    v.workflow_id,
                    v.variant_id,
                    v.prompt,
                    json.dumps(v.params),
                    v.status,
                    v.gen_time_ms,
                    v.image_path,
                    v.vl_score if v.vl_score >= 0 else None,
                    json.dumps(v.vl_issues),
                    json.dumps(v.vl_strengths),
                    v.vl_suggestion,
                    v.error,
                ))
        except Exception as exc:
            logger.warning("Failed to persist variant: %s", exc)

    def cancel_job(self) -> bool:
        """Cancel the current running job."""
        with self._job_lock:
            if self._current_job and self._current_job.status == "running":
                self._current_job.status = "cancelled"
                return True
        return False

    def get_job_status(self) -> Optional[Dict[str, Any]]:
        """Return current job status dict, or None."""
        with self._job_lock:
            if self._current_job:
                return self._current_job.to_dict()
        return None

    # ── Metrics API ───────────────────────────────────────────────────────────

    def get_metrics(
        self,
        workflow_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        min_score: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Query metrics history from the database.

        Args:
            workflow_id: Filter by workflow (None = all).
            limit: Max rows to return.
            offset: Pagination offset.
            min_score: Filter to rows with vl_score >= this value.

        Returns:
            Dict with keys: runs (list), total (int), summary (dict).
        """
        conditions = []
        args: List[Any] = []
        if workflow_id:
            conditions.append("workflow_id = ?")
            args.append(workflow_id)
        if min_score is not None:
            conditions.append("vl_score >= ?")
            args.append(min_score)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                total = conn.execute(f"SELECT COUNT(*) FROM benchmark_runs {where}", args).fetchone()[0]
                rows = conn.execute(
                    f"SELECT * FROM benchmark_runs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    args + [limit, offset],
                ).fetchall()

                runs = []
                for r in rows:
                    row_dict = dict(r)
                    row_dict["params"] = json.loads(row_dict.pop("params_json", "{}"))
                    row_dict["vl_issues"] = json.loads(row_dict.get("vl_issues") or "[]")
                    row_dict["vl_strengths"] = json.loads(row_dict.get("vl_strengths") or "[]")
                    runs.append(row_dict)

                # Summary stats — build WHERE clause for done rows
                done_conditions = list(conditions) + ["status = 'done'"]
                done_where = "WHERE " + " AND ".join(done_conditions)
                summary_row = conn.execute(f"""
                    SELECT
                        COUNT(*) as total_runs,
                        AVG(vl_score) as avg_score,
                        MAX(vl_score) as best_score,
                        MIN(vl_score) as worst_score,
                        AVG(gen_time_ms) as avg_time_ms,
                        MIN(gen_time_ms) as fastest_ms,
                        MAX(gen_time_ms) as slowest_ms
                    FROM benchmark_runs
                    {done_where}
                """, args).fetchone()
                summary = dict(summary_row) if summary_row else {}

                # Sparkline: last 20 scores for the workflow
                sparkline_rows = conn.execute(f"""
                    SELECT vl_score FROM benchmark_runs
                    WHERE status = 'done' AND vl_score IS NOT NULL
                    {('AND ' + ' AND '.join(conditions)) if conditions else ''}
                    ORDER BY created_at DESC LIMIT 20
                """, args).fetchall()
                sparkline = [r[0] for r in reversed(sparkline_rows)]

        except Exception as exc:
            logger.warning("Metrics query failed: %s", exc)
            return {"runs": [], "total": 0, "summary": {}, "sparkline": []}

        return {"runs": runs, "total": total, "summary": summary, "sparkline": sparkline}

    def get_best_settings(self, workflow_id: str, top_n: int = 5) -> List[Dict[str, Any]]:
        """Return the top N param sets by VL score for a workflow.

        Args:
            workflow_id: Workflow to query.
            top_n: Number of top results to return.

        Returns:
            List of {params, vl_score, gen_time_ms} dicts.
        """
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT params_json, vl_score, gen_time_ms
                    FROM benchmark_runs
                    WHERE workflow_id = ? AND status = 'done' AND vl_score IS NOT NULL
                    ORDER BY vl_score DESC LIMIT ?
                """, (workflow_id, top_n)).fetchall()
                return [
                    {"params": json.loads(r["params_json"]), "vl_score": r["vl_score"], "gen_time_ms": r["gen_time_ms"]}
                    for r in rows
                ]
        except Exception as exc:
            logger.warning("get_best_settings failed: %s", exc)
            return []


_engine_instance: Optional[TuningEngine] = None
_engine_lock = threading.Lock()


def get_tuning_engine() -> TuningEngine:
    """Return the singleton TuningEngine instance."""
    global _engine_instance
    with _engine_lock:
        if _engine_instance is None:
            _engine_instance = TuningEngine()
    return _engine_instance
