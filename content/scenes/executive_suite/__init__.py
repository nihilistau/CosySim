"""Executive Suite scene package.

A neon corporate operating-system desktop — a windowed NeonOS shell (window
manager + dock + taskbar + animated skyline) hosting eight functional apps
(files / mail / notes / music / code / terminal / browser / settings), a live
in-world AI assistant and a live system tray.

Version: v1.62.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.62.0 [2026-06-15] — Final polish (ES-T5): assistant reply sanitizer +
                            tightened prompt; integration verified end-to-end
    v1.62.0 [2026-06-15] — Live AI assistant + live system tray (ES-T4)
    v1.62.0 [2026-06-15] — Functional OS app backends (ES-T3)
    v1.62.0 [2026-06-15] — OS desktop shell (ES-T2): window manager + dock +
                            taskbar + skyline; app-registry API (window.ES)
    v1.62.0 [2026-06-15] — Initial scaffold (ES-T1): bootable placeholder scene
"""
from content.scenes.executive_suite.executive_suite_scene import ExecutiveSuiteScene

__all__ = ["ExecutiveSuiteScene"]
