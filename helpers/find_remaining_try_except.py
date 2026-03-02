import ast
import sys

def main(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
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

    print(f"Functions with try...except Exception in {filepath}:")
    for f in funcs_with_try:
        print(f" - {f}")

if __name__ == '__main__':
    filepath = sys.argv[1] if len(sys.argv) > 1 else 'engine/mcp/cosysim_server.py'
    main(filepath)
