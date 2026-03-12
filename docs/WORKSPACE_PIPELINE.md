# Workspace Pipeline — Cross-Service Orchestrator

> **Module:** `engine/nexus/workspace_pipeline.py`
> **Version:** v1.18a
> **Skills:** `engine/skills/builtin/workspace_skills.py` (19 skills)
> **Tests:** `tests/test_workspace_pipeline.py` (53 tests)

## Overview

The Workspace Pipeline orchestrates multi-service Google Workspace operations
through a stage-based execution model.  Each pipeline is a sequence of **stages**
that call real Google service clients — no mocks, no stubs.

```
Input (topic/question/data)
  │
  ├─→ fetch_news ─→ RSS articles from curated sources
  ├─→ nlm_research ─→ NotebookLM deep research
  ├─→ workspace_generate ─→ Workspace Gemini text generation
  ├─→ create_doc / create_sheet ─→ structured content
  ├─→ drive_upload / drive_search ─→ file management
  └─→ nexus_store ─→ persist to Nexus KMS
```

## Architecture

```
                    ┌─────────────────────────────────────────┐
                    │         WorkspacePipeline                │
                    │    13 Stages • 9 Templates               │
                    └──────────┬──────────────────────────────┘
                               │
         ┌─────────┬───────────┼───────────┬──────────┬────────┐
         │         │           │           │          │        │
    ┌────┴────┐ ┌──┴───┐ ┌────┴────┐ ┌────┴───┐ ┌───┴────┐ ┌─┴──────┐
    │ Sheets  │ │ Docs │ │  Drive  │ │  NLM   │ │ Gemini │ │  News  │
    │ Gemini  │ │Client│ │ Gemini  │ │ Engine │ │ Direct │ │Pipeline│
    └────┬────┘ └──┬───┘ └────┬────┘ └────┬───┘ └───┬────┘ └─┬──────┘
         │         │          │           │          │        │
    ┌────┴─────────┴──────────┴───────────┴──────────┴────────┴───┐
    │              WorkspaceGeminiClient + Account Pool            │
    │     (appsgenaiserver-pa.clients6.google.com)                │
    └─────────────────────────────────────────────────────────────┘
```

## Stage Registry (13 Stages)

| Stage | Client | Description |
|-------|--------|-------------|
| `nlm_research` | NLM Direct Client | Deep NotebookLM research with source synthesis |
| `nlm_add_source` | NLM Direct Client | Upload source material to a notebook |
| `create_doc` | GoogleDocsClient | Create a Google Doc with Gemini-generated content |
| `create_sheet` | GoogleSheetsClient | Build a spreadsheet from a prompt |
| `fill_sheet` | GoogleSheetsClient | Enrich existing sheet with Gemini data |
| `drive_search` | GoogleDriveClient | Semantic AI Overview search across Drive |
| `drive_upload` | GoogleDriveClient | Upload content to Google Drive |
| `drive_ask` | GoogleDriveClient | Ask Gemini questions about Drive files |
| `nexus_store` | Nexus Client | Persist results to Nexus knowledge base |
| `doc_export` | GoogleDocsClient | Export document content as text/HTML |
| `workspace_generate` | WorkspaceGeminiClient | Direct Gemini text generation |
| `fetch_news` | NewsPipeline | Fetch RSS articles from curated sources |
| *(custom)* | User-defined | Register via `pipeline.register_stage()` |

## Pipeline Templates (9 Templates)

### `research_and_distill`
NLM research → Sheets data → Drive upload → Nexus storage.
Best for: Deep topic research with structured output.

```python
pipeline.run("research_and_distill", topic="quantum computing advances")
```

### `create_knowledge_doc`
NLM research → Google Doc → Nexus storage.
Best for: Long-form knowledge documents.

```python
pipeline.run("create_knowledge_doc", topic="MCP framework patterns", title="MCP Guide")
```

### `data_enrichment`
Fill existing sheet with Gemini data → Nexus storage.
Best for: Enriching spreadsheets with AI-generated data.

```python
pipeline.run("data_enrichment", sheet_id="abc123", prompt="Add market analysis")
```

### `cross_source_synthesis`
Drive search → Drive ask → Nexus storage.
Best for: Synthesizing insights across multiple Drive files.

```python
pipeline.run("cross_source_synthesis", question="How does auth work?", query="authentication")
```

### `news_pipeline`
Fetch RSS → (optional) NLM research → Create sheet digest → Nexus storage.
Best for: Automated news ingestion and curation.

```python
pipeline.run("news_pipeline", topic="AI News", categories=["ai_research", "tech"])
```

### `doc_to_notebook`
Export Doc → Add to NLM notebook → NLM research → Nexus storage.
Best for: Converting existing documents into distilled knowledge.

```python
pipeline.run("doc_to_notebook", doc_id="doc123", notebook_id="nb456")
```

