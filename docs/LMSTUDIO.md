# LMStudio Integration

> CosySim Documentation — v1.52.0 [2026-03-26]
>
> Local inference backbone via LMStudio v1 native API at localhost:1234. SSE streaming,
> stateful conversations via response_id, ServerController, LMLinkManager (federation),
> TaskQueue, and 23 modules providing the complete inference subsystem.

LMStudio is CosySim's primary inference backend. Every character reply,
autonomous thought, classification task, benchmark, and vision analysis
flows through the LMStudio subsystem — 23 modules providing a complete
client, server controller, conversation manager, task queue, multi-instance
federation, and model lifecycle.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    CosySim Engine                        │
│                                                         │
│  ┌───────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ AgentGovernor │  │  TaskQueue   │  │ LMSTaskBridge│ │
│  │   + Pipeline  │  │  (priority)  │  │  (Copilot)   │ │
│  └───────┬───────┘  └──────┬───────┘  └──────┬───────┘ │
│          │                 │                  │         │
│  ┌───────▼─────────────────▼──────────────────▼───────┐ │
│  │              InferenceOrchestrator                  │ │
│  │      (tier selection, priority routing)             │ │
│  └───────────────────────┬────────────────────────────┘ │
│                          │                              │
│  ┌───────────────────────▼────────────────────────────┐ │
│  │                  LMSClient                          │ │
│  │  (chat, stream, vision, structured, stateful,       │ │
│  │   model lifecycle, bearer auth, MCP tools)          │ │
│  └───────────────────────┬────────────────────────────┘ │
│                          │                              │
│  ┌───────────────────────▼────────────────────────────┐ │
│  │   ServerController   │   LMLinkManager             │ │
│  │  (load/unload,       │  (multi-instance federation,│ │
│  │   health, agents)    │   peer routing, failover)   │ │
│  └──────────────────────┴─────────────────────────────┘ │
└─────────────────────────────┬───────────────────────────┘
                              │ HTTP + Bearer Auth
                    ┌─────────▼──────────┐
                    │   LMStudio Server  │
                    │  localhost:1234     │
                    │  v1 Native API     │
                    └────────────────────┘
```

---

## Module Inventory (23 Files)

| File | Purpose |
|------|---------|
| `__init__.py` | Package initialization, singleton exports |
| `lms_client.py` | **Core API client** — full v1 REST implementation |
| `server_controller.py` | **Server lifecycle** — load/unload, health, agent isolation |
| `conversation.py` | **Stateful chats** — branching, editing, response_id tracking |
| `task_queue.py` | **Priority queue** — async task execution with workers |
| `lmlink_manager.py` | **Multi-instance federation** — peer discovery, routing, failover |
| `model_manager.py` | **Model lifecycle** — concurrent/JIT/JIT-TTL with VRAM reaper |
| `orchestrator.py` | **Inference orchestrator** — tier selection, priority routing |
| `router.py` | **Three-tier router** — T1 GPU, T2 CPU utility, T3 CPU router |
| `router_data.py` | **Router data structures** — request/response containers |
| `router_v3_client.py` | **Router v3** — interface to router service |
| `inference_config.py` | **Config types** — InferenceConfig, LoadConfig dataclasses |
| `client.py` | **LMStudioManager** — SDK/CLI wrapper for model management |
| `sdk_client.py` | **SDK client** — WebSocket-based (legacy fallback) |
| `tool_factory.py` | **Tool factory** — creates MCP tool manifests |
| `tool_registry.py` | **Tool registry** — tracks tool availability |
| `resource_manager.py` | **Resources** — VRAM/memory/concurrency limits |
| `auto_tuner.py` | **Auto-tuning** — quantization selection, context optimization |
| `benchmark.py` | **Benchmarking** — TPS, latency, memory measurements |
| `concurrency.py` | **Concurrency** — slot allocation, parallel requests |
| `inference_monitor.py` | **Metrics** — token/latency/error tracking |
| `llmster_manager.py` | **LLMster** — specialized provider integration |
| `finetuned_router.py` | **Custom routing** — finetuned strategies |

---

## LMSClient API

The core client in `engine/lmstudio/lms_client.py`. Access via singleton:

```python
from engine.lmstudio import get_lms_client

