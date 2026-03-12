# Workspace Pipeline — Cross-Service Orchestrator

> **Module:** `engine/nexus/workspace_pipeline.py`
> **Version:** v1.19b
> **Skills:** `engine/skills/builtin/workspace_skills.py` (27 skills)
> **Tests:** `tests/test_workspace_pipeline.py` (74 tests)

## Overview

The Workspace Pipeline orchestrates multi-service Google Workspace operations
through a stage-based execution model.  Each pipeline is a sequence of **stages**
that call real Google service clients — no mocks, no stubs.

```
Input (topic/question/data)
  │
  ├─→ prewarm ─→ pre-warm AI models for faster first-request
  ├─→ fetch_news ─→ RSS articles from curated sources
  ├─→ nlm_research ─→ NotebookLM deep research
  ├─→ workspace_generate ─→ Workspace Gemini text generation
  ├─→ gemini_enrich ─→ Gemini content transformation/enrichment
  ├─→ create_doc / create_sheet ─→ structured content
  ├─→ docs_to_sheets / sheets_to_doc ─→ cross-format conversion
  ├─→ drive_upload / drive_search ─→ file management
  ├─→ drive_copy / drive_export ─→ v2internal file operations
  ├─→ drive_permissions ─→ list or set file access
  ├─→ sheet_revisions ─→ spreadsheet revision history
  └─→ nexus_store ─→ persist to Nexus KMS
```

## Architecture

```
                    ┌─────────────────────────────────────────┐
                    │         WorkspacePipeline                │
                    │    21 Stages • 21 Templates              │
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

## Stage Registry (17 Stages)

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
| `export_doc` | GoogleDocsClient | Export document content as text/HTML |
| `columnsmith` | GoogleSheetsClient | Column formula/transformation execution |
| `workspace_generate` | WorkspaceGeminiClient | Direct Gemini text generation |
| `fetch_news` | NewsPipeline | Fetch RSS articles from curated sources |
| `docs_to_sheets` | Docs + Sheets + Gemini | Export doc → structure as spreadsheet |
| `sheets_to_doc` | Sheets + Docs + Gemini | Read sheet range → transform to prose |
| `gemini_enrich` | WorkspaceGeminiClient | Content transformation/enrichment via Gemini |
| `prewarm` | espresso-pa | Pre-warm AI models for reduced first-request latency |
| `drive_copy` | GoogleDriveClient (v2internal) | Copy files via internal v2 API |
| `drive_export` | GoogleDriveClient (v2internal) | Export files to text/html/pdf/csv/docx/xlsx |
| `drive_permissions` | GoogleDriveClient (v2internal) | List or set file access permissions |
| `sheet_revisions` | GoogleSheetsClient (extended) | Fetch spreadsheet revision history |
| *(custom)* | User-defined | Register via `pipeline.register_stage()` |

## Pipeline Templates (21 Templates)

### Core Templates (v1.17–v1.18a)

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

### Cross-Service Chain Templates (v1.18c)

### `docs_nlm_distill`
Create Doc → Export → Add to NLM → Research → Nexus.
Best for: Distilling document content into structured knowledge via NLM.

```python
pipeline.docs_nlm_distill(topic="architecture patterns", title="Architecture Guide")
```

### `sheets_enrichment_cycle`
Create Sheet → Fill with Gemini → Columnsmith transforms → Convert to Doc → Nexus.
Best for: Building structured data that gets enriched and documented.

```python
pipeline.run("sheets_enrichment_cycle", topic="market analysis", prompt="Top 20 AI companies")
```

### `drive_nlm_nexus`
Drive Search → Ask Gemini → Enrich → (optional) NLM → Create Doc → Nexus.
Best for: Mining Drive for knowledge and synthesizing with NLM research.

```python
pipeline.run("drive_nlm_nexus", query="authentication design", question="How does auth work?")
```

### `full_cross_service`
Prewarm → Drive Search → NLM Research → Gemini Enrich → Sheet → Doc → Drive Upload → Nexus.
Best for: Complete rotation through all services — the "crown jewel" pipeline.

```python
pipeline.full_cross_service(topic="neural architecture search", question="Compare NAS techniques")
```

### `knowledge_distillation`
Workspace Generate → Gemini Enrich → NLM Add Source → NLM Research → Nexus.
Best for: Deep knowledge distillation — generate → refine → research → store.

```python
pipeline.knowledge_distillation(topic="transformer optimization", prompt="Explain KV cache compression")
```

### `news_full_cycle`
Fetch News → Gemini Enrich → (optional) NLM → Sheet + Doc + Drive → Nexus.
Best for: Complete news-to-knowledge pipeline with all output formats.

```python
pipeline.news_full_cycle(topic="AI News Weekly", categories=["ai_research", "llm"])
```

### `doc_structure_extract`
Export Doc → Gemini Enrich → Docs-to-Sheets → Nexus.
Best for: Extracting structured data from prose documents.

```python
pipeline.run("doc_structure_extract", doc_id="abc123", prompt="Extract key metrics and dates")
```

### `sheet_knowledge_report`
Sheets-to-Doc → NLM Add Source → NLM Research → Drive Upload → Nexus.
Best for: Converting spreadsheet data into researched knowledge reports.

```python
pipeline.run("sheet_knowledge_report", sheet_id="xyz789", topic="Q4 performance analysis")
```

### Drive & Sheets Internal Templates (v1.19b)

### `drive_template_clone`
Copy file → Set permissions → Nexus store.
Best for: Creating shared copies of template files.

```python
pipeline.run("drive_template_clone", file_id="abc123", title="Q4 Report Copy", role="reader", perm_type="anyone")
```

### `drive_export_and_distill`
Export file → Gemini enrich → NLM research → Nexus store.
Best for: Exporting Drive files and distilling content into knowledge.

```python
pipeline.run("drive_export_and_distill", file_id="abc123", export_mime="text/plain", topic="architecture docs")
```

### `drive_audit_permissions`
List permissions → Nexus store audit log.
Best for: Security audits of file access across Drive.

```python
pipeline.run("drive_audit_permissions", file_id="abc123", category="security_audit")
```

### `sheet_revision_audit`
Fetch revision history → Nexus store audit.
Best for: Tracking spreadsheet changes and edit history.

```python
pipeline.run("sheet_revision_audit", spreadsheet_id="xyz789", category="revision_audit")
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
workspace_full_cross_service(topic="NAS", question="Compare techniques")
workspace_distill(topic="transformer opts", title="Optimization Guide")
workspace_news_full_cycle(topic="AI Weekly", categories="ai_research|llm")
workspace_enrich(text="Raw content...", prompt="Summarize and structure")
workspace_copy_file(file_id="abc123", title="Copy", role="reader")
workspace_export_file(file_id="abc123", export_mime="text/plain")
workspace_set_permissions(file_id="abc123", role="writer", perm_type="user", value="user@example.com")
workspace_sheet_revisions(spreadsheet_id="xyz789")
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
POST /api/workspace/drive/copy          — Copy file (v2internal)
POST /api/workspace/drive/export        — Export file (v2internal)
POST /api/workspace/drive/permissions   — List/set file permissions
POST /api/workspace/sheets/revisions    — Get spreadsheet revision history
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
