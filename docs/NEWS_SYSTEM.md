# News & Intelligence System

> v0.73b · Automated news ingestion, NLM distillation, and curated intelligence feeds.

---

## Overview

The News System turns CosySim into a self-updating intelligence feed:

1. **Ingestion** — Fetch top stories from RSS/web sources 3× daily
2. **NLM Distillation** — Upload sources to NotebookLM notebooks, ask curated questions
3. **Nexus Storage** — Answers land in Nexus as searchable Q&A and knowledge entries
4. **Scene Delivery** — Intel Hub + Phone scene display live curated news
5. **Agent Access** — Any agent can query `nexus_ask("latest AI news")` and get real answers

---

## Architecture

```
News System
├── engine/nexus/news/
│   ├── __init__.py
│   ├── news_pipeline.py      — Orchestrator: fetch → parse → dedup → distill → store
│   ├── rss_fetcher.py        — RSS feed fetcher + HTML scraper
│   ├── dedup_filter.py       — Title/URL fingerprint deduplication
│   ├── source_registry.py    — Curated source list per category
│   └── news_models.py        — NewsItem, NewsDigest, NewsCategory dataclasses
├── engine/skills/builtin/
│   └── news_skills.py        — LLM skills: fetch_news, get_news_digest, search_news
└── engine/nexus/scheduler_daemon.py
    — 3 news tasks: news-fetch (3×/day), news-distill (1×/day), news-cleanup (weekly)
```

---

## News Categories

| Category | Sources | NLM Notebook |
|----------|---------|-------------|
| `ai_research` | arxiv, HuggingFace blog, OpenAI blog, Anthropic, Google DeepMind | `news-ai-research` |
| `tech` | Hacker News, Ars Technica, The Verge, WIRED | `news-tech` |
| `world` | Reuters, AP News, BBC World | `news-world` |
| `science` | Nature News, New Scientist, Phys.org | `news-science` |
| `crypto` | CoinDesk, The Block, Decrypt | `news-crypto` |

New categories can be added by extending `source_registry.py`.

---

## Pipeline Stages

### Stage 1: Fetch (`news-fetch` task, runs at 07:00 / 13:00 / 20:00)

```python
from engine.nexus.news.rss_fetcher import RSSFetcher

fetcher = RSSFetcher()
items = fetcher.fetch_category("ai_research", limit=20)
# → List[NewsItem]: title, url, summary, published_at, source_name
```

- Respects per-source rate limits (1 req/5s)
- Falls back to HTML scrape if RSS unavailable
- Stores raw items in Nexus with content_type=`raw_news`

### Stage 2: Deduplication

```python
from engine.nexus.news.dedup_filter import DedupFilter

dedup = DedupFilter()
fresh = dedup.filter(items)
# Removes: same URL, title similarity > 85%, within 48h window
```

- URL fingerprint stored in Nexus `news_seen` index
- Title similarity via character-level n-gram (no heavy NLP deps)
- 48-hour dedup window (configurable)

### Stage 3: NLM Upload & Distillation (`news-distill` task, runs at 21:00)

Each category has a dedicated NLM notebook. The distillation loop:

```
1. Collect today's fresh items for category (up to 15)
2. Format each item as: "## {title}\n{summary}\n\nSource: {url}"
3. Upload as text source to category notebook
4. Ask 10 curated questions (see below)
5. Store each Q&A answer in Nexus with category + date tags
6. Store the full conversation chain with session_id
```

**Curated questions per category:**

*ai_research*
- "What are the most significant AI research findings reported today?"
- "Which papers or announcements could change how we build AI systems?"
- "What are the key technical claims and are there limitations or caveats mentioned?"
- "Which organisations are leading today's AI developments?"
- "What should a developer building with LLMs know from today's news?"
- "Are there any safety, ethics, or policy developments?"
- "What open-source models or tools were announced?"
- "What benchmarks or evaluations were published?"
- "What is the overall sentiment — optimistic, cautious, or alarming?"
- "Summarise today's AI news in 5 bullet points."

*tech* — similar structure, focused on developer tools, infrastructure, products

*world* — geopolitics, economy, climate impact summaries

*science* — breakthroughs, replication, clinical relevance

### Stage 4: Nexus Storage

```python
from engine.nexus.client import get_nexus_client

client = get_nexus_client()
client.add_qa(
    question="What are the most significant AI research findings today?",
    answer="...(NLM answer)...",
    category="news",
    tags=["ai_research", "2026-01-15"],
)
```

Each distilled Q&A becomes immediately queryable via `nexus_ask()`.

### Stage 5: Cleanup (`news-cleanup` task, weekly)

- Removes raw_news entries older than 30 days
- Archives Q&A older than 90 days (moves to `news_archive` category)
- Rebuilds Nexus search index

---

## Scene Delivery

