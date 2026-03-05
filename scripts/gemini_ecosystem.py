"""Gemini Ecosystem Orchestrator — multi-service Gemini 3.0 compute graph.

The Google AI ecosystem is a network of free Gemini 3.0 compute nodes:

    NLM (NotebookLM)
        create_note      → 10k-word Gemini prompt, full notebook context
        generate_audio   → 30-min podcast, feed back as source
        generate_table   → structured data extraction
        generate_flashcards → Q&A deck
        add_source_*     → close the loop: output → new source → richer context

    Colab (Jupyter + Gemini AI agent)
        generate_notebook  → Gemini one-shots the full .ipynb
        gemini_cell        → cell that calls Gemini API (Gemini calling Gemini)
        execute_notebook   → kernel runs all cells, captures output
        output_to_drive    → persist to Drive for NLM source ingestion

    GAS (Google Apps Script)
        generate_script  → Gemini one-shots the full .gs file
        execute_function → run via GAS API, capture return value
        sheets_macro     → GAS-driven Gemini-in-Sheets enrichment
        webhook_trigger  → fire and forget for workspace automation

    Sheets (Google Sheets)
        write_rows       → JSON → spreadsheet
        read_rows        → spreadsheet → next stage context
        gemini_formula   → =AI(prompt) formulas via GAS bridge
        export_csv       → CSV text → NLM add_source_text (loop closer)

    Drive
        upload_file      → local file → Drive
        share_url_to_nlm → Drive URL → NLM add_source_url (loop closer)

The LOOP CLOSER stages are what make this exponential:
    Every stage output can be fed BACK as a new NLM source.
    Each circuit makes the notebook smarter.
    Knowledge compounds. Gemini calls Gemini via Colab.
    GAS calls Gemini. Sheets calls Gemini. NLM reads all their outputs.

Pipeline example:
    Stage 1 (nlm_create_note):  "Extract all skills as JSON"
    Stage 2 (sheets_write):      JSON → Google Sheet
    Stage 3 (gas_gemini_enrich): GAS calls Gemini → adds "example prompt" column
    Stage 4 (sheets_export_csv): CSV text
    Stage 5 (nlm_add_source):    CSV → NLM source  ← LOOP CLOSED
    Stage 6 (nlm_create_note):  "Using the enriched skill data, generate 100 Q&A"
    Stage 7 (colab_gemini_cell): Colab runs Gemini cell → benchmark analysis
    Stage 8 (nlm_add_source):    Colab output → NLM source  ← LOOP CLOSED
    Stage 9 (nlm_generate_audio): "Deep-dive podcast covering everything above"
    Stage 10 (nlm_add_source):   Audio → NLM source  ← LOOP CLOSED
    Stage 11 (nlm_create_note):  "You just listened to yourself. What did you miss?"

Usage:
    python scripts/gemini_ecosystem.py --pipeline knowledge_amplifier
    python scripts/gemini_ecosystem.py --pipeline colab_gemini_chain
    python scripts/gemini_ecosystem.py --pipeline full_ecosystem
    python scripts/gemini_ecosystem.py --pipeline full_ecosystem --loops 3
    python scripts/gemini_ecosystem.py --list
    python scripts/gemini_ecosystem.py --save-pipelines
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

PIPELINES_DIR = PROJECT_ROOT / "data" / "nexus" / "ecosystems"
PIPELINES_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_DIR = PROJECT_ROOT / "data" / "nexus" / "ecosystem_outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

AUDIO_DIR = PROJECT_ROOT / "data" / "nexus" / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_NOTEBOOK_ID = "e81e6364-ce39-401e-b7db-bb6bfd7970f7"


# ──── Gemini cell templates (Colab cells that call Gemini API) ─────────────────

# A Colab code cell that calls Gemini 3.0 with injected prompt + previous context.
# This is Gemini calling Gemini — NLM generates this cell, Colab executes it.
COLAB_GEMINI_CELL_TEMPLATE = """\
import google.generativeai as genai
import os, json

genai.configure(api_key=os.environ.get('GEMINI_API_KEY', ''))
_model = genai.GenerativeModel('gemini-2.5-pro')

_context = {context_repr}

_prompt = {prompt_repr}

_full = _prompt + ("\\n\\nContext:\\n" + _context if _context.strip() else "")
_response = _model.generate_content(_full)
result = _response.text
print(result)
"""

# GAS function that calls Gemini via UrlFetchApp and writes result to a Sheet.
GAS_GEMINI_FUNCTION_TEMPLATE = """\
/**
 * CosySim GAS — Gemini enrichment function.
 * Reads context from Sheet, calls Gemini API, writes result back.
 */
function cosysimGeminiEnrich() {{
  var scriptProps = PropertiesService.getScriptProperties();
  var apiKey = scriptProps.getProperty('GEMINI_API_KEY') || '';
  var sheetId = '{sheet_id}';

  var ss = SpreadsheetApp.openById(sheetId);
  var sheet = ss.getActiveSheet();
  var data = sheet.getDataRange().getValues();
  var headers = data[0];

  // Build context from all rows
  var contextLines = [headers.join(' | ')];
  for (var i = 1; i < Math.min(data.length, 50); i++) {{
    contextLines.push(data[i].join(' | '));
  }}
  var context = contextLines.join('\\n');

  var prompt = {prompt_repr};
  var fullPrompt = prompt + '\\n\\nData:\\n' + context;

  var url = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent?key=' + apiKey;
  var resp = UrlFetchApp.fetch(url, {{
    method: 'post',
    contentType: 'application/json',
    muteHttpExceptions: true,
    payload: JSON.stringify({{
      contents: [{{parts: [{{text: fullPrompt}}]}}]
    }})
  }});

  var result = '';
  try {{
    result = JSON.parse(resp.getContentText()).candidates[0].content.parts[0].text;
  }} catch(e) {{
    result = 'ERROR: ' + resp.getContentText().substring(0, 200);
  }}

  // Append result row
  sheet.appendRow([new Date().toISOString(), 'gemini_result', result]);

  // Return for programmatic use
  return result;
}}

function onOpen() {{
  SpreadsheetApp.getUi().createMenu('CosySim').addItem('Gemini Enrich', 'cosysimGeminiEnrich').addToUi();
}}
"""

# Full Colab notebook template — Gemini generates content for each section.
COLAB_NOTEBOOK_TEMPLATE = """\
## CosySim Analysis Notebook
*Generated by Gemini Ecosystem Orchestrator*

{task_description}

---

### Stage: Data Loading
Load the context data and prepare it for analysis.

```python
import json, os, sys
from pathlib import Path
import pandas as pd

# Context injected from previous pipeline stage
context_data = {context_repr}

if isinstance(context_data, str):
    try:
        context_data = json.loads(context_data)
    except json.JSONDecodeError:
        pass

print(f"Context loaded: {{type(context_data).__name__}}")
if isinstance(context_data, list):
    df = pd.DataFrame(context_data) if context_data and isinstance(context_data[0], dict) else None
    if df is not None:
        print(df.head())
else:
    print(str(context_data)[:500])
```

### Stage: Gemini Analysis
Call Gemini API to analyse the loaded data.

```python
import google.generativeai as genai

genai.configure(api_key=os.environ.get('GEMINI_API_KEY', ''))
model = genai.GenerativeModel('gemini-2.5-pro')

prompt = {prompt_repr}

# Include dataframe summary if available
extra_context = ''
if 'df' in dir() and df is not None:
    extra_context = f'\\n\\nData summary:\\n{{df.describe().to_string()}}\\n\\nFirst 10 rows:\\n{{df.head(10).to_string()}}'

response = model.generate_content(prompt + extra_context)
analysis_result = response.text
print(analysis_result)
```

### Stage: Output
Persist results for the pipeline.

