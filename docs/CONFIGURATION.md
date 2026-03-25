# CosySim Configuration Guide

> CosySim Documentation — v1.51.1 [2026-03-25]
>
> Complete reference for all configuration files, YAML sections, environment variables,
> and per-scene settings. Config version in default.yaml: v1.49.

---

## Config Files

| File | Purpose |
|------|---------|
| `config/default.yaml` | Master configuration — all settings with defaults (source of truth) |
| `config/development.yaml` | Development overrides (debug on, CPU devices, relaxed limits) |
| `config/production.yaml` | Production overrides (CUDA, stricter logging, rate limiting) |
| `config/mcp.json` | MCP server command definitions |
| `config/voices.yaml` | TTS voice profiles (11 profiles) |
| `config/skill_manifests.yaml` | Skill registry per scene |

## Config Hierarchy

Configuration is loaded by `engine/config.py` (`ConfigManager`) in this order:

1. **`config/default.yaml`** — base values for every setting
2. **`config/{environment}.yaml`** — deep-merged on top of defaults
3. **Environment variables** — override individual keys (see below)

The environment is determined by `COSYSIM_ENV` (or legacy `COSYVOICE_ENV`), defaulting to `"default"`.

Access config values with dot notation: `get_config().get("lmstudio.base_url", default)`.

## default.yaml Sections

### system

| Key | Default | Description |
|-----|---------|-------------|
| `name` | CosySim AI Playground | Project name |
| `version` | v1.49 | Config version |
| `environment` | default | Active environment |

### paths

| Key | Default |
|-----|---------|
| `project_root` | `.` |
| `data_dir` | `./data` |
| `models_dir` | `./pretrained_models` |
| `cache_dir` | `./cache` |
| `logs_dir` | `./logs` |
| `media_dir` | `./content/simulation/media` |
| `assets_dir` | `./content/assets` |
| `database_dir` | (relative to project root) |

### database

| Key | Default | Description |
|-----|---------|-------------|
| `sqlite.path` | `simulation.db` | SQLite database file |
| `sqlite.pool_size` | 5 | Connection pool size |
| `sqlite.timeout` | 30 | Connection timeout (seconds) |
| `chromadb.path` | `./content/simulation/chroma_db` | Vector store path |
| `chromadb.collection` | `memories` | Default collection name |
| `chromadb.embedding_model` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model |

### llm

| Key | Default | Description |
|-----|---------|-------------|
| `provider` | lmstudio | LLM provider |
| `base_url` | `http://localhost:1234/v1` | API base URL |
| `model` | (auto) | Model name |
| `temperature` | 0.7 | Sampling temperature |
| `max_tokens` | 5000 | Max output tokens |
| `stream` | true | Enable streaming |

### lmstudio

| Key | Default | Description |
|-----|---------|-------------|
| `host` | 127.0.0.1 | Server host |
| `port` | 1234 | Server port |
| `api_token` | (bearer token) | Bearer auth token for LMStudio API — required for authenticated requests. Set via config, never hardcode. |
| `context_length` | 4096 | Default context window |
| `vram_cap_mb` | (hardware-dependent) | VRAM limit |
| `load_mode` | concurrent | Model loading strategy |
| `concurrent_slots` | 4 | Max concurrent inference slots |
| `mcp_enabled` | true | Enable MCP integration |
| `cosysim_mcp_url` | (auto) | MCP server URL |
| `gpu_offload` | 0.9 | GPU offload fraction |
| `max_output_tokens` | 4000 | Max output tokens per request |
| `speculative.enabled` | false | Speculative decoding |
| `router.enabled` | true | Model routing |

#### Model Profiles

| Profile | Purpose |
|---------|---------|
| `models.primary` | Main conversation model |
| `models.utility` | Lightweight utility tasks |
| `models.router` | Fast routing/classification |
| `models.draft` | Speculative decoding draft model |
| `models.embedding` | Embedding generation |

### agent_profiles

| Profile | Context Length | Max Tokens | Temperature | Top-p |
|---------|--------------|------------|-------------|-------|
| `big` | 8192 | 4000 | 0.75 | 0.9 |
| `small` | 2048 | 800 | 0.6 | 0.9 |
| `router` | 1024 | 200 | 0.3 | 0.9 |