client = get_lms_client()
```

### Constructor

```python
LMSClient(
    base_url: Optional[str] = None,    # default: from config
    *,
    timeout: float = 120.0,
    config=None,
    api_token: Optional[str] = None,   # bearer token
)
```

### Chat Methods (6)

| Method | Purpose |
|--------|---------|
| `chat(messages, *, config, model, temperature, max_tokens, stop_strings, integrations, response_format, store)` | Non-streaming chat via `/api/v1/chat` |
| `chat_stateful(user_message, *, previous_response_id, system, config, model)` | Stateful chat — server retains KV cache |
| `chat_stream(messages, *, config, model, on_event, store)` | SSE streaming with typed events |
| `chat_stream_stateful(user_message, *, previous_response_id, system, config, model, on_event)` | Stateful + streaming combined |
| `quick_reply(user_message, *, system, **kwargs)` | One-shot: system + user -> reply string |
| `chat_with_mcp(messages, mcp_servers, **kwargs)` | Chat with MCP tool integrations |

### Specialized Chat Methods (2)

| Method | Purpose |
|--------|---------|
| `chat_structured(messages, schema, *, schema_name, **kwargs)` | JSON schema-enforced structured output |
| `chat_with_images(text, image_urls, *, system, **kwargs)` | Vision: text + images -> VLM analysis |

### Model Lifecycle (6)

| Method | Purpose |
|--------|---------|
| `get_models(loaded_only, *, raw)` | List models with metadata |
| `get_model_info(model_id)` | Detailed model info (architecture, params, vision) |
| `resolve_model(hint)` | Resolve best model ID (30s cache) |
| `load_model(model_id, *, config, echo_load_config)` | Load model, returns instance ID + load time |
| `unload_model(model_id)` | Unload model, free VRAM |
| `download_model(model, *, quantization)` | Download from catalog |

### Speculative Decoding (2)

| Method | Purpose |
|--------|---------|
| `enable_speculative(main_model, draft_model, *, main_config, draft_config)` | Load main + draft for speculative decoding |
| `disable_speculative(draft_model)` | Unload draft model |

### Utility (5)

| Method | Purpose |
|--------|---------|
| `is_available()` | Check if server responds |
| `invalidate_model_cache()` | Clear model resolution cache |
| `count_tokens(text, model)` | Token count for text |
| `get_context_length(model)` | Context window size |
| `close()` | Close HTTP connection |
| `download_status(job_id)` | Check download progress |

### Response Types

**LMSResponse** — returned from all chat methods:

```python
@dataclass
class LMSResponse:
    content: str                    # generated text
    model: str                     # model used
    finish_reason: str             # "stop", "length", "tool_calls"
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: float
    request_id: str
    response_id: str               # for stateful continuations (resp_...)
    reasoning_content: str         # thinking model CoT
    reasoning_tokens: int
    tool_calls: List[Dict]
    server_tps: float              # tokens/sec from server
    time_to_first_token_s: float
    model_load_time_s: float
    metadata: Dict
```

**LMSStreamEvent** — received during streaming:

```python
@dataclass
class LMSStreamEvent:
    event_type: str      # chat.start, message.delta, chat.end, error, etc.
    content: str         # for message.delta, reasoning.delta
    progress: float      # for model_load.progress, prompt_processing.progress
    model_instance_id: str
    load_time_seconds: float
    tool_name: str
    tool_arguments: Dict
    tool_output: str
    error: Optional[Dict]
    stats: Optional[Dict]   # from chat.end
    response_id: str
    is_done: bool
```

**LMSModel** — rich model metadata:

```python
@dataclass
class LMSModel:
    type: str
    publisher: str
    key: str                         # model identifier
    display_name: str
    architecture: Optional[str]
    quantization: Optional[str]      # Q4_K_M, Q8_0, etc.
    format: Optional[str]            # gguf, mlx, etc.
    size_bytes: int
    max_context_length: int
    params_string: Optional[str]     # "7B", "70B", etc.
    loaded_instances: List[LMSModelInstance]
    capabilities: LMSCapabilities    # .vision, .trained_for_tool_use
    description: Optional[str]

    @property
    def is_loaded(self) -> bool      # any instances loaded?
    @property
    def instance_id(self) -> str     # first instance ID