```python
import pathlib, time

out_path = pathlib.Path('/tmp/cosysim_analysis_{run_id}.json')
out_path.write_text(json.dumps({{
    'run_id': '{run_id}',
    'timestamp': time.time(),
    'prompt': prompt,
    'result': analysis_result,
}}, indent=2))
print(f'Saved to {{out_path}}')
print('COSYSIM_RESULT_START')
print(analysis_result)
print('COSYSIM_RESULT_END')
```
"""


# ──── Data model ───────────────────────────────────────────────────────────────

@dataclass
class EcosystemNode:
    """One compute node in the Gemini ecosystem graph.

    Attributes:
        name:            Unique identifier for this node's output in the DataBus.
        service:         Which Google service handles this node.
                         nlm | colab | gas | sheets | drive
        method:          What operation to perform within that service.
                         NLM:    create_note | audio | flashcards | table |
                                 add_source_text | add_source_url | add_source_file
                         Colab:  generate_notebook | gemini_cell | execute
                         GAS:    generate | execute | gemini_enrich
                         Sheets: write | read | export_csv
                         Drive:  upload | share_to_nlm
        prompt:          Gemini instruction for this node. Supports {previous},
                         {bus.key}, {notebook_id}, {sheet_id}.
        inject_previous: Auto-inject previous node's output into {previous}.
        store_in_nexus:  Store this node's output in Nexus knowledge base.
        nexus_category:  Nexus category for stored entries.
        parse_as:        How to parse this node's output: text | json | qa_pairs | csv_rows
        max_words:       Truncate previous output to N words before injection.
        audio_type:      1=deep_dive 2=brief 3=critique 4=debate (audio nodes only).
        loop_back:       If True, output is immediately added back as NLM source.
        sheet_name:      Sheet tab name for Sheets nodes (default: "Sheet1").
    """

    name: str
    service: str = "nlm"
    method: str = "create_note"
    prompt: str = ""
    inject_previous: bool = True
    store_in_nexus: bool = True
    nexus_category: str = "cosysim_knowledge"
    parse_as: str = "text"
    max_words: Optional[int] = None
    audio_type: int = 1
    loop_back: bool = False
    sheet_name: str = "Sheet1"

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EcosystemNode":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class DataBus:
    """Shared state flowing between ecosystem nodes.

    Attributes:
        previous:      Output of the most recently executed node.
        node_outputs:  All node outputs keyed by node name.
        notebook_id:   Active NLM notebook UUID.
        sheet_id:      Active Google Sheet ID (created on first sheets_write).
        sheet_url:     Public URL of the active sheet.
        drive_files:   Drive file IDs keyed by name.
        audio_files:   Local audio file paths keyed by node name.
        colab_output:  Colab execution output keyed by node name.
        gas_results:   GAS function return values keyed by node name.
        nlm_sources:   Source IDs added to the NLM notebook, keyed by node name.
        run_id:        Unique identifier for this pipeline run.
        loop_count:    Current loop iteration (for --loops).
        errors:        Non-fatal errors keyed by node name.
    """

    previous: str = ""
    node_outputs: Dict[str, Any] = field(default_factory=dict)
    notebook_id: str = DEFAULT_NOTEBOOK_ID
    sheet_id: str = ""
    sheet_url: str = ""
    drive_files: Dict[str, str] = field(default_factory=dict)
    audio_files: Dict[str, str] = field(default_factory=dict)
    colab_output: Dict[str, str] = field(default_factory=dict)
    gas_results: Dict[str, Any] = field(default_factory=dict)
    nlm_sources: Dict[str, str] = field(default_factory=dict)
    run_id: str = field(default_factory=lambda: f"{int(time.time())}")
    loop_count: int = 0
    errors: Dict[str, str] = field(default_factory=dict)

    def resolve(self, text: str) -> str:
        """Inject bus values into a prompt template string."""
        text = text.replace("{previous}", self.previous)
        text = text.replace("{notebook_id}", self.notebook_id)
        text = text.replace("{sheet_id}", self.sheet_id)
        text = text.replace("{sheet_url}", self.sheet_url)
        text = text.replace("{run_id}", self.run_id)
        text = text.replace("{loop_count}", str(self.loop_count))
        # {bus.key} → node_outputs[key]
        for k, v in self.node_outputs.items():
            placeholder = "{bus." + k + "}"
            if placeholder in text:
                text = text.replace(placeholder, str(v) if not isinstance(v, str) else v)
        return text

    def set_output(self, node_name: str, output: Any) -> None:
        """Record a node's output and update previous."""
        self.node_outputs[node_name] = output
        if isinstance(output, str):
            self.previous = output
        elif isinstance(output, (dict, list)):
            self.previous = json.dumps(output, indent=2, ensure_ascii=False)
        else:
            self.previous = str(output)


@dataclass
class EcosystemPipeline:
    """An ordered list of ecosystem nodes forming a compute graph."""

    name: str
    description: str = ""
    notebook_id: str = DEFAULT_NOTEBOOK_ID
    nodes: List[EcosystemNode] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "notebook_id": self.notebook_id,
            "nodes": [n.to_dict() for n in self.nodes],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EcosystemPipeline":
        nodes = [EcosystemNode.from_dict(n) for n in d.get("nodes", [])]
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            notebook_id=d.get("notebook_id", DEFAULT_NOTEBOOK_ID),
            nodes=nodes,
        )

    @classmethod
    def load(cls, path: Path) -> "EcosystemPipeline":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save(self, path: Optional[Path] = None) -> Path:
        if path is None:
            path = PIPELINES_DIR / f"{self.name}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path


# ──── Built-in pipelines ───────────────────────────────────────────────────────

def _knowledge_amplifier() -> EcosystemPipeline:
    """NLM → analyse → add back as source → richer analysis.
    Each loop makes the notebook smarter. Pure NLM recursion."""
    return EcosystemPipeline(
        name="knowledge_amplifier",
        description="NLM self-amplification: analyse → add result as source → deeper analysis",
        nodes=[
            EcosystemNode(
                name="extract_architecture",
                service="nlm",
                method="create_note",
                inject_previous=False,
                prompt="""
Analyse every source in this notebook and extract a complete architecture map:

1. Every Python class with its purpose, parent class, and key methods
2. Every singleton getter (get_*) and what it returns
3. Every @skill decorator with pack, category, description
4. Every scheduler task with schedule and what it does
5. Every REST route with method, path, handler
6. Every Socket.IO event with direction and payload

Return as structured JSON:
{
  "classes": [{"name": "...", "parent": "...", "purpose": "...", "key_methods": [...]}],
  "singletons": [{"getter": "...", "returns": "...", "module": "..."}],
  "skills": [{"name": "...", "pack": "...", "category": "...", "description": "..."}],
  "scheduler_tasks": [{"name": "...", "schedule": "...", "purpose": "..."}],
  "routes": [{"method": "...", "path": "...", "handler": "...", "file": "..."}],
  "socketio": [{"event": "...", "direction": "...", "payload": "...", "file": "..."}]
}
""",
                parse_as="json",
                store_in_nexus=True,
                nexus_category="architecture",
            ),
            EcosystemNode(
                name="add_architecture_source",
                service="nlm",
                method="add_source_text",
                prompt="CosySim Architecture Map — Loop {loop_count}",
                loop_back=False,
                store_in_nexus=False,
            ),
            EcosystemNode(
                name="deep_qa_from_architecture",
                service="nlm",
                method="create_note",
                prompt="""
You now have an architecture map as a source. The map covers:
{previous}

Using the architecture map AND all original sources, generate 50 deep Q&A pairs.

Focus on:
- How do classes wire together? Which singletons connect which systems?
- What happens when a skill is called? Trace the full call chain.
- How does the interceptor pipeline transform a request?
- What's the Nexus knowledge lifecycle for a new entry?
- How do scheduler tasks interact with other systems?
- What are the non-obvious dependencies and gotchas?

Return ONLY valid JSON:
[{"question": "...", "answer": "..."}]

Each answer: 6-10 sentences, code references, no generalities.
""",
                parse_as="qa_pairs",
                store_in_nexus=True,
                nexus_category="cosysim_knowledge_deep",
            ),
            EcosystemNode(
                name="add_qa_source",
                service="nlm",
                method="add_source_text",
                prompt="CosySim Deep Q&A — Loop {loop_count}",
                store_in_nexus=False,
            ),
            EcosystemNode(
                name="gap_analysis",
                service="nlm",
                method="create_note",
                prompt="""
You have: architecture map + deep Q&A as sources, plus all original code sources.

{previous}

Now identify what is MISSING or UNCLEAR after two passes:
1. Which systems have no documentation in the Q&A?
2. Which classes have undocumented behaviour?
3. Which skill packs need usage examples?
4. What edge cases are not covered?
5. What would a new developer be confused by?

Generate 20 more Q&A pairs covering EXACTLY these gaps.
Return ONLY valid JSON: [{"question": "...", "answer": "..."}]
""",
                parse_as="qa_pairs",
                store_in_nexus=True,
                nexus_category="cosysim_knowledge_gaps",
            ),
        ],
    )