### tts

| Key | Default | Description |
|-----|---------|-------------|
| `engine` | cosyvoice | TTS engine |
| `model_name` | CosyVoice-300M | Voice model |
| `sample_rate` | 22050 | Audio sample rate |
| `warm_start` | true | Pre-warm model |
| `stream` | true | Stream audio |
| `device` | cuda | Compute device |
| `server_url` | `http://localhost:8600` | TTS server URL |
| `streaming.enabled` | true | Enable streaming mode |
| `streaming.chunk_method` | sentence | Chunking strategy |
| `streaming.max_chunk_chars` | 500 | Max characters per chunk |
| `speculative.enabled` | false | Speculative synthesis |

### stt

| Key | Default | Description |
|-----|---------|-------------|
| `engine` | whisper | STT engine |
| `model_size` | base | Whisper model size |
| `language` | en | Language |
| `device` | cuda | Compute device |

### scenes

Each scene has `host`, `port`, and `debug` settings. Default host is `localhost`, debug is `false`.
Some scenes expose additional YAML-configurable settings.

#### Penthouse Extended Settings

The penthouse scene supports extensive YAML configuration beyond the standard
`host`/`port`/`debug` keys:

```yaml
scenes:
  penthouse:
    host: "localhost"
    port: 5556
    debug: false
    max_characters: 2                    # Max concurrent characters in scene
    agent_loop_interval: 8               # Agent decision interval (seconds)
    default_lighting: "evening"          # Initial lighting preset
    default_camera_view: "overview"      # Starting camera angle
    enable_first_person: true            # Enable pointer-lock first-person mode
    positions:                           # Valid character positions
      - bed
      - couch
      - fireplace
      - bar
      - bathroom
      - vanity
      - balcony
      - doorway
    outfits:                             # Available outfit states
      - casual
      - formal
      - silk_robe
      - nothing
      - lingerie
      - leather
      - evening_dress
      - swimwear
      - athletic
      - sleep
    personality_profiles:                # Character personality templates
      - bold_dominant
      - shy_submissive
      - playful_tease
      - intellectual_aloof
      - nurturing_warm
    stats:                               # Character stat dimensions (0-100)
      - arousal
      - pleasure
      - happiness
      - horniness
      - drunkenness
      - dominance
      - fear
      - anger
      - openness
      - tiredness
```

#### All Scene Ports

| Scene | Port |
|-------|------|
| `phone` | 5555 |
| `penthouse` | 5556 |
| `lounge` | 5557 |
| `casino` | 5559 |
| `gallery` | 5560 |
| `arena` | 5561 |
| `realm` | 5562 |
| `neoncity` | 5563 |
| `coders` | 5564 |
| `heist` | 5565 |
| `command_center` | 5566 |
| `hub` | 8500 |
| `dashboard` | 8501 |
| `admin` | 8502 |
| `assets` | 8503 |
| `creator` | 8504 |

### hardware

| Key | Default | Description |
|-----|---------|-------------|
| `gpu_name` | NVIDIA GeForce RTX 2060 | GPU model |
| `gpu_vram_mb` | 12288 | VRAM in MB |
| `ram_gb` | 32 | System RAM |
| `cpu` | Intel Core i9 | CPU model |

### comfyui

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | false | Enable image generation |
| `base_url` | `http://localhost:8188` | ComfyUI API URL |
| `output_dir` | `C:/ComfyUI/output` | Generated image output |
| `timeout` | 500 | Request timeout (seconds) |
| `generation.steps` | 30 | Diffusion steps |
| `generation.cfg` | 5.5 | Classifier-free guidance scale |
| `generation.sampler` | euler | Sampler algorithm |
| `generation.scheduler` | normal | Noise schedule |
| `generation.denoise` | 1.0 | Denoising strength |

### media_standards

Defines resolution, format, and constraints for generated media:

- **Images**: selfie (512x768 PNG), portrait (512x768 PNG), thumbnail (200x200 JPG)
- **Video**: message (640x480 H.264 24fps), call (640x480 H.264 15fps)
- **Audio**: voice_message/voice_mail (22050 Hz mono WAV, 10s-1h)

### mcp

