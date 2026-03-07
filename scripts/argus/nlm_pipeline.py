"""ARGUS → NLM → Nexus distillation pipeline.

After an ARGUS crawl run captures API traffic and discoveries, this pipeline:

1. Builds a rich API discovery document from the endpoint registry + ARGUS config
2. Creates/updates a persistent NLM notebook with that document as a source
3. Asks deliberate API-knowledge questions via NLM batch-ask
4. Stores all Q&A pairs in Nexus (argus category) for instant agent retrieval
5. Persists notebook ID across runs so sources accumulate over time

The compound effect: each ARGUS run adds new knowledge to NLM, which is
distilled into Nexus Q&A. Over time, agents can answer API questions from
Nexus cache without burning any compute.

Usage::

    from scripts.argus.nlm_pipeline import ArgusNLMPipeline

    pipeline = ArgusNLMPipeline()
    result = pipeline.run()                  # full pipeline
    result = pipeline.run(dry_run=True)      # build doc, skip NLM

    # CLI:
    python -m scripts.argus.nlm_pipeline
    python -m scripts.argus.nlm_pipeline --dry-run
    python -m scripts.argus.nlm_pipeline --target nlm
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from scripts.argus.paths import NLM_PIPELINE_STATE_PATH

logger = logging.getLogger(__name__)

# ── State file — persists notebook IDs across runs ─────────────────────────
_STATE_FILE = NLM_PIPELINE_STATE_PATH

# ── Notebook naming — one notebook per target, refreshed weekly ────────────
_NOTEBOOK_PREFIX = "ARGUS API Intelligence"

# ── Distillation questions — targeted for API/protocol knowledge ────────────
DISTILLATION_QUESTIONS: Dict[str, List[str]] = {
    "nlm": [
        "List every NotebookLM batchexecute rpcid with its name and purpose.",
        "What is the exact HTTP request format for a NotebookLM batchexecute call?",
        "Which NLM rpcids are used for notebook creation and source management?",
        "Which NLM rpcids handle notebook chat and Q&A interactions?",
        "What authentication cookies and headers does NLM require?",
        "Describe the response format for NLM batchexecute — what does wrb.fr contain?",
        "Which NLM rpcids have never been observed and need further investigation?",
        "What are the most recently discovered NLM rpcids?",
        "How does NLM handle source uploads — what rpcids and payload formats?",
        "What is the GetFeatureFlags rpcid and what information does it return?",
    ],
    "gemini": [
        "List all known Gemini API rpcids with their names and functions.",
        "What is the endpoint and format for Gemini batchexecute calls?",
        "Which Gemini rpcids handle conversation creation and messaging?",
        "What are the response rpcids and streaming formats used by Gemini?",
        "Which Gemini rpcids relate to model selection or configuration?",
        "What authentication mechanism does Gemini use?",
        "Describe newly discovered or low-coverage Gemini rpcids.",
        "What is the GetLinkedNotebooks rpcid and what does it return?",
        "How does Gemini differ from NLM in its batchexecute protocol?",
        "Which Gemini features have been confirmed via live traffic capture?",
    ],
    "aistudio": [
        "List the main AI Studio gRPC service names and their method counts.",
        "What is the URL pattern for AI Studio gRPC-web calls?",
        "Which AI Studio methods handle LLM inference and streaming?",
        "Describe the AI Studio AppletService — what methods exist?",
        "What AI Studio methods relate to model tuning and fine-tuning?",
        "How does AI Studio authentication work — what tokens are needed?",
        "Which AI Studio services have been fully mapped via ARGUS?",
        "What streaming protocol does AI Studio use and how are events structured?",
        "Describe the AI Studio BatchRunService and its use cases.",
        "What new AI Studio methods were discovered in the most recent ARGUS scan?",
    ],
    "general": [
        "Compare the API protocols used by NLM, Gemini, and AI Studio.",
        "What authentication patterns are common across Google's AI services?",
        "What are the most important ARGUS discoveries across all three targets?",
        "Which APIs have the highest coverage and which need more investigation?",
        "What practical actions should an API client developer take based on these discoveries?",
        "Summarise the complete picture of Google AI API access methods available.",
        "What rpcids or methods exist in ARGUS config but have never been observed live?",
        "Which discoveries would be most valuable for building API automation tools?",
    ],
}


# ── State helpers ────────────────────────────────────────────────────────────

def _load_state() -> Dict[str, Any]:
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_state(state: Dict[str, Any]) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.debug("Could not save ARGUS NLM state: %s", exc)


def _week_label() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year}-W{now.isocalendar()[1]:02d}"


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ── Document builder ─────────────────────────────────────────────────────────

class ArgusDocBuilder:
    """Builds a rich markdown document from ARGUS discovery data."""

    def build(self, target: Optional[str] = None) -> str:
        """Build the full API discovery document.

        Args:
            target: If set, build doc for one target only. Otherwise all three.

        Returns:
            Formatted markdown document ready for NLM source upload.
        """
        try:
            from scripts.argus.config import (
                NLM_RPCIDS,
                GEMINI_RPCIDS,
                AISTUDIO_METHODS,
            )
            from scripts.argus.discovery.endpoint_registry import get_registry
            registry = get_registry()
            reg_data = registry.get_full_data()
            stats = registry.get_stats()
        except Exception as exc:
            logger.warning("ArgusDocBuilder: could not load registry: %s", exc)
            NLM_RPCIDS = {}
            GEMINI_RPCIDS = {}
            AISTUDIO_METHODS = {}
            reg_data = {"nlm_rpcids": {}, "gemini_rpcids": {}, "aistudio_methods": {}}
            stats = {}

        lines: List[str] = [
            f"# ARGUS API Discovery Document — {_now_str()}",
            "",
            "This document was auto-generated by ARGUS, the CosySim autonomous API",
            "discovery agent. It contains all discovered endpoints, rpcids, and methods",
            "from live traffic capture across Google AI services.",
            "",
        ]

        if target is None or target == "nlm":
            lines += self._build_nlm_section(NLM_RPCIDS, reg_data.get("nlm_rpcids", {}), stats)
        if target is None or target == "gemini":
            lines += self._build_gemini_section(GEMINI_RPCIDS, reg_data.get("gemini_rpcids", {}), stats)
        if target is None or target == "aistudio":
            lines += self._build_aistudio_section(AISTUDIO_METHODS, reg_data.get("aistudio_methods", {}), stats)

        # Append recent scan summary from Nexus if available
        lines += self._load_recent_scan_summary()

        return "\n".join(lines)

    def _build_nlm_section(
        self,
        rpcids: Dict[str, str],
        registry_data: Dict[str, Any],
        stats: Dict[str, Any],
    ) -> List[str]:
        lines = [
            "---",
            "## NotebookLM API",
            "",
            "**Protocol:** Google batchexecute (POST to `/_/LabsTailwindUi/data/batchexecute`)",
            "**Format:** `f.req=[[['rpcid','payload',null,'generic']]]`",
            "**Auth:** `__Secure-1PSID`, `__Secure-1PAPISID` session cookies + SAPISIDHASH header",
            "**Response:** `)]}' prefix + wrb.fr JSON frames`",
            "",
            f"**Coverage:** {stats.get('nlm_rpcids_seen', '?')}/{stats.get('nlm_rpcids_total', len(rpcids))} rpcids observed",
            "",
            "### Known rpcids",
            "",
        ]
        for rpcid, name in sorted(rpcids.items(), key=lambda x: x[1]):
            entry = registry_data.get(rpcid, {})
            seen = entry.get("seen", 0)
            last = entry.get("last", "never")
            status = "✅ observed" if seen > 0 else "⚠️ not yet seen"
            lines.append(f"- `{rpcid}` — **{name}** | {status} | seen {seen}× | last: {last}")
        lines.append("")
        return lines

    def _build_gemini_section(
        self,
        rpcids: Dict[str, str],
        registry_data: Dict[str, Any],
        stats: Dict[str, Any],
    ) -> List[str]:
        lines = [
            "---",
            "## Gemini API",
            "",
            "**Protocol:** Google batchexecute (POST to `https://gemini.google.com/_/BardChatUi/data/batchexecute`)",
            "**Auth:** Same cookie pattern as NLM",
            "",
            f"**Coverage:** {stats.get('gemini_rpcids_seen', '?')}/{stats.get('gemini_rpcids_total', len(rpcids))} rpcids observed",
            "",
            "### Known rpcids",
            "",
        ]
        for rpcid, name in sorted(rpcids.items(), key=lambda x: x[1]):
            entry = registry_data.get(rpcid, {})
            seen = entry.get("seen", 0)
            last = entry.get("last", "never")
            status = "✅ observed" if seen > 0 else "⚠️ not yet seen"
            lines.append(f"- `{rpcid}` — **{name}** | {status} | seen {seen}× | last: {last}")
        lines.append("")
        return lines

    def _build_aistudio_section(
        self,
        methods: Dict[str, Any],
        registry_data: Dict[str, Any],
        stats: Dict[str, Any],
    ) -> List[str]:
        lines = [
            "---",
            "## AI Studio API",
            "",
            "**Protocol:** gRPC-web (POST to `https://alkalimakersuite-pa.clients6.google.com/$rpc/{Service}/{Method}`)",
            "**Auth:** `Authorization: SAPISIDHASH {timestamp}_{sha1}` + session cookies",
            "**Format:** Binary gRPC-web frames (Content-Type: application/grpc-web+proto)",
            "",
            f"**Coverage:** {stats.get('aistudio_methods_seen', '?')}/{stats.get('aistudio_methods_total', len(methods))} methods observed",
            "",
            "### Known gRPC Services & Methods",
            "",
        ]

        # Group methods by service
        by_service: Dict[str, List[str]] = {}
        for method_key, info in sorted(methods.items()):
            if isinstance(info, dict):
                svc = info.get("service", "Unknown")
                method = info.get("method", method_key)
            else:
                # Legacy string format "Service/Method"
                parts = method_key.split("/", 1)
                svc = parts[0] if len(parts) == 2 else "Unknown"
                method = parts[1] if len(parts) == 2 else method_key
            by_service.setdefault(svc, []).append(method)

        for svc, svc_methods in sorted(by_service.items()):
            lines.append(f"#### {svc} ({len(svc_methods)} methods)")
            for m in sorted(svc_methods):
                entry = registry_data.get(f"{svc}/{m}", {})
                seen = entry.get("seen", 0)
                status = "✅" if seen > 0 else "⚠️"
                lines.append(f"  - {status} `{m}`")
            lines.append("")

        return lines

    def _load_recent_scan_summary(self) -> List[str]:
        """Load the most recent ARGUS scan results from Nexus."""
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            results = client.search("ARGUS Scan Results", limit=3)
            if not results:
                return []
            lines = ["---", "## Recent ARGUS Scan History", ""]
            for r in results[:3]:
                title = r.get("title", "")
                content = r.get("content", "")[:600]
                lines.append(f"### {title}")
                lines.append(content)
                lines.append("")
            return lines
        except Exception:
            return []


# ── Main pipeline ─────────────────────────────────────────────────────────────

class ArgusNLMPipeline:
    """Distils ARGUS API discoveries through NotebookLM into Nexus Q&A.

    Designed to run after each ARGUS crawl. Each run uploads fresh discovery
    data to the NLM notebook and asks distillation questions. Answers flow back
    into Nexus as cached Q&A pairs, making agents smarter with each crawl cycle.
    """

    def __init__(self) -> None:
        self._state = _load_state()
        self._doc_builder = ArgusDocBuilder()

    def _get_hybrid(self):
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        return get_nlm_hybrid()

    def _get_nexus(self):
        from engine.nexus.client import get_nexus_client
        return get_nexus_client()

    def _get_or_create_notebook(self, target: str) -> Optional[str]:
        """Get or create the weekly ARGUS notebook for the given target.

        Args:
            target: 'nlm', 'gemini', 'aistudio', or 'all'.

        Returns:
            NLM notebook ID string, or None if unavailable.
        """
        week = _week_label()
        key = f"argus_notebook_{target}_{week}"
        notebook_id = self._state.get(key)

        if notebook_id:
            logger.debug("Reusing ARGUS notebook %s for %s/%s", notebook_id, target, week)
            return notebook_id

        notebook_name = f"{_NOTEBOOK_PREFIX} — {target.upper()} {week}"
        try:
            from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
            result = get_nlm_node_bridge().create_notebook(
                title=notebook_name,
                description=(
                    f"ARGUS API discoveries for {target.upper()} (week {week}). "
                    "Auto-generated from live traffic capture and endpoint registry."
                ),
            )
            if isinstance(result, dict) and result.get("notebook_id"):
                notebook_id = result["notebook_id"]
                self._state[key] = notebook_id
                _save_state(self._state)
                logger.info("Created ARGUS notebook %s → %s", notebook_name, notebook_id)
                return notebook_id
        except Exception as exc:
            logger.debug("Could not create ARGUS NLM notebook: %s", exc)
        return None

    def _upload_discovery_doc(self, notebook_id: str, doc_text: str, target: str) -> bool:
        """Upload the discovery document as a text source to the NLM notebook."""
        date_label = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        source_title = f"ARGUS {target.upper()} Discovery — {date_label}"
        try:
            from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
            result = get_nlm_node_bridge().add_source(
                notebook_id,
                text_content=doc_text,
                title=source_title,
            )
            if isinstance(result, dict) and not result.get("error"):
                logger.info("Uploaded ARGUS discovery doc to notebook %s", notebook_id)
                return True
            logger.debug("Upload returned: %s", result)
        except Exception as exc:
            logger.debug("ARGUS discovery doc upload failed: %s", exc)
        return False

    def _run_distillation(self, notebook_id: str, target: str) -> List[Dict[str, str]]:
        """Ask targeted questions via NLM batch-ask.

        Args:
            notebook_id: NLM notebook with ARGUS discovery data.
            target: Which question set to use.

        Returns:
            List of {question, answer} dicts.
        """
        questions = list(DISTILLATION_QUESTIONS.get(target, []))
        # Always append general questions
        if target != "general":
            questions += DISTILLATION_QUESTIONS["general"]

        try:
            hybrid = self._get_hybrid()
            results = hybrid.ask_batch(notebook_id, questions)
            qa_pairs = []
            for q, r in zip(questions, results):
                if isinstance(r, dict):
                    answer = r.get("answer", "")
                else:
                    answer = str(r)
                if answer and len(answer) > 20 and "error" not in answer.lower()[:30]:
                    qa_pairs.append({"question": q, "answer": answer})
            logger.info("Distilled %d/%d Q&A pairs for %s", len(qa_pairs), len(questions), target)
            return qa_pairs
        except Exception as exc:
            logger.debug("ARGUS distillation batch failed (%s): %s", target, exc)
            return []

    def _store_qa_to_nexus(self, qa_pairs: List[Dict[str, str]], target: str) -> int:
        """Store distilled Q&A pairs in Nexus under the argus category.

        Args:
            qa_pairs: List of {question, answer} dicts.
            target: Target label for tagging.

        Returns:
            Count of pairs stored.
        """
        stored = 0
        try:
            nexus = self._get_nexus()
            for pair in qa_pairs:
                q = f"[ARGUS:{target.upper()}] {pair['question']}"
                a = pair["answer"]
                nexus.add_qa(q, a, category="argus")
                stored += 1
                time.sleep(0.05)  # avoid DB hammering
        except Exception as exc:
            logger.debug("Nexus ARGUS Q&A storage failed: %s", exc)
        return stored

    def _store_doc_to_nexus(self, doc_text: str, target: str) -> None:
        """Archive the full discovery document in Nexus for audit trail."""
        try:
            nexus = self._get_nexus()
            date_label = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            nexus.add_entry(
                title=f"ARGUS Discovery Doc — {target.upper()} {date_label}",
                content=doc_text[:8000],  # Nexus entry cap
                content_type="document",
                category="argus",
            )
        except Exception as exc:
            logger.debug("Doc archive to Nexus failed: %s", exc)

    def run(
        self,
        target: str = "all",
        dry_run: bool = False,
        skip_upload: bool = False,
    ) -> Dict[str, Any]:
        """Run the full ARGUS → NLM → Nexus distillation pipeline.

        Args:
            target: 'nlm', 'gemini', 'aistudio', or 'all'.
            dry_run: Build doc but skip NLM and Nexus writes.
            skip_upload: Build + upload to existing notebook, skip creation.

        Returns:
            Dict with keys: target, notebook_id, uploaded, qa_count, stored, error.
        """
        targets = ["nlm", "gemini", "aistudio"] if target == "all" else [target]
        overall: Dict[str, Any] = {
            "targets": targets,
            "runs": [],
            "total_qa": 0,
            "total_stored": 0,
            "dry_run": dry_run,
        }

        for tgt in targets:
            run_result = self._run_single(tgt, dry_run=dry_run, skip_upload=skip_upload)
            overall["runs"].append(run_result)
            overall["total_qa"] += run_result.get("qa_count", 0)
            overall["total_stored"] += run_result.get("stored", 0)

        logger.info(
            "ARGUS NLM pipeline complete — %d Q&A distilled, %d stored to Nexus",
            overall["total_qa"],
            overall["total_stored"],
        )
        return overall

    def _run_single(self, target: str, dry_run: bool, skip_upload: bool) -> Dict[str, Any]:
        """Run pipeline for a single target service."""
        result: Dict[str, Any] = {
            "target": target,
            "notebook_id": None,
            "uploaded": False,
            "qa_count": 0,
            "stored": 0,
        }

        # 1. Build discovery document
        logger.info("ARGUS NLM pipeline: building discovery doc for %s", target)
        doc_text = self._doc_builder.build(target=target)
        result["doc_length"] = len(doc_text)

        if dry_run:
            result["dry_run_doc"] = doc_text[:500]
            logger.info("Dry run — doc built (%d chars), no uploads", len(doc_text))
            return result

        # 2. Archive doc to Nexus
        self._store_doc_to_nexus(doc_text, target)

        # 3. Get or create NLM notebook
        notebook_id = self._get_or_create_notebook(target)
        if not notebook_id:
            result["error"] = "NLM notebook unavailable"
            logger.info("ARGUS NLM pipeline skipped for %s: NLM offline", target)
            return result
        result["notebook_id"] = notebook_id

        # 4. Upload discovery doc as source
        if not skip_upload:
            uploaded = self._upload_discovery_doc(doc_text=doc_text, notebook_id=notebook_id, target=target)
            result["uploaded"] = uploaded
            if not uploaded:
                result["error"] = "Source upload failed — distillation skipped"
                return result
            # Wait for NLM to index the source
            time.sleep(5)
        else:
            result["uploaded"] = False  # skipped by caller

        # 5. Run distillation
        qa_pairs = self._run_distillation(notebook_id, target)
        result["qa_count"] = len(qa_pairs)

        # 6. Store Q&A to Nexus
        if qa_pairs:
            stored = self._store_qa_to_nexus(qa_pairs, target)
            result["stored"] = stored

        return result


# ── CLI entry point ─────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s — %(message)s",
    )

    parser = argparse.ArgumentParser(description="ARGUS → NLM → Nexus distillation pipeline")
    parser.add_argument(
        "--target",
        choices=["nlm", "gemini", "aistudio", "all"],
        default="all",
        help="Which API target to distil (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build discovery doc but skip NLM and Nexus writes",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Skip source upload, run distillation against existing notebook",
    )
    args = parser.parse_args()

    pipeline = ArgusNLMPipeline()
    result = pipeline.run(
        target=args.target,
        dry_run=args.dry_run,
        skip_upload=args.skip_upload,
    )

    print(f"\n=== ARGUS NLM Pipeline ===")
    print(f"Targets: {result['targets']}")
    print(f"Total Q&A distilled: {result['total_qa']}")
    print(f"Total stored to Nexus: {result['total_stored']}")
    if result.get("dry_run"):
        print("(dry run — no writes)")
    for run in result["runs"]:
        err = run.get("error", "")
        status = f"❌ {err}" if err else f"✅ {run.get('stored', 0)} Q&A stored"
        print(f"  [{run['target'].upper()}] notebook={run.get('notebook_id', 'N/A')} | {status}")


if __name__ == "__main__":
    main()
