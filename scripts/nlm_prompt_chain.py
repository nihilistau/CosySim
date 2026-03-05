"""NLM Prompt Chain — Programmable Gemini 3.0 Pipeline.

Each stage is a full Gemini 3.0 call against the notebook sources.
The prompt can contain anything: JavaScript to parse sources, data
transformation instructions, format directives, cross-references to
previous stage output.  Every stage output becomes the next stage's
context — chained Gemini reasoning with full 10k-word prompt budget
at each step.

Available render methods per stage:
  create_note      → freeform document / code / JSON / any output
  generate_table   → structured rows + columns (Gemini auto-formats)
  generate_audio   → deep-dive podcast script
  generate_flashcards → Q&A card deck

Prompt can include:
  {previous}       → full previous stage output (auto-injected)
  {sources}        → list of notebook source titles (auto-injected)
  {notebook_id}    → notebook UUID

Example chain:
  Stage 1: "Write JS that parses all sources and extracts every @skill"
  Stage 2: "{previous} → now format this as a table: Name | Pack | Params"
  Stage 3: generate_table  (Gemini renders the table Gemini described)

Usage:
    python scripts/nlm_prompt_chain.py --pipeline pipelines/skill_audit.json
    python scripts/nlm_prompt_chain.py --pipeline pipelines/deep_qa.json --loops 2
    python scripts/nlm_prompt_chain.py --list-pipelines
    python scripts/nlm_prompt_chain.py --notebook-id <uuid> --pipeline ...
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

PIPELINES_DIR = PROJECT_ROOT / "data" / "nexus" / "pipelines"
PIPELINES_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_DIR = PROJECT_ROOT / "data" / "nexus" / "chain_outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_NOTEBOOK_ID = "e81e6364-ce39-401e-b7db-bb6bfd7970f7"


# ──── Pipeline definition ─────────────────────────────────────────────────────

@dataclass
class Stage:
    """One step in a Gemini prompt chain."""

    name: str
    method: str = "create_note"        # create_note | generate_table | generate_audio | generate_flashcards
    prompt: str = ""                    # The 10k-word prompt. Use {previous} to inject prior output.
    inject_previous: bool = True        # Auto-inject {previous} if placeholder present
    store_in_nexus: bool = True         # Store output in Nexus
    nexus_category: str = "cosysim_knowledge"
    parse_as: str = "text"             # text | json | qa_pairs | table
    max_words: Optional[int] = None    # Truncate previous output to this many words

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "method": self.method,
            "prompt": self.prompt,
            "inject_previous": self.inject_previous,
            "store_in_nexus": self.store_in_nexus,
            "nexus_category": self.nexus_category,
            "parse_as": self.parse_as,
            "max_words": self.max_words,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Stage":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Pipeline:
    """An ordered list of Gemini prompt stages."""

    name: str
    description: str = ""
    notebook_id: str = DEFAULT_NOTEBOOK_ID
    stages: List[Stage] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "notebook_id": self.notebook_id,
            "stages": [s.to_dict() for s in self.stages],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Pipeline":
        stages = [Stage.from_dict(s) for s in d.get("stages", [])]
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            notebook_id=d.get("notebook_id", DEFAULT_NOTEBOOK_ID),
            stages=stages,
        )

    @classmethod
    def load(cls, path: Path) -> "Pipeline":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save(self, path: Optional[Path] = None) -> Path:
        if path is None:
            path = PIPELINES_DIR / f"{self.name}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path


# ──── Built-in pipelines ──────────────────────────────────────────────────────

def _build_skill_audit_pipeline() -> Pipeline:
    """Extract every @skill → format as table → deep Q&A."""
    return Pipeline(
        name="skill_audit",
        description="Extract all @skill decorators, format as table, generate usage Q&A",
        stages=[
            Stage(
                name="extract_skills",
                method="create_note",
                inject_previous=False,
                prompt="""
Analyse all notebook sources and extract EVERY @skill decorator definition.
For each skill return a JSON object. Return a JSON array, no other text.

