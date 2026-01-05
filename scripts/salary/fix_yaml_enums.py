#!/usr/bin/env python3
"""Fix YAML file by replacing Python enum objects with integer values."""
import sys
import re
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.utils.http_utils import get_workspace_dir

def fix_yaml_enums(filepath: Path):
    """Replace Python enum objects in YAML with integer values."""
    print(f"Reading {filepath}...")
    with open(filepath, 'r') as f:
        lines = f.readlines()
    
    # Process line by line to handle enum objects
    fixed_lines = []
    i = 0
    replacements = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Check if this line has a Python enum object
        if '!!python/object/apply' in line:
            # Extract field name and indentation
            match = re.match(r'(\s+)(\w+):\s+!!python/object/apply:', line)
            if match:
                indent = match.group(1)
                field = match.group(2)
                
                # Next line should be "- value" (can be integer or string)
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    # Match integer: "- 1" or string: "- year" or "- 'year'"
                    value_match = re.match(r'(\s+)-\s+([^\n]+)', next_line)
                    if value_match:
                        value = value_match.group(2).strip()
                        # Remove quotes if present
                        if value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]
                        elif value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        # Replace with simple format
                        fixed_lines.append(f"{indent}{field}: {value}\n")
                        i += 2  # Skip both lines
                        replacements += 1
                        continue
        
        fixed_lines.append(line)
        i += 1
    
    fixed_content = ''.join(fixed_lines)
    
    # Count remaining
    remaining = len(re.findall(r'!!python/object/apply', fixed_content))
    
    print(f"Made {replacements} replacements")
    print(f"Remaining Python objects: {remaining}")
    
    # Always write the fixed content (even if some remain)
    if replacements > 0:
        print(f"Writing fixed content to {filepath}...")
        with open(filepath, 'w') as f:
            f.write(fixed_content)
    
    if remaining == 0:
        print("✅ Fixed!")
        return True
    else:
        # Try one more iteration on the fixed content
        print(f"Trying one more iteration to fix remaining {remaining} objects...")
        return fix_yaml_enums(filepath) if replacements > 0 else False

if __name__ == '__main__':
    workspace = get_workspace_dir()
    test_data_file = workspace / 'tests' / 'data' / 'dol_golden_test_data.yaml'
    
    if fix_yaml_enums(test_data_file):
        print("\n✅ YAML file fixed! You can now re-run auto-annotation.")
    else:
        print("\n❌ Failed to fix all enum objects")
        sys.exit(1)
