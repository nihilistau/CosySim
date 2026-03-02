import os
import re
import sys
from pathlib import Path


def scan_directory(directory="engine"):
    """Scans for raw requests to Nexus endpoints."""

    target_dir = Path(directory)
    if not target_dir.exists():
        print(f"Directory {directory} not found.")
        return

    # Regex to find `requests.post` or `requests.get`
    req_pattern = re.compile(r"requests\.(get|post|put|delete)\(")
    # Regex to roughly identify Nexus URLs (contains 'api', 'nexus', or self._url/NEXUS_URL)
    nexus_url_pattern = re.compile(r"(api/|NEXUS_URL|self\._url|nexus_url)")

    found_files = 0
    total_matches = 0

    print("=" * 60)
    print(f" SCANNING FOR RAW NEXUS HTTP REQUESTS IN: {directory}")
    print("=" * 60)

    for py_file in target_dir.rglob("*.py"):
        try:
            with open(py_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            continue

        file_matches = []
        for i, line in enumerate(lines):
            if req_pattern.search(line) and nexus_url_pattern.search(line):
                file_matches.append((i + 1, line.strip()))

        if file_matches:
            found_files += 1
            print(f"\n {py_file}")
            for line_num, code in file_matches:
                total_matches += 1
                print(f"   Line {line_num:4d} | {code}")

    print("\n" + "=" * 60)
    print(
        f" SCAN COMPLETE: Found {total_matches} remaining raw requests across {found_files} files."
    )
    print("   -> Run this script periodically to track refactoring progress.")
    print("=" * 60)


if __name__ == "__main__":
    scan_dirs = ["engine", "scenes", "scripts"]
    for d in scan_dirs:
        scan_directory(d)
