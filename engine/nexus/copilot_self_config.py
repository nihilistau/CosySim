"""
Copilot Self-Configuration — Read and apply Copilot config from Nexus.

On startup, Copilot should load its own configuration, instruction files,
agent definitions, and hook scripts from Nexus rather than relying solely
on static files.  This module provides the bridge between Nexus-stored
configuration and the Copilot runtime.

Capabilities:
    - Sync instruction files to/from Nexus
    - Sync agent definitions to/from Nexus
    - Sync hook scripts to/from Nexus
    - Read copilot preferences (e.g., preferred models, workflow rules)
    - Store session-learned preferences back to Nexus

This module does NOT modify files on disk — it reads from Nexus and returns
the data for Copilot to use.  Disk files remain the bootstrap source.

Thread-safe singleton — call ``get_copilot_config()``.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ── Nexus Categories ────────────────────────────────────────────────────

NEXUS_CATEGORIES = {
    "instructions": "copilot-instructions",
    "agents": "copilot-agents",
    "hooks": "copilot-hooks",
    "preferences": "copilot-preferences",
    "rules": "copilot-rules",
}


# ── Singleton ───────────────────────────────────────────────────────────

_instance: Optional[CopilotSelfConfig] = None
_lock = threading.Lock()


def get_copilot_config() -> CopilotSelfConfig:
    """Get or create the singleton CopilotSelfConfig instance."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = CopilotSelfConfig()
    return _instance


# ── Core Class ──────────────────────────────────────────────────────────


