"""Ads-off split test on the long-tail pages.

Each indexed employer profile sits in one arm for good, picked by a salted hash of its
slug; `/salaries/` and every query-string facet of it are in the off arm. Thin profiles
and every other page are outside the test (`None`). The pre-registration (dates, metric,
decision rule) lives in the ops repo's `monetization/PIPELINE.md`.
"""

import hashlib
from enum import IntEnum, unique

# Changing the salt reshuffles every page between arms, which ends the test.
_ARM_SALT = "ads-test-2026-10"


@unique
class AdsArm(IntEnum):
    INVALID = 0
    OFF = 1
    ON = 2

    @property
    def slug(self) -> str:
        return self.name.lower()

    @property
    def content_group(self) -> str:
        """GA4 content group the page view carries; the ops-repo readout splits on it."""
        return f"ads-test:{self.slug}"


SALARY_SEARCH_ARM = AdsArm.OFF


def employer_ads_arm(slug: str) -> AdsArm:
    """The arm of `/employer/<slug>/`, stable across requests and deploys."""
    digest = hashlib.sha256(f"{_ARM_SALT}:{slug}".encode()).digest()
    return AdsArm.OFF if digest[0] & 1 else AdsArm.ON
