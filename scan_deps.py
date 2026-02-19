import ast
import sys
from pathlib import Path

issues = []
root = Path(r'C:\Files\Models\CosySim')

for py_file in root.glob('content/**/*.py'):
    if py_file.name.startswith('__'):
        continue
    
    try:
        content = py_file.read_text(encoding='utf-8')
        tree = ast.parse(content)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in ['comfyui_generator', 'simulation']:
                        issues.append((str(py_file.relative_to(root)), alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.module and (node.module.startswith('comfyui_generator') or node.module.startswith('simulation')):
                    issues.append((str(py_file.relative_to(root)), node.module))
    except Exception as e:
        pass

if issues:
    print(f'Found {len(issues)} dependency issues:')
    for file, module in set(issues):
        print(f'  ❌ {file}: imports {module}')
else:
    print('✅ No obvious import issues found!')
