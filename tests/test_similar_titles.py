"""Tests for token-overlap similar-title ranking and the thin-page rescue.

Regression covered (2026-07-04): the old first-word icontains heuristic
recommended Senior Software Engineer / Senior Programmer Analyst as "similar"
to "Senior Vice President, Legal & Compliance" — any big "Senior *" cluster
matched any "Senior ..." title. Content-token overlap must never rank a
qualifier-only match, and the broader-role CTA must resolve a hyper-specific
requisition title to its base role.
"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from lib.business.salary.job_title_stats import INDEXABLE_MIN_FILINGS
from lib.business.salary.similar_titles import (
    _UNIVERSE_CACHE_KEY,
    content_tokens,
    find_broader_role,
    rank_similar,
    salaries_search_token,
)
from models.job_title import JobTitleCluster

_DUMMY_CACHE = {
    "default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}
}


class TestContentTokens(TestCase):
    def test_strips_seniority_and_requisition_junk(self):
        self.assertEqual(
            content_tokens("Senior Software Engineer II"),
            frozenset({"software", "engineer"}),
        )
        # numeric requisition ids drop out entirely (letters-only tokens)
        self.assertEqual(
            content_tokens("Software Engineer 161559609"),
            frozenset({"software", "engineer"}),
        )

    def test_qualifier_only_title_has_no_content(self):
        self.assertEqual(content_tokens("Senior Lead II"), frozenset())


@override_settings(CACHES=_DUMMY_CACHE)
class TestRankAndBroaderRole(TestCase):
    def setUp(self):
        cache.delete(_UNIVERSE_CACHE_KEY)
        big = INDEXABLE_MIN_FILINGS
        self._mk("software-engineer", "Software Engineer", big * 100)
        self._mk("senior-software-engineer", "Senior Software Engineer", big * 30)
        self._mk("compliance-officer", "Compliance Officer", big * 2)
        self._mk("vice-president", "Vice President", big * 3)
        # indexable "Senior *" cluster that must NOT match on "senior" alone
        self._mk("senior-accountant", "Senior Accountant", big * 50)

    def _mk(self, slug, title, filings):
        return JobTitleCluster.objects.create(
            slug=slug, canonical_title=title, total_filings=filings
        )

    def test_no_qualifier_only_matches(self):
        """The old first-word bug: 'Senior X' must not surface every big
        'Senior *' cluster."""
        similar = rank_similar(
            "Senior Vice President, Legal & Compliance", own_slug=None
        )
        slugs = [s.slug for s in similar]
        self.assertNotIn("senior-accountant", slugs)
        self.assertNotIn("senior-software-engineer", slugs)
        self.assertIn("vice-president", slugs)
        self.assertIn("compliance-officer", slugs)

    def test_more_shared_tokens_rank_first(self):
        similar = rank_similar("Software Engineer Kbgfjg353961", own_slug=None)
        # both SWE clusters share 2 tokens and beat any 1-token match;
        # bigger cluster first on the tie
        self.assertEqual(
            [s.slug for s in similar[:2]],
            ["software-engineer", "senior-software-engineer"],
        )

    def test_broader_role_is_token_subset(self):
        broader = find_broader_role(
            "Software Engineer Kbgfjg353961", own_slug=None
        )
        self.assertIsNotNone(broader)
        self.assertEqual(broader.slug, "software-engineer")

    def test_broader_role_excludes_self_and_non_subsets(self):
        self.assertIsNone(
            find_broader_role("Software Engineer", own_slug="software-engineer")
        )
        # no indexable subset exists for an unrelated title
        self.assertIsNone(find_broader_role("Marine Biologist", own_slug=None))

    def test_salaries_search_token_prefers_distinctive(self):
        self.assertEqual(
            salaries_search_token("Senior Compliance Analyst II"), "compliance"
        )


@override_settings(CACHES=_DUMMY_CACHE)
class TestThinPageBanner(TestCase):
    def setUp(self):
        cache.delete(_UNIVERSE_CACHE_KEY)
        JobTitleCluster.objects.create(
            slug="software-engineer",
            canonical_title="Software Engineer",
            total_filings=INDEXABLE_MIN_FILINGS * 100,
        )
        JobTitleCluster.objects.create(
            slug="software-engineer-kbgfjg",
            canonical_title="Software Engineer Kbgfjg353961",
            total_filings=2,
        )

    def test_thin_page_renders_broader_role_cta(self):
        html = Client().get("/job-title/software-engineer-kbgfjg/").content.decode()
        self.assertIn("broader-role-cta", html)
        self.assertIn("/job-title/software-engineer/", html)

    def test_indexable_page_has_no_cta(self):
        html = Client().get("/job-title/software-engineer/").content.decode()
        self.assertNotIn("broader-role-cta", html)
