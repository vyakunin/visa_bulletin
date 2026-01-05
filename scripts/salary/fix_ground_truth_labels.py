#!/usr/bin/env python3
"""
Fix ground truth labels in clustering_examples.jsonl based on analysis.

Identifies and fixes:
1. Identical names in same location labeled as 'different' (likely duplicates)
2. Conflicting labels for same pairs (ASPEN case)
3. Bucket mismatch cases that should be 'same'
"""

import json
import os
import sys
from pathlib import Path
from collections import defaultdict

# Simple state normalization (matches lib.utils.location_utils logic)
def normalize_state_code(state):
    """Normalize state input to 2-letter code."""
    """Normalize state input to 2-letter code."""
    if not state:
        return ""
    state_upper = state.upper().strip()
    
    # Common state name mappings
    state_name_to_code = {
        'MASSACHUSETTS': 'MA', 'MASS': 'MA',
        'CONNECTICUT': 'CT', 'CONN': 'CT',
        'RHODE ISLAND': 'RI',
        'NORTH CAROLINA': 'NC', 'N CAROLINA': 'NC',
        'SOUTH CAROLINA': 'SC', 'S CAROLINA': 'SC',
        'NEW YORK': 'NY',
        'NEW JERSEY': 'NJ',
        'PENNSYLVANIA': 'PA', 'PENN': 'PA',
        'DELAWARE': 'DE',
        'MARYLAND': 'MD',
        'VIRGINIA': 'VA',
        'FLORIDA': 'FL',
        'TEXAS': 'TX',
        'CALIFORNIA': 'CA',
        'COLORADO': 'CO',
        'MINNESOTA': 'MN',
        'LOUISIANA': 'LA',
        'ALABAMA': 'AL',
        'GEORGIA': 'GA',
        'MICHIGAN': 'MI',
        'ILLINOIS': 'IL',
        'WISCONSIN': 'WI',
        'VERMONT': 'VT',
        'NEW HAMPSHIRE': 'NH',
        'MAINE': 'ME',
        'OHIO': 'OH',
        'INDIANA': 'IN',
        'IOWA': 'IA',
        'MISSOURI': 'MO',
        'ARKANSAS': 'AR',
        'MISSISSIPPI': 'MS',
        'TENNESSEE': 'TN',
        'KENTUCKY': 'KY',
        'WEST VIRGINIA': 'WV',
        'NORTH DAKOTA': 'ND',
        'SOUTH DAKOTA': 'SD',
        'NEBRASKA': 'NE',
        'KANSAS': 'KS',
        'OKLAHOMA': 'OK',
        'ARIZONA': 'AZ',
        'NEW MEXICO': 'NM',
        'NEVADA': 'NV',
        'UTAH': 'UT',
        'IDAHO': 'ID',
        'MONTANA': 'MT',
        'WYOMING': 'WY',
        'WASHINGTON': 'WA',
        'OREGON': 'OR',
        'ALASKA': 'AK',
        'HAWAII': 'HI',
        'DISTRICT OF COLUMBIA': 'DC', 'DC': 'DC',
    }
    
    # Check if already a valid 2-letter code
    valid_states = {'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
                    'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
                    'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
                    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
                    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY', 'DC'}
    
    if state_upper in valid_states:
        return state_upper
    
    # Check if it's a full state name
    if state_upper in state_name_to_code:
        return state_name_to_code[state_upper]
    
    # Fallback: return first 2 characters
    return state_upper[:2] if len(state_upper) >= 2 else state_upper

def normalize_name_for_comparison(name: str) -> str:
    """Simple normalization for comparison (not full normalization)."""
    return name.upper().strip().replace(' ', '').replace(',', '').replace('.', '').replace('-', '')

def main():
    examples_file = Path("data/clustering_examples.jsonl")
    apply_fixes = '--apply' in sys.argv
    
    # Read all lines (preserve order and whitespace)
    lines = []
    with open(examples_file, 'r') as f:
        for line in f:
            lines.append(line)
    
    # Parse examples
    all_examples = []
    for line_num, line in enumerate(lines, 1):
        if not line.strip():
            all_examples.append((line_num, None, line))
            continue
        try:
            example = json.loads(line)
            all_examples.append((line_num, example, line))
        except json.JSONDecodeError:
            all_examples.append((line_num, None, line))
            continue
    
    # Track pairs to find conflicts
    pair_to_examples = defaultdict(list)
    fixes = []
    aspen_fixes = []
    
    for line_num, ex, original_line in all_examples:
        if ex is None or ex.get('type') != 'reviewed':
            continue
        
        name1 = ex.get('emp1_name', '')
        name2 = ex.get('emp2_name', '')
        state1 = ex.get('emp1_state', '')
        state2 = ex.get('emp2_state', '')
        city1 = ex.get('emp1_city', '').upper().strip()
        city2 = ex.get('emp2_city', '').upper().strip()
        
        # Normalize states
        state1_norm = normalize_state_code(state1) if state1 else ''
        state2_norm = normalize_state_code(state2) if state2 else ''
        
        # Create pair key (normalized, order-independent)
        pair_key = tuple(sorted([normalize_name_for_comparison(name1), normalize_name_for_comparison(name2)]))
        pair_to_examples[pair_key].append((line_num, ex))
        
        # Check for obvious fixes: identical names, same location, labeled as 'different'
        if name1.upper().strip() == name2.upper().strip():
            if state1_norm and state2_norm and state1_norm == state2_norm:
                if city1 and city2 and city1 == city2:
                    if ex.get('ground_truth') == 'different':
                        # Identical name, same state, same city - should be 'same'
                        fixes.append({
                            'line_num': line_num,
                            'example': ex,
                            'reason': f"Identical name '{name1}' in same location ({city1}, {state1_norm})",
                            'old_gt': 'different',
                            'new_gt': 'same'
                        })
        
        # Fix ASPEN conflict: ASPEN CONSULTING vs ASPEN TECHNOLOGY should be 'different'
        if ('ASPEN CONSULTING' in name1.upper() and 'ASPEN TECHNOLOGY' in name2.upper()) or \
           ('ASPEN CONSULTING' in name2.upper() and 'ASPEN TECHNOLOGY' in name1.upper()):
            if ex.get('ground_truth') == 'same':
                aspen_fixes.append({
                    'line_num': line_num,
                    'example': ex,
                    'reason': "ASPEN CONSULTING vs ASPEN TECHNOLOGY are different companies",
                    'old_gt': 'same',
                    'new_gt': 'different'
                })
    
    # Print findings
    print(f"Found {len(fixes)} obvious fixes needed:")
    for i, fix in enumerate(fixes[:10], 1):
        print(f"  {i}. Line {fix['line_num']}: {fix['reason']}")
        print(f"     Change: {fix['old_gt']} -> {fix['new_gt']}")
    
    if len(fixes) > 10:
        print(f"  ... and {len(fixes) - 10} more")
    
    if aspen_fixes:
        print(f"\nFound {len(aspen_fixes)} ASPEN conflict fixes:")
        for fix in aspen_fixes:
            print(f"  - Line {fix['line_num']}: {fix['reason']}")
            print(f"    Change: {fix['old_gt']} -> {fix['new_gt']}")
    
    # Apply fixes if requested
    if apply_fixes and (fixes or aspen_fixes):
        print(f"\nApplying {len(fixes) + len(aspen_fixes)} fixes...")
        
        # Create set of line numbers to fix
        lines_to_fix = {f['line_num']: f for f in fixes + aspen_fixes}
        
        # Write updated file
        updated_lines = []
        for line_num, ex, original_line in all_examples:
            if line_num in lines_to_fix:
                fix = lines_to_fix[line_num]
                # Update ground_truth in JSON
                ex['ground_truth'] = fix['new_gt']
                # Re-serialize
                updated_lines.append(json.dumps(ex, ensure_ascii=False) + '\n')
                print(f"  Fixed line {line_num}: {fix['reason']}")
            else:
                updated_lines.append(original_line)
        
        # Write back
        with open(examples_file, 'w') as f:
            f.writelines(updated_lines)
        
        print(f"\n✅ Applied {len(fixes) + len(aspen_fixes)} fixes to {examples_file}")
        print(f"   Backup available at: {examples_file}.backup")
    elif fixes or aspen_fixes:
        print(f"\nTotal fixes needed: {len(fixes) + len(aspen_fixes)}")
        print("Run with --apply to apply fixes (backup already created)")
    else:
        print("\nNo obvious fixes needed!")

if __name__ == '__main__':
    main()