```

---

## ServerController

Server lifecycle management in `engine/lmstudio/server_controller.py`. Access:

```python
from engine.lmstudio import get_server_controller

sc = get_server_controller()
```

### Model Management

| Method | Purpose |
|--------|---------|
| `load_model(model_key, *, context_length, gpu_offload, stop_strings)` | Load with config -> ModelInstance |
| `unload_model(model_key)` | Unload -> free VRAM |
| `list_models()` | All loaded and available models |
| `configure_inference(model_key, *, stop_strings, temperature, max_tokens)` | Update inference params |
| `get_instance_config(model_key)` | Get load/inference config |
| `estimate_vram(model_key)` | Estimate VRAM (MB) before load |
| `count_tokens(text, model_key)` | Token count |

### Agent Instance Isolation

| Method | Purpose |
|--------|---------|
| `create_agent_instance(agent_id, model_key, *, context_length, gpu_offload)` | Create agent-isolated instance |
| `get_agent_instance(agent_id)` | Retrieve agent's instance |
| `release_agent_instance(agent_id)` | Release (free resources) |
| `list_agent_instances()` | All active agent instances |

### Health Monitoring

| Method | Purpose |
|--------|---------|
| `is_server_running()` | Check if server is reachable |
| `get_server_status()` | ServerHealth (VRAM, health, queue) |
| `start_health_monitoring()` | Start background health thread |
| `stop_health_monitoring()` | Stop health thread |
| `last_health()` | Last cached health snapshot |
| `get_metrics()` | TPS, latency, queue depth |
| `get_full_status()` | Everything: health + models + agents + metrics |

### Data Types

**ModelInstance:**

```python
@dataclass
class ModelInstance:
    model_key: str
    instance_id: str
    context_length: int
    gpu_offload: float
    stop_strings: List[str]
    temperature: Optional[float]
    max_tokens: Optional[int]

    @property
    def idle_seconds(self) -> float
    @property
    def uptime_seconds(self) -> float
    def touch(self, tokens: int = 0) -> None
```

**ServerHealth:**

```python
@dataclass
class ServerHealth:
    status: str                   # "ok", "degraded", "critical"
    vram_used_mb: int
    vram_total_mb: int
    vram_free_mb: int
    temperature_c: Optional[float]
    queued_requests: int
    active_requests: int
    error_rate: float             # 0.0-1.0

    @property
    def vram_usage_pct(self) -> float
    @property
    def healthy(self) -> bool     # status == "ok"
```

---

## SSE Streaming Protocol

LMStudio v1 uses Server-Sent Events (NOT OpenAI-style). The stream format
uses typed `event:` lines followed by `data:` JSON.

### Event Types (19)

| Event | Data Fields | Purpose |
|-------|-------------|---------|
| `chat.start` | `model_instance_id` | Session begins |
| `model_load.start` | `model_instance_id` | Model loading begins |
| `model_load.progress` | `progress (0.0-1.0)` | Loading progress |
| `model_load.end` | `load_time_seconds` | Loading complete |
| `prompt_processing.start` | `model_instance_id` | Tokenization begins |
| `prompt_processing.progress` | `progress` | Processing progress |
| `prompt_processing.end` | `tokens` | Prompt tokenized |
| `reasoning.start` | `model_instance_id` | Thinking model CoT begins |
| `reasoning.delta` | `content` | Reasoning text chunk |
| `reasoning.end` | `tokens` | Reasoning complete |
| `tool_call.start` | `tool_name` | Tool call begins |
| `tool_call.arguments` | `arguments` | Tool arguments |
| `tool_call.success` | `output` | Tool succeeded |
| `tool_call.failure` | `error` | Tool failed |
| `message.start` | `model_instance_id` | Generation begins |
| `message.delta` | `content` | **Text chunk** (yield this) |
| `message.end` | `tokens` | Generation complete |
| `chat.end` | `stats, response_id` | Session ends, full stats |
| `error` | `error: {type, message}` | Error occurred |

### Wire Format

```
event: message.delta
data: {"content": "Hello "}

event: message.delta
data: {"content": "world"}

event: message.end
data: {"tokens": 2}

event: chat.end
data: {"stats": {"input_tokens": 15, "total_output_tokens": 2,
                  "tokens_per_second": 42.5,
                  "time_to_first_token_seconds": 0.12,
                  "model_load_time_seconds": 0.0},
       "response_id": "resp_abc123"}
