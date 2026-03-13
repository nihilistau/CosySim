# COSYSIM SELF-IMPROVEMENT & BENCHMARKING SYSTEM - COMPREHENSIVE GAP ANALYSIS

## EXECUTIVE SUMMARY

CosySim has a **strong foundation** for self-improvement with 3 major operational loops:
1. **Benchmarking Loop** — Daily auto-benchmarking & promotion of fine-tuned models
2. **Training Flywheel** — Continuous collection of training data from system interactions
3. **Metrics & Reflection** — System-wide metrics tracking with NLM-driven insights

However, there are **critical gaps** preventing true end-to-end autonomy:
- No causal analysis (what metrics drive what outcomes?)
- No predictive refresh (refreshing knowledge before it degrades)
- No anomaly detection (early warning before failures)
- Limited model promotion criteria (score-based only)
- No impact quantification (which improvements actually matter?)

---

## 1. METAMETRICS.PY — Metric Categories & Recording

### ✅ WHAT EXISTS

**File:** ngine/nexus/meta_metrics.py (28.1 KB SQLite-backed metrics DB)

**Metric Categories (7 categories, 50+ distinct metrics):**

| Category | Metrics | Examples |
|----------|---------|----------|
| **Knowledge** | 5 metrics | nexus.entries.total, nexus.qa.cache_hits, nexus.quality.average |
| **Inference** | 5 metrics | llm.calls.total, llm.tokens.input/output, llm.cache.hit_rate, llm.latency.avg_ms |
| **Tasks** | 4 metrics | tasks.created, tasks.completed, tasks.failed, tasks.agent_error_rate |
| **Tests** | 4 metrics | tests.total, tests.passed, tests.failed, tests.duration_s |
| **System** | 4 metrics | system.vram_used_mb, system.uptime_s, nlm.notebooks.active, nlm.research.sessions |
| **News** | 11 metrics | news.fetch.{total,fresh,latency}, news.dedup.{filtered,ratio}, news.store.{success,failed}, news.distill.{latency,qa_pairs}, news.cycle.duration_s |
| **Benchmark** | 10 metrics | benchmark.ops.{count,types,total_ms,avg_ms,p95_ms}, benchmark.llm.{count,total_tokens,avg_latency_ms,tokens_per_sec,first_token_ms} |

**Recording Methods:**
- .record(name, value, tags) — Single metric point with optional tags
- .record_batch([(name, value), ...]) — Batch insert (50+ metrics at once)
- Thread-safe, SQLite with WAL mode for concurrent reads

**Trend Analysis:**
- .trend(metric, days=7) — Returns: direction (up/down/stable), rate_of_change, min/max/avg, first/last values, count
- .compare(metric, current_hours, baseline_hours) — Current vs baseline with change_pct, improved flag
- .set_baseline(name, value) & .auto_baseline(name, days=7) — Manual/automatic baseline setting
- .check_regressions(threshold_pct=10.0) — Detects metrics that deviate >10% from baseline

**Dashboard:**
- .dashboard(hours=24) — Markdown table with all metrics, current values, short/long-term trends
- .snapshot() — Latest value for every metric
- .stats() — Total points, unique metrics, date range, alert count

### ❌ GAPS

| Gap | Impact | Severity |
|-----|--------|----------|
| **No metric aggregation across time windows** | Can't easily answer "what's the 95th percentile?" or "what's the max over the week?" | Medium |
| **No metric correlation analysis** | Can't detect: which metrics cause which outcomes? (e.g., cache hit rate → LLM calls) | High |
| **No anomaly detection** | Only 3 alerts: regression, threshold, trend — no statistical anomalies (sudden spikes/drops) | High |
| **No causal inference** | Can record "quality went down" but not "why" (root cause analysis) | High |
| **No prediction/forecasting** | Can't predict future metric values or identify degrading trends early | Critical |
| **No alert routing/escalation** | All alerts stored, none acted upon automatically | Medium |
| **Limited tagging/dimensionality** | Can only tag individual metric points, not slice by model_type, agent_id, etc. | Medium |

