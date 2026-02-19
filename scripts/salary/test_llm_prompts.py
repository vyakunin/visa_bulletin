#!/usr/bin/env python3
"""
Test LLM responses with old vs new prompts to compare improvements.

Tests known false positive cases to see if new prompt fixes them.
"""

import asyncio
import os
import sys

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
import django

django.setup()

import logging

from lib.business.salary.clustering_evaluator import EmployerPair
from lib.business.salary.llm_verifier import call_ollama_async
from lib.utils.bazel_runfiles import get_template_file

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test cases: (name1, name2, city1, state1, city2, state2, expected_answer, reason)
TEST_CASES = [
    # True positives that LLM incorrectly rejected (should be YES)
    ("KNOTEL, INC.", "KNOTEL, INC.", "New York", "NY", "New York", "NY", "YES", "Identical strings"),
    ("Technomax LLC", "TECHNOMAX LLC", "San Francisco", "CA", "San Francisco", "CA", "YES", "Case difference only"),
    ("ECOPAX, LLC", "Ecopax Inc", "Boston", "MA", "Boston", "MA", "YES", "Case + suffix variation"),
    ("Edgesoft Corp", "EDGESOFT, INC.", "Seattle", "WA", "Seattle", "WA", "YES", "Case + suffix variation"),
    ("Page Southerland Page, Inc.", "PAGE SOUTHERLAND PAGE, INC.", "Austin", "TX", "Austin", "TX", "YES", "Case difference only"),
    ("A Team Pacific Roofing, Inc.", "A Team Pacific Roofing, Incorporated", "Portland", "OR", "Portland", "OR", "YES", "Inc vs Incorporated"),
    ("Bjork Construction Company, Inc.", "Bjork Construction Company. Inc.", "Denver", "CO", "Denver", "CO", "YES", "Punctuation difference"),
    ("Ascension Medical Group - Northern Wisconsin, Inc.", "Ascension Medical Group – Northern Wisconsin, Inc.", "Milwaukee", "WI", "Milwaukee", "WI", "YES", "Unicode dash difference"),
    ("ULTIMATE CARE INC.", "ULTIMATE CARE, INC", "Miami", "FL", "Miami", "FL", "YES", "Punctuation difference"),
    ("THE GUARDIAN LIFE INSURANCE CO. OF AMERICA", "GUARDIAN LIFE INSURANCE COMPANY OF AMERICA", "New York", "NY", "New York", "NY", "YES", "CO vs COMPANY"),

    # False positives that should be NO (actually different companies)
    ("NCI TECHNOLOGY, INC.", "NCI Group, INC.", "Washington", "DC", "Washington", "DC", "NO", "TECHNOLOGY vs Group"),
    ("Macro Consultants LLC", "MACRO INTERNATIONAL INC", "Chicago", "IL", "Chicago", "IL", "NO", "Consultants vs International"),
    ("SYNAPSE GROUP INC.", "SYNAPSE TECHNOLOGIES LLC.", "Boston", "MA", "Boston", "MA", "NO", "Group vs Technologies"),
    ("ZK Corporation", "ZK Technology, LLC", "San Jose", "CA", "San Jose", "CA", "NO", "Corporation vs Technology"),
]


OLD_PROMPT = """Are these two employer names referring to the same company?

Name 1: {emp1_name}
Location 1: {emp1_city}, {emp1_state}

Name 2: {emp2_name}
Location 2: {emp2_city}, {emp2_state}

Similarity score: {similarity:.3f}

Answer with only "YES" or "NO" followed by a brief explanation.
"""