```

### Parsing in LMSClient

```python
# _stream_native() reads SSE line-by-line
# _parse_v1_stream_event() parses event: + data: pairs
# Yields content strings from message.delta events
# Callback on_event(LMSStreamEvent) receives ALL typed events
# Final stats extracted from chat.end into LMSResponse

for chunk in client.chat_stream(messages, on_event=on_event):
    print(chunk, end="", flush=True)
```

---

## Stateful Conversations

`engine/lmstudio/conversation.py` provides client-side conversation
management with server-side KV cache integration.

### Conversation Class

| Method | Purpose |
|--------|---------|
| `send(user_msg, ...)` | Send message; auto-uses previous response_id |
| `send_stateless(prompt, ...)` | One-off query (store: false) |
| `add_system_message(content)` | Prepend system message |
| `add_assistant_message(content)` | Append for replay |
| `edit_message(index, new_content)` | Edit history (invalidates server state) |
| `truncate(keep_turns)` | Keep only first N turns |
| `fork(new_id, system)` | Clone conversation with same history |
| `branch_at(turn_index, new_id)` | Fork at turn using recorded response_id |
| `invalidate()` | Force replay on next send |
| `update_system_if_changed(new_system)` | Update system only if hash changed |
| `get_history()` | Messages as dicts |
| `get_summary()` | turn_count, created_at, last_active |

### ConversationManager

| Method | Purpose |
|--------|---------|
| `create(conv_id, system, model)` | Create new conversation |
| `get(conv_id)` | Retrieve by ID |
| `get_or_create(conv_id, **kwargs)` | Get or create |
| `delete(conv_id)` | Delete conversation |
| `invalidate_all(reason)` | Invalidate all (e.g., model unloaded) |
| `invalidate_model(model_id)` | Invalidate conversations using a model |
| `on_invalidate(callback)` | Register invalidation listener |
| `list_conversations()` | All conversation metadata |
| `get_stats()` | Total conversations, turns, active |

### response_id Tracking

- Format: `resp_<random>` (e.g., `resp_abc123def456`)
- Recorded in `Conversation._response_id_history`
- Used for continuations: `previous_response_id` in `chat_stateful()`
- Branching: `branch_at(turn)` looks up the response_id at that turn

### Example

```python
from engine.lmstudio.conversation import get_conversation_manager

mgr = get_conversation_manager()
conv = mgr.create("aria_phone", system="You are Aria...")

resp1 = conv.send("Hello!")
print(resp1.response_id)   # resp_xyz...

resp2 = conv.send("What's your name?")  # auto-uses previous response_id

conv.edit_message(1, "Actually, goodbye!")  # clears server state, replays

alt = conv.branch_at(1, new_id="aria_alt")  # fork at turn 1
alt.send("Different path")
```

---

## TaskQueue

Async priority task execution in `engine/lmstudio/task_queue.py`.

### Enums

**TaskType:** `PROMPT`, `INFERENCE`, `COMPLETION`, `CLASSIFICATION`, `EMBEDDING`, `VISION`, `EVALUATION`

**TaskStatus:** `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`

**TaskPriority:**

| Level | Value | Use Case |
|-------|-------|----------|
| `REALTIME` | 0 | Scene agent, player interaction |
| `INTERACTIVE` | 1 | Phone chat, UI response |
| `BACKGROUND` | 2 | Autonomous text, periodic checks |
| `BATCH` | 3 | Images, analytics |

### Public Methods

| Method | Purpose |
|--------|---------|
| `submit(task_type, messages, *, config, priority, model, on_complete)` | Submit task -> task_id |
| `cancel(task_id)` | Cancel pending/running task |
| `get_task(task_id)` | Retrieve task state |
| `wait_for(task_id, timeout)` | Blocking wait for completion |
| `start(num_workers)` | Start worker threads |
| `stop()` | Graceful shutdown |
| `queue_depth` | Property: pending count |
| `active_tasks` | Property: executing count |
| `get_status()` | Queue status + metrics |
| `get_recent_tasks(limit)` | Completed/failed tasks |
| `on_complete(callback)` | Register completion callback |
| `on_error(callback)` | Register error callback |

### Task Data Class

```python
@dataclass
class Task:
    task_id: str
    task_type: TaskType
    status: TaskStatus
    priority: TaskPriority
    model: str
    messages: List[Dict]
    result: Optional[LMSResponse]
    error: Optional[str]
    created_at: float
    started_at: float
    completed_at: float

    @property
    def queue_time_ms(self) -> float    # started_at - created_at
    @property
    def total_time_ms(self) -> float    # completed_at - created_at