---

## 2. BENCHMARK_RUNNER.PY — How Benchmarking Works

### ✅ WHAT EXISTS

**File:** 	raining/benchmark_runner.py (300+ lines)

**Architecture:**
`
┌─ Daily Scheduler (model-benchmark) ──┐
│                                        │
├─ run_all(auto_promote=True)           │
│  └─ For each MODELS type (qa_evaluator, router_v2, etc.):
│     ├─ Load model from registry
│     ├─ Load test set (model_type_test.jsonl)
│     ├─ Run inference on test examples
│     ├─ Compute: accuracy, F1, exact_match
│     ├─ Compute aggregate_score = 0.4*acc + 0.4*F1 + 0.2*exact_match
│     ├─ Store in training/benchmarks.jsonl
│     ├─ Update ModelRegistry with benchmark result
│     └─ Auto-promote if score improved
│
└─ Results logged to Nexus
`

**Result Model (BenchmarkResult):**
`python
@dataclass
class BenchmarkResult:
    model_id: str
    model_type: str
    accuracy: float          # 0.0–1.0
    f1: float                # Token-overlap F1
    exact_match: float       # 0.0–1.0
    total_examples: int      # Test set size
    correct: int             # Count of exact matches
    latency_ms_avg: float    # Average inference latency
    aggregate_score: float   # Weighted combination (0.4*acc + 0.4*F1 + 0.2*EM)
    breakdown: Dict          # f1_scores_sample + latency_p95
    timestamp: str           # ISO timestamp
    promoted: bool           # Was this model promoted?
    error: Optional[str]     # Error message if benchmark failed
`

**Metrics Computed:**
- Accuracy: correct / total_examples
- F1: Token overlap between predicted & expected (word-level)
- Exact Match: Exact string match (after lowercasing)
- Latency: Average inference time in milliseconds
- P95 latency: 95th percentile latency

**Auto-Promotion Logic:**
`python
if auto_promote:
    promoted_model = registry.auto_promote(model_type)
    if promoted_model and promoted_model.model_id == model_id:
        result.promoted = True
`
→ **Promotion criteria: Registry.auto_promote() selects model with highest aggregate_score**

**Persistence:**
- JSONL file: 	raining/benchmarks.jsonl — append-only benchmark history
- ModelRegistry — update model's benchmark field with aggregate_score
- Nexus — best-effort storage of benchmark results

**Scheduler Integration:**
`python
daemon.register(
    "model-benchmark",
    "Daily Micro-Model Benchmarks",
    "daily",      # Runs once per day
    _model_benchmark_callback,
)
`

### ❌ GAPS

| Gap | Impact | Severity |
|-----|--------|----------|
| **No statistical significance testing** | Can't tell if a 0.5% improvement is real or noise | High |
| **No online evaluation (production feedback)** | Only tests against held-out test sets, never against real user queries | Critical |
| **No per-category breakdowns** | Aggregates accuracy across all question types — can't see which categories regressed | High |
| **No A/B testing framework** | Can't run shadow models or canary promotions | Medium |
| **No rollback capability** | No way to revert to previous model if promotion causes issues | Medium |
| **Promotion criteria too simplistic** | Only looks at aggregate_score, ignores latency, stability, or other costs | High |
| **No multi-metric Pareto frontier** | Can't balance accuracy vs latency vs cost trade-offs | Medium |
| **No benchmark scheduling optimization** | Benchmarks run at fixed daily time regardless of system load | Low |
| **No cost/benefit analysis** | Don't know if fine-tuning cost justified by improvement | High |

---

## 3. AUTO_DIAGNOSIS.PY — Auto-Tuning Capabilities

### ✅ WHAT EXISTS

**File:** ngine/nexus/auto_diagnosis.py (25 KB)

