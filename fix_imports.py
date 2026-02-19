import os
import re
from pathlib import Path

# Find all Python files in content/
root = Path(r"C:\Files\Models\CosySim")
files_to_fix = []

for py_file in root.glob("content/**/*.py"):
    if py_file.name == "__init__.py":
        continue
    
    content = py_file.read_text(encoding='utf-8')
    
    # Check if it has problematic imports
    if "from simulation." in content or "from engine." in content:
        files_to_fix.append(py_file)

print(f"Found {len(files_to_fix)} files with imports to fix:")
for f in files_to_fix:
    print(f"  - {f.relative_to(root)}")