```

---

## LMLink Federation

Multi-instance model routing in `engine/lmstudio/lmlink_manager.py`.
Connects multiple LMStudio instances (local + remote via Tailscale)
into a federated inference pool.

### LMLinkManager

| Method | Purpose |
|--------|---------|
| `enabled` | Property: federation enabled |
| `strategy` | Property: routing strategy |
| `get_peer(name)` | Retrieve peer by name |
| `get_local_peer()` | Local instance peer |
| `get_remote_peers()` | All remote peers |
| `get_healthy_peers()` | Healthy peers only |
| `resolve_peer(model_key, *, prefer_local)` | Best peer for model (affinity + load) |
| `list_remote_models()` | Query all peers for available models |
| `check_peer_health(peer)` | Single peer health check |
| `check_all_peers()` | Health check all peers |
| `start_health_monitoring()` | Background health loop (60s) |
| `stop_health_monitoring()` | Stop monitoring |
| `resolve_with_failover(model_key, max_retries, retry_delay_ms)` | Resolve with automatic failover |
| `get_status()` | Federation status summary |

### LMLinkPeer

```python
@dataclass
class LMLinkPeer:
    name: str
    host: str
    port: str
    capabilities: List[str]   # ["inference", "embedding", "vision"]
    max_models: int
    priority: int             # lower = preferred
    tags: List[str]

    @property
    def api_base(self) -> str
    @property
    def healthy(self) -> bool
    @property
    def error_rate(self) -> float

    def record_success(self, latency_ms: float) -> None
    def record_failure(self) -> None
```

### Routing Strategies

| Strategy | Behavior |
|----------|----------|
| `capability_first` | Route to peer with required capabilities |
| `round_robin` | Distribute evenly across peers |
| `least_loaded` | Route to peer with lowest queue depth |
| `local_first` | Prefer local, overflow to remote |

### Configuration (config/lmlink.yaml)

```yaml
lmlink:
  enabled: false
  local:
    name: "workstation"
    host: "localhost"
    port: 1234
    gpu: "nvidia"
    vram_mb: 12288
    capabilities: [inference, embedding, vision]

  peers:
    - name: "nuc"
      host: "100.x.x.x"         # Tailscale IP
      port: 1234
      capabilities: [inference]
      max_models: 2
      priority: 2

  routing:
    strategy: "capability_first"
    affinity:
      - pattern: "*70B*"
        prefer: workstation      # large models on GPU
      - pattern: "*0.6B*"
        prefer: nuc              # tiny models on edge device
    failover:
      enabled: true
      max_retries: 2
      retry_delay_ms: 1000
      fallback_to_local: true
    load_balance:
      check_interval_seconds: 30
      max_queue_depth: 5
      vram_threshold_pct: 90

  health:
    check_interval_seconds: 60
    timeout_ms: 5000
    auto_reconnect: true
    max_reconnect_attempts: 3
```

---

## Model Profiles

Configured in `config/default.yaml` under `lmstudio.models`:

| Profile | Tier | Max Tokens | Context | Use Case |
|---------|------|-----------|---------|----------|
| `big` | T1 (GPU) | 4000 | 4096 | Character dialogue, narration |
| `small` | T2 (CPU) | 800 | 2048 | Quick decisions, auto-texts |
| `router` | T3 (CPU) | 200 | 1024 | Intent classification |
| `draft` | T3 | 128 | -- | Speculative decoding |
| `vision` | T1 (GPU) | -- | -- | VLM image analysis |

### Resolution Logic (LMSClient.resolve_model)

1. If `config.lmstudio.models.<role>.key` is set -> use it
2. Query `/api/v1/models` for loaded models
3. If default model configured and loaded -> use it
4. Else -> use first loaded model
5. Cache for 30 seconds

### InferenceConfig Factory

```python
from engine.lmstudio.inference_config import InferenceConfig

