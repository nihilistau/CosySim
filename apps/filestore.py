#!/usr/bin/env python3
"""
FileStore CLI - Gemini File Search (Managed RAG)
==================================================

Create persistent document stores in Google AI, upload project docs
and code, query with grounded citations, and auto-distill to Nexus.

Version: v1.57.2 [2026-03-27]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-27] - Initial standalone CLI

Usage:
    python apps/filestore.py list                            # List all stores
    python apps/filestore.py create "my-store"               # Create a store
    python apps/filestore.py upload <store> <file> [files...] # Upload documents
    python apps/filestore.py docs <store>                    # List docs in a store
    python apps/filestore.py query <store> "question"        # Grounded query
    python apps/filestore.py bootstrap                       # Upload core project docs
    python apps/filestore.py bootstrap-code                  # Upload engine source code
    python apps/filestore.py delete <store>                  # Delete a store
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap, ROOT
bootstrap()


def main() -> int:
    if not sys.argv[1:] or sys.argv[1] in ("-h", "--help"):
        print("""
  FileStore - Gemini File Search (Managed RAG) v1.57.2
  =====================================================

  Usage: python apps/filestore.py <command> [args...]

  Store Management:
    list                             List all file search stores
    create <name>                    Create a new store
    delete <store-name>              Delete a store

  Documents:
    upload <store> <file> [files..]  Upload files to a store
    docs <store>                     List documents in a store

  Query:
    query <store> "question"         Grounded query with citations
                                     (auto-distills answer to Nexus)

  Bootstrap:
    bootstrap                        Upload core project docs (13 files)
    bootstrap-code                   Upload engine source files (14 files)
    bootstrap-all                    Both docs + code

  Note: The File Search API accepts .py, .md, .yaml etc. directly
  (unlike NLM which requires renaming).
""")
        return 0

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    try:
        from engine.integrations.file_search_client import (
            get_file_search_client,
            bootstrap_project_stores,
            bootstrap_code_store,
        )

        client = get_file_search_client()

        if cmd == "list":
            stores = client.list_stores()
            if not stores:
                print("  No file search stores found.")
                return 0
            print(f"\n  File Search Stores ({len(stores)})")
            print(f"  {'-' * 60}")
            for s in stores:
                print(f"  {s['display_name']:<30} {s['name']}")
            print()
            return 0

        elif cmd == "create":
            if not rest:
                print("Usage: filestore create <display-name>")
                return 1
            name = " ".join(rest)
            store_name = client.create_store(name)
            print(f"  Created store: {name}")
            print(f"  Resource: {store_name}")
            return 0

        elif cmd == "delete":
            if not rest:
                print("Usage: filestore delete <store-resource-name>")
                return 1
            ok = client.delete_store(rest[0])
            print(f"  {'Deleted' if ok else 'Failed to delete'}: {rest[0]}")
            return 0 if ok else 1

        elif cmd == "upload":
            if len(rest) < 2:
                print("Usage: filestore upload <store-name> <file> [files...]")
                return 1
            store_name = rest[0]
            files = rest[1:]
            uploaded = 0
            for f in files:
                path = f if Path(f).is_absolute() else str(ROOT / f)
                if not Path(path).exists():
                    print(f"  SKIP (not found): {f}")
                    continue
                result = client.upload_document(store_name, path)
                if result is not None:
                    print(f"  OK: {Path(f).name}")
                    uploaded += 1
                else:
                    print(f"  FAIL: {Path(f).name}")
            print(f"\n  Uploaded {uploaded}/{len(files)} files")
            return 0

        elif cmd == "docs":
            if not rest:
                print("Usage: filestore docs <store-name>")
                return 1
            docs = client.list_documents(rest[0])
            if not docs:
                print("  No documents found in store.")
                return 0
            print(f"\n  Documents ({len(docs)})")
            print(f"  {'-' * 50}")
            for d in docs:
                print(f"  {d.get('display_name', '?')}")
            print()
            return 0

        elif cmd == "query":
            if len(rest) < 2:
                print("Usage: filestore query <store-name> \"question\"")
                return 1
            store_name = rest[0]
            question = " ".join(rest[1:])
            print(f"  Querying: {question[:60]}...")
            result = client.query(store_name, question)
            print(f"\n  {result['answer']}")
            if result.get("grounded"):
                print(f"\n  [Grounded in {result['store']}]")
            return 0

        elif cmd == "bootstrap":
            print("  Uploading core project documentation...")
            result = bootstrap_project_stores()
            print(f"  Uploaded: {result['uploaded']}/{result['total']}")
            print(f"  Skipped: {result['skipped']}, Failed: {result['failed']}")
            print(f"  Store: {result['store']}")
            return 0

        elif cmd == "bootstrap-code":
            print("  Uploading engine source code...")
            result = bootstrap_code_store()
            print(f"  Uploaded: {result['uploaded']}/{result['total']}")
            print(f"  Skipped: {result['skipped']}, Failed: {result['failed']}")
            print(f"  Store: {result['store']}")
            return 0

        elif cmd == "bootstrap-all":
            print("  Uploading core project documentation...")
            r1 = bootstrap_project_stores()
            print(f"  Docs: {r1['uploaded']}/{r1['total']} uploaded")

            print("  Uploading engine source code...")
            r2 = bootstrap_code_store()
            print(f"  Code: {r2['uploaded']}/{r2['total']} uploaded")
            return 0

        else:
            print(f"Unknown command: {cmd}")
            return 1

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
