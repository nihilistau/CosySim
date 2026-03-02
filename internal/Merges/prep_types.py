import os

with open('engine/mcp/comms_framework.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

start_idx = 0
for i, line in enumerate(lines):
    if line.startswith('logger = logging.getLogger'):
        start_idx = i
        break

end_idx = 0
for i, line in enumerate(lines):
    if line.startswith('#  AGENT GOVERNOR'):
        end_idx = i
        break

types_content = [
    "from __future__ import annotations\n",
    "import abc\n",
    "import logging\n",
    "from dataclasses import dataclass, field\n",
    "from typing import Any, Callable, Dict, List, Optional, Set\n",
    "from engine.paths import CONFIG_DIR\n\n"
] + lines[start_idx:end_idx]

with open('engine/mcp/comms_types.py', 'w', encoding='utf-8') as f:
    f.writelines(types_content)

new_framework_lines = lines[:start_idx] + [
    "from engine.mcp.comms_types import (\n",
    "    SkillEntry, SceneManifest, SkillManifest,\n",
    "    InteractionPolicy, ResponseContext,\n",
    "    InterceptorBase, InterceptorPipeline,\n",
    "    TRIGGER_AUTO, TRIGGER_OPTIONAL, TRIGGER_REQUIRED\n",
    ")\n\n",
    "logger = logging.getLogger(__name__)\n\n"
] + lines[end_idx:]

with open('engine/mcp/comms_framework.py', 'w', encoding='utf-8') as f:
    f.writelines(new_framework_lines)