Format:
[
  {
    "name": "skill_function_name",
    "pack": "pack name from pack= parameter",
    "description": "description= string",
    "category": "category= string or empty",
    "parameters": [{"name": "param", "type": "str", "default": null}],
    "returns": "return type or description",
    "cooldown": null,
    "file": "engine/skills/builtin/xxx_skills.py"
  }
]

Include every skill from every builtin pack and every scene pack.
""",
                parse_as="json",
            ),
            Stage(
                name="format_skill_table",
                method="create_note",
                prompt="""
Given this complete skill registry extracted from the codebase:

{previous}

Produce a comprehensive markdown document with:

1. **Summary table** — one row per skill:
   | Pack | Skill Name | Category | Description | Parameters |
   |------|-----------|---------|-------------|------------|

2. **Pack breakdown** — one section per pack, listing all skills with full details

3. **Usage patterns** — for each category (GAME, SOCIAL, MEMORY, etc.),
   show example agent prompts that would trigger those skills

4. **Gap analysis** — what skill categories are missing or underserved?

Display as clean markdown, tables aligned, all data from the JSON above.
""",
                parse_as="text",
            ),
            Stage(
                name="generate_qa",
                method="create_note",
                prompt="""
Using the skill registry and documentation above:

{previous}

Generate a JSON array of 30 Q&A pairs about the CosySim skill system.
Focus on: how to use specific skills, what parameters they need,
which pack to import, how to register a new skill, how agents discover skills.

Return ONLY valid JSON:
[{"question": "...", "answer": "..."}]
""",
                parse_as="qa_pairs",
            ),
        ],
    )


def _build_deep_qa_pipeline() -> Pipeline:
    """Flashcard generation → deep knowledge extraction → Nexus seeding."""
    return Pipeline(
        name="deep_qa",
        description="Generate flashcards then use them as context for 100 deep Q&A pairs",
        stages=[
            Stage(
                name="flashcards",
                method="generate_flashcards",
                inject_previous=False,
                prompt="",
                parse_as="qa_pairs",
            ),
            Stage(
                name="deep_qa_from_cards",
                method="create_note",
                prompt="""
You just generated these flashcards from the CosySim codebase:

{previous}

Now using this knowledge base as your context, generate 100 DEEPER Q&A pairs.
Go beyond the flashcards — focus on:
- Exact implementation details (class names, method signatures, config keys)
- How components wire together step by step
- What happens at runtime vs init time
- Error handling and fallback chains
- How to extend each system (add scenes, skills, interceptors, tasks)
- Performance characteristics and bottlenecks
- Testing strategies per module

Return ONLY valid JSON array:
[{"question": "...", "answer": "..."}]

Each answer: 4-8 sentences, concrete specifics, no generalities.
""",
                parse_as="qa_pairs",
                nexus_category="cosysim_knowledge_deep",
            ),
        ],
    )


def _build_api_map_pipeline() -> Pipeline:
    """Extract all REST endpoints + Socket.IO events → full API reference."""
    return Pipeline(
        name="api_map",
        description="Extract every API endpoint and Socket.IO event, format as reference doc",
        stages=[
            Stage(
                name="extract_endpoints",
                method="create_note",
                inject_previous=False,
                prompt="""
Parse all notebook sources and find EVERY HTTP route and Socket.IO event handler.

For each HTTP route extract:
- Method (GET/POST/PATCH/DELETE)
- Path pattern (e.g. /api/hud/state)
- Handler function name
- What it returns / accepts
- Which scene file it lives in

For each Socket.IO event extract:
- Event name
- Direction (client→server or server→client)
- Payload shape
- Which file emits/handles it

Return as JSON:
{
  "routes": [{"method": "GET", "path": "/api/...", "handler": "...", "returns": "...", "file": "..."}],
  "socketio": [{"event": "...", "direction": "...", "payload": "...", "file": "..."}]
}
""",
                parse_as="json",
            ),
            Stage(
                name="api_reference_doc",
                method="create_note",
                prompt="""
