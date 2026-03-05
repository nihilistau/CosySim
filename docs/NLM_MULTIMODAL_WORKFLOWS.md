# NLM Multimodal Workflows — The Full Picture

> Version: 5.0 | Updated: 2026-06
> Gemini 3.0 is multimodal. Every source can be text, URL, YouTube, image,
> audio, video, or PDF. Every generated artifact can feed the next call.
> We are the connector. The recursion is the architecture.

---

## What We Actually Have

```
Sources IN                          Generation OUT
──────────────────────────────      ───────────────────────────────────────
text          → izAoDd (paste)      CYK0Xb  → report / analysis / code
URL           → izAoDd (url)        QA9ei   → 30-min podcast (MP3)
YouTube URL   → izAoDd (native)     ciyUvf  → flashcard Q&A pairs
Google Sheets → izAoDd (url)        R7cb6c  → quiz with citations
image (.png)  → o4cbdc + PUT        yyryJe  → concept mind map (JSON tree)
audio (.mp3)  → o4cbdc + PUT        LBwxtb  → long-form narrative
video (.mp4)  → o4cbdc + PUT        Krh3pd  → export to Google Sheets
PDF           → o4cbdc + PUT        otmP3b  → video content suggestions
                                    Ljjv0c  → deep research
```

**The insight:** every OUTPUT can become the next call's INPUT.
The generated MP3 can be uploaded back. The Sheets URL can be added as a source.
The report artifact can feed the flashcard generator.
Gemini 3.0 reads, listens to, and watches whatever we give it.

---

## The Self-Referential Audio Loop

This is the most powerful workflow in the system.

```
Round 1:
  QA9ei("Explain CosySim architecture deeply. Hosts: Alex (architect) + Sam (sceptic)")
  → 30-min MP3 (~14,000 words when transcribed)
  → add_source_file(mp3)  ← Gemini now LISTENS to its own podcast

Round 2:
  QA9ei("Alex and Sam just finished a podcast about CosySim. Now they cover everything
         the first episode missed: gotchas, failure modes, operational concerns.
         Sam pushes back hard on every claim Alex makes.")
  → another 30-min MP3, builds on Round 1 context
  → add_source_file(mp3)

Round 3:
  QA9ei("Third episode. The team has been running CosySim for a week now.
         They debrief: what worked, what didn't, what they'd change.")
  → future-simulation of operational knowledge

After 3 rounds:
  run_knowledge_flywheel(all 3 transcripts + original docs)
  → 300+ Q&A pairs from one combined analysis
  → Nexus Q&A cache saturated with rich, multi-perspective knowledge
```

Each audio generation costs 0 tokens. Transcription is local (Whisper, ~90s per 30min).
Three rounds = 3 free Gemini calls + 3 local Whisper runs = 300+ Q&A pairs.

---

## The Visual Feedback Loop

ComfyUI generates images. We automate the quality improvement cycle.

```python
# Notebook already has: character description, style guide, reference images as sources
prompt = "A cyberpunk hacker in a neon-lit server room, photorealistic, 8k"
iteration = 0

while iteration < 5:
    # ComfyUI generates
    image_path = comfyui.generate(prompt)

    # Gemini evaluates — VISUALLY
    source_id = nlm.add_source_file(PORTRAIT_NB, image_path)
    report = nlm.create_note(PORTRAIT_NB, f"""
    The most recently added image source is the current generation attempt.
    The other image sources are the reference style guides.

    Evaluate the current generation:
    1. Composition score (1-10): does it match the reference style?
    2. Technical quality (1-10): lighting, detail, coherence
    3. Prompt adherence (1-10): does it match '{prompt}'?
    4. Overall score (1-10)
    5. Specific issues: list exactly what's wrong
    6. IMPROVED PROMPT: write a refined version of the prompt that fixes the issues.
       Maximum 77 tokens (SDXL limit). Return ONLY the improved prompt on the last line.
    """)

    score = parse_score(report["content"])
    if score >= 8:
        break

    prompt = extract_last_line(report["content"])  # the improved prompt
    nlm.delete_source(PORTRAIT_NB, source_id)  # clean up
    iteration += 1
```

Gemini sees the image, reads the style references, produces a specific refined prompt.
No human review. Automated quality gate.

---

## The Video Bug Diagnosis

A screenshot of a broken UI is worth more than any bug report.