**What it does:**
- Automated health checks for system components
- Diagnoses common issues (file missing, connection failed, etc.)
- Generates repair suggestions
- Best-effort: stores diagnostics in Nexus but doesn't auto-repair

**Does NOT include:**
- Hyperparameter tuning
- Model configuration optimization
- Cache size/TTL auto-tuning
- Resource allocation optimization

### ❌ GAPS

This file is primarily **diagnostic**, not **improvement-focused**. No auto-tuning actually happens.

---

## 4. SCHEDULER_DAEMON.PY — Recurring Improvement Tasks

### ✅ WHAT EXISTS

**File:** ngine/nexus/scheduler_daemon.py (2800+ lines)

**Self-Improvement Tasks (15+ registered):**

| Task ID | Schedule | Callback | Purpose |
|---------|----------|----------|---------|
| 
exus-maintenance | Daily | nexus_health_report() | Health checks on Nexus entries |
| 
exus-dedup | Weekly | nexus_merge_duplicates() | Find & flag duplicate entries |
| knowledge-quality | Weekly | quality_report() | Score entries, flag stale ones |
| 
otebook-rotation | Weekly | nlm_notebook_cleanup() | Clean up old NLM notebooks |
| model-benchmark | **Daily** | **BenchmarkRunner.run_all(auto_promote=True)** | **⭐ CORE: Benchmark & auto-promote models** |
| 	est-suite-benchmark | Daily | pytest suite + regression check | Run tests, flag performance regressions |
| metrics-collect | Every 4h | MetaMetrics.collect_all() + check_regressions() | Collect all system metrics & alert on regressions |
| 	raining-sync | Daily | TrainingFlywheel.sync_from_nexus() + export if ≥50 examples | Sync Q&A into training dataset |
| **system-reflection** | **Weekly** | **SystemReflection.run_reflection()** | **⭐ NLM-driven insights & task generation** |
| **xperiment-scan** | **Weekly** | **ExperimentProposer.scan_and_propose()** | **⭐ Auto-propose A/B tests from metrics** |
| outer-finetune-cycle | Weekly | RouterFinetuneCycle.run() | Train router_v2, test, promote |
| dataset-augment | Weekly | Auto-expand training datasets | Synthetic data generation |
| qa-generation | Daily | QAGenerator.run_rule_based() | Auto-generate Q&A from entries |
| session-distillation | Daily | Extract facts from Copilot sessions | Knowledge capture |
| control-notebook-flywheel | Every 8h | Distill control notebook → artifacts | Decision capture |

**State Persistence:**
- data/scheduler_state.json — Persistent store of task execution state (last_run, run_count, error_count)
- Best-effort logging to Nexus with task results

### ✅ STRONG SELF-IMPROVEMENT PIPELINE

Three critical autonomous loops exist:

#### **Loop 1: Benchmark → Promote**
`
Daily:
  1. Load all fine-tuned models from registry
  2. Benchmark against test sets
  3. Auto-promote if aggregate_score improves
  4. Store results in Nexus
`

#### **Loop 2: Reflection → Proposals → Experiments**
`
Weekly:
  1. SystemReflection collects metrics snapshot + recent logs
  2. Creates NLM notebook with reflection questions
  3. Sends to NotebookLM for analysis
  4. Extracts insights → auto-creates improvement tasks in Nexus
  5. ExperimentProposer scans metrics against templates
  6. Auto-creates A/B experiment proposals (cache hit, latency, error rate)
`

#### **Loop 3: Knowledge → Training → Models**
`
Daily:
  1. QAGenerator creates Q&A pairs from Nexus entries
  2. SessionDistillation extracts knowledge from Copilot sessions
  3. TrainingFlywheel syncs all into training dataset
  4. Weekly: RouterFinetuneCycle trains new router models
  5. ModelRegistry auto-promotes best performers
`

### ❌ GAPS