Given this complete API inventory:

{previous}

Produce a full API Reference document in markdown:

# CosySim REST API Reference

## Endpoints by Scene
(group routes by scene, show method + path + description + example response)

## Socket.IO Events
| Direction | Event | Payload | Source |
|-----------|-------|---------|--------|

## Common Patterns
- Authentication/session handling
- Error response format
- Pagination
- Real-time update pattern

## JavaScript Client Examples
For the 10 most important endpoints, show fetch() + socket.on() examples.
""",
                parse_as="text",
            ),
        ],
    )


def _build_architecture_report_pipeline() -> Pipeline:
    """Full architecture report: parse sources → JS analysis → table → report."""
    return Pipeline(
        name="architecture_report",
        description="JavaScript source analysis → data table → full architecture report",
        stages=[
            Stage(
                name="js_analysis",
                method="create_note",
                inject_previous=False,
                prompt="""
Write a JavaScript analysis script AND run it mentally against all sources.

The script logic:
```javascript
// Analyse CosySim architecture
const analysis = {
  engine_modules: [],     // engine/* modules with line counts
  scene_registry: [],     // all scenes with port, type, skills count
  interceptors: [],       // all interceptor classes with what they do
  skill_packs: [],        // pack name + skill count + categories
  scheduler_tasks: [],    // task name + schedule + what it does
  nexus_categories: [],   // knowledge categories and entry counts
  singleton_map: [],      // all get_* singletons and what they return
};
```

Execute this analysis against all sources and return the populated JSON object.
Be exhaustive — count every module, every scene, every interceptor.
Return ONLY the JSON, no explanation.
""",
                parse_as="json",
            ),
            Stage(
                name="architecture_tables",
                method="create_note",
                prompt="""
Given this architectural analysis of the CosySim codebase:

{previous}

Produce a structured architecture document with these tables:

## Engine Modules
| Module | Purpose | Key Classes | Line Count |
|--------|---------|-------------|-----------|

## Active Scenes
| Scene | Port | Type | Skills | Key Features |
|-------|------|------|--------|--------------|

## Interceptor Pipeline
| Interceptor | Stage | What It Does | Config Key |
|-------------|-------|-------------|-----------|

## Skill Packs
| Pack | Skills | Categories | Scene or Global |
|-----|--------|-----------|----------------|

## Scheduler Tasks
| Task | Schedule | What It Does | Output |
|------|---------|-------------|--------|

## Singleton Registry
| Getter | Returns | Module |
|--------|---------|--------|

After each table, one paragraph of architectural insight.
""",
                parse_as="text",
            ),
            Stage(
                name="generate_report_table",
                method="generate_table",
                inject_previous=False,
                prompt="",
                parse_as="table",
                store_in_nexus=True,
                nexus_category="architecture",
            ),
        ],
    )


def _build_nexus_seeder_pipeline() -> Pipeline:
    """Maximum Nexus seeding — extract everything into Q&A pairs."""
    return Pipeline(
        name="nexus_seeder",
        description="Maximum-yield Nexus seeding: 200+ Q&A pairs across all CosySim systems",
        stages=[
            Stage(
                name="system_overview_qa",
                method="create_note",
                inject_previous=False,
                prompt="""
Generate 50 Q&A pairs covering CosySim architecture and core systems.
Questions should be what a new developer or local AI agent would ask.
Cover: MCPFramework, scenes, skills, interceptors, Nexus, LMStudio, scheduler.

Return ONLY JSON: [{"question": "...", "answer": "..."}]
Answers: 3-6 sentences, concrete details, include class/method names.
""",
                parse_as="qa_pairs",
                nexus_category="cosysim_knowledge",
            ),
            Stage(
                name="operations_qa",
                method="create_note",
                inject_previous=False,
                prompt="""