```python
# 1. Capture the bug
screenshot_path = browser.screenshot("http://localhost:5555")  # broken scene

# 2. The notebook already has all source code as sources
source_id = nlm.add_source_file(CODEBASE_NB, screenshot_path)

# 3. Gemini reads the screenshot AND the source code simultaneously
report = nlm.create_note(CODEBASE_NB, """
    The most recently added source is a screenshot of a broken UI component.

    Looking at the screenshot and the source code:
    1. Describe exactly what you see in the screenshot (visual state)
    2. Identify which file and function is responsible for rendering this component
    3. State the exact root cause of the visual bug
    4. Write the minimal code change to fix it (show before/after)
    5. What test would catch this in future?

    Be specific. Name files, line numbers, variable names from the source code.
""")

# 4. Apply the fix
fix = parse_code_diff(report["content"])
apply_fix(fix)

# 5. Clean up
nlm.delete_source(CODEBASE_NB, source_id)
```

This is the most direct path from "something looks wrong" to "here is the fix."
Gemini has visual evidence AND source code simultaneously. No ambiguity.

---

## YouTube Intelligence at Scale

NLM handles YouTube natively. No Whisper. No scraping. Just the URL.

```python
# Curated YouTube corpus — AI talks, tutorials, competitor demos, keynotes
YOUTUBE_CORPUS = [
    "https://youtube.com/watch?v=...",  # Andrej Karpathy on LLM internals
    "https://youtube.com/watch?v=...",  # Google DeepMind latest research talk
    "https://youtube.com/watch?v=...",  # LMStudio tutorial deep-dive
    # ... 20 more curated sources
]

# Add all to a single notebook — NLM processes them in parallel
for url in YOUTUBE_CORPUS:
    nlm.add_source_url(INTELLIGENCE_NB, url)

# One flywheel run extracts knowledge from all 20 videos
report, qa_pairs = nlm.run_knowledge_flywheel(
    INTELLIGENCE_NB,
    analysis_prompt=INTELLIGENCE_BRIEF_10K  # custom 10k brief
)

# 60+ Q&A pairs from 20 videos. Straight into Nexus.
for pair in qa_pairs:
    nexus.add_qa(pair["question"], pair["answer"])

# Audio brief: "what did we learn from this week's YouTube corpus?"
job_id, artifact_id = nlm.generate_audio(
    INTELLIGENCE_NB,
    focus_text="Weekly intelligence brief. Cover the 5 most important findings..."
)
```

20 hours of video → 60 Q&A pairs + 30-min synthesis podcast.
Total compute: 3 NLM API calls. Zero local GPU.

---

## The Sheets Read-Write Loop

Gemini writes data → we export to Sheets → Gemini reads its own Sheets → refines.

```python
# Round 1: Generate structured benchmark data
report = nlm.create_note(BENCHMARK_NB, """
    Create a comprehensive benchmark comparison table. Columns:
    Model | Size | Median Latency (ms) | P95 (ms) | Quality Score | VRAM (GB) | Notes
    Include all models from the sources. Add a Recommendation row at the bottom.
    Return as a properly formatted markdown table.
""")

# Export to Sheets — now it's a live spreadsheet
sheets_url = nlm.export_to_sheets(report["id"], "Benchmark Comparison")

# Round 2: Add the Sheets URL back — Gemini reads its own table
sheets_source = nlm.add_source_url(BENCHMARK_NB, sheets_url)
refined_report = nlm.create_note(BENCHMARK_NB, """
    The Google Sheet in the sources contains our benchmark comparison table.
    Looking at the data in the sheet:
    1. Which model has the best quality/latency trade-off?
    2. Which model should be promoted to 'primary' in our config?
    3. Are there any anomalies in the data worth investigating?
    4. Write the exact config YAML change to promote the winner.
""")

# Apply the recommended config change
config_change = extract_yaml(refined_report["content"])
apply_config(config_change)

nlm.delete_source(BENCHMARK_NB, sheets_source)
```

---

## The Chart-to-Action Pipeline

Colab generates a matplotlib chart → Gemini reads it visually → produces action items.

```python
# Colab executes analysis and saves a chart
chart_path = colab.execute_and_save_chart("""
import matplotlib.pyplot as plt
import json, pathlib

data = [json.loads(l) for l in pathlib.Path('benchmarks.jsonl').read_text().splitlines()]
# ... generate chart ...
plt.savefig('/content/chart.png', dpi=150, bbox_inches='tight')
""")

# Feed the chart image to NLM — Gemini reads it visually
source_id = nlm.add_source_file(METRICS_NB, chart_path)

report = nlm.create_note(METRICS_NB, """
    The most recently added source is a performance chart from our benchmark suite.

    Reading the chart visually:
    1. What trend is the chart showing?
    2. Is performance improving, degrading, or plateauing?
    3. What is the approximate inflection point (week/date)?
    4. What does this mean for our fine-tuning strategy?
    5. What specific action should we take this week?

    Be concrete. Reference specific values you can read from the chart.
""")

action = extract_action_items(report["content"])
nexus.add_entry("Chart Analysis Action Items", action, category="performance")

# Generate audio brief with the chart as context — Gemini will narrate what it sees
job_id, artifact_id = nlm.generate_audio(METRICS_NB, focus_text="""
    The sources include a performance chart. Narrate what you see in the chart.
    Explain the trend to a non-technical manager. What does it mean?
    What will happen if we do nothing? What should we do?
    5 minutes. Conversational. No jargon.
""")
```

