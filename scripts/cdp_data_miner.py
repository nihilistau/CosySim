"""
CDP Data Miner — extracts training data from CDP monitor logs.

The CDP event log (logs/cdp_events.jsonl) is a labelled debugging session stream.
Every file-change or manual marker creates a boundary. What happened before vs after
those boundaries gives us supervised examples for multiple model types.

Three dataset types extracted
─────────────────────────────────────────────────────────────────────────────
1. browser_debugger
   Input:  list of browser errors + which file changed
   Output: natural-language description of the fix / root cause
   Use:    "given these errors, what file do I change and why?"

2. error_classifier
   Input:  raw CDP error message
   Output: error category label
   Use:    fast triage — route error to the right handler

3. fix_sequence
   Input:  ordered errors before + after a file change
   Output: structured JSON {changed_file, fixed_count, introduced_count, outcome}
   Use:    reinforcement-learning reward signal (did the change help?)

Usage
─────────────────────────────────────────────────────────────────────────────
  # Mine all datasets:
  python scripts/cdp_data_miner.py mine

  # Mine and print a sample:
  python scripts/cdp_data_miner.py mine --sample 5

  # Stats on existing log:
  python scripts/cdp_data_miner.py stats

  # Run as scheduled task (used by SchedulerDaemon):
  python scripts/cdp_data_miner.py run
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ROOT         = Path(__file__).resolve().parent.parent
EVENTS_PATH  = ROOT / "logs" / "cdp_events.jsonl"
MARKERS_PATH = ROOT / "logs" / "cdp_markers.jsonl"
OUT_DIR      = ROOT / "training" / "datasets" / "collected"

# ── Error category patterns ───────────────────────────────────────────────────

ERROR_CATEGORIES: List[Tuple[str, re.Pattern]] = [
    ("duplicate_script",    re.compile(r"already been declared|Identifier .* has already")),
    ("missing_route_404",   re.compile(r"\b404\b.*(?:/api/|/shared/)")),
    ("missing_route",       re.compile(r"\b404\b")),
    ("cors_blocked",        re.compile(r"CORS policy|Access-Control-Allow-Origin")),
    ("missing_model",       re.compile(r"Invalid model identifier|model.*not.*found", re.I)),
    ("js_ref_error",        re.compile(r"\bis not defined\b|\bis not a function\b")),
    ("js_syntax_error",     re.compile(r"SyntaxError|Unexpected token|Unexpected end")),
    ("js_type_error",       re.compile(r"TypeError")),
    ("js_range_error",      re.compile(r"RangeError")),
    ("js_exception",        re.compile(r"\bUncaught\b")),
    ("network_refused",     re.compile(r"ERR_CONNECTION_REFUSED")),
    ("network_failed",      re.compile(r"net::ERR_|Failed to fetch|ERR_ABORTED")),
    ("load_failed",         re.compile(r"LOAD FAILED")),
    ("missing_blueprint",   re.compile(r"register_shared_assets|register_hud|register_announcer")),
    ("aria_ghost",          re.compile(r"aria_widget.*fallback|_buildFallback", re.I)),
    ("server_error_5xx",    re.compile(r"\b5[0-9][0-9]\b")),
]

# ── Human-readable fix templates (used to generate training output text) ──────

FIX_TEMPLATES: Dict[str, str] = {
    "duplicate_script":   (
        "The error indicates a script was loaded twice. "
        "Check the scene template for explicit <script> or <link> tags that duplicate "
        "what an HTML include already provides (e.g. navbar_v2.html emits its own tags)."
    ),
    "missing_route_404":  (
        "A 404 on /api/ or /shared/ means a Flask blueprint is not registered. "
        "Ensure the scene calls register_shared_assets(app), register_hud_route(app), "
        "and register_announcer_route(app) in its start() method."
    ),
    "missing_route":      (
        "A 404 response means either the route is not registered or the file does not exist. "
        "Check scene.py register_* calls and verify the static file path."
    ),
    "cors_blocked":       (
        "A CORS error means the server lacks the Access-Control-Allow-Origin header. "
        "Add flask_cors to the relevant Flask app or configure CORS in the route."
    ),
    "missing_model":      (
        "LMStudio rejected an empty model identifier. "
        "The auto-resolve logic failed to populate lmstudio.models.primary.key. "
        "Fix the model resolution fallback to use the first loaded model when the key is empty."
    ),
    "js_ref_error":       (
        "A JS ReferenceError means a variable or class was used before it was defined. "
        "Usually caused by a script load order issue or a missing script tag."
    ),
    "js_syntax_error":    (
        "A SyntaxError means invalid JavaScript, often from duplicate const declarations. "
        "Check for double-loaded scripts in the template."
    ),
    "network_refused":    (
        "ERR_CONNECTION_REFUSED means the scene server is not running on that port. "
        "Start the scene or check the port mapping."
    ),
    "network_failed":     (
        "A network failure means the request could not reach the server. "
        "Check CORS headers and that the service is running."
    ),
    "aria_ghost":         (
        "The old aria_widget.js is being loaded, creating a ghost 'Radio' button. "
        "Remove the aria_widget.js script tag from the template and use aria_widget.html include instead."
    ),
}


def classify_error(msg: str) -> str:
    """Return the best-matching error category for a message."""
    for category, pattern in ERROR_CATEGORIES:
        if pattern.search(msg):
            return category
    return "other"


# ── Log parsing ───────────────────────────────────────────────────────────────

def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    results = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return results


def _build_windows(events: List[Dict], markers: List[Dict]) -> List[Dict]:
    """Partition events into windows between file-change markers.

    Returns a list of window dicts, each containing:
      - marker_before: the marker that opened this window
      - marker_after:  the marker that closed it (None = open/current)
      - errors_before: errors in the 60s before the opening marker
      - errors_after:  errors in the 60s after the opening marker
      - file_changed:  file path if the marker was a file_change
    """
    if not markers:
        return []

    windows = []
    for i, mark in enumerate(markers):
        if not mark["msg"].startswith("file_change:"):
            continue
        file_path = mark["msg"].replace("file_change: ", "").strip()
        ts_mark   = mark["ts"]

        # Collect errors in a window around the file change
        # Before: events with ts < ts_mark and ts >= ts_mark - 120s (2 min look-back)
        # After:  events with ts >= ts_mark and ts < ts_mark + 120s

        def ts_in_range(ts: str, start: str, end: Optional[str]) -> bool:
            return start <= ts < end if end else ts >= start

        before_start = _shift_ts(ts_mark, -120)
        after_end    = _shift_ts(ts_mark,  120)

        errors_before = [
            e for e in events
            if e.get("level") in ("ERR", "EXC")
            and before_start <= e.get("ts", "") < ts_mark
        ]
        errors_after = [
            e for e in events
            if e.get("level") in ("ERR", "EXC")
            and ts_mark <= e.get("ts", "") < after_end
        ]

        windows.append({
            "marker":        mark,
            "file_changed":  file_path,
            "errors_before": errors_before,
            "errors_after":  errors_after,
            "ts_mark":       ts_mark,
        })

    return windows


def _shift_ts(ts: str, seconds: int) -> str:
    """Shift an ISO timestamp string by N seconds (approximate, string-based)."""
    try:
        dt = datetime.strptime(ts[:23], "%Y-%m-%d %H:%M:%S.%f")
        shifted = dt.timestamp() + seconds
        return datetime.fromtimestamp(shifted).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    except Exception:
        return ts


# ── Training example generators ───────────────────────────────────────────────

def _make_browser_debugger_examples(windows: List[Dict]) -> List[Dict]:
    """Generate browser_debugger training examples from file-change windows."""
    examples = []
    for w in windows:
        before = w["errors_before"]
        after  = w["errors_after"]
        file_  = w["file_changed"]

        if not before:
            continue   # no errors before change — not useful

        # Summarise what changed (error types)
        categories_before = [classify_error(e["msg"]) for e in before]
        categories_after  = [classify_error(e["msg"]) for e in after]
        fixed_types  = set(categories_before) - set(categories_after)
        new_types    = set(categories_after) - set(categories_before)
        fixed_count  = len(before) - len(after)

        # Build input text
        error_lines = "\n".join(
            f"  [{e['scene']}]  {e['level']}  {e['msg'][:120]}"
            for e in before[:15]
        )
        input_text = (
            f"File changed: {file_}\n\n"
            f"Browser errors observed before the change:\n{error_lines}\n\n"
            f"What was the likely fix and root cause?"
        )

        # Build output text from fix templates
        fix_parts = []
        for cat in fixed_types:
            if cat in FIX_TEMPLATES:
                fix_parts.append(FIX_TEMPLATES[cat])
        if not fix_parts:
            fix_parts = [
                f"Modified {file_}. "
                f"Error count changed from {len(before)} to {len(after)} "
                f"({'reduced' if fixed_count > 0 else 'increased or unchanged'})."
            ]

        if new_types:
            fix_parts.append(
                f"Note: new error types appeared after the change: {', '.join(new_types)}. "
                f"The fix may be incomplete."
            )

        output_text = " ".join(fix_parts)

        # Quality: higher when more errors cleared
        quality = min(1.0, max(0.3, (len(before) - len(after)) / max(len(before), 1) + 0.5))

        examples.append({
            "id":             str(uuid.uuid4()),
            "model_type":     "browser_debugger",
            "input":          input_text,
            "output":         output_text,
            "quality":        round(quality, 3),
            "collected_at":   time.time(),
            "source":         "cdp_monitor",
            "metadata": {
                "file_changed":       file_,
                "errors_before_count": len(before),
                "errors_after_count":  len(after),
                "fixed_types":         list(fixed_types),
                "new_types":           list(new_types),
                "ts_mark":             w["ts_mark"],
            },
        })

    return examples


def _make_error_classifier_examples(events: List[Dict]) -> List[Dict]:
    """Label every individual error event with its category."""
    examples = []
    seen: set[str] = set()

    for e in events:
        if e.get("level") not in ("ERR", "EXC"):
            continue
        msg = e.get("msg", "").strip()
        if not msg or msg in seen:
            continue
        seen.add(msg)

        category = classify_error(msg)
        if category == "other":
            continue   # skip unlabelled — noise

        examples.append({
            "id":           str(uuid.uuid4()),
            "model_type":   "error_classifier",
            "input":        f"Classify this browser error:\n{msg[:300]}",
            "output":       category,
            "quality":      1.0,
            "collected_at": time.time(),
            "source":       "cdp_monitor",
            "metadata": {
                "scene":    e.get("scene", ""),
                "raw_msg":  msg[:300],
            },
        })

    return examples


def _make_fix_sequence_examples(windows: List[Dict]) -> List[Dict]:
    """Structured before/after fix records for reinforcement signal."""
    examples = []
    for w in windows:
        before = w["errors_before"]
        after  = w["errors_after"]
        delta  = len(before) - len(after)
        if delta == 0 and not before:
            continue

        outcome = (
            "fixed"    if len(after) == 0 and before else
            "improved" if delta > 0 else
            "degraded" if delta < 0 else
            "unchanged"
        )

        examples.append({
            "id":           str(uuid.uuid4()),
            "model_type":   "fix_sequence",
            "input":        json.dumps({
                "file_changed":  w["file_changed"],
                "errors_before": [e["msg"][:150] for e in before[:10]],
            }),
            "output": json.dumps({
                "errors_after":    [e["msg"][:150] for e in after[:10]],
                "fixed_count":     max(0, delta),
                "introduced_count": max(0, -delta),
                "outcome":         outcome,
            }),
            "quality":      {"fixed": 1.0, "improved": 0.8, "unchanged": 0.5, "degraded": 0.2}[outcome],
            "collected_at": time.time(),
            "source":       "cdp_monitor",
            "metadata": {"ts_mark": w["ts_mark"], "outcome": outcome},
        })

    return examples


# ── Writer ────────────────────────────────────────────────────────────────────

def _append_examples(model_type: str, examples: List[Dict]) -> int:
    if not examples:
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{model_type}_live.jsonl"
    # De-dupe by id against existing
    existing_ids: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    existing_ids.add(json.loads(line)["id"])
                except Exception:
                    pass
    new = [e for e in examples if e["id"] not in existing_ids]
    if new:
        with path.open("a", encoding="utf-8") as f:
            for e in new:
                f.write(json.dumps(e) + "\n")
    return len(new)


# ── Public entry point ────────────────────────────────────────────────────────

def mine() -> Dict[str, int]:
    """Process CDP logs and return count of new examples per dataset type."""
    events  = _load_jsonl(EVENTS_PATH)
    markers = _load_jsonl(MARKERS_PATH)

    if not events:
        logger.info("cdp_data_miner: no events log found at %s", EVENTS_PATH)
        return {}

    windows = _build_windows(events, markers)

    debugger   = _make_browser_debugger_examples(windows)
    classifier = _make_error_classifier_examples(events)
    sequences  = _make_fix_sequence_examples(windows)

    counts = {
        "browser_debugger": _append_examples("browser_debugger", debugger),
        "error_classifier": _append_examples("error_classifier", classifier),
        "fix_sequence":     _append_examples("fix_sequence",     sequences),
    }

    total = sum(counts.values())
    logger.info(
        "cdp_data_miner: mined %d new examples (%s)",
        total,
        ", ".join(f"{k}={v}" for k, v in counts.items()),
    )
    return counts


def stats() -> Dict[str, Any]:
    """Return statistics about the current log and extracted datasets."""
    events  = _load_jsonl(EVENTS_PATH)
    markers = _load_jsonl(MARKERS_PATH)

    level_counts: Dict[str, int] = {}
    scene_counts: Dict[str, int] = {}
    for e in events:
        lv = e.get("level", "?")
        sc = e.get("scene", "?")
        level_counts[lv] = level_counts.get(lv, 0) + 1
        scene_counts[sc] = scene_counts.get(sc, 0) + 1

    category_counts: Dict[str, int] = {}
    for e in events:
        if e.get("level") in ("ERR", "EXC"):
            cat = classify_error(e.get("msg", ""))
            category_counts[cat] = category_counts.get(cat, 0) + 1

    dataset_counts: Dict[str, int] = {}
    for model_type in ("browser_debugger", "error_classifier", "fix_sequence"):
        p = OUT_DIR / f"{model_type}_live.jsonl"
        dataset_counts[model_type] = sum(1 for ln in (p.read_text(encoding="utf-8").splitlines() if p.exists() else []) if ln.strip())

    return {
        "events_total":    len(events),
        "markers_total":   len(markers),
        "file_changes":    sum(1 for m in markers if m.get("msg", "").startswith("file_change:")),
        "manual_markers":  sum(1 for m in markers if not m.get("msg", "").startswith("file_change:")),
        "by_level":        level_counts,
        "by_scene":        scene_counts,
        "by_error_cat":    category_counts,
        "datasets":        dataset_counts,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    p = argparse.ArgumentParser(description="CDP Data Miner")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("mine", help="Mine log → training datasets")
    m.add_argument("--sample", type=int, default=0, metavar="N",
                   help="Print N sample examples per dataset")

    sub.add_parser("stats", help="Show log statistics")
    sub.add_parser("run",   help="Mine + log results (scheduler use)")

    args = p.parse_args()

    if args.cmd in ("mine", "run"):
        counts = mine()
        total  = sum(counts.values())
        if counts:
            print(f"\nMined {total} new training examples:")
            for k, v in sorted(counts.items()):
                print(f"  {k:<24} {v}")
        else:
            print("No new examples (log may be empty or no file-change markers yet).")

        if getattr(args, "sample", 0):
            for model_type in ("browser_debugger", "error_classifier", "fix_sequence"):
                p_ = OUT_DIR / f"{model_type}_live.jsonl"
                if not p_.exists():
                    continue
                lines = [json.loads(l) for l in p_.read_text(encoding="utf-8").splitlines() if l.strip()]
                print(f"\n── {model_type} sample ({'─' * 40})")
                for ex in lines[-args.sample:]:
                    print(f"  Q: {ex['input'][:120]}")
                    print(f"  A: {ex['output'][:120]}")
                    print(f"  quality={ex['quality']}")
                    print()

    elif args.cmd == "stats":
        s = stats()
        print(f"\nCDP Log Statistics")
        print(f"  Events:        {s['events_total']}")
        print(f"  Markers:       {s['markers_total']}  (file_changes={s['file_changes']}  manual={s['manual_markers']})")
        print(f"\nErrors by category:")
        for cat, cnt in sorted(s["by_error_cat"].items(), key=lambda x: -x[1]):
            print(f"  {cat:<28} {cnt}")
        print(f"\nEvents by scene:")
        for sc, cnt in sorted(s["by_scene"].items(), key=lambda x: -x[1])[:12]:
            print(f"  {sc:<20} {cnt}")
        print(f"\nDataset sizes (collected/live):")
        for k, v in sorted(s["datasets"].items()):
            print(f"  {k:<28} {v}")


if __name__ == "__main__":
    main()