| Key | Default | Description |
|-----|---------|-------------|
| `port` | 8700 | MCP server port |
| `base_url` | `http://localhost:8700` | MCP base URL |
| `servers` | cosysim (enabled) | Registered MCP servers |

### characters

| Key | Default | Description |
|-----|---------|-------------|
| `default_personality` | playful | Default character personality |
| `default_role` | girlfriend | Default character role |
| `memory.max_context_messages` | 200 | Conversation history window |
| `memory.importance_threshold` | 0.5 | Memory importance filter |
| `memory.embedding_batch_size` | 32 | Batch size for embeddings |

### services

| Service | Enabled | Key Settings |
|---------|---------|-------------|
| `autonomous_messenger` | true | frequency: moderate, active_hours: 8-23 |
| `voice_calls` | true | max_duration: 3600s |
| `video_calls` | true | fps: 15, resolution: 640x480 |

### security

| Key | Default | Description |
|-----|---------|-------------|
| `input_validation.max_message_length` | 10000 | Max input characters |
| `input_validation.max_file_size` | 10485760 | Max upload size (10 MB) |
| `rate_limiting.enabled` | false | Rate limiting (enabled in production) |
| `rate_limiting.requests_per_minute` | 60 | Request cap |

### logging

| Key | Default | Description |
|-----|---------|-------------|
| `level` | INFO | Log level |
| `file` | `./logs/cosysim.log` | Log file path |
| `max_bytes` | 10485760 | Max log file size (10 MB) |
| `backup_count` | 5 | Rotated log files to keep |

### pipeline

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | true | Enable inference pipeline |
| `watcher.enabled` | true | Stream watcher |
| `watcher.trigger_tokens` | 8 | Tokens before triggering watcher |
| `watcher.batch_size` | 16 | Watcher batch size |
| `kill_switch.enabled` | true | Safety kill switch |
| `kill_switch.threshold` | 0.3 | Kill confidence threshold |
| `kill_switch.max_retries` | 2 | Retries before kill |
| `kill_switch.repetition_limit` | 3 | Max repeated tokens |
| `token_ahead.pre_warm_timeout` | 5.0 | Pre-warm timeout (seconds) |
| `conversation.max_branches` | 10 | Max conversation branches |
| `conversation.branch_ttl` | 300 | Branch time-to-live (seconds) |

### observability

| Key | Default | Description |
|-----|---------|-------------|
| `metrics_db` | `data/metrics.db` | Metrics database path |
| `system_tick_interval` | 1.0 | Metrics tick interval (seconds) |
| `retention_hours` | 24 | Metrics retention window |
| `alerts.gpu_vram_pct` | yellow/red thresholds | VRAM usage alerts |
| `alerts.queue_depth` | yellow/red thresholds | Queue depth alerts |
| `alerts.avg_latency_ms` | yellow/red thresholds | Latency alerts |
| `alerts.kill_rate` | yellow/red thresholds | Kill switch rate alerts |
| `alerts.error_rate` | yellow/red thresholds | Error rate alerts |

### training

| Key | Default | Description |
|-----|---------|-------------|
| `auto_capture` | true | Capture training examples from live traffic |
| `min_quality` | 0.7 | Minimum quality score for captured data |
| `auto_train.enabled` | false | Automatic training trigger |
| `auto_train.min_examples` | 100 | Min examples before auto-train |
| `auto_train.schedule` | daily | Auto-train schedule |
| `datasets.tag_extraction` | 100 (threshold) | Per-dataset thresholds |

### notebooklm

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | true | Enable NLM Live Proxy |
| `proxy_url` | `http://localhost:8800` | NLM Live Proxy URL |
| `base_url` | `http://localhost:8800` | Alias for proxy_url |
| `default_notebook_id` | (empty) | Default notebook for queries |
| `timeout` | 120 | Per-request timeout (seconds) |
| `metadata_path` | `data/nlm_notebooks.json` | Notebook metadata persistence |

### comms

| Key | Default | Description |
|-----|---------|-------------|
| `governance_enabled` | true | Route through interceptor chain |
| `skill_manifest_path` | `config/skill_manifests.yaml` | Skill manifest location |
| `stats_poll_interval_ms` | 2000 | Stats polling interval |
| `interceptors` | all enabled (except memory_enhancer) | Interceptor toggles |

