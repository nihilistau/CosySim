---
description: Code versioning, comment headers, and change tracking standards
globs: "**/*.py,**/*.js,**/*.css,**/*.html"
---

# Versioning & Comment Standards

## Module Headers (Required on all files)

Python:
```python
"""
Module Title
============

Description.

Version: v1.42.1 [2026-03-21]
Author:  CosySim Team

Change Log:
    v1.42.1 [2026-03-21] — What changed
"""
```

JS: `/** @version v1.42.1 [2026-03-21] */`
CSS: `/* v1.42.1 [2026-03-21] — description */`
HTML: `<!-- v1.42.1 [2026-03-21] — description -->`

## Section Dividers

Use for files with 100+ lines:
```python
# ──── Section Name ────────────────────────────────────────────────
```

## Version Stamps

Tag significant code blocks:
```python
# v1.42.1 [2026-03-21] — Brief description of change
```

## Rules

- Always update the Change Log when modifying a file
- Never remove existing version stamps
- Use `vMAJOR.MINOR.PATCH [YYYY-MM-DD]` format
- Current version: v1.42 (check CHANGELOG.md for latest)
- Store version bumps in Nexus as changelog entries
