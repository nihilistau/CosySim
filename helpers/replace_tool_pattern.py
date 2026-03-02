import re
import sys

def replace_pattern(filepath, pattern, replacement):
    with open(filepath, 'r', encoding='utf-8') as f:
        code = f.read()
    
    new_code = re.sub(pattern, replacement, code, flags=re.DOTALL)
    
    if code != new_code:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_code)
        print(f"Successfully replaced pattern in {filepath}")
    else:
        print("Pattern not found or no changes made.")

if __name__ == '__main__':
    # Example usage, meant to be modified per script
    pass
