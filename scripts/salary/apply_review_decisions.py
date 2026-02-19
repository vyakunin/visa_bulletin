#!/usr/bin/env python3
"""
Apply review decisions from dry run to database.

This script applies the decisions made during the dry run review.
"""

import os

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
import django

django.setup()

from django.db import transaction
from django.utils import timezone

from django_config.logging_config import setup_logging
from lib.business.salary.employer_clustering import match_employers
from lib.utils.logging_utils import ScriptLogger
from models.salary import Employer, EmployerClusteringReview

setup_logging()
import logging

logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


def find_employer_by_name(name: str, city: str = '', state: str = '') -> Employer | None:
    """Find employer in database by name and optionally location."""
    employers = Employer.objects.filter(name=name)
    if city:
        employers = employers.filter(city__iexact=city)
    if state:
        employers = employers.filter(state__iexact=state)

    employer = employers.first()
    if employer:
        return employer

    # Try normalized name match
    normalized = Employer.normalize_name(name)
    employers = Employer.objects.filter(name_normalized=normalized)
    if city:
        employers = employers.filter(city__iexact=city)
    if state:
        employers = employers.filter(state__iexact=state)

    return employers.first()


def create_or_update_review(emp1: Employer, emp2: Employer, should_approve: bool,
                            similarity: float, reason: str, reviewed_by: str = 'manual') -> EmployerClusteringReview:
    """Create or update review entry."""
    if emp1.id > emp2.id:
        emp1, emp2 = emp2, emp1

    review, created = EmployerClusteringReview.objects.get_or_create(
        employer1=emp1,
        employer2=emp2,
        defaults={
            'similarity_score': similarity,
            'match_reason': reason,
            'status': 'approved' if should_approve else 'rejected',
            'reviewed_by': reviewed_by,
            'reviewed_at': timezone.now(),
        }
    )

    if not created:
        review.status = 'approved' if should_approve else 'rejected'
        review.reviewed_by = reviewed_by
        review.reviewed_at = timezone.now()
        review.similarity_score = similarity
        review.match_reason = reason
        review.save()

    return review