config = InferenceConfig.from_agent_profile("big")
config = InferenceConfig.from_yaml(yaml_dict)
merged = InferenceConfig.merge(base, override)
```

---

## Bearer Authentication

LMStudio requires a bearer token for API access.

### Token Resolution (Priority Order)

1. Constructor parameter: `api_token` to `LMSClient.__init__()`
2. Environment variable: `LMSTUDIO_API_TOKEN` or `LOCAL_LM_STUDIO_TOKEN`
3. Config file: `config/default.yaml` -> `lmstudio.api_token`

### Header Format

```
Authorization: Bearer sk-lm-<random>:<random>
```

### Implementation

```python
# LMSClient (lms_client.py)
headers: Dict[str, str] = {}
if self._api_token:
    headers["Authorization"] = f"Bearer {self._api_token}"
self._client = httpx.Client(timeout=timeout, headers=headers)

# ComputeRouter (compute_router.py)
def _resolve_lmstudio_headers() -> Dict[str, str]:
    token = (
        os.environ.get("LMSTUDIO_API_TOKEN", "").strip()
        or os.environ.get("LOCAL_LM_STUDIO_TOKEN", "").strip()
        or str(cfg.get("lmstudio.api_token", "")).strip()
    )
    return {"Authorization": f"Bearer {token}"} if token else {}
```

### Token Generation

Navigate to: **LMStudio -> Developer -> Server Settings -> Manage Tokens**

---

## Vision Support

CosySim supports vision models (Qwen2-VL, LLaVA, InternVL) for image
understanding via the LMStudio v1 API.

### Client API

```python
response = client.chat_with_images(
    text="What do you see in this screenshot?",
    image_urls=["data:image/png;base64,...", "https://example.com/img.png"],
    system="You are a helpful assistant with vision capabilities.",
)
```

### Input Format (v1 Native)

```python
messages = [
    {"role": "system", "content": system},
    {"role": "user", "content": [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
    ]},
]
```

### Supported Image Types

- Data URLs: `data:image/png;base64,...`
- HTTP URLs: `https://example.com/image.png`
- Local files: automatically base64-encoded

### Vision Skills (engine/skills/builtin/vision_skills.py)

| Skill | Purpose |
|-------|---------|
| `screenshot_analysis(image_path, prompt, system)` | Analyze image content |
| `extract_ui_elements(image_path, system)` | Detect buttons, text fields, labels |
| `compare_images(image1_path, image2_path)` | Highlight differences |
| `read_text(image_path)` | OCR-style text extraction |

### Model Configuration

```yaml
lmstudio:
  models:
    vision: "qwen/qwen3-vl-4b"    # default VLM
```

Model capability check:
```python
model = client.get_model_info()
if model.capabilities.vision:
    # VLM is available
```

---

## ComputeRouter

Multi-backend inference routing in `engine/integrations/compute_router.py`.
Routes between LMStudio (local), Copilot (cloud), Colab (GPU), and tunnel servers.

### Routing Priority

1. **Active Colab tunnels** — fastest GPU (when available)
2. **Colab AI agent** — mid-tier cloud (always available)
3. **Local LMStudio** — fallback (always on)

### Public Methods

| Method | Purpose |
|--------|---------|
| `infer(prompt, *, model, backend)` | Route inference request |
| `jit_infer(prompt, tier)` | One-off JIT inference |
| `check_backend(backend)` | Check backend availability |
| `get_usage(account_name)` | Usage counters |
| `check_limit(account_name, service)` | Usage vs limit |
| `select_backend(model, hint)` | Select best backend |

### Routing Hints

| Hint | Backend |
|------|---------|
| `"lmstudio"` | Force local LMStudio |
| `"copilot"` | Force Copilot (Claude) |
| `"colab"` | Prefer Colab tunnel |
| `"fast"` | claude-haiku-4.5 |
| `"balanced"` | claude-sonnet-4.6 |
| `"smart"` | claude-opus-4.6 |
| `"code"` | gpt-5.2-codex |

### Account Tier Limits

| Resource | Free | Pro |
|----------|------|-----|
| Colab requests/day | 100 | 1000 |
| Colab GPU hours/day | 6.0 | 24.0 |
| NLM queries/day | 50 | 500 |
| Drive storage GB | 15.0 | 100.0 |