Generate 50 Q&A pairs covering CosySim OPERATIONAL knowledge.
Focus on: how to run it, configure it, debug it, extend it, monitor it.
Cover: config keys, launch commands, port numbers, log locations,
       how to add scenes/skills/interceptors/scheduler tasks,
       how to refresh cookies, how to trigger training, how to read benchmarks.

Return ONLY JSON: [{"question": "...", "answer": "..."}]
Answers: concrete steps, exact file paths, exact command syntax.
""",
                parse_as="qa_pairs",
                nexus_category="cosysim_operations",
            ),
            Stage(
                name="integration_qa",
                method="create_note",
                inject_previous=False,
                prompt="""
Generate 50 Q&A pairs covering CosySim INTEGRATION knowledge.
Focus on: how LMStudio integrates, how Nexus integrates, how NLM integrates,
how Google services (Colab, GAS, Drive) integrate, how ARGUS works,
how GitHub Copilot API works, how TTS works, how ComfyUI works.

Return ONLY JSON: [{"question": "...", "answer": "..."}]
Answers: exact API calls, auth patterns, fallback chains, error handling.
""",
                parse_as="qa_pairs",
                nexus_category="cosysim_integrations",
            ),
            Stage(
                name="training_qa",
                method="create_note",
                inject_previous=False,
                prompt="""
Generate 50 Q&A pairs covering CosySim TRAINING and SELF-IMPROVEMENT systems.
Focus on: DataCollector, ModelZoo, training pipelines, benchmark system,
RouterDataCollector, CoderPipeline, how to trigger a finetune run,
how the knowledge flywheel works, how NLM distillation works.

