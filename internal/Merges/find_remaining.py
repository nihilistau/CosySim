import ast

with open('engine/mcp/cosysim_server.py', 'r', encoding='utf-8') as f:
    code = f.read()

tree = ast.parse(code)
funcs_with_try = []

for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef):
        has_try = False
        for child in ast.walk(node):
            if isinstance(child, ast.Try):
                for handler in child.handlers:
                    if isinstance(handler.type, ast.Name) and handler.type.id == 'Exception':
                        has_try = True
                        break
        
        if has_try:
            funcs_with_try.append(node.name)

print("Functions with try...except Exception:")
for f in funcs_with_try:
    print(f" - {f}")