def _colab_gemini_chain() -> EcosystemPipeline:
    """NLM generates a Colab notebook with Gemini cells → execute → results → NLM source.
    This is Gemini calling Gemini: NLM Gemini writes a notebook that has Gemini API cells,
    Colab executes them, outputs loop back as NLM sources."""
    return EcosystemPipeline(
        name="colab_gemini_chain",
        description=(
            "NLM writes Colab notebook with Gemini cells → Colab executes → "
            "Gemini cells call Gemini → output feeds back as NLM source"
        ),
        nodes=[
            EcosystemNode(
                name="design_analysis_notebook",
                service="nlm",
                method="create_note",
                inject_previous=False,
                prompt="""
Design a Colab notebook that performs a deep analysis of the CosySim codebase.

The notebook should have these sections, each as a separate Python code cell:

CELL 1 — Setup:
```python
!pip install google-generativeai pandas matplotlib -q
import google.generativeai as genai, os, json, pandas as pd
genai.configure(api_key=os.environ.get('GEMINI_API_KEY',''))
model = genai.GenerativeModel('gemini-2.5-pro')
print("Ready")
```

CELL 2 — Load architecture data (the JSON from the architecture analysis):
Include the full JSON architecture map inline as a Python dict.

CELL 3 — Gemini quality analysis cell:
Ask Gemini to analyse: "Given this architecture, what are the top 5 risks, bottlenecks,
and improvement opportunities? Be specific with file names and class names."

CELL 4 — Gemini dependency mapping cell:
Ask Gemini to produce a dependency matrix showing which modules depend on which,
formatted as a pandas DataFrame.

CELL 5 — Gemini missing skills cell:
Ask Gemini: "What skill packs are missing from CosySim that would make agents more capable?
Give 10 specific skill pack proposals with 5 skills each."

CELL 6 — Save all results:
Write all three Gemini outputs to /tmp/cosysim_colab_analysis.json

Write the complete notebook content now, all cells, all code, ready to run.
""",
                parse_as="text",
                store_in_nexus=False,
            ),
            EcosystemNode(
                name="execute_analysis_notebook",
                service="colab",
                method="execute",
                prompt="",  # uses previous (the notebook design) as task description
                store_in_nexus=True,
                nexus_category="colab_analysis",
            ),
            EcosystemNode(
                name="add_colab_results_to_nlm",
                service="nlm",
                method="add_source_text",
                prompt="Colab Gemini Analysis — Run {run_id}",
                store_in_nexus=False,
            ),
            EcosystemNode(
                name="synthesize_from_colab",
                service="nlm",
                method="create_note",
                prompt="""
You now have the results of a Colab notebook that called Gemini to analyse CosySim.
The analysis identified risks, dependencies, and missing skill proposals.

{previous}

Using both the Colab analysis AND all original sources, produce:

1. RISK REGISTER (top 10 risks, likelihood, impact, mitigation)
2. DEPENDENCY GRAPH (which engine modules are critical path vs optional)
3. SKILL DEVELOPMENT ROADMAP (10 proposed skill packs, priority order, estimated complexity)
4. IMMEDIATE ACTION ITEMS (5 specific code changes that would improve the system today)

Format as a structured markdown document with tables.
""",
                parse_as="text",
                store_in_nexus=True,
                nexus_category="cosysim_analysis",
            ),
        ],
    )


def _sheets_enrichment() -> EcosystemPipeline:
    """NLM extracts skill data → Sheets → GAS calls Gemini to enrich → CSV → NLM source.
    Shows the Sheets leg of the ecosystem loop."""
    return EcosystemPipeline(
        name="sheets_enrichment",
        description=(
            "NLM extract → Sheets → GAS Gemini enrichment → CSV → NLM source → "
            "richer NLM analysis"
        ),
        nodes=[
            EcosystemNode(
                name="extract_skills_for_sheets",
                service="nlm",
                method="create_note",
                inject_previous=False,
                prompt="""
Extract EVERY @skill decorator from all sources.
Return ONLY a JSON array — each element has exactly these keys:
{
  "name": "function_name",
  "pack": "pack string",
  "category": "GAME|SOCIAL|MEMORY|MEDIA|SYSTEM|NARRATIVE|ENVIRONMENT|COMMUNICATION",
  "description": "description= string",
  "parameters": "param1: type, param2: type",
  "returns": "return type description",
  "file": "relative/path/to/skills.py"
}
Include every skill. No other text.
""",
                parse_as="json",
            ),
            EcosystemNode(
                name="write_skills_to_sheets",
                service="sheets",
                method="write",
                prompt="CosySim Skills Registry — {run_id}",
                store_in_nexus=False,
            ),
            EcosystemNode(
                name="gas_gemini_enrich_skills",
                service="gas",
                method="gemini_enrich",
                prompt=(
                    "For each skill in this spreadsheet, add a column 'example_agent_prompt' "
                    "containing a realistic natural language message that would cause an AI agent "
                    "to call that skill. Make each prompt distinct and believable in a cyberpunk "
                    "RPG context. Write the example prompt for every row."
                ),
                store_in_nexus=False,
            ),
            EcosystemNode(
                name="export_enriched_csv",
                service="sheets",
                method="export_csv",
                prompt="",
                store_in_nexus=False,
            ),
            EcosystemNode(
                name="add_enriched_skills_to_nlm",
                service="nlm",
                method="add_source_text",
                prompt="Skills Registry with Agent Prompts — {run_id}",
                store_in_nexus=False,
            ),
            EcosystemNode(
                name="generate_agent_training_qa",
                service="nlm",
                method="create_note",
                prompt="""
You now have a source: every CosySim skill with example agent prompts that trigger each one.

{previous}

Using this enriched skill registry, generate 60 training Q&A pairs for teaching AI agents
how to use CosySim skills effectively:

- 20 pairs: "When should I use [skill] vs [other_skill]?"
- 20 pairs: "What parameters does [skill] need and what does it return?"
- 20 pairs: "What agent message would trigger [skill]?"

Format: [{"question": "...", "answer": "..."}]
Focus on the cyberpunk RPG context. Mention real skill names, packs, parameters.
""",
                parse_as="qa_pairs",
                store_in_nexus=True,
                nexus_category="agent_training",
            ),
        ],
    )


def _audio_loop() -> EcosystemPipeline:
    """NLM audio → add back as source → follow-up audio builds on the first.
    Self-referential audio knowledge loop. Each pass adds depth the previous missed."""
    return EcosystemPipeline(
        name="audio_loop",
        description=(
            "NLM generates podcast → feed back as source → follow-up podcast "
            "builds on the first → recursive depth amplification"
        ),
        nodes=[
            EcosystemNode(
                name="first_podcast",
                service="nlm",
                method="audio",
                inject_previous=False,
                prompt="""
Host: Alex (senior CosySim architect) and Jamie (new developer joining the team).
Format: Jamie asks naive questions, Alex gives deep technical answers.

Cover in this order:
1. What is CosySim at its core? (MCPFramework, scenes, agents — 5 min)
2. How does the interceptor pipeline work? Real call trace. (5 min)
3. How do @skill decorators connect to LLM agents? (5 min)
4. What is Nexus and why does it matter? (5 min)
5. How does the NLM knowledge loop compound over time? (5 min)
6. What's the most common mistake new developers make? (5 min)

Make it dense with specifics: class names, method names, config keys, file paths.
""",
                audio_type=1,
                parse_as="text",
                store_in_nexus=True,
                nexus_category="audio_knowledge",
            ),
            EcosystemNode(
                name="add_podcast_1_as_source",
                service="nlm",
                method="add_source_file",
                prompt="",
                store_in_nexus=False,
            ),
            EcosystemNode(
                name="second_podcast",
                service="nlm",
                method="audio",
                inject_previous=False,
                prompt="""
Host: Alex and Jamie again. Alex has just listened to their own first podcast.

The first podcast covered: MCPFramework, interceptors, skills, Nexus, NLM loop, common mistakes.

Now go DEEPER into what the first podcast glossed over:
1. Edge cases in the interceptor pipeline that crash silently (5 min)
2. How Nexus FTS5 actually works and when it fails (5 min)
3. The exact sequence when a scheduler task triggers — what can go wrong (5 min)
4. LMStudio SSE streaming: why it's asymmetric and how to handle race conditions (5 min)
5. The one architecture decision that would have been done differently in hindsight (5 min)
6. What will break first as CosySim scales past 30 scenes (5 min)

Reference the first podcast explicitly: "As I said before..." or "What I didn't mention was..."
""",
                audio_type=1,
                parse_as="text",
                store_in_nexus=True,
                nexus_category="audio_knowledge",
            ),
            EcosystemNode(
                name="distill_both_podcasts",
                service="nlm",
                method="create_note",
                inject_previous=False,
                prompt="""
You now have two podcast episodes as sources — both dense technical conversations
about CosySim architecture. Extract everything as a knowledge document.

Produce:
1. Key facts list (100 specific technical facts, one per line)
2. Common pitfalls list (every mistake mentioned in both podcasts)
3. Architecture decisions log (every "we chose X because Y" statement)
4. Open questions (every "we should look into..." or "this might need fixing")
5. 40 Q&A pairs distilled from both podcasts

Return as a structured markdown document with JSON Q&A array at the end.
""",
                parse_as="text",
                store_in_nexus=True,
                nexus_category="audio_distilled",
            ),
        ],
    )