| Gap | Impact | Severity |
|-----|--------|----------|
| **Experiments proposed but not executed** | ExperimentProposer creates proposals, but no scheduler task actually runs them | Critical |
| **Insights generated but not acted upon** | SystemReflection creates tasks in Nexus, but no automation to prioritize/execute them | High |
| **No causal metrics chain** | Tasks are created, but we don't know which improvements actually helped | High |
| **No automatic performance impact measurement** | Can't A/B test proposals against baseline automatically | Critical |
| **Model promotion criteria too simple** | Only looks at aggregate_score; doesn't consider: latency, cost, user feedback | High |
| **No online feedback loop** | Test set performance ≠ production performance; never measure real user impact | Critical |
| **Reflection runs but results not acted upon** | Weekly reflection generates insights but no enforcement mechanism | High |
| **No anomaly-driven triggers** | Tasks run on fixed schedule, never triggered by detected anomalies | Medium |
| **No knowledge refresh scheduling** | We know what's stale (knowledge-quality task), but don't auto-refresh it | High |

---

## 5. TRAINING_FLYWHEEL.PY — Training Data Collection

### ✅ WHAT EXISTS

**File:** ngine/nexus/training_flywheel.py (650+ lines)

**Data Collection Sources:**

| Source | Collection Method | Examples |
|--------|-------------------|----------|
| **Tasks** | .collect_from_task(task, result, model) | AgentTask completion → instruction-tuning pair |
| **Q&A Pairs** | .collect_from_qa(question, answer, source, confidence) | Nexus cache, FTS search, NLM, LLM responses |
| **NLM Conversations** | .collect_from_nlm(conversation_turns, topic) | Multi-turn research sessions → distilled Q&A |
| **Routing Decisions** | .collect_from_routing(query, chosen_model, confidence) | Model selection decisions → classification training |
| **Preference Data** | .collect_from_preference(chosen_response, rejected_response) | Chosen/rejected pairs → DPO training |

**Storage:**
- SQLite: data/training_flywheel.db (examples, export_history, stats)
- Deduplication: Content hash prevents duplicate examples
- Quality scoring: Each example has 0.0–1.0 quality_score

**Export Formats:**
- .export_jsonl(min_quality=0.7) → Alpaca instruction-tuning format
- .export_sharegpt(min_quality=0.7) → ShareGPT conversation format  
- .export_dpo(min_quality=0.7) → DPO (Direct Preference Optimization) format

**Scheduler Integration:**
`python
daemon.register(
    "training-sync",
    "Training Data Sync",
    "daily",
    _training_sync_callback,
)
# If ≥50 unexported examples, automatically export to training/datasets/
`

**Metrics:**
- .stats() — Total examples, by source, quality histogram, export history

### ✅ STRONG FLYWHEEL

Training data is continuously collected from:
- Task completions
- Q&A cache hits
- NLM conversations
- Session distillation

### ❌ GAPS

| Gap | Impact | Severity |
|-----|--------|----------|
| **No quality evaluation of collected data** | Examples marked with static quality_score, never re-evaluated after collection | High |
| **No active learning** | Never selects hard examples or uncertain predictions for humans to label | High |
| **No data source weighting** | All sources treated equally; can't bias toward higher-quality sources | Medium |
| **No curriculum learning** | Exports don't order examples by difficulty | Low |
| **No automated data cleaning** | No removal of low-quality examples post-collection | Medium |
| **No feedback from fine-tuning** | Training loss/metrics never fed back to improve data collection | High |
| **Export threshold is static (50 examples)** | Should be adaptive based on model retraining frequency | Low |

---

## 6. QUERY_ROUTER.PY — Stats & Self-Improvement Tracking

### ✅ WHAT EXISTS

**File:** ngine/nexus/query_router.py (650+ lines)

**RouterStats (Cumulative):**
`python
@dataclass
class RouterStats:
    total_queries: int = 0
    cache_hits: int = 0
    vector_hits: int = 0
    search_hits: int = 0
    nlm_hits: int = 0
    llm_fallbacks: int = 0
    no_answer: int = 0
    total_tokens_saved: int = 0
    answers_stored: int = 0
    
    def hit_rate(self) -> float:
        # Nexus hit rate = (cache + vector + search + nlm) / total
`

