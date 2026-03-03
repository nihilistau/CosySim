"""VSCode History Extractor — Mine VSCode edit history for coder training data.

Scans %APPDATA%/Code/User/History/ for file edit history entries.
Each entry has: source (the chat prompt that triggered the edit),
timestamp, and a snapshot of the file at that point.

Builds FIM (fill-in-middle) training examples:
    instruction = user's chat prompt
    input = file content before edit
    output = file content after edit

Also scans workspaceStorage/*/chatSessions/ for full conversations.
Output: training/datasets/collected/vscode_history.jsonl (coder format).
"""
from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ──── Extension → language map ────

_EXT_TO_LANG: Dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
    ".sql": "sql",
    ".tf": "terraform",
    ".lua": "lua",
    ".kt": "kotlin",
    ".swift": "swift",
    ".r": "r",
    ".R": "r",
    ".ps1": "powershell",
    ".psm1": "powershell",
}

_DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[2]
    / "training" / "datasets" / "collected" / "vscode_history.jsonl"
)


# ──── Main Class ────

class VSCodeHistoryExtractor:
    """Extracts FIM training pairs from VSCode local edit history.

    Reads the VSCode ``%APPDATA%/Code/User/History/`` directory to find
    before/after file snapshots linked to chat-edit prompts.

    Usage:
        extractor = VSCodeHistoryExtractor()
        result = extractor.run()
        print(result)
    """

    # ──── Path Discovery ────

    def _find_history_root(self) -> Optional[Path]:
        """Locate the VSCode edit history root directory.

        Only meaningful on Windows (uses ``%APPDATA%``).

        Returns:
            Path to ``%APPDATA%/Code/User/History``, or None if not found.
        """
        appdata = os.environ.get("APPDATA", "")
        if not appdata:
            logger.debug("APPDATA env var not set; cannot find VSCode history")
            return None
        root = Path(appdata) / "Code" / "User" / "History"
        if root.exists():
            return root
        logger.debug("VSCode history root not found: %s", root)
        return None

    def _find_workspace_storage_root(self) -> Optional[Path]:
        """Locate the VSCode workspaceStorage root directory.

        Returns:
            Path to ``%APPDATA%/Code/User/workspaceStorage``, or None if not found.
        """
        appdata = os.environ.get("APPDATA", "")
        if not appdata:
            return None
        root = Path(appdata) / "Code" / "User" / "workspaceStorage"
        return root if root.exists() else None

    def _find_workspace_hash(self, workspace_path: str) -> Optional[str]:
        """Find the VSCode hash directory corresponding to a workspace path.

        VSCode maps each open workspace to a hex-hash directory under
        ``workspaceStorage/``.  This method scans ``workspace.json`` files
        to find the one matching *workspace_path*.

        Args:
            workspace_path: Absolute path of the workspace root.

        Returns:
            Hex hash directory name, or None if not found.
        """
        storage_root = self._find_workspace_storage_root()
        if storage_root is None:
            return None

        needle = workspace_path.replace("\\", "/").lower()

        for workspace_json in storage_root.glob("*/workspace.json"):
            try:
                data = json.loads(workspace_json.read_text(encoding="utf-8"))
                folder: str = data.get("folder", "")
                # Handle file:// URI
                if folder.startswith("file:///"):
                    folder = folder[8:].replace("/", "\\")
                folder_norm = folder.replace("\\", "/").lower()
                if needle in folder_norm or folder_norm in needle:
                    return workspace_json.parent.name
            except Exception as exc:
                logger.debug("Error reading %s: %s", workspace_json, exc)

        return None

    # ──── Language Inference ────

    @staticmethod
    def _infer_language(file_path: str) -> str:
        """Infer programming language from file extension.

        Args:
            file_path: File path or name (extension used for lookup).

        Returns:
            Language string (e.g. ``"python"``), or ``"unknown"``.
        """
        ext = Path(file_path).suffix.lower()
        return _EXT_TO_LANG.get(ext, "unknown")

    @staticmethod
    def _classify_source_type(source: str) -> str:
        """Classify whether an edit was triggered by a chat action.

        Args:
            source: The ``source`` field from an ``entries.json`` entry.

        Returns:
            ``"chat_edit"`` if the source looks like a Copilot chat prompt,
            ``"manual_edit"`` otherwise.
        """
        if source and source.lower().startswith("chat"):
            return "chat_edit"
        return "manual_edit"

    # ──── Core Extraction ────

    def extract_edit_pairs(
        self,
        workspace_path: str = "C:\\Files\\Models\\CosySim",
        max_pairs: int = 5000,
    ) -> List[Dict[str, Any]]:
        """Extract before/after edit pairs for a given workspace.

        Scans the VSCode History directory for entries belonging to *workspace_path*,
        then assembles FIM training pairs from consecutive snapshots of each file.

        Args:
            workspace_path: Absolute path to the workspace root.
            max_pairs: Maximum number of pairs to return.

        Returns:
            List of training pair dicts with keys:
            ``instruction``, ``input_code``, ``output_code``,
            ``file_path``, ``language``, ``source_type``.
        """
        history_root = self._find_history_root()
        if history_root is None:
            logger.warning("VSCode history root not found; returning empty list")
            return []

        workspace_hash = self._find_workspace_hash(workspace_path)
        if workspace_hash is None:
            logger.info(
                "No workspace hash found for %s; scanning all history entries",
                workspace_path,
            )

        pairs: List[Dict[str, Any]] = []

        # Each sub-directory of History contains entries.json + snapshot files
        for entries_json in history_root.glob("*/entries.json"):
            if len(pairs) >= max_pairs:
                break
            try:
                entry_data = json.loads(entries_json.read_text(encoding="utf-8", errors="replace"))
            except Exception as exc:
                logger.debug("Malformed entries.json %s: %s", entries_json, exc)
                continue

            resource: str = entry_data.get("resource", "")
            entries: List[Dict[str, Any]] = entry_data.get("entries", [])
            if len(entries) < 2:
                continue

            # Filter to workspace if we have a hash
            if workspace_hash and workspace_hash not in str(entries_json):
                # Check resource path against workspace
                resource_norm = resource.replace("\\", "/").lower()
                ws_norm = workspace_path.replace("\\", "/").lower()
                if ws_norm not in resource_norm:
                    continue

            file_ext = Path(resource).suffix if resource else ""
            language = self._infer_language(resource)
            parent_dir = entries_json.parent

            # Walk consecutive entry pairs
            for i in range(len(entries) - 1):
                if len(pairs) >= max_pairs:
                    break
                before_entry = entries[i]
                after_entry = entries[i + 1]

                before_id: str = before_entry.get("id", "")
                after_id: str = after_entry.get("id", "")
                source: str = after_entry.get("source", "") or ""
                timestamp = after_entry.get("timestamp", 0)

                before_file = parent_dir / before_id
                after_file = parent_dir / after_id

                if not before_file.exists() or not after_file.exists():
                    continue

                try:
                    input_code = before_file.read_text(encoding="utf-8", errors="replace")
                    output_code = after_file.read_text(encoding="utf-8", errors="replace")
                except Exception as exc:
                    logger.debug("Failed to read snapshot files: %s", exc)
                    continue

                if input_code == output_code:
                    continue  # No actual change

                # Strip "Chat Edit: '" wrapper if present
                instruction = source
                if instruction.lower().startswith("chat edit:"):
                    instruction = instruction[len("chat edit:"):].strip().strip("'\"")
                if not instruction:
                    instruction = f"Edit {Path(resource).name}"

                pairs.append({
                    "instruction": instruction,
                    "input_code": input_code,
                    "output_code": output_code,
                    "file_path": resource,
                    "language": language,
                    "source_type": self._classify_source_type(source),
                    "timestamp": timestamp,
                })

        logger.info(
            "Extracted %d edit pairs from workspace %s",
            len(pairs),
            workspace_path,
        )
        return pairs

    def extract_all(
        self,
        workspace_path: str = "C:\\Files\\Models\\CosySim",
    ) -> List[Dict[str, Any]]:
        """Extract all available edit pairs for a workspace.

        Args:
            workspace_path: Absolute path to the workspace root.

        Returns:
            Combined list of training pair dicts.
        """
        return self.extract_edit_pairs(workspace_path)

    # ──── Output ────

    def save_to_jsonl(
        self,
        pairs: List[Dict[str, Any]],
        output_path: Optional[str] = None,
    ) -> str:
        """Write training pairs to a JSONL file.

        Args:
            pairs: List of training pair dicts.
            output_path: Destination file path. Defaults to
                ``training/datasets/collected/vscode_history.jsonl``.

        Returns:
            Absolute path of the written file.
        """
        out = Path(output_path) if output_path else _DEFAULT_OUTPUT
        out.parent.mkdir(parents=True, exist_ok=True)

        with out.open("w", encoding="utf-8") as f:
            for pair in pairs:
                f.write(json.dumps(pair, ensure_ascii=False) + "\n")

        logger.info("Saved %d training pairs to %s", len(pairs), out)
        return str(out)

    # ──── Full Pipeline ────

    def run(
        self,
        workspace_path: str = "C:\\Files\\Models\\CosySim",
        output_path: Optional[str] = None,
        max_pairs: int = 5000,
    ) -> Dict[str, Any]:
        """Run the full extraction pipeline: extract → save → report stats.

        Args:
            workspace_path: Absolute path to the workspace root.
            output_path: Optional output file path.
            max_pairs: Maximum pairs to extract.

        Returns:
            Stats dict with keys: ``pairs_extracted``, ``output_path``,
            ``by_language``, ``by_source_type``.
        """
        pairs = self.extract_edit_pairs(workspace_path, max_pairs=max_pairs)
        saved_path = self.save_to_jsonl(pairs, output_path)

        by_language: Dict[str, int] = defaultdict(int)
        by_source_type: Dict[str, int] = defaultdict(int)
        for p in pairs:
            by_language[p.get("language", "unknown")] += 1
            by_source_type[p.get("source_type", "unknown")] += 1

        return {
            "pairs_extracted": len(pairs),
            "output_path": saved_path,
            "by_language": dict(by_language),
            "by_source_type": dict(by_source_type),
        }


# ──── CLI Entry Point ────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract VSCode edit history as training data")
    parser.add_argument("--workspace", default="C:\\Files\\Models\\CosySim")
    parser.add_argument("--output", default=None)
    parser.add_argument("--max", type=int, default=5000)
    args = parser.parse_args()

    extractor = VSCodeHistoryExtractor()
    result = extractor.run(args.workspace, output_path=args.output, max_pairs=args.max)
    print(f"Extracted {result['pairs_extracted']} training pairs → {result['output_path']}")