### framework

| Key | Default | Description |
|-----|---------|-------------|
| `state_persistence` | true | Persist MCP framework state |
| `state_file` | `data/mcp_framework_state.json` | State file path |
| `max_event_log` | 500 | Max event log entries |
| `max_consequence_age_turns` | 50 | Consequence expiry (turns) |

### testing

| Key | Default | Description |
|-----|---------|-------------|
| `database` | `simulation_test.db` | Test database file |
| `mock_external_services` | true | Mock LLM/TTS in tests |
| `default_suite` | `full` | Default suite for scheduler |
| `scene_ports` | `[5555, 5556, 5571, 8500]` | Scene ports for health checks |
| `unit_test_timeout` | 300 | Unit test timeout (seconds) |
| `health_check_timeout` | 30 | Scene health check timeout |
| `store_results_in_nexus` | true | Persist results in Nexus KMS |
| `schedule_interval_minutes` | 0 | Recurring schedule (0 = disabled) |

#### testing.smart_runner

Controls the tiered test runner (`scripts/smart_test_runner.py`):

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | true | Enable smart runner features |
| `default_tier` | 2 | Default tier when none specified |
| `parallel_workers` | 4 | pytest-xdist worker count |
| `timing_cache` | `data/test_timing.json` | Per-test timing data cache |
| `reports_dir` | `data/test_reports` | JSON report output directory |
| `skip_patterns` | `[test_agent_loop.py, live_wire_test.py]` | Always-skipped test patterns |
| `tier_1_patterns` | `[test_scene_imports, ...]` | Tier 1 (smoke) file patterns |
| `tier_2_patterns` | `[test_penthouse*, ...]` | Tier 2 (core) file patterns |
| `tier_3_patterns` | `[test_pipeline*, ...]` | Tier 3 (integration) file patterns |

#### testing.browser_checks

Controls CDP-based browser test suites used by the test scheduler:

| Check | Description |
|-------|-------------|
| `console_errors` | Capture JavaScript console errors |
| `network_failures` | Detect failed network requests |
| `dom_health` | Validate DOM structure and rendering |

See [Testing](TESTING.md) for CLI usage and the full 4-tier strategy.

### assets

| Key | Default | Description |
|-----|---------|-------------|
| `validation.check_existence` | true | Validate asset files exist |
| `validation.check_format` | true | Validate file formats |
| `validation.check_integrity` | true | Validate file integrity |
| `versioning.enabled` | true | Enable asset versioning |
| `versioning.max_versions` | 5 | Max versions to keep |

## Environment Variables

All environment variables use the `COSYSIM_` prefix (legacy `COSYVOICE_` is also supported).

| Variable | Config Path | Description |
|----------|-------------|-------------|
| `COSYSIM_ENV` | (startup) | Environment name (development / production) |
| `COSYSIM_DB_PATH` | `database.sqlite.path` | Database file location |
| `COSYSIM_PHONE_PORT` | `scenes.phone.port` | Phone UI port |
| `COSYSIM_DASHBOARD_PORT` | `scenes.dashboard.port` | Dashboard port |
| `COSYSIM_LLM_URL` | `llm.base_url` | LLM provider URL |
| `COSYSIM_LLM_MODEL` | `llm.model` | Model name override |
| `COSYSIM_TTS_DEVICE` | `tts.device` | TTS device (cuda / cpu) |
| `COSYSIM_TTS_URL` | `tts.server_url` | TTS server URL |
| `COSYSIM_STT_DEVICE` | `stt.device` | STT device |
| `COSYSIM_LOG_LEVEL` | `logging.level` | Log level |
| `COSYSIM_MCP_ENABLED` | `lmstudio.mcp_enabled` | Enable MCP integration |
| `COSYSIM_MCP_PORT` | `mcp.port` | MCP server port |
| `COSYSIM_GOVERNANCE_ENABLED` | `comms.governance_enabled` | Enable governance interceptors |

## development.yaml Overrides

```yaml
system.environment: development
database.sqlite.path: simulation_dev.db
scenes.phone.debug: true
scenes.phone.auto_reload: true
scenes.penthouse.debug: true
tts.warm_start: false
tts.device: cpu
stt.device: cpu
comfyui.enabled: false
logging.level: DEBUG
security.rate_limiting.enabled: false
```