---

## LMSTaskBridge

Delegate inference tasks from Copilot CLI to local LMStudio models.
Located in `engine/nexus/lms_task_bridge.py`.

### Public Methods

| Method | Purpose |
|--------|---------|
| `run_prompt(prompt, *, model, system_prompt, temperature, max_tokens, task_type, priority)` | Single prompt -> TaskResult |
| `run_batch(prompts, *, model, system_prompt, store_results)` | Batch of prompts |
| `run_task(task_type, prompt, *, context, model, store_result)` | Structured task (evaluate/summarize/generate/classify/compare) |
| `check_lmstudio()` | Health check |
| `wait_for(task_id, timeout)` | Block until complete |

### TaskResult

```python
@dataclass
class TaskResult:
    task_id: str = ""
    status: str = "pending"       # pending, running, completed, failed
    output: str = ""
    model: str = ""
    latency_ms: float = 0.0
    tokens_generated: int = 0
    tps: float = 0.0
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool           # completed and no error
```

### Example

```python
from engine.nexus.lms_task_bridge import LMSTaskBridge

bridge = LMSTaskBridge()

result = bridge.run_prompt("Summarize this code", model="qwen3-0.6b")
if result.ok:
    print(result.output)

results = bridge.run_batch([
    {"prompt": "Variation 1", "temperature": 0.3},
    {"prompt": "Variation 2", "temperature": 0.9},
], store_results=True)

result = bridge.run_task(
    task_type="evaluate",
    prompt="Rate this dialog for naturalness",
    context={"dialog": "A: Hi\nB: Hello"},
    store_result=True,
)
```

---

## LMStudio Skills

### Server Control (engine/skills/builtin/lmstudio_server_skills.py)

| Skill | Category | Cooldown | Cost | Purpose |
|-------|----------|----------|------|---------|
| `lms_load_model(model_key, context_length, gpu_offload, stop_strings)` | SYSTEM | 10s | 3.0 | Load model |
| `lms_unload_model(model_key)` | SYSTEM | 5s | 1.0 | Unload model |
| `lms_list_models()` | SYSTEM | 2s | 0.5 | List models |
| `lms_server_health()` | SYSTEM | 5s | 0.5 | Server status |
| `lms_configure_model(model_key, stop_strings, temperature, max_tokens)` | SYSTEM | 2s | 1.0 | Update params |
| `lms_create_agent_instance(agent_id, model_key)` | SYSTEM | 5s | 2.0 | Agent isolation |
| `lms_release_agent_instance(agent_id)` | SYSTEM | 2s | 0.5 | Release instance |

### Inference & Benchmarking (engine/skills/builtin/inference_skills.py)

| Skill | Purpose |
|-------|---------|
| `benchmark_model(prompt, model, iterations, max_tokens)` | Run benchmark -> TPS, latency |
| `store_benchmark(model, method, tps, latency_ms, ...)` | Store results in Nexus |
| `get_leaderboard(method, limit)` | Retrieve benchmark leaderboard |
| `check_lmstudio()` | Check LMStudio status |
| `delegate_task(task_type, prompt, model, priority)` | Delegate via LMSTaskBridge |

---

## Three-Tier Inference Router

`engine/lmstudio/router.py` implements priority-based routing:

| Tier | Target | Use Case |
|------|--------|----------|
| **T1** | GPU model | Character dialogue, narration, complex reasoning |
| **T2** | CPU utility | Quick decisions, classifications |
| **T3** | CPU router | Intent classification, routing |

The router selects tier based on `InferenceConfig.priority` and available
models, then dispatches through either the SDK WebSocket channel or REST
HTTP channel.

---

## Model Loading Modes

`engine/lmstudio/model_manager.py` supports three strategies:

| Mode | Behavior |
|------|----------|
| `concurrent` | Models loaded at startup, stay loaded |
| `jit` | Load on first request, stay loaded |
| `jit_ttl` | Load on first request, unload after idle TTL |

The VRAM-aware TTL reaper runs in the background, evicting idle models
when memory pressure exceeds `resource_manager.vram_threshold_pct` (default 85%).

---

## Configuration Reference

Complete `lmstudio` section in `config/default.yaml`:

```yaml
lmstudio:
  host: "127.0.0.1"
  port: 1234
  base_url: "http://127.0.0.1:1234"
  api_token: ""                         # bearer token (or env var)
  api_version: "v1"                     # v1 native API

  default_load_opts:
    gpu: 0.9                            # GPU offload fraction
    ttl: 3600                           # idle TTL seconds
    context_length: 4096

  vram_cap_mb: 11500                    # hard cap (RTX 2060 = 12GB)
  cli: "lms"

  mcp_enabled: true
  cosysim_mcp_url: "http://localhost:8700/mcp/sse"
  mcp_json_path: ""

  load_mode: "concurrent"               # concurrent | jit | jit_ttl
  concurrent_slots: 4
  concurrent_model: ""                   # pin model (empty = auto)
  jit_ttl_seconds: 300

  resource_manager:
    vram_threshold_pct: 85
    auto_offload: true

  inference_defaults:
    max_output_tokens: 4000

  load_defaults:
    context_length: 4096
    gpu_offload: 0.9

  speculative:
    draft_model: ""                     # e.g., "qwen2.5-0.5b-instruct"

  router:
    tier_selection: "auto"
    priority_aware: true

  models:
    big:
      max_tokens: 4000
    small:
      max_tokens: 800
    router:
      max_tokens: 200
    vision: "qwen/qwen3-vl-4b"

  sdk:
    enabled: true

  llmster:
    enabled: false

  remote_hosts: []

  gpu_name: "NVIDIA GeForce RTX 2060"
  gpu_vram_mb: 12288
  ram_gb: 32
  cpu: "Intel Core i9"
```

---

## Singleton Access

| Singleton | Module | Access |
|-----------|--------|--------|
| `LMSClient` | `engine/lmstudio/lms_client.py` | `get_lms_client()` |
| `ServerController` | `engine/lmstudio/server_controller.py` | `get_server_controller()` |
| `ConversationManager` | `engine/lmstudio/conversation.py` | `get_conversation_manager()` |
| `LMLinkManager` | `engine/lmstudio/lmlink_manager.py` | via `__init__.py` |
| `InferenceOrchestrator` | `engine/lmstudio/orchestrator.py` | via `__init__.py` |
| `ComputeRouter` | `engine/integrations/compute_router.py` | `get_compute_router()` |
| `LMSTaskBridge` | `engine/nexus/lms_task_bridge.py` | direct instantiation |

---

## Health Checks

```bash
# Quick availability check
curl http://localhost:1234/api/v1/models

# From Python
from engine.lmstudio import get_lms_client
client = get_lms_client()
print(client.is_available())

# Full status
from engine.lmstudio import get_server_controller
sc = get_server_controller()
print(sc.get_full_status())
```

---

## Metrics Summary

| Metric | Value |
|--------|-------|
| Total files in `engine/lmstudio/` | 23 |
| LMSClient public methods | 21 |
| ServerController public methods | 23 |
| TaskQueue public methods | 13 |
| LMLinkManager public methods | 18 |
| Conversation public methods | 12 |
| ConversationManager public methods | 8 |
| SSE event types | 19 |
| Model profiles | 5 (big, small, router, draft, vision) |
| Routing tiers | 3 (T1 GPU, T2 CPU, T3 CPU router) |
| Priority levels | 4 (REALTIME, INTERACTIVE, BACKGROUND, BATCH) |
| Server control skills | 7 |
| Inference/benchmark skills | 5 |
| Vision skills | 4 |

---

## See Also

- [Architecture](ARCHITECTURE.md) — System architecture, MCP pipeline, interceptor chain
- [MCP Framework](MCP_FRAMEWORK.md) — Full MCP system, AgentGovernor, skill registration
- [Training](TRAINING.md) — DataCollector, FinetuneOrchestrator, BenchmarkRunner
- [Configuration](CONFIGURATION.md) — `lmstudio.*` config keys reference

---

## Change Log

| Version | Date | Description |
|---------|------|-------------|
| v1.50 | 2026-03-22 | Updated to v1.50; fixed header version from v0.91b; confirmed v1 API, SSE streaming, response_id stateful; removed stale cross-refs |
| v0.91b | 2025-08-01 | Initial LMStudio integration documentation |