# Decisions from dry run (example_number: (emp1_name, emp1_city, emp1_state, emp2_name, emp2_city, emp2_state, decision))
DECISIONS = {
    5: ('PURDUE UNIVERSITY', 'FORT WAYNE', 'INDIANA', 'PURDUE UNIVERSITY', 'WEST LAFAYETTE', 'INDIANA', True),
    9: ('WELLINGTON MANAGEMENT COMPANY LLP', 'BOSTON', 'MASSACHUSETTS', 'WELLINGTON MANAGEMENT COMPANY, LLP', 'BOSTON', 'MA', True),
    14: ('CRA INTERNATIONAL, INC', 'BOSTON', 'MASSACHUSETTS', 'CRA INTERNATIONAL, INC', 'BOSTON', 'MA', True),
    21: ('AVCO CONSULTING INC', 'WORCESTER', 'MASSACHUSETTS', 'AVCO CONSULTING INC', 'WORCESTER', 'MA', True),
    25: ('AKAMAI TECHNOLOGIES, INC.', 'CAMBRIDGE', 'MASSACHUSETTS', 'AKAMAI TECHNOLOGIES, INC.', 'CAMBRIDGE', 'MA', True),
    50: ('PURDUE UNIVERSITY', 'FORT WAYNE', 'INDIANA', 'PURDUE UNIVERSITY', 'WEST LAFAYETTE', 'INDIANA', True),
    54: ('WELLINGTON MANAGEMENT COMPANY LLP', 'BOSTON', 'MASSACHUSETTS', 'WELLINGTON MANAGEMENT COMPANY, LLP', 'BOSTON', 'MA', True),
    59: ('CRA INTERNATIONAL, INC', 'BOSTON', 'MASSACHUSETTS', 'CRA INTERNATIONAL, INC', 'BOSTON', 'MA', True),
    66: ('AVCO CONSULTING INC', 'WORCESTER', 'MASSACHUSETTS', 'AVCO CONSULTING INC', 'WORCESTER', 'MA', True),
    70: ('AKAMAI TECHNOLOGIES, INC.', 'CAMBRIDGE', 'MASSACHUSETTS', 'AKAMAI TECHNOLOGIES, INC.', 'CAMBRIDGE', 'MA', True),
    84: ('UNIVERSITY OF ARKANSAS AT LITTLE ROCK', 'LITTLE ROCK', 'ARKANSAS', 'University of Arkansas at Little Rock', 'Little Rock', 'ARKANSAS', True),
    88: ('UNIVERSITY OF MASSACHUSETTS AMHERST', 'AMHERST', 'MA', 'UNIVERSITY OF MASSACHUSETTS AMHERST', 'AMHERST', 'MASSACHUSETTS', True),
    92: ('NORTHEASTERN UNIVERSITY', 'BOSTON', 'MA', 'NORTHEASTERN UNIVERSITY', 'BOSTON', 'MASSACHUSETTS', True),
    93: ('GRAHAM HOLDINGS COMPANY', 'ARLINGTON', 'VIRGINIA', 'GRAHAM CAPITAL MANAGEMENT, L.P.', 'ROWAYTON', 'CT', False),
    95: ('ASPEN TECHNOLOGY, INC', 'BEDFORD', 'MASSACHUSETTS', 'ASPEN TECHNOLOGY, INC', 'BURLINGTON', 'MA', True),
    96: ('ASPEN TECHNOLOGY, INC', 'BEDFORD', 'MASSACHUSETTS', 'ASPEN CONSULTING, INC.', 'CHESTNUT HILL', 'MA', True),
    97: ('ASPEN TECHNOLOGY, INC', 'BURLINGTON', 'MA', 'ASPEN CONSULTING, INC.', 'CHESTNUT HILL', 'MA', False),
    105: ('AQR CAPITAL MANAGEMENT', 'GREENWICH', 'CONNECTICUT', 'AQR CAPITAL MANAGEMENT', 'GREENWICH', 'CT', True),
    108: ('CORPORATION SERVICE COMPANY', 'WILMINGTON', 'DELAWARE', 'SERVICE MANAGEMENT GROUP, LLC', 'SHELTON', 'CT', False),
    113: ('Bain Capital, LP', 'Boston', 'MASSACHUSETTS', 'BAIN CAPITAL, LLC', 'BOSTON', 'MA', True),
    123: ('TRINITY PARTNERS, LLC', 'WALTHAM', 'MASSACHUSETTS', 'TRINITY TECHNOLOGIES CORPORATION', 'WELLESLEY', 'MA', False),
    127: ('CHILDREN\'S HOSPITAL', 'BOSTON', 'MASSACHUSETTS', 'CHILDREN\'S HOSPITAL', 'NEW ORLEANS', 'LOUISIANA', False),
    128: ('CHILDREN\'S HOSPITAL', 'BOSTON', 'MASSACHUSETTS', 'CHILDREN\'S HOSPITAL', 'BOSTON', 'MA', True),
    129: ('CHILDREN\'S HOSPITAL', 'NEW ORLEANS', 'LOUISIANA', 'CHILDREN\'S HOSPITAL', 'BOSTON', 'MA', False),
    132: ('BROWN UNIVERSITY', 'PROVIDENCE', 'RI', 'BROWN UNIVERSITY', 'PROVIDENCE', 'RHODE ISLAND', True),
    137: ('WEBILENT TECHNOLOGY INC.', 'SOUTH WINDSOR', 'CONNECTICUT', 'WEBILENT TECHNOLOGY INC.', 'WINDSOR', 'CT', True),
    144: ('MAXIMA CONSULTING INC', 'WAKEFIELD', 'MASSACHUSETTS', 'MAXIMA CONSULTING INC', 'WAKEFIELD', 'MA', True),
    154: ('TRUSTEES OF BOSTON UNIVERSITY', 'BOSTON', 'MA', 'TRUSTEES OF BOSTON UNIVERSITY', 'BOSTON', 'MASSACHUSETTS', True),
    159: ('ROCA, INC.', 'CHELSEA', 'MA', 'Roca USA, Inc', 'Miami', 'FLORIDA', False),
    161: ('COLUMBIA COLLEGE', 'COLUMBIA', 'MISSOURI', 'COLUMBIA COLLEGE', 'VIENNA', 'VIRGINIA', True),
    162: ('YALE UNIVERSITY', 'NEW HAVEN', 'CT', 'YALE UNIVERSITY', 'NEW HAVEN', 'CONNECTICUT', True),
    164: ('THE BOSTON CONSULTING GROUP', 'BOSTON', 'MASSACHUSETTS', 'THE BOSTON CONSULTING GROUP', 'BOSTON', 'MA', True),
    186: ('Navajo Technical University', 'Crownpoint', 'NEW MEXICO', 'NAVAJO TECHNICAL UNIVERSITY', 'CROWNPOINT', 'NEW MEXICO', True),
    198: ('UNIVERSITY OF RHODE ISLAND', 'KINGSTON', 'RI', 'UNIVERSITY OF RHODE ISLAND', 'KINGSTON', 'RHODE ISLAND', True),
}


def main():
    script_logger.log_call(
        args={'decisions_count': len(DECISIONS)},
        context='Applying review decisions from dry run'
    )

    logger.info(f"Applying {len(DECISIONS)} review decisions...")

    applied = 0
    not_found = 0
    errors = 0

    for example_num, (emp1_name, emp1_city, emp1_state, emp2_name, emp2_city, emp2_state, should_approve) in DECISIONS.items():
        try:
            emp1 = find_employer_by_name(emp1_name, emp1_city, emp1_state)
            emp2 = find_employer_by_name(emp2_name, emp2_city, emp2_state)

            if not emp1 or not emp2:
                logger.warning(f"Example #{example_num}: Employer not found (emp1: {emp1 is not None}, emp2: {emp2 is not None})")
                not_found += 1
                continue

            # Get similarity and reason from production algorithm
            is_match, confidence, reason = match_employers(emp1, emp2)
            similarity = confidence

            with transaction.atomic():
                review = create_or_update_review(
                    emp1,
                    emp2,
                    should_approve,
                    similarity,
                    reason or "Manual review decision from dry run",
                    reviewed_by='manual-borderline'
                )

            applied += 1
            status = 'APPROVED' if should_approve else 'REJECTED'
            logger.info(f"Example #{example_num}: {status} - {emp1_name} vs {emp2_name}")

        except Exception as e:
            logger.error(f"Error processing example #{example_num}: {e}", exc_info=True)
            errors += 1

    logger.info("\nSummary:")
    logger.info(f"  Applied: {applied}")
    logger.info(f"  Not found: {not_found}")
    logger.info(f"  Errors: {errors}")

    print(f"\n✅ Applied {applied} review decisions to database")


if __name__ == '__main__':
    main()

