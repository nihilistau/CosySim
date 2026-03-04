"""Fix split interceptor files: remove doubled docstring, add imports."""
from __future__ import annotations

import re
from pathlib import Path

INTERCEPTORS_DIR = Path("engine/agents/interceptors")
SKIP = {"__init__.py"}

IMPORTS = '''\
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from engine.mcp.comms_framework import (
    InterceptorBase,
    ResponseContext,
    TRIGGER_OPTIONAL,
    TRIGGER_REQUIRED,
)

logger = logging.getLogger(__name__)

'''


def fix_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")

    # Pattern: header docstring ends, then standalone """ starts an orphaned string
    # We replace the orphaned """ (on its own line after the header docstring) with imports
    # Header looks like:  """...\n"""\n"""  where the last """ is the problem
    fixed = re.sub(
        r'("""[\s\S]+?""")\s*\n"""\s*\n',
        lambda m: m.group(1) + "\n\n" + IMPORTS,
        text,
        count=1,
    )
    if fixed == text:
        print(f"  [skip] {path.name} (no match)")
        return False

    path.write_text(fixed, encoding="utf-8")
    print(f"  [fix]  {path.name}")
    return True


def main() -> None:
    files = [f for f in sorted(INTERCEPTORS_DIR.glob("*.py")) if f.name not in SKIP]
    fixed = sum(fix_file(f) for f in files)
    print(f"\n{fixed}/{len(files)} files fixed")


if __name__ == "__main__":
    main()
