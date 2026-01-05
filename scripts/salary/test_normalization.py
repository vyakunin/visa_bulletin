#!/usr/bin/env python3
"""Test normalization improvements"""

import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
import django
django.setup()

from models.salary import Employer

test_cases = [
    ('E-KO Image Inc.', 'EKO Image Inc.'),
    ('HBSS CONNEC CORP', 'HBSS Connect Corp'),
    ('APPLIED TESTESTING  GEOSCIENCES, LLC', 'APPLIED TESTESTING & GEOSCIENCES, LLC'),
    ('Councilor, Buchanan  Mitchell, P.C.', 'Councilor, Buchanan & Mitchell, P.C.'),
    ('SAG Producers Pension Plans', 'SAG Producers Pension Plan'),
]

print("Current normalization behavior:")
print("=" * 80)
for name1, name2 in test_cases:
    norm1 = Employer.normalize_name(name1)
    norm2 = Employer.normalize_name(name2)
    match = '✓ MATCH' if norm1 == norm2 else '✗ DIFFERENT'
    print(f'\n{match}')
    print(f'  "{name1}" → "{norm1}"')
    print(f'  "{name2}" → "{norm2}"')