---

## The Cross-Modal Knowledge Build

Combine every input type for the richest possible knowledge extraction.

```python
# Start with text sources
nlm.add_source_text(NB, "CosySim Architecture", architecture_doc)
nlm.add_source_text(NB, "Source Code", codebase_summary)

# Add YouTube tutorial
nlm.add_source_url(NB, "https://youtube.com/watch?v=...")  # relevant tutorial

# Add reference diagram (image)
nlm.add_source_file(NB, "docs/architecture_diagram.png")

# Add previous podcast transcript (audio self-reference)
nlm.add_source_file(NB, "data/nlm_audio/previous_episode.mp3")

# Now Gemini has: written docs + video tutorial + visual diagram + audio context
# ALL simultaneously. This is what no human reviewer can do.

report = nlm.create_note(NB, """
    You have:
    - Written architecture documentation
    - Source code
    - A video tutorial (from YouTube)
    - An architecture diagram (image)
    - A previous podcast discussion (audio)

    Synthesise ALL of these into a unified understanding.
    What does the diagram show that the text doesn't explain?
    What did the YouTube tutorial demonstrate that conflicts with our approach?
    What did the podcast discussion raise that the docs don't address?
    Write the 10 most important things someone needs to know, synthesising all sources.
""")
```

Five source types. One Gemini call. Unified synthesis.

---

## Implementation Notes

### add_source_file — the upload flow

```
1. o4cbdc([filename], nb_id, [2], [1, null, null, [1]])
   → returns [[source_id, filename, [gcs_signed_upload_url, ...]]]

2. PUT file_bytes to gcs_signed_upload_url
   headers: Content-Type: <mime_type>, Content-Length: <bytes>
   timeout: 300s (video files can be large)

3. Poll rLM1Ne until source_id is no longer in pending list
   → NLM has processed the file, Gemini has indexed it
```

### MIME types that work

| Extension | MIME type        | Gemini understands |
|-----------|------------------|--------------------|
| `.jpg`    | image/jpeg       | Full visual understanding |
| `.png`    | image/png        | Full visual understanding |
| `.mp3`    | audio/mpeg       | Transcription + understanding |
| `.wav`    | audio/wav        | Transcription + understanding |
| `.mp4`    | video/mp4        | Frame + audio + transcription |
| `.mov`    | video/quicktime  | Frame + audio + transcription |
| `.pdf`    | application/pdf  | Text + embedded images |
| `.webm`   | video/webm       | Frame + audio + transcription |

### YouTube — native ingestion

Pass the YouTube URL directly to `add_source_url()`.
NLM handles transcription, chapter extraction, and indexing.
The full video becomes a queryable source. No Whisper needed.
Use this for: tutorials, research talks, demos, competitor analysis.

### The 10k word prompt

Every generation call (CYK0Xb, QA9ei, ciyUvf, R7cb6c) accepts ~10,000 words of prompt.
This is not a question — it's a complete creative brief.

For CYK0Xb: write a full technical specification of exactly what you want.
For QA9ei: write a producer's script with named hosts, segment breakdowns, tone notes.
For multimodal: reference specific source types explicitly ("the chart in the image source...",
"the podcast discussion mentioned...", "the YouTube tutorial showed...")

Gemini executes the brief precisely. The quality of output is proportional to
the specificity of the prompt.

---

## The Compound Effect

```
Week 1:   3 NLM calls → 180 Q&A pairs in Nexus
Week 4:   Nexus has 2,000 pairs → 75% of agent queries hit cache → fewer LLM calls
Week 12:  Nexus has 8,000 pairs → 90% cache hit rate → near-zero local GPU usage
Week 52:  20,000+ pairs → 98% cache → system runs on cached knowledge, almost free

The more we use it, the better it gets.
The more it improves, the less compute it needs.
The less compute it needs, the more we can run.
```

---

*See also: NLM_KNOWLEDGE_FLYWHEEL.md (the original flywheel playbook)*
*Client implementation: engine/integrations/nlm_direct_client.py*
*rpcid reference: data/nlm_rpc_registry.json v5.0*
