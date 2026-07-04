"""Tests for the scoped slug refresh in populate_job_title_slugs.

Regression covered (2026-07-04, post 06-25 PERM re-cluster): 513/1265 indexable
job-title clusters carried stale slugs (slug != slugify(canonical_title)) — e.g.
the 117k-filing Software Engineer cluster on 'software-engineer-161559609' while
'software-engineer' sat unclaimed. The refresh must reclaim free derived slugs
for the indexable set without renaming INTO a counter-suffixed slug and without
churning noindexed thin pages.
"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from models.job_title import JobTitleCluster
from scripts.salary.populate_job_title_slugs import _find_stale_slugs, _refresh_stale_slugs


class TestScopedSlugRefresh(TestCase):
    def _mk(self, slug: str, title: str, filings: int) -> JobTitleCluster:
        return JobTitleCluster.objects.create(
            slug=slug, canonical_title=title, total_filings=filings
        )

    def test_reclaims_free_derived_slug_biggest_first(self):
        big = self._mk("software-engineer-161559609", "Software Engineer", 117845)
        small = self._mk("software-engineer-9", "Software Engineer", 120)

        _refresh_stale_slugs(dry_run=False, min_filings=100, skip_collisions=True)

        big.refresh_from_db()
        small.refresh_from_db()
        self.assertEqual(big.slug, "software-engineer")
        # smaller twin collides with the freshly-claimed clean slug -> keeps its own
        self.assertEqual(small.slug, "software-engineer-9")

    def test_collision_keeps_current_slug_instead_of_counter_suffix(self):
        self._mk("technical-lead", "Technical Lead", 3511)
        stale = self._mk("senior-technical-lead", "Technical Lead", 4626)

        _refresh_stale_slugs(dry_run=False, min_filings=100, skip_collisions=True)

        stale.refresh_from_db()
        # renaming to 'technical-lead-1' would be a downgrade -> untouched
        self.assertEqual(stale.slug, "senior-technical-lead")

    def test_min_filings_scopes_out_thin_pages(self):
        thin = self._mk("dairy-trader-kbgfjg353961-1", "Dairy Trader", 3)

        _refresh_stale_slugs(dry_run=False, min_filings=100, skip_collisions=True)

        thin.refresh_from_db()
        self.assertEqual(thin.slug, "dairy-trader-kbgfjg353961-1")
        self.assertEqual(_find_stale_slugs(min_filings=100), [])

    def test_second_pass_claims_slug_freed_by_first_pass(self):
        # 'market-analyst' is held by a STALE cluster (derives 'data-analyst');
        # once pass 1 renames it away, the smaller stale cluster deriving
        # 'market-analyst' claims it on pass 2.
        holder = self._mk("market-analyst", "Data Analyst", 9000)
        claimant = self._mk("market-analyst-77", "Market Analyst", 500)

        _refresh_stale_slugs(dry_run=False, min_filings=100, skip_collisions=True)

        holder.refresh_from_db()
        claimant.refresh_from_db()
        self.assertEqual(holder.slug, "data-analyst")
        self.assertEqual(claimant.slug, "market-analyst")
