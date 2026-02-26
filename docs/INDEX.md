# CosySim Documentation Index

> All project documentation in one place. v0.55b — 3,521 tests, 160+ MCP tools, 18 scenes.

## Getting Started

| Doc | Description |
|-----|-------------|
| [README](../README.md) | Project overview, quick start, architecture |
| [Deployment](DEPLOYMENT.md) | Service architecture, startup, ports, health checks |
| [Configuration](CONFIGURATION.md) | All config files and settings |
| [Roadmap](../ROADMAP.md) | Version history and future plans |

## Architecture & Design

| Doc | Description |
|-----|-------------|
| [Architecture](ARCHITECTURE.md) | System design, layers, data flow, interceptor pipeline |
| [Interceptors](INTERCEPTORS.md) | Interceptor pipeline — all 25 hooks, priorities, custom interceptors |
| [MCP Framework](MCP_FRAMEWORK.md) | Tools, governance, state, dialog, rules, skills |
| [Characters](CHARACTERS.md) | Personality, stats, buffs, tags, relationships |
| [LMStudio](LMSTUDIO.md) | InferenceOrchestrator, model management, routing, streaming, branching |
| [Spatial System](SPATIAL.md) | SceneMap, Location, character positioning, proximity gating |

## Scenes & Content

| Doc | Description |
|-----|-------------|
| [Scenes Guide](SCENES.md) | All 13 game scenes — mechanics, APIs, rules |
| [Skills](SKILLS.md) | @skill decorator, 13 built-in + 13 scene packs (160+ skills) |
| [Admin Guide](ADMIN_GUIDE.md) | Admin panel pages and operations |

## APIs & Integration

| Doc | Description |
|-----|-------------|
| [API Reference](API.md) | REST endpoints, Socket.IO events, all scenes |
| [TTS](TTS.md) | Qwen3-TTS server, voice design, streaming |
| [NotebookLM & Nexus](NOTEBOOKLM.md) | NotebookLM integration via Nexus dual-backend |
| [NotebookLM HAR SDK](NOTEBOOKLM_HAR_SDK.md) | Batchexecute protocol, RPC endpoints, HAR extraction script |
| [Nexus Integration](NEXUS_INTEGRATION.md) | NexusClient, 16 skills, namespaces, memory, distillers, training, workflows |

## External Systems

| Doc | Description |
|-----|-------------|
| [Nexus Architecture](../../Nexus/docs/ARCHITECTURE.md) | Knowledge Management System design |
| [Nexus README](../../Nexus/README.md) | Nexus quick start, API endpoints, MCP tools |

## Observability

| Doc | Description |
|-----|-------------|
| [Logging](LOGGING.md) | CosyLogger ring buffer, SystemMonitor, structured logging patterns |
| [KPI](KPI.md) | `@timed` decorator, LLM KPIs, benchmarking dashboard |

## Training & Testing

| Doc | Description |
|-----|-------------|
| [Training](TRAINING.md) | Gemma 270M fine-tuning pipeline, datasets, Colab |
| [Router Training Data](ROUTER_TRAINING.md) | RouterDataCollector, inference capture, tier label export |
| [Testing](TESTING.md) | Test commands, fixtures, writing tests (3,521 tests, 75+ files) |

## Development

| Doc | Description |
|-----|-------------|
| [Contributing](CONTRIBUTING.md) | Scene creation, skill writing, interceptors, tests |
| [Changelog](../CHANGELOG.md) | Sprint history and changes |

## Internal (Development Logs)

| Doc | Description |
|-----|-------------|
| [Agent Revelations](internal/AGENT_REVELATIONS.md) | Sprint implementation logs |
| [Project CozyDreamz](internal/Project-CozyDreamz.md) | Original project design document |