def _gas_automation() -> EcosystemPipeline:
    """NLM → generates GAS script → GAS executes (calling Gemini) → stores results.
    Shows GAS as an autonomous compute node that bridges workspace + Gemini."""
    return EcosystemPipeline(
        name="gas_automation",
        description=(
            "NLM designs GAS automation → GAS executes with Gemini calls → "
            "results stored in Nexus and Drive"
        ),
        nodes=[
            EcosystemNode(
                name="design_gas_script",
                service="nlm",
                method="create_note",
                inject_previous=False,
                prompt="""
Design a Google Apps Script that automates CosySim knowledge management:

The script should:
1. Read the current contents of a tracking spreadsheet
2. For each row, call the Gemini API to generate a one-paragraph summary
3. Write summaries into a new "Summary" column
4. Create a Google Doc with all summaries formatted as a report
5. Send a completion email with the Doc link

Write the complete Apps Script code (.gs) now.
Include: callGemini(prompt), processBatch(sheetId), createReport(summaries), sendNotification(docUrl)

The Gemini API key comes from PropertiesService.getScriptProperties().getProperty('GEMINI_API_KEY')
Write clean, complete, production-quality GAS code.
""",
                parse_as="text",
                store_in_nexus=True,
                nexus_category="gas_scripts",
            ),
            EcosystemNode(
                name="create_and_run_gas",
                service="gas",
                method="execute",
                prompt="",  # uses previous (the script design) as source
                store_in_nexus=True,
                nexus_category="gas_results",
            ),
            EcosystemNode(
                name="add_gas_results_to_nlm",
                service="nlm",
                method="add_source_text",
                prompt="GAS Automation Results — {run_id}",
                store_in_nexus=False,
            ),
        ],
    )


def _full_ecosystem() -> EcosystemPipeline:
    """The complete loop: all five services in one compounding pipeline.
    NLM → Colab → Sheets → GAS → Drive → back to NLM.
    Each circuit adds more context. Knowledge compounds exponentially."""
    return EcosystemPipeline(
        name="full_ecosystem",
        description=(
            "Complete Google AI compute graph: NLM → Colab (Gemini cells) → "
            "Sheets → GAS (Gemini) → Drive → NLM source → richer NLM. "
            "Exponential knowledge compounding."
        ),
        nodes=[
            # ── Phase 1: NLM extract ─────────────────────────────────────────
            EcosystemNode(
                name="full_extract",
                service="nlm",
                method="create_note",
                inject_previous=False,
                prompt="""
Perform a complete extraction of the CosySim codebase.
Return a single JSON object with:
{
  "version": "current version string",
  "scenes": [{"name": ..., "port": ..., "skills": [...]}],
  "engine_modules": [{"path": ..., "classes": [...], "lines": ...}],
  "skills": [{"name": ..., "pack": ..., "category": ..., "description": ...}],
  "interceptors": [{"class": ..., "stage": ..., "purpose": ...}],
  "scheduler_tasks": [{"name": ..., "schedule": ..., "purpose": ...}],
  "nexus_categories": [...],
  "test_count": ...,
  "known_issues": [...]
}
""",
                parse_as="json",
                store_in_nexus=True,
                nexus_category="full_extract",
            ),
            # ── Phase 2: Sheets (structured data layer) ──────────────────────
            EcosystemNode(
                name="write_full_extract_to_sheets",
                service="sheets",
                method="write",
                prompt="CosySim Full Extract — {run_id}",
                store_in_nexus=False,
            ),
            # ── Phase 3: GAS calls Gemini to enrich the Sheet ────────────────
            EcosystemNode(
                name="gas_enrich_extract",
                service="gas",
                method="gemini_enrich",
                prompt=(
                    "Analyse this CosySim system data. For each scene, add a column "
                    "'quality_score' (1-10) and 'improvement_priority' (high/medium/low). "
                    "For each skill, add 'test_coverage_estimate' (none/partial/good). "
                    "Add a final summary row with overall system health assessment."
                ),
                store_in_nexus=False,
            ),
            # ── Phase 4: Export Sheet → NLM source ──────────────────────────
            EcosystemNode(
                name="export_enriched_sheet",
                service="sheets",
                method="export_csv",
                prompt="",
                store_in_nexus=False,
            ),
            EcosystemNode(
                name="add_sheet_to_nlm",
                service="nlm",
                method="add_source_text",
                prompt="System Quality Assessment Sheet — {run_id}",
                store_in_nexus=False,
            ),
            # ── Phase 5: Colab runs Gemini cells for deep analysis ────────────
            EcosystemNode(
                name="colab_deep_analysis",
                service="colab",
                method="gemini_cell",
                prompt=(
                    "Given the CosySim architecture data: {bus.full_extract}\n\n"
                    "Perform three analyses:\n"
                    "1. Which three scenes have the most technical debt? Why?\n"
                    "2. What is the critical path for a message from user → LLM → skill → response?\n"
                    "3. Write a 20-line Python health check script that verifies CosySim is running.\n"
                    "Return all three as a JSON object."
                ),
                store_in_nexus=True,
                nexus_category="colab_analysis",
            ),
            # ── Phase 6: Colab output → NLM source ──────────────────────────
            EcosystemNode(
                name="add_colab_to_nlm",
                service="nlm",
                method="add_source_text",
                prompt="Colab Deep Analysis — {run_id}",
                store_in_nexus=False,
            ),
            # ── Phase 7: NLM now has 3 extra sources — synthesise ────────────
            EcosystemNode(
                name="final_synthesis",
                service="nlm",
                method="create_note",
                prompt="""
You now have:
- Original codebase sources
- Full JSON system extract
- Quality assessment spreadsheet (with Gemini-added scores)
- Colab analysis (technical debt, critical path, health check)

Produce a MASTER KNOWLEDGE DOCUMENT:

## CosySim System Intelligence Report — Loop {loop_count}

### Executive Summary (2 paragraphs)

### System Health Scorecard
| Component | Score | Issues | Priority |
|-----------|-------|--------|---------|

### Critical Path (step-by-step trace of a full request lifecycle)

### Technical Debt Register (top 10, with specific file:line references)

### 30-Day Improvement Roadmap (specific, ordered, achievable tasks)

### Agent Intelligence Pack (30 Q&A pairs every agent should know)

Return as full markdown document with the Q&A as JSON at the very end.
""",
                parse_as="text",
                store_in_nexus=True,
                nexus_category="master_intelligence",
            ),
            # ── Phase 8: Audio of the master report ─────────────────────────
            EcosystemNode(
                name="master_report_audio",
                service="nlm",
                method="audio",
                inject_previous=False,
                prompt="""
Host: Senior architect presenting the full CosySim system intelligence report.
Format: Executive briefing — dense, authoritative, no filler.

Cover the master document's key findings:
- System health overview (5 min)
- Critical technical debt that needs immediate action (5 min)
- How the ecosystem compute graph works and what it produces (5 min)
- 30-day roadmap highlights (5 min)
- What the system will look like after 10 more ecosystem loops (5 min)
- Final recommendation to the development team (5 min)
""",
                audio_type=1,
                parse_as="text",
                store_in_nexus=True,
                nexus_category="audio_knowledge",
            ),
            # ── Phase 9: Audio → NLM source (final loop back) ───────────────
            EcosystemNode(
                name="add_audio_to_nlm",
                service="nlm",
                method="add_source_file",
                prompt="",
                store_in_nexus=False,
            ),
        ],
    )