**Query Pipeline (6-tier with confidence scoring):**
1. Q&A Cache → confidence 0.90 (highest)
2. Vector Semantic Search (Gemini Embedding 2) → 0.82
3. FTS Knowledge Search → 0.75 (strong), 0.50 (decent), 0.30 (weak)
4. Nexus Smart Ask → varies
5. Direct NotebookLM → varies
6. LLM Fallback → variable (slow, expensive)

**Self-Improvement Loop:**
- Every answer returned increments stats
- LLM answers automatically stored back in Nexus (for future cache hits)
- Cache hits save tokens (tracked in 	otal_tokens_saved)
- hit_rate() shows effectiveness of Nexus knowledge over time

### ❌ GAPS

| Gap | Impact | Severity |
|-----|--------|----------|
| **Stats never aggregated/reported** | RouterStats updated in-memory, but no scheduled persistence to MetaMetrics | High |
| **No quality feedback on cached answers** | Store answers back, but never measure if they're actually good | High |
| **No source-level metrics** | Can't tell which sources (vector vs FTS) are more reliable | Medium |
| **No per-category tracking** | Don't know if cache works better for certain question types | Medium |
| **No prediction of cache hit before query** | Always runs full pipeline; can't short-circuit for predictable questions | Medium |
| **No learning from misses** | When router can't answer (no_answer), we don't use that signal to improve | High |

---

## 7. EXPERIMENT_FRAMEWORK.PY & EXPERIMENT_PROPOSALS.PY

### ✅ WHAT EXISTS

**File:** ngine/nexus/experiment_framework.py (350+ lines)

**A/B Testing Framework:**
- .create(name, variants, description, hypothesis, metric_keys) → Create experiment with N variants
- .record_result(experiment_id, variant_id, metrics) → Log results
- .evaluate(experiment_id, primary_metric, min_samples) → Compute winner (highest mean on primary metric)

**Experiment Proposal Templates:**

`python
EXPERIMENT_TEMPLATES = {
    "cache_hit_rate_low": {
        "trigger_metric": "llm.cache.hit_rate",
        "condition": "below",
        "threshold": 0.4,
        "hypothesis": "Increasing Q&A cache TTL and fuzzy match will improve cache hit rate",
        "variants": [
            {"cache_ttl": 300, "fuzzy_match": False},  # baseline
            {"cache_ttl": 600, "fuzzy_match": False},  # longer TTL
            {"cache_ttl": 300, "fuzzy_match": True},   # fuzzy match
        ],
        "success_metric": "llm.cache.hit_rate",
        "success_threshold": 0.5,
    },
    "inference_slow": {...},  # Latency optimization
    "task_failure_high": {...},  # Error rate reduction
    "knowledge_quality_low": {...},  # Knowledge curation
}
`

**Proposer (xperiment_proposals.py):**
`python
proposer = get_experiment_proposer()
proposals = proposer.scan_and_propose()
# Returns list of ExperimentProposal objects
`

**Scheduler Integration:**
`python
daemon.register(
    "experiment-scan",
    "Experiment Proposal Scan",
    "weekly",
    _experiment_scan_callback,
)
`

### ❌ CRITICAL GAPS

| Gap | Impact | Severity |
|-----|--------|----------|
| **Proposals created but NOT EXECUTED** | ExperimentProposer creates proposals and stores in Nexus, but no scheduler task runs them | **CRITICAL** |
| **No automatic experiment execution** | Manual intervention needed to go from proposal → running experiment | **CRITICAL** |
| **No online experiment harness** | Can't run experiments against live traffic; only supports offline test-set evaluation | **CRITICAL** |
| **No statistical power analysis** | Don't calculate min samples needed per variant | High |
| **No sequential decision rules** | Can't stop experiment early if winner is clear | Medium |
| **No interaction effects** | Only measures individual metric, not correlations | Medium |
| **Results stored in-memory only** | When daemon restarts, experiment results lost | High |