### Intel Hub — Live Ticker

The Intel Hub (`/intel`) displays a scrolling news ticker sourced from Nexus:

- Endpoint: `GET /api/news/ticker` → returns last 20 Q&A summaries
- Socket.IO event: `world_news.update` emitted after each distill cycle
- Displayed in the bottom ticker bar on the Intel Hub UI
- Filterable by category (buttons: ALL / AI / TECH / WORLD)

### Phone Scene — News Feed Tab

The Phone scene (`/phone`) has a **FEED** tab that shows curated news:

- `GET /api/news/feed?category=all&limit=10`
- Rendered as chat-style messages from "NEXUS FEED" sender
- Clicking a headline shows the full Q&A distillation
- Pull-to-refresh triggers a Nexus query for latest entries

---

## Agent Skills

Three skills available in the `news` skill pack:

### `fetch_news(category, limit)`
Fetch latest news for a category from Nexus Q&A store.
Returns formatted string of top headlines + summaries.

### `get_news_digest(category, date)`
Get the full distilled digest for a category on a given date.
Returns multi-paragraph summary from NLM Q&A session.

### `search_news(query, category, days_back)`
Semantic search through news Q&A in Nexus.
Returns ranked matches with date and category tags.

```python
# Example agent call:
result = search_news("open source LLM", category="ai_research", days_back=7)
```

---

## Scheduler Tasks

Three tasks are registered in the scheduler daemon:

| Task | Schedule | Duration est. |
|------|----------|---------------|
| `news-fetch` | 07:00, 13:00, 20:00 daily | ~2 min |
| `news-distill` | 21:30 daily | ~8 min (NLM calls) |
| `news-cleanup` | Sunday 04:00 | ~1 min |

**Adding these tasks increments scheduler count from 35 → 38.**
Update these 6 test files when adding:
- `tests/test_scheduler_daemon.py`
- `tests/test_autonomy_skills.py`
- `tests/test_master_notebook_builder.py`
- `tests/test_qa_expander.py`
- `tests/test_router_finetune_cycle.py`
- `tests/test_nlm_generator.py`

---

## NotebookLM Integration

The news system uses NotebookLM notebooks as ephemeral working memory:

```
Notebook lifecycle per category:
1. Check if notebook exists in Nexus registry
2. If not: create via notebooklm-create_notebook tool
3. Add today's news items as text sources
4. Ask curated questions (10 per category per day)
5. Store answers in Nexus
6. Sources accumulate (up to 50 per notebook) — rotate when full
```

**Notebook IDs** (stored in Nexus under `news_notebooks` key):

```json
{
  "ai_research": "nb-news-ai",
  "tech": "nb-news-tech",
  "world": "nb-news-world",
  "science": "nb-news-science",
  "crypto": "nb-news-crypto"
}
```

**Session chaining** — each distillation run uses a single NotebookLM session to build context across all 10 questions:

```
session_id = None
for question in curated_questions:
    result = notebooklm.ask(question, session_id=session_id)
    session_id = result["session_id"]  # thread maintained
    store_in_nexus(question, result["answer"])
```

This ensures later questions benefit from earlier answers in the same session.

---

## Configuration

```yaml
news_system:
  enabled: true
  categories:
    - ai_research
    - tech
    - world
    - science
  fetch_limit_per_source: 20
  dedup_window_hours: 48
  distill_questions_per_category: 10
  max_sources_per_notebook: 15
  nexus_retention_days: 30
  archive_after_days: 90
  ticker_item_count: 20
```

---

## Testing

```bash
# News system tests
python -m pytest tests/test_news_pipeline.py -v
python -m pytest tests/test_news_skills.py -v

# Smart runner
python scripts/smart_test.py --domain news
```

---

## Accessing News as an Agent

The most common pattern for agents:

```python
# Get today's AI research digest
from engine.nexus.client import get_nexus_client

client = get_nexus_client()
results = client.search("ai research news", category="news", limit=5)

# Or via nexus_ask (searches Q&A cache first)
answer = client.ask("What are the latest AI research developments?")
```

Via MCP skill:
```
fetch_news(category="ai_research", limit=5)
→ "1. OpenAI released... 2. Meta announced... 3. DeepMind paper..."
```

---

## Nexus Knowledge Structure

News entries in Nexus follow this structure:

| Field | Value |
|-------|-------|
| `content_type` | `news` (distilled) or `raw_news` (pre-distill) |
| `category` | `news` |
| `tags` | `["{date}", "{category}", "news", "distilled"]` |
| `title` | Question asked |
| `content` | NLM answer |
| `source` | `news_pipeline:{category}` |

The `date` tag format is `YYYY-MM-DD` enabling time-ranged queries:
```python
results = client.search("AI news", tags=["2026-01-15", "ai_research"])
```