BUILTIN_PIPELINES: Dict[str, callable] = {
    "knowledge_amplifier": _knowledge_amplifier,
    "colab_gemini_chain": _colab_gemini_chain,
    "sheets_enrichment": _sheets_enrichment,
    "audio_loop": _audio_loop,
    "gas_automation": _gas_automation,
    "full_ecosystem": _full_ecosystem,
}


# ──── Runner ───────────────────────────────────────────────────────────────────

class EcosystemRunner:
    """Execute an EcosystemPipeline across the full Google AI compute graph.

    Dispatches each node to the appropriate service client:
    - nlm → NLMDirectClient
    - colab → ColabNotebookBuilder
    - gas → GASClient
    - sheets → GoogleSheetsClient
    - drive → GoogleDriveClient

    Manages the DataBus: each node's output is injected into subsequent nodes
    via {previous} and {bus.name} placeholders.

    Args:
        pipeline: The EcosystemPipeline to execute.
        nexus_client: Optional Nexus client for storing outputs.
        account_name: Google account pool name (default: "nihilistcod").
    """

    def __init__(
        self,
        pipeline: EcosystemPipeline,
        nexus_client: Any = None,
        account_name: str = "nihilistcod",
    ) -> None:
        self._pipeline = pipeline
        self._nexus = nexus_client
        self._account_name = account_name
        self._nlm: Any = None
        self._sheets: Any = None
        self._gas: Any = None
        self._colab_builder: Any = None
        self._drive: Any = None

    # ──── Client init ─────────────────────────────────────────────────────────

    def _get_nlm(self) -> Any:
        if self._nlm is None:
            from engine.integrations.nlm_direct_client import get_nlm_direct_client
            self._nlm = get_nlm_direct_client(self._account_name)
        return self._nlm

    def _get_sheets(self) -> Any:
        if self._sheets is None:
            from engine.integrations.gsheets_client import GoogleSheetsClient
            from engine.integrations.google_account_pool import get_account_pool
            pool = get_account_pool()
            account = pool.get_account(self._account_name)
            self._sheets = GoogleSheetsClient(account)
        return self._sheets

    def _get_gas(self) -> Any:
        if self._gas is None:
            from engine.integrations.gas_client import GASClient
            from engine.integrations.google_account_pool import get_account_pool
            pool = get_account_pool()
            account = pool.get_account(self._account_name)
            self._gas = GASClient(account)
        return self._gas

    def _get_colab(self) -> Any:
        if self._colab_builder is None:
            from engine.integrations.colab_notebook_builder import ColabNotebookBuilder
            from engine.integrations.colab_client import get_colab_client
            from engine.integrations.google_drive_client import get_drive_client
            colab = get_colab_client(self._account_name)
            drive = get_drive_client(self._account_name)
            self._colab_builder = ColabNotebookBuilder(colab, drive)
        return self._colab_builder

    def _get_drive(self) -> Any:
        if self._drive is None:
            from engine.integrations.google_drive_client import get_drive_client
            self._drive = get_drive_client(self._account_name)
        return self._drive

    # ──── NLM nodes ──────────────────────────────────────────────────────────

    def _run_nlm_create_note(self, node: EcosystemNode, bus: DataBus) -> str:
        """Execute NLM create_note — the core Gemini 3.0 call."""
        nlm = self._get_nlm()
        prompt = bus.resolve(node.prompt)
        logger.info("[NLM:create_note] %s — prompt %d words", node.name, len(prompt.split()))
        result = nlm.create_note(bus.notebook_id, prompt)
        content: str = result.get("content", "") if isinstance(result, dict) else str(result)
        logger.info("[NLM:create_note] %s — received %d chars", node.name, len(content))
        return content

    def _run_nlm_audio(self, node: EcosystemNode, bus: DataBus) -> str:
        """Generate NLM audio → poll until ready → download → return local path."""
        nlm = self._get_nlm()
        focus = bus.resolve(node.prompt)
        logger.info("[NLM:audio] %s — starting generation", node.name)
        job_id, artifact_id = nlm.generate_audio(
            bus.notebook_id, focus, audio_type=node.audio_type
        )
        logger.info("[NLM:audio] %s — job=%s artifact=%s, polling...", node.name, job_id, artifact_id)

        # Poll until ready — poll_artifact handles polling loop and returns the completed artifact dict
        logger.info("[NLM:audio] %s — polling (max 600s)...", node.name)
        artifact = nlm.poll_artifact(bus.notebook_id, artifact_id, max_wait=600, poll_interval=20)

        out_path = AUDIO_DIR / f"{node.name}_{bus.run_id}.mp3"
        nlm.download_audio(artifact, str(out_path))
        bus.audio_files[node.name] = str(out_path)
        logger.info("[NLM:audio] %s — saved to %s", node.name, out_path)
        return str(out_path)

    def _run_nlm_flashcards(self, node: EcosystemNode, bus: DataBus) -> str:
        """Generate NLM flashcards → return as Q&A text."""
        nlm = self._get_nlm()
        logger.info("[NLM:flashcards] %s", node.name)
        result = nlm.generate_flashcards(bus.notebook_id)
        if isinstance(result, dict):
            return result.get("content", str(result))
        return str(result)

    def _run_nlm_table(self, node: EcosystemNode, bus: DataBus) -> str:
        """Generate NLM data table → return as text."""
        nlm = self._get_nlm()
        logger.info("[NLM:table] %s", node.name)
        result = nlm.generate_data_table(bus.notebook_id)
        if isinstance(result, dict):
            return result.get("content", str(result))
        return str(result)

    def _run_nlm_add_source_text(self, node: EcosystemNode, bus: DataBus) -> str:
        """Add previous output as text source → closes the loop."""
        nlm = self._get_nlm()
        title = bus.resolve(node.prompt) or f"Source: {node.name} — {bus.run_id}"
        content = _truncate_words(bus.previous, node.max_words)
        if not content.strip():
            logger.warning("[NLM:add_source_text] %s — no content to add", node.name)
            return ""
        logger.info("[NLM:add_source_text] %s — adding %d chars as '%s'", node.name, len(content), title)
        source_id = nlm.add_source_text(bus.notebook_id, title, content)
        bus.nlm_sources[node.name] = source_id
        # Wait for source to be processed
        try:
            nlm.wait_for_source(bus.notebook_id, source_id, max_wait=120)
            logger.info("[NLM:add_source_text] %s — source ready: %s", node.name, source_id)
        except TimeoutError:
            logger.warning("[NLM:add_source_text] %s — source timeout, continuing", node.name)
        return source_id

    def _run_nlm_add_source_url(self, node: EcosystemNode, bus: DataBus) -> str:
        """Add a URL (Drive, Sheets, web) as NLM source."""
        nlm = self._get_nlm()
        url = bus.resolve(node.prompt) or bus.sheet_url
        if not url:
            logger.warning("[NLM:add_source_url] %s — no URL", node.name)
            return ""
        logger.info("[NLM:add_source_url] %s — adding %s", node.name, url)
        source_id = nlm.add_source_url(bus.notebook_id, url)
        bus.nlm_sources[node.name] = source_id
        try:
            nlm.wait_for_source(bus.notebook_id, source_id, max_wait=120)
        except TimeoutError:
            logger.warning("[NLM:add_source_url] %s — source timeout", node.name)
        return source_id

    def _run_nlm_add_source_file(self, node: EcosystemNode, bus: DataBus) -> str:
        """Add a local file (audio MP3, image, PDF) as NLM source."""
        nlm = self._get_nlm()
        # Find the most recently generated audio file if this follows an audio node
        file_path: str = ""
        if bus.audio_files:
            file_path = list(bus.audio_files.values())[-1]
        elif bus.previous and Path(bus.previous).exists():
            file_path = bus.previous
        if not file_path or not Path(file_path).exists():
            logger.warning("[NLM:add_source_file] %s — no file to add", node.name)
            return ""
        logger.info("[NLM:add_source_file] %s — uploading %s", node.name, file_path)
        source_id = nlm.add_source_file(bus.notebook_id, file_path)
        bus.nlm_sources[node.name] = source_id
        try:
            nlm.wait_for_source(bus.notebook_id, source_id, max_wait=300)
            logger.info("[NLM:add_source_file] %s — source ready: %s", node.name, source_id)
        except TimeoutError:
            logger.warning("[NLM:add_source_file] %s — source timeout", node.name)
        return source_id

    # ──── Colab nodes ─────────────────────────────────────────────────────────

    def _run_colab_execute(self, node: EcosystemNode, bus: DataBus) -> str:
        """Build and execute a Colab notebook from the previous stage's design."""
        builder = self._get_colab()
        task = bus.resolve(node.prompt) or bus.previous
        logger.info("[Colab:execute] %s — submitting notebook task", node.name)
        execution = builder.build_and_run(task_description=task, save_to_drive=True)
        output = execution.total_output or ""
        bus.colab_output[node.name] = output
        if execution.drive_url:
            bus.drive_files[node.name] = execution.drive_url
            logger.info("[Colab:execute] %s — Drive: %s", node.name, execution.drive_url)
        logger.info("[Colab:execute] %s — status=%s output=%d chars", node.name, execution.status, len(output))
        return output

    def _run_colab_gemini_cell(self, node: EcosystemNode, bus: DataBus) -> str:
        """Execute a single Gemini API call inside Colab — Gemini calling Gemini.

        Builds a one-cell notebook that:
        1. Installs google-generativeai
        2. Calls Gemini API with the node's prompt + previous context
        3. Returns the output

        This is the core of the promptception loop — NLM Gemini 3.0 designs the
        prompt, Colab's kernel executes the Gemini SDK call with full GPU context.
        """
        builder = self._get_colab()
        prompt = bus.resolve(node.prompt)
        context = _truncate_words(bus.previous, node.max_words or 3000)
        run_id = bus.run_id

        # Build a single-cell notebook that calls Gemini API
        cell_task = COLAB_GEMINI_CELL_TEMPLATE.format(
            context_repr=repr(context),
            prompt_repr=repr(prompt),
        )

        # Wrap in a full notebook description
        notebook_task = (
            f"Create a Colab notebook that runs this exact code cell:\n\n"
            f"```python\n{cell_task}\n```\n\n"
            f"The notebook should have exactly two cells: "
            f"(1) `!pip install google-generativeai -q` and "
            f"(2) the code cell above. Execute both and print the result."
        )

        logger.info("[Colab:gemini_cell] %s — launching Gemini cell via Colab", node.name)
        execution = builder.build_and_run(
            task_description=notebook_task,
            save_to_drive=True,
        )
        output = execution.total_output or ""
        bus.colab_output[node.name] = output

        # Extract content between COSYSIM_RESULT_START / END markers if present
        result = _extract_between_markers(output, "COSYSIM_RESULT_START", "COSYSIM_RESULT_END")
        if not result:
            result = output

        logger.info("[Colab:gemini_cell] %s — %d chars output", node.name, len(result))
        return result

    # ──── GAS nodes ──────────────────────────────────────────────────────────

    def _run_gas_generate(self, node: EcosystemNode, bus: DataBus) -> str:
        """Ask NLM to design a GAS script, then create the project."""
        gas = self._get_gas()
        script_source = bus.previous  # Previous NLM node designed the script

        # Create a new GAS project
        logger.info("[GAS:generate] %s — creating project", node.name)
        project = gas.create_project(f"CosySim_{node.name}_{bus.run_id}")

        # Save the script content to the project
        gas.update_file(
            project_id=project.script_id,
            filename="Code",
            content=script_source,
        )
        logger.info("[GAS:generate] %s — project %s", node.name, project.script_id)
        bus.gas_results[node.name] = project.script_id
        return project.script_id

    def _run_gas_execute(self, node: EcosystemNode, bus: DataBus) -> str:
        """Create a GAS project from previous design and execute the main function."""
        gas = self._get_gas()
        script_source = bus.previous

        # Extract the first function name from the script
        func_match = re.search(r"^function\s+(\w+)\s*\(", script_source, re.MULTILINE)
        func_name = func_match.group(1) if func_match else "main"

        logger.info("[GAS:execute] %s — creating project", node.name)
        project = gas.create_project(f"CosySim_{node.name}_{bus.run_id}")
        gas.update_file(
            project_id=project.script_id,
            filename="Code",
            content=script_source,
        )

        # Execute the function
        logger.info("[GAS:execute] %s — running %s()", node.name, func_name)
        result = gas.run_function(project.script_id, func_name)
        result_str = json.dumps(result, indent=2, ensure_ascii=False) if not isinstance(result, str) else result
        bus.gas_results[node.name] = result
        logger.info("[GAS:execute] %s — result: %s", node.name, result_str[:200])
        return result_str

    def _run_gas_gemini_enrich(self, node: EcosystemNode, bus: DataBus) -> str:
        """Create a GAS script that calls Gemini to enrich the current Sheet."""
        if not bus.sheet_id:
            logger.warning("[GAS:gemini_enrich] %s — no sheet_id in bus", node.name)
            return ""

        prompt = bus.resolve(node.prompt)
        gas_code = GAS_GEMINI_FUNCTION_TEMPLATE.format(
            sheet_id=bus.sheet_id,
            prompt_repr=repr(prompt),
        )

        gas = self._get_gas()
        logger.info("[GAS:gemini_enrich] %s — creating GAS project for sheet %s", node.name, bus.sheet_id)
        project = gas.create_project(f"CosySim_Enrich_{bus.run_id}")
        gas.update_file(
            project_id=project.script_id,
            filename="Code",
            content=gas_code,
        )

        logger.info("[GAS:gemini_enrich] %s — running cosysimGeminiEnrich()", node.name)
        try:
            result = gas.run_function(project.script_id, "cosysimGeminiEnrich")
            result_str = str(result) if not isinstance(result, str) else result
            bus.gas_results[node.name] = result
            logger.info("[GAS:gemini_enrich] %s — enrichment complete", node.name)
            return result_str
        except Exception as exc:
            logger.warning("[GAS:gemini_enrich] %s — execution failed: %s", node.name, exc)
            bus.errors[node.name] = str(exc)
            return f"GAS enrichment attempted (execution error: {exc})"

    # ──── Sheets nodes ────────────────────────────────────────────────────────

    def _run_sheets_write(self, node: EcosystemNode, bus: DataBus) -> str:
        """Write previous JSON output to Google Sheets."""
        sheets = self._get_sheets()

        # Parse previous output as rows
        rows: List[Dict[str, Any]] = []
        try:
            parsed = json.loads(bus.previous)
            if isinstance(parsed, list):
                if parsed and isinstance(parsed[0], dict):
                    rows = parsed
                else:
                    rows = [{"value": str(item)} for item in parsed]
            elif isinstance(parsed, dict):
                rows = [{"key": k, "value": json.dumps(v) if not isinstance(v, str) else v}
                        for k, v in parsed.items()]
        except (json.JSONDecodeError, ValueError):
            # Treat as plain text
            rows = [{"content": line} for line in bus.previous.splitlines() if line.strip()]

        if not rows:
            logger.warning("[Sheets:write] %s — no rows to write", node.name)
            return ""

        title = bus.resolve(node.prompt) or f"CosySim_{node.name}_{bus.run_id}"

        if not bus.sheet_id:
            logger.info("[Sheets:write] %s — creating sheet '%s'", node.name, title)
            sheet_meta = sheets.create_sheet(title)
            bus.sheet_id = sheet_meta["id"]
            bus.sheet_url = sheet_meta["url"]
            logger.info("[Sheets:write] %s — sheet created: %s", node.name, bus.sheet_url)
        else:
            logger.info("[Sheets:write] %s — appending to existing sheet %s", node.name, bus.sheet_id)

        sheets.append_rows(bus.sheet_id, rows, sheet_name=node.sheet_name)
        logger.info("[Sheets:write] %s — wrote %d rows", node.name, len(rows))
        return bus.sheet_url

    def _run_sheets_read(self, node: EcosystemNode, bus: DataBus) -> str:
        """Read rows from the current sheet → JSON string."""
        if not bus.sheet_id:
            logger.warning("[Sheets:read] %s — no sheet_id", node.name)
            return ""
        sheets = self._get_sheets()
        rows = sheets.read_rows(bus.sheet_id, node.sheet_name)
        result = json.dumps(rows, indent=2, ensure_ascii=False)
        logger.info("[Sheets:read] %s — read %d rows", node.name, len(rows))
        return result

    def _run_sheets_export_csv(self, node: EcosystemNode, bus: DataBus) -> str:
        """Export current sheet as CSV text for NLM source ingestion."""
        if not bus.sheet_id:
            logger.warning("[Sheets:export_csv] %s — no sheet_id", node.name)
            return ""
        sheets = self._get_sheets()
        raw = sheets.read_raw(bus.sheet_id, node.sheet_name)
        if not raw:
            return ""
        csv_lines = [",".join(f'"{str(cell)}"' for cell in row) for row in raw]
        result = "\n".join(csv_lines)
        logger.info("[Sheets:export_csv] %s — %d rows, %d chars", node.name, len(raw), len(result))
        return result

    # ──── Drive nodes ─────────────────────────────────────────────────────────

    def _run_drive_upload(self, node: EcosystemNode, bus: DataBus) -> str:
        """Upload previous output or audio file to Drive."""
        drive = self._get_drive()
        # Try to find a file to upload
        file_path: Optional[str] = None
        if bus.audio_files:
            file_path = list(bus.audio_files.values())[-1]
        elif bus.previous and Path(bus.previous).exists():
            file_path = bus.previous

        if file_path and Path(file_path).exists():
            title = bus.resolve(node.prompt) or Path(file_path).name
            result = drive.upload_file(file_path, title)
            file_id = result.get("id", "")
            bus.drive_files[node.name] = file_id
            logger.info("[Drive:upload] %s — uploaded %s → %s", node.name, file_path, file_id)
            return f"https://drive.google.com/file/d/{file_id}/view"
        else:
            # Upload text content as a plain text file
            content = bus.previous
            title = bus.resolve(node.prompt) or f"cosysim_{node.name}_{bus.run_id}.txt"
            tmp = OUTPUT_DIR / f"{node.name}_{bus.run_id}.txt"
            tmp.write_text(content, encoding="utf-8")
            result = drive.upload_file(str(tmp), title)
            file_id = result.get("id", "")
            bus.drive_files[node.name] = file_id
            logger.info("[Drive:upload] %s — uploaded text → %s", node.name, file_id)
            return f"https://drive.google.com/file/d/{file_id}/view"

    def _run_drive_share_to_nlm(self, node: EcosystemNode, bus: DataBus) -> str:
        """Make a Drive file publicly viewable, then add it as NLM source."""
        drive = self._get_drive()
        # Get most recent drive file
        file_id: str = ""
        if bus.drive_files:
            file_id = list(bus.drive_files.values())[-1]
        if not file_id:
            logger.warning("[Drive:share_to_nlm] %s — no drive file", node.name)
            return ""

        drive.share_publicly(file_id)
        url = f"https://drive.google.com/file/d/{file_id}/view"
        logger.info("[Drive:share_to_nlm] %s — sharing %s", node.name, url)
        # Add to NLM
        return self._run_nlm_add_source_url(node, bus)

    # ──── Nexus storage ───────────────────────────────────────────────────────

    def _store_in_nexus(self, node: EcosystemNode, content: str, bus: DataBus) -> None:
        """Store node output in Nexus knowledge base."""
        if not self._nexus or not content.strip():
            return

        # Handle Q&A pairs
        if node.parse_as == "qa_pairs":
            pairs = _extract_qa_pairs(content)
            stored = 0
            for pair in pairs:
                try:
                    self._nexus.add_qa(pair["question"], pair["answer"], category=node.nexus_category)
                    stored += 1
                except Exception as exc:
                    logger.debug("Nexus QA store failed: %s", exc)
            logger.info("[Nexus] %s — stored %d Q&A pairs in '%s'", node.name, stored, node.nexus_category)
            return

        # Handle JSON
        if node.parse_as == "json":
            try:
                parsed = json.loads(content)
                content = json.dumps(parsed, indent=2, ensure_ascii=False)
            except (json.JSONDecodeError, ValueError):
                pass

        try:
            self._nexus.add_entry(
                title=f"{node.name} — loop {bus.loop_count} run {bus.run_id}",
                content=content,
                content_type="note",
                category=node.nexus_category,
            )
            logger.info("[Nexus] %s — stored in '%s'", node.name, node.nexus_category)
        except Exception as exc:
            logger.warning("[Nexus] %s — store failed: %s", node.name, exc)

    # ──── Dispatch ────────────────────────────────────────────────────────────

    def _run_node(self, node: EcosystemNode, bus: DataBus) -> Optional[str]:
        """Dispatch a single node to the appropriate service executor."""
        logger.info("══ Node: %s [%s:%s]", node.name, node.service, node.method)

        # Truncate previous if max_words set
        saved_previous = bus.previous
        if node.inject_previous and node.max_words:
            bus.previous = _truncate_words(bus.previous, node.max_words)

        try:
            output: Optional[str] = None

            if node.service == "nlm":
                if node.method == "create_note":
                    output = self._run_nlm_create_note(node, bus)
                elif node.method == "audio":
                    output = self._run_nlm_audio(node, bus)
                elif node.method == "flashcards":
                    output = self._run_nlm_flashcards(node, bus)
                elif node.method == "table":
                    output = self._run_nlm_table(node, bus)
                elif node.method == "add_source_text":
                    output = self._run_nlm_add_source_text(node, bus)
                elif node.method == "add_source_url":
                    output = self._run_nlm_add_source_url(node, bus)
                elif node.method == "add_source_file":
                    output = self._run_nlm_add_source_file(node, bus)
                else:
                    logger.warning("Unknown NLM method: %s", node.method)

            elif node.service == "colab":
                if node.method == "execute":
                    output = self._run_colab_execute(node, bus)
                elif node.method == "gemini_cell":
                    output = self._run_colab_gemini_cell(node, bus)
                else:
                    logger.warning("Unknown Colab method: %s", node.method)

            elif node.service == "gas":
                if node.method == "generate":
                    output = self._run_gas_generate(node, bus)
                elif node.method == "execute":
                    output = self._run_gas_execute(node, bus)
                elif node.method == "gemini_enrich":
                    output = self._run_gas_gemini_enrich(node, bus)
                else:
                    logger.warning("Unknown GAS method: %s", node.method)

            elif node.service == "sheets":
                if node.method == "write":
                    output = self._run_sheets_write(node, bus)
                elif node.method == "read":
                    output = self._run_sheets_read(node, bus)
                elif node.method == "export_csv":
                    output = self._run_sheets_export_csv(node, bus)
                else:
                    logger.warning("Unknown Sheets method: %s", node.method)

            elif node.service == "drive":
                if node.method == "upload":
                    output = self._run_drive_upload(node, bus)
                elif node.method == "share_to_nlm":
                    output = self._run_drive_share_to_nlm(node, bus)
                else:
                    logger.warning("Unknown Drive method: %s", node.method)

            else:
                logger.warning("Unknown service: %s", node.service)

        except Exception as exc:
            logger.error("[%s] node %s FAILED: %s", node.service, node.name, exc, exc_info=True)
            bus.errors[node.name] = str(exc)
            output = None
        finally:
            # Restore original previous if we truncated
            if node.inject_previous and node.max_words:
                bus.previous = saved_previous

        if output is not None:
            bus.set_output(node.name, output)

            # Immediate loop-back: add as NLM source right after producing output
            if node.loop_back and node.service != "nlm":
                logger.info("[loop_back] %s — adding output as NLM source", node.name)
                loop_node = EcosystemNode(
                    name=f"{node.name}_loop_back",
                    service="nlm",
                    method="add_source_text",
                    prompt=f"Loop-back: {node.name} — {bus.run_id}",
                    store_in_nexus=False,
                )
                self._run_node(loop_node, bus)

            if node.store_in_nexus:
                self._store_in_nexus(node, output, bus)

        return output

    # ──── Pipeline execution ─────────────────────────────────────────────────

    def run(self, loops: int = 1, notebook_id: Optional[str] = None) -> DataBus:
        """Execute the full pipeline, optionally multiple times.

        Args:
            loops: Number of times to loop through the pipeline. Each loop
                   adds more sources to the notebook, compounding knowledge.
            notebook_id: Override the pipeline's notebook_id.

        Returns:
            The final DataBus state with all outputs, sources, and errors.
        """
        bus = DataBus(
            notebook_id=notebook_id or self._pipeline.notebook_id,
            run_id=str(int(time.time())),
        )

        logger.info("╔══ Ecosystem Pipeline: %s", self._pipeline.name)
        logger.info("║   Notebook: %s", bus.notebook_id)
        logger.info("║   Nodes: %d | Loops: %d", len(self._pipeline.nodes), loops)
        logger.info("╚══ Starting...")

        for loop_i in range(loops):
            bus.loop_count = loop_i
            logger.info("══════════ Loop %d / %d ══════════", loop_i + 1, loops)

            for node in self._pipeline.nodes:
                self._run_node(node, bus)

            # Save loop output
            loop_output = OUTPUT_DIR / f"{self._pipeline.name}_loop{loop_i}_{bus.run_id}.json"
            loop_output.write_text(
                json.dumps(
                    {
                        "pipeline": self._pipeline.name,
                        "loop": loop_i,
                        "run_id": bus.run_id,
                        "notebook_id": bus.notebook_id,
                        "sheet_id": bus.sheet_id,
                        "sheet_url": bus.sheet_url,
                        "nlm_sources_added": list(bus.nlm_sources.keys()),
                        "audio_files": bus.audio_files,
                        "errors": bus.errors,
                        "node_output_sizes": {k: len(str(v)) for k, v in bus.node_outputs.items()},
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            logger.info("Loop %d saved to %s", loop_i, loop_output)

        logger.info("╔══ Pipeline Complete: %s", self._pipeline.name)
        logger.info("║   NLM sources added: %d", len(bus.nlm_sources))
        logger.info("║   Colab runs: %d", len(bus.colab_output))
        logger.info("║   GAS results: %d", len(bus.gas_results))
        if bus.sheet_url:
            logger.info("║   Sheet: %s", bus.sheet_url)
        if bus.errors:
            logger.warning("║   Errors: %s", list(bus.errors.keys()))
        logger.info("╚══ Done.")
        return bus


# ──── Helpers ──────────────────────────────────────────────────────────────────

def _truncate_words(text: str, max_words: Optional[int]) -> str:
    """Truncate text to at most max_words words."""
    if not max_words or not text:
        return text
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + f"\n... [truncated at {max_words} words]"


def _extract_qa_pairs(content: str) -> List[Dict[str, str]]:
    """Extract Q&A pairs from text that may contain a JSON array."""
    pairs: List[Dict[str, str]] = []

    # Try to find JSON array in the content
    json_match = re.search(r"\[\s*\{.*?\}\s*\]", content, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(0))
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        q = item.get("question") or item.get("q") or ""
                        a = item.get("answer") or item.get("a") or ""
                        if q and a:
                            pairs.append({"question": str(q), "answer": str(a)})
        except (json.JSONDecodeError, ValueError):
            pass

    if pairs:
        return pairs

    # Fallback: look for Q: ... A: ... patterns
    qa_pattern = re.compile(
        r"(?:Q|Question)\s*:\s*(.+?)\n+(?:A|Answer)\s*:\s*(.+?)(?=\n+(?:Q|Question)\s*:|$)",
        re.DOTALL | re.IGNORECASE,
    )
    for m in qa_pattern.finditer(content):
        q = m.group(1).strip()
        a = m.group(2).strip()
        if q and a:
            pairs.append({"question": q, "answer": a})

    return pairs


def _extract_between_markers(text: str, start: str, end: str) -> str:
    """Extract content between named markers in text."""
    try:
        i = text.index(start) + len(start)
        j = text.index(end, i)
        return text[i:j].strip()
    except ValueError:
        return ""


# ──── CLI ──────────────────────────────────────────────────────────────────────

def _load_pipeline(name: str, notebook_id: Optional[str] = None) -> EcosystemPipeline:
    """Load a named pipeline from builtins or disk."""
    if name in BUILTIN_PIPELINES:
        pl = BUILTIN_PIPELINES[name]()
        if notebook_id:
            pl.notebook_id = notebook_id
        return pl

    # Try disk
    path = PIPELINES_DIR / f"{name}.json"
    if path.exists():
        pl = EcosystemPipeline.load(path)
        if notebook_id:
            pl.notebook_id = notebook_id
        return pl

    raise FileNotFoundError(f"Pipeline not found: '{name}'. Use --list to see available pipelines.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gemini Ecosystem Orchestrator — multi-service Gemini compute graph",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--pipeline", "-p", help="Pipeline name to run")
    parser.add_argument("--loops", "-l", type=int, default=1, help="Number of loops (default: 1)")
    parser.add_argument("--notebook-id", "-n", help="Override notebook UUID")
    parser.add_argument("--account", "-a", default="nihilistcod", help="Google account pool name")
    parser.add_argument("--list", action="store_true", help="List all available pipelines")
    parser.add_argument("--save-pipelines", action="store_true", help="Save all built-in pipelines to disk")
    parser.add_argument("--dry-run", action="store_true", help="Print pipeline nodes without executing")
    args = parser.parse_args()

    if args.list:
        print("\nBuilt-in pipelines:")
        for name, factory in BUILTIN_PIPELINES.items():
            pl = factory()
            print(f"  {name:30s} — {pl.description}")
        # Also list disk pipelines
        disk = list(PIPELINES_DIR.glob("*.json"))
        if disk:
            print("\nDisk pipelines:")
            for p in disk:
                try:
                    pl = EcosystemPipeline.load(p)
                    print(f"  {pl.name:30s} — {pl.description}")
                except Exception:
                    print(f"  {p.stem:30s} — (failed to load)")
        return

    if args.save_pipelines:
        for name, factory in BUILTIN_PIPELINES.items():
            pl = factory()
            path = pl.save()
            print(f"Saved: {path}")
        return

    if not args.pipeline:
        parser.print_help()
        return

    pipeline = _load_pipeline(args.pipeline, args.notebook_id)

    if args.dry_run:
        print(f"\nPipeline: {pipeline.name}")
        print(f"Notebook: {pipeline.notebook_id}")
        print(f"Nodes ({len(pipeline.nodes)}):")
        for i, node in enumerate(pipeline.nodes, 1):
            print(f"  {i:2d}. [{node.service}:{node.method}] {node.name}")
            if node.prompt and not node.prompt.isspace():
                preview = node.prompt.strip()[:80].replace("\n", " ")
                print(f"       prompt: {preview}...")
        return

    # Init Nexus
    nexus = None
    try:
        from engine.nexus.client import get_nexus_client
        nexus = get_nexus_client()
        logger.info("Nexus client ready")
    except Exception as exc:
        logger.warning("Nexus unavailable: %s — outputs will not be stored", exc)

    runner = EcosystemRunner(pipeline, nexus_client=nexus, account_name=args.account)
    bus = runner.run(loops=args.loops, notebook_id=args.notebook_id)

    # Summary
    print(f"\n{'=' * 60}")
    print(f"Pipeline: {pipeline.name} | Loops: {args.loops}")
    print(f"NLM sources added: {len(bus.nlm_sources)}")
    print(f"Colab runs: {len(bus.colab_output)}")
    if bus.sheet_url:
        print(f"Sheet: {bus.sheet_url}")
    if bus.audio_files:
        print(f"Audio: {list(bus.audio_files.values())}")
    if bus.errors:
        print(f"Errors in: {list(bus.errors.keys())}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