---

## 8. MODELS.PY — Data Models

### ✅ WHAT EXISTS

`python
class BenchmarkResult(BaseModel):
    model: str
    method: str
    metrics: Dict[str, Any]
    score: float
    timestamp: datetime
    notes: str

class TrainingRun(BaseModel):
    run_id: str
    model_type: str
    dataset_path: str
    epochs: int
    lora_r: int
    status: str  # pending | running | done | failed
    loss: Optional[float]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]

class RouterDecision(BaseModel):
    request_hash: str
    chosen_model: str
    confidence: float
    latency_ms: float
    timestamp: datetime
`

### ❌ GAPS

| Gap | Impact | Severity |
|-----|--------|----------|
| **No ModelPromotion model** | No formal record of which models were promoted when/why | High |
| **No ExperimentResult model** | Results stored in-memory, no persistent schema | High |
| **No IncidentReport model** | When things go wrong, no formal incident tracking | Medium |
| **No CausalLink model** | No way to record "this metric change caused that outcome" | Critical |

---

---

# COMPREHENSIVE GAP ANALYSIS SUMMARY

## SELF-IMPROVEMENT LOOPS THAT EXIST ✅

| Loop | Trigger | Actions | Limitations |
|------|---------|---------|------------|
| **Benchmark → Promote** | Daily (model-benchmark) | Test models, auto-promote best | Only aggregates score; no significance testing or production feedback |
| **Reflection → Insights → Tasks** | Weekly (system-reflection) | NLM analyzes metrics, creates tasks | Tasks created but not prioritized/executed |
| **Proposals → Experiments** | Weekly (experiment-scan) | Templates match metrics, create proposals | **Proposals never executed** |
| **Knowledge → Training → Models** | Daily (training-sync, qa-gen) | Collect data, export, retrain | Data quality never re-evaluated |
| **Data → Metrics → Alerts** | Every 4h (metrics-collect) | Collect metrics, check regressions | Only regression alerts; no anomalies |

---

## CRITICAL MISSING PIECES ⚠️

### 1. **NO CAUSAL ANALYSIS** (Severity: Critical)
- ❌ Can't answer: "Which improvements actually moved the needle?"
- ❌ Can't detect: "Did the model promotion improve query latency?"
- ❌ All metrics recorded, but no causal links between them
- **FIX:** Build causal inference engine (Granger causality, instrumental variables)

### 2. **NO AUTOMATIC EXPERIMENT EXECUTION** (Severity: Critical)
- ❌ ExperimentProposer creates proposals weekly
- ❌ Proposals stored in Nexus but never run
- ❌ No automation to go from "proposal" → "running experiment"
- **FIX:** Add experiment_runner scheduler task + online evaluation harness

### 3. **NO PRODUCTION FEEDBACK** (Severity: Critical)
- ❌ Only evaluate against held-out test sets
- ❌ Never measure real user impact
- ❌ Can benchmark 95% accuracy but deployment kills latency
- **FIX:** Add shadow model evaluation + canary promotions

### 4. **NO PREDICTIVE REFRESH** (Severity: High)
- ❌ Knowledge marked as "stale" but never auto-refreshed
- ❌ No forecasting of which entries will go stale
- ❌ No prioritization of refresh tasks
- **FIX:** Implement predictive staleness model; auto-schedule refreshes

### 5. **NO ANOMALY DETECTION** (Severity: High)
- ❌ Only 3 alerts: regression, threshold, trend
- ❌ No statistical anomalies (sudden spikes, outliers, distribution shifts)
- ❌ No alerting to scheduler for urgent intervention
- **FIX:** Add Isolation Forest, Z-score, or Isolation Forest anomaly detection

