"""
System Services TUI
===================

TUI launcher filtered to show only system-pillar targets.

Version: v1.50.0 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.50.0 [2026-03-22] — Initial three-pillar separation
"""
from tui import main

if __name__ == "__main__":
    main(pillar="service")