class CopilotSelfConfig:
    """Manages Copilot configuration via Nexus.

    Reads instruction files, agent definitions, and hook scripts from
    the project and syncs them to/from Nexus.  Nexus becomes the
    authoritative source; disk files are the bootstrap fallback.
    """

    def __init__(self, project_root: Optional[Path] = None) -> None:
        self._root = project_root or _PROJECT_ROOT
        self._instructions_dir = self._root / ".github" / "instructions"
        self._agents_dir = self._root / ".github" / "agents"
        self._hooks_dir = self._root / ".github" / "hooks"
        self._cache: Dict[str, Any] = {}

    @staticmethod
    def _entry_field(entry: Any, field: str, default: Any = "") -> Any:
        """Read a field from either a Nexus model or a plain dict."""
        if isinstance(entry, dict):
            return entry.get(field, default)
        return getattr(entry, field, default)

    @staticmethod
    def _normalized_tags(category: str, tags: Optional[List[str]] = None) -> List[str]:
        """Normalize tags the same way Nexus persistence does."""
        try:
            from engine.nexus.nexus_namespaces import normalize_namespace_tags

            normalized = normalize_namespace_tags(category=category, tags=list(tags or []))
            if not normalized.get("errors"):
                return list(normalized.get("tags", []))
        except Exception as exc:
            logger.debug("Could not normalize Copilot sync tags for %s: %s", category, exc)
        return sorted({tag for tag in (tags or []) if tag})

    def _find_existing_entry(
        self,
        client: Any,
        query: str,
        expected_title: str,
        category: str,
    ) -> Optional[Any]:
        """Find an exact matching Nexus entry instead of skipping on any loose hit."""
        results = client.search(query, limit=10)
        for entry in results or []:
            if (
                self._entry_field(entry, "title") == expected_title
                and self._entry_field(entry, "category") == category
            ):
                return entry
        return None

    def _sync_entry(
        self,
        client: Any,
        *,
        query: str,
        title: str,
        content: str,
        content_type: str,
        category: str,
        tags: List[str],
    ) -> str:
        """Create or update a Copilot config entry in Nexus."""
        normalized_tags = self._normalized_tags(category, tags)
        existing = self._find_existing_entry(client, query, title, category)
        if existing is None:
            client.add_entry(
                title=title,
                content=content,
                content_type=content_type,
                category=category,
                tags=normalized_tags,
            )
            return "stored"

        same_content = self._entry_field(existing, "content") == content
        same_type = self._entry_field(existing, "content_type") == content_type
        existing_tags = self._normalized_tags(category, list(self._entry_field(existing, "tags", []) or []))
        if same_content and same_type and existing_tags == normalized_tags:
            return "skipped"

        entry_id = self._entry_field(existing, "id")
        if entry_id and client.update_entry(
            entry_id,
            title=title,
            content=content,
            content_type=content_type,
            category=category,
            tags=normalized_tags,
        ):
            return "updated"

        if entry_id and hasattr(client, "delete_entry"):
            try:
                if client.delete_entry(entry_id):
                    client.add_entry(
                        title=title,
                        content=content,
                        content_type=content_type,
                        category=category,
                        tags=normalized_tags,
                    )
                    return "updated"
            except Exception as exc:
                logger.debug("Failed to recreate stale Copilot config entry %s: %s", title, exc)

        client.add_entry(
            title=title,
            content=content,
            content_type=content_type,
            category=category,
            tags=normalized_tags,
        )
        return "stored"

    # ── Instruction Files ───────────────────────────────────────────

    def list_instructions(self) -> List[Dict[str, str]]:
        """List all instruction files from disk."""
        results: List[Dict[str, str]] = []
        if not self._instructions_dir.exists():
            return results

        for path in sorted(self._instructions_dir.glob("*.md")):
            results.append({
                "name": path.stem,
                "filename": path.name,
                "path": str(path),
                "size": str(path.stat().st_size),
            })
        return results

    def read_instruction(self, name: str) -> Optional[str]:
        """Read an instruction file by stem name."""
        path = self._instructions_dir / f"{name}.md"
        if not path.exists():
            path = self._instructions_dir / f"{name}.instructions.md"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def sync_instructions_to_nexus(self) -> Dict[str, int]:
        """Push all instruction files to Nexus."""
        stored = 0
        updated = 0
        skipped = 0
        instructions = self.list_instructions()

        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
        except Exception as exc:
            logger.warning("Nexus unavailable: %s", exc)
            return {"stored": 0, "skipped": 0, "error": str(exc)}

        for info in instructions:
            content = Path(info["path"]).read_text(encoding="utf-8")
            try:
                outcome = self._sync_entry(
                    client,
                    query=f"copilot instruction {info['name']}",
                    title=f"[Copilot Instruction] {info['name']}",
                    content=content,
                    content_type="document",
                    category=NEXUS_CATEGORIES["instructions"],
                    tags=["copilot", "instruction", info["name"]],
                )
                if outcome == "stored":
                    stored += 1
                elif outcome == "updated":
                    updated += 1
                else:
                    skipped += 1
            except Exception as exc:
                logger.debug("Failed to store instruction %s: %s", info["name"], exc)

        return {"stored": stored, "updated": updated, "skipped": skipped}

    def get_instructions_from_nexus(self) -> List[Dict[str, Any]]:
        """Retrieve instruction files from Nexus."""
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            results = client.search("copilot instruction", limit=50)
            return results if results else []
        except Exception:
            return []

    # ── Agent Definitions ───────────────────────────────────────────

    def list_agents(self) -> List[Dict[str, str]]:
        """List all agent definition files from disk."""
        results: List[Dict[str, str]] = []
        if not self._agents_dir.exists():
            return results

        for path in sorted(self._agents_dir.glob("*.md")):
            results.append({
                "name": path.stem.replace(".agent", ""),
                "filename": path.name,
                "path": str(path),
                "size": str(path.stat().st_size),
            })
        return results

    def read_agent(self, name: str) -> Optional[str]:
        """Read an agent definition by name."""
        path = self._agents_dir / f"{name}.agent.md"
        if not path.exists():
            path = self._agents_dir / f"{name}.md"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def sync_agents_to_nexus(self) -> Dict[str, int]:
        """Push all agent definitions to Nexus."""
        stored = 0
        updated = 0
        skipped = 0
        agents = self.list_agents()

        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
        except Exception as exc:
            logger.warning("Nexus unavailable: %s", exc)
            return {"stored": 0, "skipped": 0, "error": str(exc)}

        for info in agents:
            content = Path(info["path"]).read_text(encoding="utf-8")
            try:
                outcome = self._sync_entry(
                    client,
                    query=f"copilot agent {info['name']}",
                    title=f"[Copilot Agent] {info['name']}",
                    content=content,
                    content_type="document",
                    category=NEXUS_CATEGORIES["agents"],
                    tags=["copilot", "agent", info["name"]],
                )
                if outcome == "stored":
                    stored += 1
                elif outcome == "updated":
                    updated += 1
                else:
                    skipped += 1
            except Exception as exc:
                logger.debug("Failed to store agent %s: %s", info["name"], exc)

        return {"stored": stored, "updated": updated, "skipped": skipped}

    # ── Hook Scripts ────────────────────────────────────────────────

    def list_hooks(self) -> List[Dict[str, str]]:
        """List all hook scripts from disk."""
        results: List[Dict[str, str]] = []
        if not self._hooks_dir.exists():
            return results

        for ext in ("*.ps1", "*.json"):
            for path in sorted(self._hooks_dir.rglob(ext)):
                results.append({
                    "name": path.stem,
                    "filename": path.name,
                    "path": str(path),
                    "size": str(path.stat().st_size),
                })
        return results

    def sync_hooks_to_nexus(self) -> Dict[str, int]:
        """Push hook scripts to Nexus."""
        stored = 0
        updated = 0
        skipped = 0
        hooks = self.list_hooks()

        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
        except Exception as exc:
            logger.warning("Nexus unavailable: %s", exc)
            return {"stored": 0, "skipped": 0, "error": str(exc)}

        for info in hooks:
            content = Path(info["path"]).read_text(encoding="utf-8")
            try:
                outcome = self._sync_entry(
                    client,
                    query=f"copilot hook {info['name']}",
                    title=f"[Copilot Hook] {info['name']}",
                    content=content,
                    content_type="code",
                    category=NEXUS_CATEGORIES["hooks"],
                    tags=["copilot", "hook", info["name"]],
                )
                if outcome == "stored":
                    stored += 1
                elif outcome == "updated":
                    updated += 1
                else:
                    skipped += 1
            except Exception as exc:
                logger.debug("Failed to store hook %s: %s", info["name"], exc)

        return {"stored": stored, "updated": updated, "skipped": skipped}

    # ── Full Sync ───────────────────────────────────────────────────

    def sync_all_to_nexus(self) -> Dict[str, Any]:
        """Sync all Copilot configuration to Nexus.

        Returns summary of what was stored and skipped.
        """
        result: Dict[str, Any] = {}
        result["instructions"] = self.sync_instructions_to_nexus()
        result["agents"] = self.sync_agents_to_nexus()
        result["hooks"] = self.sync_hooks_to_nexus()

        total_stored = sum(
            r.get("stored", 0) for r in result.values()
            if isinstance(r, dict)
        )
        total_updated = sum(
            r.get("updated", 0) for r in result.values()
            if isinstance(r, dict)
        )
        total_skipped = sum(
            r.get("skipped", 0) for r in result.values()
            if isinstance(r, dict)
        )
        result["summary"] = {
            "total_stored": total_stored,
            "total_updated": total_updated,
            "total_skipped": total_skipped,
        }
        logger.info(
            "Copilot config sync: %d stored, %d updated, %d skipped",
            total_stored,
            total_updated,
            total_skipped,
        )
        return result

    # ── Preferences ─────────────────────────────────────────────────

    def store_preference(self, key: str, value: Any) -> None:
        """Store a Copilot preference in Nexus."""
        self._cache[key] = value
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            client.add_qa(
                question=f"What is the Copilot preference for {key}?",
                answer=json.dumps(value) if not isinstance(value, str) else value,
                category=NEXUS_CATEGORIES["preferences"],
            )
        except Exception as exc:
            logger.debug("Failed to store preference: %s", exc)

    def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a Copilot preference, checking cache then Nexus."""
        if key in self._cache:
            return self._cache[key]

        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            result = client.ask(f"What is the Copilot preference for {key}?")
            if result and result.get("answer"):
                answer = result["answer"]
                try:
                    value = json.loads(answer)
                except (json.JSONDecodeError, TypeError):
                    value = answer
                self._cache[key] = value
                return value
        except Exception:
            pass

        return default

    # ── Status ──────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Return the current configuration status."""
        return {
            "instructions": len(self.list_instructions()),
            "agents": len(self.list_agents()),
            "hooks": len(self.list_hooks()),
            "cached_preferences": len(self._cache),
            "project_root": str(self._root),
        }