### `sheet_to_knowledge`
Drive search → NLM research → Nexus storage.
Best for: Converting spreadsheet data into searchable knowledge.

```python
pipeline.run("sheet_to_knowledge", query="Q3 metrics", topic="quarterly analysis")
```

### `generate_and_store`
Workspace Gemini generation → Nexus storage.
Best for: Quick content generation with automatic persistence.

```python
pipeline.run("generate_and_store", topic="Write a summary of transformer architectures")
```

### `news_to_knowledge`
Fetch news → NLM research → Create Doc → Drive upload → Nexus storage.
Best for: Full knowledge pipeline from current events to stored documents.

```python
pipeline.run("news_to_knowledge", topic="Daily AI Digest", categories=["ai_research"])
```

## Usage

### Python API

```python
from engine.nexus.workspace_pipeline import get_workspace_pipeline

pipeline = get_workspace_pipeline()

# Run a template
run = pipeline.run("research_and_distill", topic="local LLM agents")
print(run.status)       # PipelineStatus.COMPLETED
print(run.final_output) # Last stage's output dict

# Run custom stages
run = pipeline.run_stages(
    [{"name": "workspace_generate"}, {"name": "nexus_store"}],
    topic="Write about neural architecture search",
    prompt="Explain NAS techniques for edge deployment",
)

# List available templates
templates = pipeline.list_templates()

# Check run status
status = pipeline.get_run(run.run_id)

# Register custom stage
pipeline.register_stage("my_stage", my_stage_function)
```

### MCP Skills

```python
# Via agent tool calling
workspace_generate(prompt="Draft a report on...", context="docs", store=True)
workspace_fetch_news(categories="ai_research|tech", max_articles=30)
workspace_research(topic="quantum computing")
workspace_pipeline(template="news_to_knowledge", topic="AI trends")
workspace_news(topic="latest tech", sources="https://a.com|https://b.com")
workspace_create_doc(title="Report", prompt="Write about...")
workspace_create_sheet(title="Data", prompt="Create spreadsheet of...")
```

### REST API

```
POST /api/workspace/pipeline       — Run any pipeline template
POST /api/workspace/generate       — Direct Gemini text generation
POST /api/workspace/news/fetch     — Fetch RSS articles
POST /api/workspace/news/digest    — Full news pipeline
POST /api/workspace/search         — Drive AI Overview search
POST /api/workspace/ask            — Ask Gemini about files
POST /api/workspace/docs/create    — Create Google Doc
POST /api/workspace/sheets/create  — Build spreadsheet
POST /api/workspace/sheets/fill    — Fill sheet with Gemini
GET  /api/workspace/pipeline/status/<id> — Check run status
GET  /api/workspace/pipeline/templates   — List templates
GET  /api/workspace/status               — Service health
```

### Scheduler Tasks

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `workspace-news-pipeline` | every 8h | RSS → NLM → Sheets → Nexus |
| `workspace-news-to-knowledge` | daily | News → NLM → Docs → Drive → Nexus |
| `workspace-research-cycle` | every 12h | Research queued topics from Nexus |
| `workspace-pipeline-health` | every 6h | Client connectivity + stage health |

Run manually:
```bash
python -m engine.nexus.scheduler_daemon run workspace-news-pipeline
python -m engine.nexus.scheduler_daemon run workspace-pipeline-health
```

## Stage Execution Model

### Context Propagation
Each stage receives a `params` dict and a `context` dict.  Stage output is
merged into the context — downstream stages see upstream results:

```
Stage 1 (fetch_news) → output: {articles: [...], articles_fetched: 20}
                         ↓ merged into context
Stage 2 (nlm_research) → sees: {articles: [...], articles_fetched: 20, topic: "..."}
                         ↓ merged into context
Stage 3 (nexus_store)  → sees all upstream outputs
```

### Optional Stages
Mark a stage as `optional: True` to allow graceful skip on failure:

```python
{"stage": "nlm_research", "params": {}, "optional": True}
```

### Error Handling
- Non-optional stage failure → pipeline stops, status = FAILED
- Optional stage failure → logged, pipeline continues
- All results preserved in `PipelineRun.stages` regardless of outcome

## Smoke Test

```bash
python scripts/workspace_smoke_test.py --quick   # Health checks only
python scripts/workspace_smoke_test.py            # Full (health + live API)
python scripts/workspace_smoke_test.py --json     # JSON output
```

## Related Documentation

- [Google Ecosystem SDK](GOOGLE_ECOSYSTEM_SDK.md) — Client implementation details
- [News System](NEWS_SYSTEM.md) — RSS sources, categories, NLM distillation
- [NLM API Reference](NLM_API_REFERENCE.md) — NotebookLM RPC registry
- [Scheduler](SCHEDULER.md) — Recurring task system
- [Skills](SKILLS.md) — @skill decorator and registry
