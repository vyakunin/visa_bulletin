"""Tests for the I-129 employer_name → EmployerCluster linker.

Locks: normalized (not exact) matching resolves USCIS spellings to the LCA cluster;
the highest-LCA-volume cluster wins when a normalized name spans clusters; unmatched
names stay NULL and aren't counted; the backfill populates employer_cluster_id and
LinkStats reports the right match rates.
"""

from decimal import Decimal

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from lib.business.i129.employer_linker import (
    link_i129_employers,
    link_uscis_employers,
    resolve_clusters_for_names,
)
from models.i129 import I129Petition
from models.salary import Employer, EmployerCluster
from models.uscis_employer import UscisEmployerApproval


def _cluster(name, slug):
    return EmployerCluster.objects.create(canonical_name=name, slug=slug)


def _employer(name, cluster, lca, state=""):
    """Create an Employer normalized the same way production stores it."""
    return Employer.objects.create(
        name=name,
        name_normalized=Employer.normalize_name(name),
        canonical_cluster=cluster,
        total_lca_count=lca,
        state=state,
    )


def _petition(case, employer_name):
    return I129Petition.objects.create(
        dol_eta_case_number=case,
        fiscal_year=2024,
        employer_name=employer_name,
        pay_annual=Decimal("100000"),
    )


class TestEmployerLinker(TestCase):
    def test_normalized_match_where_exact_fails(self):
        # LCA spelling differs from USCIS spelling but normalizes to the same form.
        cluster = _cluster("Infosys", "infosys")
        _employer("INFOSYS TECHNOLOGIES LIMITED", cluster, lca=5000)
        # Sanity: the two spellings are NOT exact-equal but ARE normalized-equal.
        assert "INFOSYS TECHNOLOGIES LIMITED" != "Infosys Limited"
        assert Employer.normalize_name("INFOSYS TECHNOLOGIES LIMITED") == (
            Employer.normalize_name("Infosys Limited")
        )

        resolved = resolve_clusters_for_names(["Infosys Limited"])
        assert resolved == {"Infosys Limited": cluster.id}

    def test_highest_lca_volume_cluster_wins_tie(self):
        # Same normalized name split across two clusters; the higher-volume one wins.
        big = _cluster("Cognizant Big", "cognizant-big")
        small = _cluster("Cognizant Small", "cognizant-small")
        norm = Employer.normalize_name("Cognizant Technology Solutions")
        _employer("Cognizant Technology Solutions", big, lca=9000, state="CA")
        # A lower-volume namesake sharing the identical normalized key (distinct
        # state to satisfy the (name_normalized, city, state) unique constraint).
        Employer.objects.create(
            name="Cognizant (namesake)",
            name_normalized=norm,
            canonical_cluster=small,
            total_lca_count=10,
            state="TX",
        )

        resolved = resolve_clusters_for_names(["Cognizant Technology Solutions"])
        assert resolved == {"Cognizant Technology Solutions": big.id}

    def test_unmatched_name_absent(self):
        _employer("Google LLC", _cluster("Google", "google"), lca=4000)
        resolved = resolve_clusters_for_names(
            ["Google LLC", "Totally Unknown Startup XYZ Inc"]
        )
        assert list(resolved.keys()) == ["Google LLC"]

    def test_backfill_populates_fk_and_stats(self):
        gcluster = _cluster("Google", "google")
        _employer("Google LLC", gcluster, lca=4000)
        # 3 matched petitions (Google) + 2 unmatched (no LCA cluster).
        _petition("C1", "Google LLC")
        _petition("C2", "Google LLC")
        _petition("C3", "Google LLC")
        _petition("C4", "Nonexistent Co")
        _petition("C5", "Nonexistent Co")

        stats = link_i129_employers(dry_run=False)
        assert stats.distinct_names == 2
        assert stats.matched_names == 1
        assert stats.matched_rows == 3
        assert stats.total_rows == 5

        linked = I129Petition.objects.filter(employer_cluster=gcluster)
        assert set(linked.values_list("dol_eta_case_number", flat=True)) == {
            "C1",
            "C2",
            "C3",
        }
        assert (
            I129Petition.objects.filter(
                employer_name="Nonexistent Co", employer_cluster__isnull=True
            ).count()
            == 2
        )

    def test_dry_run_does_not_write(self):
        gcluster = _cluster("Google", "google")
        _employer("Google LLC", gcluster, lca=4000)
        _petition("D1", "Google LLC")

        stats = link_i129_employers(dry_run=True)
        assert stats.matched_rows == 1
        assert I129Petition.objects.filter(employer_cluster__isnull=False).count() == 0

    def test_uscis_linker_backfills_same_way(self):
        gcluster = _cluster("Google", "google")
        _employer("Google LLC", gcluster, lca=4000)
        UscisEmployerApproval.objects.create(
            fiscal_year=2024, employer_name="Google LLC", initial_approval=10
        )
        UscisEmployerApproval.objects.create(
            fiscal_year=2024, employer_name="Nonexistent Co", initial_approval=1
        )

        stats = link_uscis_employers(dry_run=False)
        assert stats.matched_names == 1
        assert stats.matched_rows == 1
        assert (
            UscisEmployerApproval.objects.filter(employer_cluster=gcluster).count() == 1
        )
        assert (
            UscisEmployerApproval.objects.filter(
                employer_name="Nonexistent Co", employer_cluster__isnull=True
            ).count()
            == 1
        )
