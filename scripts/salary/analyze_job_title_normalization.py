#!/usr/bin/env python3
"""
Analyze job title normalization quality and extract golden test set.

Usage:
    bazel run //scripts/salary:analyze_job_title_normalization
"""

import os
import random

import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from models.job_title import JobTitle


def find_duplicate_words():
    """Find job titles with duplicate words in normalized form."""
    print("=" * 80)
    print("Job Titles with Duplicate Words in Normalized Form:")
    print("=" * 80)

    duplicates = []
    for jt in JobTitle.objects.all()[:10000]:
        words = jt.title_normalized.split()
        if len(words) != len(set(words)):  # Has duplicates
            duplicates.append(jt)
            print(f"❌ '{jt.title}'")
            print(
                f"   -> '{jt.title_normalized}' ({jt.experience_level or 'no level'})"
            )
            print()
            if len(duplicates) >= 30:
                break

    return duplicates


def extract_golden_set():
    """Extract a diverse golden test set."""
    print("\n" + "=" * 80)
    print("Extracting Golden Test Set (50 examples):")
    print("=" * 80)

    # Get diverse examples
    all_titles = list(JobTitle.objects.all()[:5000])
    random.seed(42)  # Reproducible
    random.shuffle(all_titles)

    golden_set = []
    for jt in all_titles[:50]:
        golden_set.append(
            {
                "original": jt.title,
                "normalized": jt.title_normalized,
                "level": jt.experience_level or "no level",
            }
        )
        print(
            f"'{jt.title}' -> '{jt.title_normalized}' ({jt.experience_level or 'no level'})"
        )

    return golden_set


def main():
    print(f"Total job titles in database: {JobTitle.objects.count():,}")
    print()

    # Find issues
    duplicates = find_duplicate_words()

    # Extract golden set
    golden_set = extract_golden_set()

    print("\n" + "=" * 80)
    print(f"Found {len(duplicates)} titles with duplicate words (showing first 30)")
    print(f"Extracted {len(golden_set)} examples for golden test set")
    print("=" * 80)


if __name__ == "__main__":
    main()