## production.yaml Overrides

```yaml
system.environment: production
database.sqlite.path: /var/lib/cosyvoice/simulation.db
database.sqlite.pool_size: 10
scenes.*.host: 0.0.0.0          # All scenes bind to all interfaces
scenes.*.debug: false
tts.warm_start: true
tts.device: cuda
stt.device: cuda
comfyui.enabled: true
logging.level: WARNING
logging.file: /var/log/cosyvoice/cosyvoice.log
security.rate_limiting.enabled: true
security.rate_limiting.requests_per_minute: 60
```

## mcp.json

Defines MCP server launch commands:

```json
{
  "mcpServers": {
    "cosysim": {
      "command": "python",
      "args": ["-m", "engine.mcp.cosysim_server"]
    },
    "nexus": {
      "command": "python",
      "args": ["-m", "nexus.mcp.server"],
      "cwd": "C:\\Files\\Nexus"
    }
  }
}
```

## voices.yaml

Defines 11 TTS voice profiles with description, model size, reference audio, and tags. Key profiles:

| Profile | Model | Description |
|---------|-------|-------------|
| `live_wire_luna` | 1.7B | Warm, playful, teasing female |
| `lola` | 1.7B | Warm, smoky 1920s jazz contralto |
| `viktor` | 1.7B | Deep measured Eastern European baritone |
| `companion_f` | 1.7B | Warm, expressive mid-range female |
| `companion_m` | 1.7B | Confident, friendly mid-range male |
| `narrator` | 0.6B | Neutral, clear narrator |

## skill_manifests.yaml

Registers skills per scene with trigger types (`auto`, `optional`, `required`). Key scenes:

- **phone** — 32 skills (memory, stats, narrative, web search, cross-scene messaging)
- **penthouse** — 39+ skills (wardrobe, interactions, timed actions, mini-games)
- **lounge** — drinks, performances, secrets, heat tracking
- **casino** — poker, tells, moods, narrative injection

---

## Top-Level YAML Keys Reference

Complete list of `config/default.yaml` top-level sections:

| Key | Description |
|-----|-------------|
| `system` | Project name, version (`v1.49`), environment |
| `paths` | Directory paths (data, models, cache, logs) |
| `database` | SQLite + ChromaDB settings |
| `llm` | LLM provider, model, temperature |
| `lmstudio` | LMStudio connection, `api_token`, model profiles, speculative decoding |
| `agent_profiles` | Per-profile context/token/temperature limits (big, small, router) |
| `tts` | Text-to-speech engine and streaming |
| `stt` | Speech-to-text engine and model |
| `scenes` | Per-scene host/port/debug + extended settings (see penthouse) |
| `hardware` | GPU, VRAM, RAM, CPU specs |
| `comfyui` | ComfyUI image generation settings |
| `media_standards` | Image/video/audio format constraints |
| `mcp` | MCP server port and registered servers |
| `characters` | Default personality, role, memory settings |
| `services` | Autonomous messenger, voice/video calls |
| `security` | Input validation, rate limiting |
| `logging` | Log level, file, rotation |
| `pipeline` | Inference pipeline, kill switch, branching |
| `observability` | Metrics DB, alerts, retention |
| `training` | Auto-capture, training triggers, datasets |
| `notebooklm` | NLM Live Proxy and notebook settings |
| `comms` | Governance, interceptors, skill manifests |
| `framework` | MCP framework state persistence |
| `testing` | Test DB, smart runner, scheduler, browser checks |
| `assets` | Asset validation and versioning |

---

## See Also

- [Architecture](ARCHITECTURE.md) — System architecture, BaseScene, MCP pipeline
- [Operations](OPERATIONS.md) — Launcher, TUI, service management
- [LMStudio](LMSTUDIO.md) — LMStudio-specific configuration deep dive
- [Testing](TESTING.md) — Smart test runner, browser checks

---

## Change Log

| Version | Date | Description |
|---------|------|-------------|
| v1.50 | 2026-03-22 | Updated to v1.50; fixed system.version from v1.04b to v1.49; added config access pattern; removed stale cross-refs |
| v1.04b | 2025-09-01 | Initial configuration guide |