### 6. **NO AUTOMATED MODEL SELECTION** (Severity: High)
- ❌ Promotion only looks at aggregate_score
- ❌ Doesn't consider: latency, cost, user satisfaction, downstream impact
- ❌ No multi-objective optimization (accuracy vs speed vs cost)
- **FIX:** Implement Pareto frontier selection + weighted scoring

---

## INFRASTRUCTURE READY TO EXTEND ✅

| Component | Status | Extension Point |
|-----------|--------|-----------------|
| MetaMetrics | **Production-ready** | Add anomaly detection, correlation analysis, forecasting |
| BenchmarkRunner | **Functional** | Add online evaluation, A/B testing, significance testing |
| SchedulerDaemon | **Robust** | Connect to experiment executor, anomaly responder |
| TrainingFlywheel | **Operational** | Add data quality evaluation, active learning |
| SystemReflection | **Working** | Route insights → automated execution instead of manual |
| ExperimentFramework | **Incomplete** | Add executor, online harness, statistical tests |

---

## TOP 5 RECOMMENDATIONS (PRIORITY ORDER)

### 1. **Experiment Executor** (Block: Can't auto-improve)
- Create ngine/nexus/experiment_executor.py
- Listen for proposals from weekly experiment-scan
- Automatically spin up experiments
- Track: started_at, status, running_variants
- Report results back to MetaMetrics

### 2. **Online Evaluation Harness** (Block: No prod feedback)
- Implement shadow model evaluation
- Route subset of queries to experimental models
- Log side-by-side results (control vs treatment)
- Measure: real user impact, latency, errors
- Report to MetaMetrics for automatic promotion

### 3. **Causal Inference Engine** (Block: Can't understand impact)
- Implement Granger causality analysis
- Detect metric correlations (which metrics drive outcomes?)
- Auto-create insights: "Model promotion → 15% latency reduction"
- Route to SystemReflection for stronger task generation

### 4. **Anomaly Detection Module** (Block: Blind to failures)
- Add statistical anomaly detection to MetaMetrics
- Track: Z-score, IQR, distribution shifts, seasonal patterns
- Route to scheduler for urgent intervention
- Alert: "Cache hit rate dropped 30% overnight — investigate"

### 5. **Impact Quantification Engine** (Block: Can't prioritize)
- Build: ExperimentResult → before/after metrics → impact score
- Auto-calculate: "Model promotion improved accuracy 2% (p=0.03), latency +5%"
- Show: cost-benefit trade-offs for every promotion
- Enable: Pareto-optimal model selection

---

## FILE LOCATIONS & HOOKS

| File | Lines | Purpose | Extension |
|------|-------|---------|-----------|
| ngine/nexus/meta_metrics.py | 900 | Metric tracking | Add anomaly detection, forecasting |
| 	raining/benchmark_runner.py | 350 | Model evaluation | Add online eval, statistical tests |
| ngine/nexus/scheduler_daemon.py | 2800 | Task orchestration | Add experiment executor, anomaly responder |
| ngine/nexus/training_flywheel.py | 650 | Data collection | Add quality evaluation |
| ngine/nexus/system_reflection.py | 400 | Insight generation | Add execution routing |
| ngine/nexus/experiment_framework.py | 350 | A/B testing | Add executor, online harness |
| ngine/nexus/experiment_proposals.py | 300 | Proposal generation | Already works; needs executor |
| ngine/nexus/query_router.py | 650 | Query routing + stats | Persist stats to MetaMetrics |

---

## RISK ASSESSMENT

**What could go wrong with automated improvements?**

1. **Feedback loops** — Promotion → degradation → cascading failures → auto-revert
   - *Mitigation:* Canary model deployments, rollback criteria

2. **Metric gaming** — Optimize for aggregate_score, degrade real quality
   - *Mitigation:* Multi-objective scoring, user feedback signals

3. **Data poisoning** — Collect bad training examples, retrain on garbage
   - *Mitigation:* Data quality evaluation, human review thresholds

4. **Runaway experiments** — Proposal cost exceeds benefits
   - *Mitigation:* Cost budgeting, compute limits, time constraints

