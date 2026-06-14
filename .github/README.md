<p align="center">
  <img src="docs/assets/scenes/landing.png" alt="CosySim — NEON CITY · Dark Renaissance" width="100%">
</p>

<h1 align="center">CosySim</h1>

<p align="center">
  <strong>A local-first, open AI simulation framework where every NPC is a real, governed LLM agent — and the world remembers.</strong>
</p>

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-1.61.0-06b6d4">
  <img alt="python" src="https://img.shields.io/badge/python-3.13-3776AB">
  <img alt="local-first" src="https://img.shields.io/badge/inference-100%25%20local-22c55e">
  <img alt="frontend" src="https://img.shields.io/badge/frontend-vanilla%20JS%20·%20no%20build-f59e0b">
  <img alt="license" src="https://img.shields.io/badge/license-see%20LICENSE-9d71ea">
</p>

<p align="center">
  35 launch targets · ~1,040 skills · 38-stage interceptor pipeline · 6-tier knowledge router · a training flywheel —<br>
  built almost entirely through <strong>agentic coding</strong>, and published so humans <em>and</em> AI agents can learn from it.
</p>

---

> **Why this repo exists.** CosySim is meant to be *read*. It is a working, end-to-end example of what local agents + agentic
> coding can build: a living cyberpunk city whose residents reason on a local model, recall the past from a persistent knowledge
> base, react to a live economy and faction war, and quietly turn every interaction into training data that improves the next one.
> Take any piece you like — the interceptor pipeline, the LMStudio steering, the NLM↔Nexus flywheel, the ARGUS toolkit — and use it
> in your own project.

## Start here

Pick the door that matches why you came:

| You want to… | Go to | Deep-dive doc |
|---|---|---|
| **Run it** in 5 minutes | [Quickstart](#quickstart) | [`docs/OPERATIONS.md`](docs/OPERATIONS.md) |
| Understand **how it fits together** | [Overview &amp; Architecture](#overview) | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| See the **game / living world** | [NEON CITY](#neon-city) | scene code in `content/scenes/` |
| Learn **how agents are steered** | [Engine Internals](#engine-internals) | [`docs/MCP_FRAMEWORK.md`](docs/MCP_FRAMEWORK.md) |
| Understand the **AI brain** (local → frontier) | [NLM + NEXUS](#nlm-nexus) | [`docs/NEXUS.md`](docs/NEXUS.md) |
| **Train / finetune / self-improve** | [CONTROL](#control) | `engine/training/`, `training/` |
| Wire **external services** | [Integrations, Apps &amp; CLI](#integrations-apps) | `docs/*_API_REFERENCE.md` |
| Do **web-app reconnaissance** | [ARGUS](#argus) | [`docs/ARGUS_METHODOLOGY.md`](docs/ARGUS_METHODOLOGY.md) |
| **Create** scenes / assets | [Creation Kit &amp; Asset Studio](#creation) | [`docs/DESIGN_SYSTEM_V2.md`](docs/DESIGN_SYSTEM_V2.md) |
| Browse **everything** | — | [`docs/INDEX.md`](docs/INDEX.md) |

## Quickstart

> **Prerequisites:** Python 3.13, [LMStudio](https://lmstudio.ai) running on `:1234` with a chat model loaded.
> Optional: [ComfyUI](https://github.com/comfyanonymous/ComfyUI) (`:8188`) for image/video, a TTS server (`:8600`) for voice.

```bash
# 1. Install
pip install -r requirements.txt && npm install

# 2. Configure secrets (nothing real is committed — see "Security & configuration")
cp .env.example .env          # then fill in any keys you have; LMStudio works with no auth

# 3. Launch
python tui.py                 # interactive Terminal UI (recommended) — ←/→/↑/↓ to navigate, Enter to launch
python launcher.py --core     # or: auto-start core services + main scenes
python launcher.py neoncity   # or: a single scene → http://localhost:5563
python launcher.py --list     # see all 35 targets + live port status
```

Then open the hub at **http://localhost:8500** — the NEON CITY landing page — and jack in.

```bash
# Handy
python cli.py ask "prompt"           # query the local model stack (38 models)
python scripts/oracle.py             # full system diagnostic (health · errors · perf)
python scripts/smart_test.py --smoke # fast test sweep (~15 files)
```

## Security &amp; configuration

This repo is **safe to fork**: no live credentials are committed. Real secrets live only in gitignored local files.