Return ONLY JSON: [{"question": "...", "answer": "..."}]
Answers: include dataset paths, training commands, model names, LoRA params.
""",
                parse_as="qa_pairs",
                nexus_category="cosysim_training",
            ),
        ],
    )


BUILTIN_PIPELINES = {
    "skill_audit": _build_skill_audit_pipeline,
    "deep_qa": _build_deep_qa_pipeline,
    "api_map": _build_api_map_pipeline,
    "architecture_report": _build_architecture_report_pipeline,
    "nexus_seeder": _build_nexus_seeder_pipeline,
}


# ──── Runner ──────────────────────────────────────────────────────────────────

class ChainRunner:
    """Executes a Pipeline stage by stage against an NLM notebook.

    The account pool is used if available. The output of every stage
    is saved to disk and stored in Nexus.
    """

    def __init__(self, notebook_id: str = DEFAULT_NOTEBOOK_ID) -> None:
        self.notebook_id = notebook_id
        self._client = self._get_client()
        self._nexus = self._get_nexus()

    def _get_client(self) -> Any:
        try:
            from engine.integrations.nlm_direct_client import get_nlm_direct_client
            client = get_nlm_direct_client()
            if client:
                logger.info("NLM direct client ready")
            else:
                logger.warning("No NLM account in pool — run: python scripts/nlm_prompt_chain.py --import-cookies")
            return client
        except Exception as exc:
            logger.error("NLM client init failed: %s", exc)
            return None

    def _get_nexus(self) -> Any:
        try:
            from engine.nexus.client import get_nexus_client
            return get_nexus_client()
        except Exception:
            return None

    # ──── Stage execution ─────────────────────────────────────────────────────

    def _build_prompt(self, stage: Stage, previous: str, sources: List[str]) -> str:
        """Inject {previous} and {sources} into the stage prompt."""
        prompt = stage.prompt

        if "{previous}" in prompt and stage.inject_previous and previous:
            # Optionally truncate previous to stay within 10k word budget
            if stage.max_words:
                words = previous.split()
                if len(words) > stage.max_words:
                    previous = " ".join(words[:stage.max_words]) + "\n\n[... truncated ...]"
            prompt = prompt.replace("{previous}", previous)

        if "{sources}" in prompt:
            sources_text = "\n".join(f"- {s}" for s in sources)
            prompt = prompt.replace("{sources}", sources_text)

        if "{notebook_id}" in prompt:
            prompt = prompt.replace("{notebook_id}", self.notebook_id)

        return prompt.strip()

    def _call_stage(self, stage: Stage, prompt: str) -> str:
        """Call the appropriate NLM method for this stage."""
        if not self._client:
            raise RuntimeError("No NLM client available")

        method = stage.method

        if method == "create_note":
            result = self._client.create_note(self.notebook_id, prompt)
            return result.get("content", "")

        if method == "generate_table":
            # generate_table returns structured data — flatten to text
            result = self._client.generate_data_table(self.notebook_id)
            if isinstance(result, dict):
                rows = result.get("rows", [])
                headers = result.get("headers", [])
                lines = ["| " + " | ".join(str(h) for h in headers) + " |"]
                lines.append("|" + "|".join("---" for _ in headers) + "|")
                for row in rows:
                    lines.append("| " + " | ".join(str(c) for c in row) + " |")
                return "\n".join(lines)
            return str(result)

        if method == "generate_flashcards":
            cards = self._client.generate_flashcards(self.notebook_id)
            # Format as text so it can feed the next stage prompt
            lines = []
            for i, card in enumerate(cards, 1):
                q = card.get("question", "")
                a = card.get("answer", "")
                lines.append(f"Q{i}: {q}")
                lines.append(f"A{i}: {a}\n")
            return "\n".join(lines)

        if method == "generate_audio":
            result = self._client.generate_audio(
                self.notebook_id,
                focus_text=prompt or "Cover all topics in the sources",
            )
            return f"[Audio generated: {result}]"

        raise ValueError(f"Unknown method: {method}")

    def _parse_output(self, text: str, parse_as: str) -> Any:
        """Parse the stage output according to parse_as."""
        if parse_as == "text":
            return text

        if parse_as == "json":
            # Strip markdown fences
            clean = re.sub(r"^```(?:json)?\s*", "", text.strip())
            clean = re.sub(r"\s*```$", "", clean)
            try:
                return json.loads(clean)
            except Exception:
                # Try to find JSON in the response
                m = re.search(r"[\[{].*[\]}]", clean, re.DOTALL)
                if m:
                    try:
                        return json.loads(m.group())
                    except Exception:
                        pass
            return text  # Fall through to raw text

        if parse_as == "qa_pairs":
            clean = re.sub(r"^```(?:json)?\s*", "", text.strip())
            clean = re.sub(r"\s*```$", "", clean)
            try:
                data = json.loads(clean)
                if isinstance(data, list):
                    return [d for d in data if isinstance(d, dict) and "question" in d]
            except Exception:
                m = re.search(r"\[.*\]", clean, re.DOTALL)
                if m:
                    try:
                        data = json.loads(m.group())
                        if isinstance(data, list):
                            return [d for d in data if isinstance(d, dict)]
                    except Exception:
                        pass
            # Fallback: parse Q:/A: lines
            pairs = []
            for m in re.finditer(r"Q\d*:\s*(.+?)\nA\d*:\s*(.+?)(?=\nQ\d*:|\Z)", text, re.DOTALL):
                pairs.append({"question": m.group(1).strip(), "answer": m.group(2).strip()})
            return pairs

        if parse_as == "table":
            return text  # Already formatted as markdown table above

        return text

    def _store_output(self, stage: Stage, output_text: str, parsed: Any) -> None:
        """Store stage output in Nexus."""
        if not self._nexus or not stage.store_in_nexus:
            return

        try:
            # Store full output as a knowledge entry
            self._nexus.add_entry(
                title=f"Chain: {stage.name}",
                content=output_text,
                content_type="document",
                category=stage.nexus_category,
            )

            # If parsed as Q&A pairs, also store in the Q&A cache
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                stored = 0
                for pair in parsed:
                    q = pair.get("question", "")
                    a = pair.get("answer", "")
                    if q and a and len(a) > 20:
                        self._nexus.add_qa(q, a, category=stage.nexus_category)
                        stored += 1
                logger.info("[nexus] Stored %d Q&A pairs from stage %s", stored, stage.name)

        except Exception as exc:
            logger.warning("[nexus] Storage failed for stage %s: %s", stage.name, exc)

    def _save_output(self, run_id: str, stage_index: int, stage: Stage, output: str) -> Path:
        """Save stage output to disk."""
        fname = f"{run_id}_stage{stage_index:02d}_{stage.name}.txt"
        path = OUTPUT_DIR / fname
        path.write_text(output, encoding="utf-8")
        return path

    # ──── Pipeline execution ──────────────────────────────────────────────────

    def run(self, pipeline: Pipeline, loops: int = 1) -> Dict[str, Any]:
        """Execute a full pipeline, returning all stage outputs."""
        run_id = f"{pipeline.name}_{int(time.time())}"
        results: Dict[str, Any] = {"run_id": run_id, "stages": {}}

        print(f"\n{'═' * 70}")
        print(f"  PIPELINE: {pipeline.name}")
        print(f"  {pipeline.description}")
        print(f"  Stages: {len(pipeline.stages)} | Loops: {loops}")
        print(f"  Notebook: {self.notebook_id}")
        print(f"{'═' * 70}\n")

        # Get source list for {sources} injection
        sources: List[str] = []
        try:
            sources = [s.get("title", "") for s in self._client.list_sources(self.notebook_id)]
        except Exception:
            pass

        for loop in range(1, loops + 1):
            if loops > 1:
                print(f"\n  ── LOOP {loop}/{loops} ──\n")

            previous_output = ""

            for i, stage in enumerate(pipeline.stages, 1):
                print(f"  [{i}/{len(pipeline.stages)}] {stage.name}  ({stage.method})")

                try:
                    # Build prompt with injections
                    prompt = self._build_prompt(stage, previous_output, sources)

                    word_count = len(prompt.split())
                    print(f"         Prompt: {word_count:,} words  →  Gemini 3.0 ...", end="", flush=True)

                    t0 = time.time()
                    raw_output = self._call_stage(stage, prompt)
                    elapsed = time.time() - t0

                    print(f"  {len(raw_output):,} chars  ({elapsed:.0f}s)")

                    # Parse output
                    parsed = self._parse_output(raw_output, stage.parse_as)

                    # Save to disk
                    out_path = self._save_output(run_id, i, stage, raw_output)
                    print(f"         Saved: {out_path.name}")

                    # Store in Nexus
                    self._store_output(stage, raw_output, parsed)
                    if stage.store_in_nexus:
                        if isinstance(parsed, list):
                            print(f"         Nexus: {len(parsed)} items stored")
                        else:
                            print(f"         Nexus: document stored")

                    # This stage's output feeds the next stage
                    if isinstance(parsed, list):
                        # Re-serialize lists so next prompt has clean text
                        previous_output = json.dumps(parsed, indent=2, ensure_ascii=False)
                    else:
                        previous_output = raw_output

                    results["stages"][stage.name] = {
                        "output_chars": len(raw_output),
                        "elapsed_s": round(elapsed, 1),
                        "file": str(out_path),
                        "items": len(parsed) if isinstance(parsed, list) else None,
                    }

                except Exception as exc:
                    print(f"  ✗ FAILED: {exc}")
                    logger.exception("Stage %s failed", stage.name)
                    results["stages"][stage.name] = {"error": str(exc)}
                    previous_output = ""  # Don't propagate error text

                print()

        print(f"{'═' * 70}")
        print(f"  Run ID: {run_id}")
        print(f"  Outputs: {OUTPUT_DIR}")
        print(f"{'═' * 70}\n")

        return results


# ──── Cookie bootstrap ────────────────────────────────────────────────────────

def import_cookies_from_chrome() -> bool:
    """Extract cookies from the running Chrome and add to account pool.

    Uses CDP (port 9222) — Chrome must be running.
    No HAR capture, no user action needed.
    """
    import asyncio

    async def _extract() -> bool:
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as pw:
                browser = await pw.chromium.connect_over_cdp("http://localhost:9222")
                ctx = browser.contexts[0] if browser.contexts else None
                if not ctx:
                    print("  ✗ No browser context found")
                    return False

                # Get all cookies for Google domains
                cookies = await ctx.cookies(
                    ["https://notebooklm.google.com",
                     "https://colab.research.google.com",
                     "https://accounts.google.com",
                     "https://workspace.google.com"]
                )
                await browser.close()

                if not cookies:
                    print("  ✗ No cookies found — open NotebookLM in Chrome first")
                    return False

                # Build cookie dict keyed by name
                cookie_dict = {c["name"]: c["value"] for c in cookies if c.get("value")}
                print(f"  ✓ Extracted {len(cookie_dict)} cookies from Chrome")

                # Add to account pool
                from engine.integrations.google_account_pool import (
                    GoogleAccount, get_account_pool
                )
                pool = get_account_pool()
                account = GoogleAccount(
                    name="chrome_live",
                    cookies=cookie_dict,
                    services=["notebooklm", "colab", "aistudio"],
                    authuser=0,
                )
                pool.add_account(account)
                pool.save()
                print("  ✓ Account 'chrome_live' added to pool and saved")
                return True

        except Exception as exc:
            print(f"  ✗ Cookie extraction failed: {exc}")
            print("  Is Chrome running with --remote-debugging-port=9222?")
            return False

    return asyncio.run(_extract())


# ──── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="NLM Prompt Chain — Programmable Gemini 3.0 Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--pipeline",       default=None,  help="Pipeline name (builtin) or path to .json")
    p.add_argument("--notebook-id",    default=DEFAULT_NOTEBOOK_ID)
    p.add_argument("--loops",          type=int, default=1, help="Repeat the pipeline N times")
    p.add_argument("--list-pipelines", action="store_true", help="List built-in pipelines and exit")
    p.add_argument("--save-pipelines", action="store_true", help="Write all built-in pipelines to data/nexus/pipelines/")
    p.add_argument("--import-cookies", action="store_true", help="Extract cookies from running Chrome → account pool")
    args = p.parse_args()

    if args.import_cookies:
        print("\n  Extracting cookies from running Chrome (port 9222)...")
        ok = import_cookies_from_chrome()
        sys.exit(0 if ok else 1)

    if args.list_pipelines:
        print(f"\n{'═' * 70}")
        print("  Built-in pipelines:")
        print(f"{'═' * 70}")
        for name, fn in BUILTIN_PIPELINES.items():
            pl = fn()
            stages = "  →  ".join(s.name for s in pl.stages)
            print(f"\n  {name}")
            print(f"  {pl.description}")
            print(f"  Stages: {stages}")
        print()
        return

    if args.save_pipelines:
        for name, fn in BUILTIN_PIPELINES.items():
            pl = fn()
            path = pl.save()
            print(f"  Saved: {path}")
        print(f"\n  All pipelines saved to {PIPELINES_DIR}")
        return

    # ── Load pipeline ─────────────────────────────────────────────────────────
    if not args.pipeline:
        print("ERROR: specify --pipeline <name> or --list-pipelines")
        print("Builtin pipelines:", ", ".join(BUILTIN_PIPELINES))
        sys.exit(1)

    if args.pipeline in BUILTIN_PIPELINES:
        pipeline = BUILTIN_PIPELINES[args.pipeline]()
    else:
        path = Path(args.pipeline)
        if not path.exists():
            path = PIPELINES_DIR / f"{args.pipeline}.json"
        if not path.exists():
            print(f"ERROR: pipeline not found: {args.pipeline}")
            sys.exit(1)
        pipeline = Pipeline.load(path)

    if args.notebook_id != DEFAULT_NOTEBOOK_ID:
        pipeline.notebook_id = args.notebook_id

    runner = ChainRunner(notebook_id=pipeline.notebook_id)
    runner.run(pipeline, loops=args.loops)


if __name__ == "__main__":
    main()