async def test_prompt(prompt_template: str, test_cases: list, prompt_name: str) -> dict:
    """Test a prompt template against test cases."""
    results = {
        'prompt_name': prompt_name,
        'total': len(test_cases),
        'correct': 0,
        'incorrect': 0,
        'details': []
    }

    for name1, name2, city1, state1, city2, state2, expected, reason in test_cases:
        pair = EmployerPair(
            emp1_name=name1,
            emp1_city=city1,
            emp1_state=state1,
            emp2_name=name2,
            emp2_city=city2,
            emp2_state=state2,
            similarity=1.0
        )

        # Build prompt
        prompt = prompt_template.format(
            emp1_name=name1,
            emp1_city=city1,
            emp1_state=state1,
            emp2_name=name2,
            emp2_city=city2,
            emp2_state=state2,
            similarity=1.0
        )

        # Call LLM
        response_text = await call_ollama_async(prompt)
        if not response_text:
            logger.warning(f"Failed to get LLM response for: {name1} vs {name2}")
            results['details'].append({
                'name1': name1,
                'name2': name2,
                'expected': expected,
                'got': 'FAILED',
                'response': None,
                'correct': False,
                'reason': reason
            })
            results['incorrect'] += 1
            continue

        # Parse response (look for YES/NO at start)
        response_upper = response_text.strip().upper()
        got = None
        if response_upper.startswith('YES'):
            got = 'YES'
        elif response_upper.startswith('NO'):
            got = 'NO'
        else:
            # Try to find YES/NO anywhere in response
            if 'YES' in response_upper[:10] or ' YES' in response_upper[:50]:
                got = 'YES'
            elif 'NO' in response_upper[:10] or ' NO' in response_upper[:50]:
                got = 'NO'

        is_correct = (got == expected)
        if is_correct:
            results['correct'] += 1
        else:
            results['incorrect'] += 1

        results['details'].append({
            'name1': name1,
            'name2': name2,
            'expected': expected,
            'got': got,
            'response': response_text.strip(),
            'correct': is_correct,
            'reason': reason
        })

    return results


async def main():
    """Test both old and new prompts."""
    print("="*80)
    print("LLM PROMPT COMPARISON TEST")
    print("="*80)
    print()

    # Load new prompt
    template_path = get_template_file("llm_prompt_template.txt")
    if not template_path:
        logger.error("Could not find prompt template")
        return 1

    with open(template_path) as f:
        new_prompt = f.read().strip()

    print(f"Testing {len(TEST_CASES)} cases...")
    print()

    # Test old prompt
    print("Testing OLD prompt...")
    old_results = await test_prompt(OLD_PROMPT, TEST_CASES, "OLD")

    # Test new prompt
    print("Testing NEW prompt...")
    new_results = await test_prompt(new_prompt, TEST_CASES, "NEW")

    # Print results
    print("\n" + "="*80)
    print("RESULTS SUMMARY")
    print("="*80)
    print()

    for results in [old_results, new_results]:
        accuracy = (results['correct'] / results['total']) * 100 if results['total'] > 0 else 0
        print(f"{results['prompt_name']} PROMPT:")
        print(f"  Accuracy: {results['correct']}/{results['total']} ({accuracy:.1f}%)")
        print()

    # Print detailed results
    print("="*80)
    print("DETAILED RESULTS")
    print("="*80)
    print()

    for i, test_case in enumerate(TEST_CASES, 1):
        name1, name2, _, _, _, _, expected, reason = test_case
        old_detail = old_results['details'][i-1]
        new_detail = new_results['details'][i-1]

        print(f"\nTest {i}: {reason}")
        print(f"  Names: {name1} vs {name2}")
        print(f"  Expected: {expected}")
        print()
        print("  OLD prompt:")
        print(f"    Got: {old_detail['got']} {'✓' if old_detail['correct'] else '✗'}")
        print(f"    Response: {old_detail['response'][:200] if old_detail['response'] else 'N/A'}")
        print()
        print("  NEW prompt:")
        print(f"    Got: {new_detail['got']} {'✓' if new_detail['correct'] else '✗'}")
        print(f"    Response: {new_detail['response'][:200] if new_detail['response'] else 'N/A'}")
        print("-" * 80)

    # Improvement summary
    improvement = new_results['correct'] - old_results['correct']
    print(f"\nIMPROVEMENT: {improvement} more correct answers with new prompt")

    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
