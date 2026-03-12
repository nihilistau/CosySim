"""Upload PROJECT_JOURNAL.md to NotebookLM.

Run this once after a fresh NotebookLM browser auth session:
    python scripts/upload_journal_to_nlm.py

The script will create a new notebook "CosySim Project Journal & Onboarding"
and upload the journal as the primary source. The notebook ID is then stored
in Nexus for future reference.

Requirements:
    - NotebookLM MCP server authenticated (run notebooklm-setup_auth in Copilot)
    - OR: use the nlm_direct_client with valid Google cookies in data/accounts/
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

JOURNAL_PATH = Path(__file__).parent.parent / "docs" / "PROJECT_JOURNAL.md"
NEXUS_URL = "http://localhost:8700"


def upload_via_mcp() -> str | None:
    """Use the NotebookLM MCP tool to create the notebook."""
    import subprocess
    result = subprocess.run(
        [
            sys.executable, "-c",
            """
import asyncio, json, sys
sys.path.insert(0, '.')

async def main():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command='node',
        args=[r'C:\\Files\\MCP\\notebooklm-mcp\\dist\\index.js'],
        env={"HEADLESS": "true", "NOTEBOOKLM_NO_GEMINI": "false", "NLM_TIER": "pro"},
    )
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = await session.call_tool('create_notebook', {
                'name': 'CosySim Project Journal & Onboarding',
                'sources': [{'type': 'file', 'value': r'C:\\Files\\Models\\CosySim\\docs\\PROJECT_JOURNAL.md'}],
                'description': 'Full project history, philosophy, architecture, and all major breakthroughs',
                'topics': ['cosysim', 'onboarding', 'architecture', 'philosophy'],
            })
            print(json.dumps(result.content[0].text if result.content else '{}'))

asyncio.run(main())
"""
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(Path(__file__).parent.parent),
    )
    if result.returncode == 0 and result.stdout.strip():
        try:
            data = json.loads(result.stdout.strip())
            return data.get("notebook_url") or data.get("url")
        except Exception:
            pass
    logger.warning("MCP upload failed: %s", result.stderr[:200])
    return None


def upload_via_nlm_direct() -> str | None:
    """Use the centralised notebook factory then add journal content."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    try:
        from engine.nexus.nlm_notebook_factory import get_notebook_factory

        factory = get_notebook_factory()
        notebook_id = factory.get_or_create(
            "CosySim Project Journal & Onboarding",
            category="bootstrap",
            dedup_key="bootstrap:project-journal",
        )
        if not notebook_id:
            logger.warning("Factory failed to create journal notebook")
            return None

        # Add journal content as source via direct client
        from engine.integrations.google_account_pool import GoogleAccountPool
        from engine.integrations.nlm_direct_client import NLMDirectClient

        pool = GoogleAccountPool()
        accounts = pool.get_available_accounts(service="notebooklm")
        if accounts:
            client = NLMDirectClient(accounts[0])
            content = JOURNAL_PATH.read_text(encoding="utf-8")
            client.add_source_text(notebook_id, content, "PROJECT_JOURNAL.md")

        return f"https://notebooklm.google.com/notebook/{notebook_id}"
    except Exception as e:
        logger.warning("NLM direct upload failed: %s", e)
        return None


def store_notebook_in_nexus(notebook_url: str) -> None:
    """Record the notebook URL in Nexus for future agent reference."""
    import requests

    try:
        requests.post(
            f"{NEXUS_URL}/api/entries",
            json={
                "title": "NLM Notebook: CosySim Project Journal & Onboarding",
                "content": (
                    f"NotebookLM notebook containing the full CosySim project history.\n"
                    f"URL: {notebook_url}\n\n"
                    "Use this notebook to onboard new agents, research project philosophy,\n"
                    "understand architectural decisions, and query the full project arc.\n\n"
                    "Source file: docs/PROJECT_JOURNAL.md"
                ),
                "content_type": "note",
                "category": "architecture",
                "tags": ["onboarding", "notebooklm", "journal"],
            },
            timeout=15,
        )
        print(f"Stored notebook reference in Nexus")
    except Exception as e:
        logger.warning("Could not store in Nexus: %s", e)


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    if not JOURNAL_PATH.exists():
        print(f"ERROR: Journal not found at {JOURNAL_PATH}")
        sys.exit(1)

    print(f"Journal: {JOURNAL_PATH} ({JOURNAL_PATH.stat().st_size:,} bytes)")
    print("Attempting upload to NotebookLM...")

    notebook_url = upload_via_mcp()
    if not notebook_url:
        print("MCP upload failed, trying NLM direct client...")
        notebook_url = upload_via_nlm_direct()

    if notebook_url:
        print(f"\nSUCCESS: {notebook_url}")
        store_notebook_in_nexus(notebook_url)
        print("\nNext steps:")
        print("  1. Open the notebook in NotebookLM")
        print("  2. Ask: 'What is the project philosophy?'")
        print("  3. Ask: 'How does the NotebookLM integration work?'")
        print("  4. Ask: 'What is the training flywheel?'")
    else:
        print("\nCould not upload automatically.")
        print("Manual upload steps:")
        print(f"  1. Open https://notebooklm.google.com")
        print(f"  2. Create new notebook: 'CosySim Project Journal & Onboarding'")
        print(f"  3. Add source → Upload file: {JOURNAL_PATH}")
        print(f"  4. Run: python scripts/upload_journal_to_nlm.py --store-url <url>")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--store-url":
        store_notebook_in_nexus(sys.argv[2])
        print(f"Stored {sys.argv[2]} in Nexus")
    else:
        main()
