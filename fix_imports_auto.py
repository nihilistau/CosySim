"""
Automated Import Path Fixer for CosySim
Fixes all import paths after the cleanup/reorganization
"""
import os
import re
from pathlib import Path

def fix_imports_in_file(file_path: Path, root: Path):
    """Fix imports in a single file"""
    try:
        content = file_path.read_text(encoding='utf-8')
        original = content
        
        # Calculate how many levels up to get to root
        relative_path = file_path.relative_to(root)
        levels_up = len(relative_path.parents) - 1
        
        # Fix sys.path additions - make sure we go to project root
        # Pattern: sys.path.append(str(Path(__file__).parent...))
        sys_path_pattern = r'sys\.path\.(append|insert\([^,]+,\s*)str\(Path\(__file__\)\.parent(\.parent)*\)\)'
        
        # Replace with correct path to root
        parent_chain = '.parent' * levels_up if levels_up > 0 else ''
        new_sys_path = f'project_root = Path(__file__){parent_chain}\nsys.path.insert(0, str(project_root))'
        
        # Add import Path if not present
        if 'from pathlib import Path' not in content and 'import Path' not in content:
            if 'import sys' in content:
                content = content.replace('import sys', 'import sys\nfrom pathlib import Path')
        
        # Replace sys.path lines
        if 'sys.path' in content:
            lines = content.split('\n')
            new_lines = []
            sys_path_added = False
            
            for line in lines:
                if 'sys.path' in line and not sys_path_added:
                    new_lines.append(new_sys_path)
                    sys_path_added = True
                elif 'sys.path' not in line:
                    new_lines.append(line)
            
            content = '\n'.join(new_lines)
        
        # Fix import statements
        replacements = [
            # Fix simulation.* imports -> content.simulation.*
            (r'from simulation\.', 'from content.simulation.'),
            (r'import simulation\.', 'import content.simulation.'),
            
            # Fix engine imports (should already be correct, but ensure)
            # (these should work as-is once sys.path is correct)
        ]
        
        for pattern, replacement in replacements:
            content = re.sub(pattern, replacement, content)
        
        # Only write if changed
        if content != original:
            file_path.write_text(content, encoding='utf-8')
            return True
        return False
        
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return False

def main():
    root = Path(r"C:\Files\Models\CosySim")
    
    print("🔧 CosySim Import Path Fixer")
    print("=" * 60)
    print()
    
    # Find all Python files in content/
    files_to_check = list(root.glob("content/**/*.py"))
    files_to_check = [f for f in files_to_check if f.name != "__init__.py"]
    
    print(f"Checking {len(files_to_check)} Python files...")
    print()
    
    fixed_count = 0
    for py_file in files_to_check:
        rel_path = py_file.relative_to(root)
        
        # Check if needs fixing
        content = py_file.read_text(encoding='utf-8')
        needs_fix = ('from simulation.' in content or 
                     'sys.path' in content)
        
        if needs_fix:
            if fix_imports_in_file(py_file, root):
                print(f"✅ Fixed: {rel_path}")
                fixed_count += 1
            else:
                print(f"⚠️  Checked: {rel_path} (no changes needed)")
    
    print()
    print("=" * 60)
    print(f"✨ Complete! Fixed {fixed_count} files")
    print()
    
    # Also create __init__.py files if missing
    print("📦 Ensuring __init__.py files exist...")
    dirs_to_check = [
        root / "content",
        root / "content" / "scenes",
        root / "content" / "simulation",
        root / "content" / "simulation" / "character_system",
        root / "content" / "simulation" / "database",
        root / "content" / "simulation" / "services",
        root / "engine",
        root / "engine" / "assets",
        root / "engine" / "scenes",
    ]
    
    for dir_path in dirs_to_check:
        init_file = dir_path / "__init__.py"
        if not init_file.exists() and dir_path.exists():
            init_file.write_text('"""Package init"""', encoding='utf-8')
            print(f"✅ Created: {init_file.relative_to(root)}")
    
    print()
    print("🎉 All done! You can now launch scenes.")

if __name__ == "__main__":
    main()
