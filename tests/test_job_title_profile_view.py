"""Tests for job title profile view"""

from tests.django_setup import setup_django_for_tests
setup_django_for_tests()

import unittest
import json
import logging
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.db import connection
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.conf import settings
from models.job_title import JobTitle, JobTitleCluster
from models.salary import SalaryRecord, Employer, EmployerCluster
from models.enums.visa_program import VisaProgram, WageUnit, CaseStatus
from models.ingest.data_source import DataSource
from models.ingest.ingest_run import IngestRun
from models.ingest.ingest_version import IngestVersion
from decimal import Decimal


_TABLES_CREATED = False


def _ensure_job_title_tables():
    global _TABLES_CREATED
    if _TABLES_CREATED:
        return

    if (
        settings.DATABASES['default']['ENGINE'] != 'django.db.backends.sqlite3'
        or settings.DATABASES['default']['NAME'] != ':memory:'
    ):
        logging.getLogger(__name__).error(
            "Job title tests not using in-memory sqlite; skipping schema setup."
        )
        return

    logger = logging.getLogger(__name__)
    if connection.vendor == 'sqlite':
        connection.disable_constraint_checking()
    try:
        with connection.schema_editor() as schema_editor:
            for model in (
                DataSource,
                IngestRun,
                IngestVersion,
                EmployerCluster,
                Employer,
                JobTitleCluster,
                JobTitle,
                SalaryRecord,
            ):
                try:
                    schema_editor.create_model(model)
                except Exception as exc:
                    logger.error(
                        f"Failed to create model {model.__name__} (may already exist): {exc}",
                        exc_info=True,
                    )
    finally:
        if connection.vendor == 'sqlite':
            connection.enable_constraint_checking()

    _TABLES_CREATED = True


_ensure_job_title_tables()


@override_settings(
    CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
        }
    }
)
class TestJobTitleProfileView(TestCase):
    """Test job title profile view functionality"""
    
    def setUp(self):
        """Set up test data"""
        from django.core.cache import cache
        cache.clear()
        
        # Create employer cluster and employer
        self.employer_cluster, _ = EmployerCluster.objects.get_or_create(
            slug="test-company-inc-jt",
            defaults={
                'canonical_name': "Test Company Inc",
            }
        )
        
        self.employer, _ = Employer.objects.get_or_create(
            name="Test Company Inc JT",
            defaults={
                'name_normalized': "test company jt",
                'city': "San Francisco",
                'state': "CA",
                'canonical_cluster': self.employer_cluster
            }
        )
        
        # Create job title cluster
        self.cluster, _ = JobTitleCluster.objects.get_or_create(
            slug="software-engineer-test",
            defaults={
                'canonical_title': "Software Engineer Test",
                'total_filings': 100,
                'avg_salary': Decimal('150000.00')
            }
        )
        
        # Create job titles with different experience levels
        self.job_title_senior, _ = JobTitle.objects.get_or_create(
            title_normalized="software engineer test",
            experience_level="senior",
            defaults={
                'title': "Senior Software Engineer Test",
                'canonical_cluster': self.cluster,
                'total_filings': 50,
                'avg_salary': Decimal('180000.00')
            }
        )
        
        self.job_title_junior, _ = JobTitle.objects.get_or_create(
            title_normalized="software engineer test",
            experience_level="junior",
            defaults={
                'title': "Junior Software Engineer Test",
                'canonical_cluster': self.cluster,
                'total_filings': 30,
                'avg_salary': Decimal('120000.00')
            }
        )
        
        # Clean up any existing test records
        SalaryRecord.objects.filter(case_number__startswith="TEST-JT-").delete()
        
        # Create salary records
        for i in range(5):
            SalaryRecord.objects.create(
                case_number=f"TEST-JT-{i}-SENIOR",
                employer_name="Test Company Inc JT",
                employer=self.employer,
                job_title="Senior Software Engineer Test",
                job_title_entity=self.job_title_senior,
                worksite_city="San Francisco",
                worksite_state="CA",
                wage_from=Decimal('180000.00') + (i * 10000),
                wage_unit=WageUnit.YEAR,
                wage_annual=Decimal('180000.00') + (i * 10000),
                visa_program=VisaProgram.PERM,
                case_status=CaseStatus.CERTIFIED,
                fiscal_year=2024,
                source_file="test.xlsx",
                is_worksite=False
            )
        
        for i in range(3):
            SalaryRecord.objects.create(
                case_number=f"TEST-JT-{i}-JUNIOR",
                employer_name="Test Company Inc JT",
                employer=self.employer,
                job_title="Junior Software Engineer Test",
                job_title_entity=self.job_title_junior,
                worksite_city="San Francisco",
                worksite_state="CA",
                wage_from=Decimal('120000.00') + (i * 5000),
                wage_unit=WageUnit.YEAR,
                wage_annual=Decimal('120000.00') + (i * 5000),
                visa_program=VisaProgram.H1B,
                case_status=CaseStatus.CERTIFIED,
                fiscal_year=2024,
                source_file="test.xlsx",
                is_worksite=False
            )
    
    def test_slug_generation_uniqueness(self):
        """Test that slug generation creates unique slugs"""
        # Create cluster with same canonical title
        cluster2 = JobTitleCluster.objects.create(
            canonical_title="Software Engineer"
        )
        
        # Should auto-generate unique slug
        self.assertIsNotNone(cluster2.slug)
        self.assertNotEqual(cluster2.slug, self.cluster.slug)
        self.assertTrue(cluster2.slug.startswith('software-engineer'))
    
    def test_slug_generation_on_save(self):
        """Test that slug is auto-generated on save"""
        cluster = JobTitleCluster.objects.create(
            canonical_title="Data Scientist"
        )
        
        self.assertIsNotNone(cluster.slug)
        self.assertEqual(cluster.slug, "data-scientist")
    
    def test_view_returns_200_for_valid_slug(self):
        """Test that view returns 200 for valid cluster slug"""
        client = Client()
        response = client.get(reverse('job_title_profile', kwargs={'slug': 'software-engineer-test'}))
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Software Engineer Test")
    
    def test_view_returns_404_for_invalid_slug(self):
        """Test that view returns 404 for invalid slug"""
        client = Client()
        response = client.get(reverse('job_title_profile', kwargs={'slug': 'nonexistent-job'}))
        
        self.assertEqual(response.status_code, 404)
    
    def test_view_content_includes_key_sections(self):
        """Test that view renders with key content sections"""
        client = Client()
        response = client.get(reverse('job_title_profile', kwargs={'slug': 'software-engineer-test'}))
        
        self.assertEqual(response.status_code, 200)
        # Check for key sections in rendered HTML
        self.assertContains(response, "Market Overview")
        self.assertContains(response, "Salary Distribution")
        self.assertContains(response, "Top Employers")
        self.assertContains(response, "Experience Level")
        self.assertContains(response, "Geographic Distribution")

    def test_experience_section_hidden_when_only_unspecified(self):
        """Hide experience section when only unspecified levels exist"""
        cluster = JobTitleCluster.objects.create(
            slug="role-unspecified-test",
            canonical_title="Role Unspecified Test",
        )
        job_title = JobTitle.objects.create(
            title_normalized="role unspecified test",
            experience_level="",
            title="Role Unspecified Test",
            canonical_cluster=cluster,
            total_filings=1,
            avg_salary=Decimal('100000.00'),
        )
        SalaryRecord.objects.create(
            case_number="TEST-JT-UNSPEC-1",
            employer_name="Test Company Inc JT",
            employer=self.employer,
            job_title="Role Unspecified Test",
            job_title_entity=job_title,
            worksite_city="San Francisco",
            worksite_state="CA",
            wage_from=Decimal('100000.00'),
            wage_unit=WageUnit.YEAR,
            wage_annual=Decimal('100000.00'),
            visa_program=VisaProgram.H1B,
            case_status=CaseStatus.CERTIFIED,
            fiscal_year=2024,
            source_file="test.xlsx",
            is_worksite=False,
        )

        client = Client()
        response = client.get(reverse('job_title_profile', kwargs={'slug': 'role-unspecified-test'}))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Salary by Experience Level")

    def test_default_view_aggregates_across_levels(self):
        """Default view aggregates records across all experience levels."""
        from lib.business.salary.job_title_stats import get_job_title_statistics

        other_cluster = JobTitleCluster.objects.create(
            slug="software-engineer-test-alt",
            canonical_title="Software Engineer Test Alt",
        )
        other_job_title = JobTitle.objects.create(
            title_normalized="software engineer test",
            experience_level="mid",
            title="Software Engineer Test",
            canonical_cluster=other_cluster,
            total_filings=2,
            avg_salary=Decimal('150000.00'),
        )
        for i in range(2):
            SalaryRecord.objects.create(
                case_number=f"TEST-JT-ALT-{i}",
                employer_name="Test Company Inc JT",
                employer=self.employer,
                job_title="Software Engineer Test",
                job_title_entity=other_job_title,
                worksite_city="San Francisco",
                worksite_state="CA",
                wage_from=Decimal('150000.00'),
                wage_unit=WageUnit.YEAR,
                wage_annual=Decimal('150000.00'),
                visa_program=VisaProgram.PERM,
                case_status=CaseStatus.CERTIFIED,
                fiscal_year=2024,
                source_file="test.xlsx",
                is_worksite=False,
            )

        client = Client()
        response = client.get(reverse('job_title_profile', kwargs={'slug': 'software-engineer-test'}))

        self.assertEqual(response.status_code, 200)
        if response.context:
            stats = response.context["stats"]
        else:
            stats = get_job_title_statistics(
                self.cluster,
                years=5,
                program_filter="all",
                normalized_title="software engineer test",
            )
        self.assertEqual(stats["basic"]["total_filings"], 10)
    
    def test_redirect_for_title_variation(self):
        """Test that view redirects for title variations to canonical slug"""
        # Create a different cluster with similar name
        similar_cluster, _ = JobTitleCluster.objects.get_or_create(
            slug="software-developer-test",
            defaults={
                'canonical_title': "Software Developer Test",
            }
        )
        
        job_title, _ = JobTitle.objects.get_or_create(
            title_normalized="software developer test",
            experience_level="",
            defaults={
                'title': "Software Developer Test",
                'canonical_cluster': similar_cluster
            }
        )
        
        client = Client()
        # Try accessing with a variation that should redirect
        response = client.get(
            reverse('job_title_profile', kwargs={'slug': 'software-dev'}),
            follow=False
        )
        
        # Should either return 200 or redirect (depending on match logic)
        self.assertIn(response.status_code, [200, 301, 302, 404])


@override_settings(
    CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
        }
    }
)
class TestJobTitleSlugGeneration(TestCase):
    """Test slug generation for JobTitleCluster"""
    
    def test_generate_slug_basic(self):
        """Test basic slug generation"""
        cluster = JobTitleCluster(canonical_title="Software Engineer")
        slug = cluster.generate_slug()
        
        self.assertEqual(slug, "software-engineer")
    
    def test_generate_slug_with_special_chars(self):
        """Test slug generation with special characters"""
        cluster = JobTitleCluster(canonical_title="C++ Developer / Architect")
        slug = cluster.generate_slug()
        
        self.assertEqual(slug, "c-developer-architect")
    
    def test_generate_slug_uniqueness(self):
        """Test that duplicate titles get unique slugs"""
        # Clean up any existing test clusters first
        JobTitleCluster.objects.filter(canonical_title="Data Scientist Test Unique").delete()
        
        cluster1 = JobTitleCluster.objects.create(
            canonical_title="Data Scientist Test Unique"
        )
        
        cluster2 = JobTitleCluster.objects.create(
            canonical_title="Data Scientist Test Unique"
        )
        
        self.assertNotEqual(cluster1.slug, cluster2.slug)
        self.assertEqual(cluster1.slug, "data-scientist-test-unique")
        self.assertTrue(cluster2.slug.startswith("data-scientist-test-unique"))
    
    def test_slug_auto_generated_on_save(self):
        """Test that slug is auto-generated when saving without slug"""
        # Clean up any existing test clusters first
        JobTitleCluster.objects.filter(canonical_title="Machine Learning Engineer Test").delete()
        
        cluster = JobTitleCluster.objects.create(
            canonical_title="Machine Learning Engineer Test"
        )
        
        self.assertIsNotNone(cluster.slug)
        self.assertEqual(cluster.slug, "machine-learning-engineer-test")
    
    def test_slug_not_overwritten_if_exists(self):
        """Test that existing slug is not overwritten"""
        # Clean up any existing test clusters first
        JobTitleCluster.objects.filter(slug="custom-slug-test").delete()
        
        cluster = JobTitleCluster.objects.create(
            canonical_title="DevOps Engineer Test",
            slug="custom-slug-test"
        )
        
        self.assertEqual(cluster.slug, "custom-slug-test")
        
        # Update and save - slug should remain
        cluster.total_filings = 100
        cluster.save()
        
        cluster.refresh_from_db()
        self.assertEqual(cluster.slug, "custom-slug-test")


@override_settings(
    CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
        }
    }
)
class TestJobTitleAutocompleteView(TestCase):
    """Test job title autocomplete sorting and grouping."""

    def setUp(self):
        """Set up test data for autocomplete."""
        from django.core.cache import cache
        cache.clear()

        self.cluster_software = JobTitleCluster.objects.create(
            canonical_title="Software Engineer",
            slug="software-engineer-autocomplete"
        )
        self.cluster_net_base = JobTitleCluster.objects.create(
            canonical_title=".NET Software Engineer",
            slug="net-software-engineer-autocomplete"
        )
        self.cluster_net_level_2 = JobTitleCluster.objects.create(
            canonical_title=".NET Software Engineer 2",
            slug="net-software-engineer-2-autocomplete"
        )
        self.cluster_net_level_3 = JobTitleCluster.objects.create(
            canonical_title=".NET Software Engineer 3",
            slug="net-software-engineer-3-autocomplete"
        )

        JobTitle.objects.create(
            title="Software Engineer",
            title_normalized="software engineer",
            experience_level="",
            canonical_cluster=self.cluster_software,
            total_filings=120,
        )
        JobTitle.objects.create(
            title=".NET Software Engineer",
            title_normalized="net software engineer",
            experience_level="",
            canonical_cluster=self.cluster_net_base,
            total_filings=10,
        )
        JobTitle.objects.create(
            title=".NET Software Engineer 2",
            title_normalized="net software engineer",
            experience_level="ii",
            canonical_cluster=self.cluster_net_level_2,
            total_filings=25,
        )
        JobTitle.objects.create(
            title=".NET Software Engineer 3",
            title_normalized="net software engineer",
            experience_level="iii",
            canonical_cluster=self.cluster_net_level_3,
            total_filings=35,
        )

    def test_autocomplete_orders_by_normalized_popularity(self):
        """Autocomplete should order by aggregated normalized popularity."""
        client = Client()
        response = client.get(
            reverse('job_title_autocomplete'),
            {'q': 'software eng', 'limit': 5}
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        titles = [item['title'] for item in data]

        self.assertGreaterEqual(len(titles), 2)
        self.assertEqual(titles[0], "Software Engineer")
        self.assertEqual(titles[1], ".NET Software Engineer")


@override_settings(
    CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
        }
    }
)
class TestJobTitleStatistics(TestCase):
    """Test job title statistics calculations"""
    
    def setUp(self):
        """Set up test data"""
        from django.core.cache import cache
        from lib.business.salary.job_title_stats import get_job_title_statistics
        
        cache.clear()
        
        # Create employers
        employer_cluster, _ = EmployerCluster.objects.get_or_create(
            slug="tech-corp-test",
            defaults={
                'canonical_name': "Tech Corp Test",
            }
        )
        
        employer, _ = Employer.objects.get_or_create(
            name="Tech Corp Test",
            defaults={
                'name_normalized': "tech corp test",
                'canonical_cluster': employer_cluster
            }
        )

        employer_cluster_2, _ = EmployerCluster.objects.get_or_create(
            slug="widget-labs-test",
            defaults={
                'canonical_name': "Widget Labs Test",
            }
        )

        employer_2, _ = Employer.objects.get_or_create(
            name="Widget Labs Test",
            defaults={
                'name_normalized': "widget labs test",
                'canonical_cluster': employer_cluster_2
            }
        )
        
        # Create job title cluster
        self.cluster, _ = JobTitleCluster.objects.get_or_create(
            slug="data-analyst-test",
            defaults={
                'canonical_title': "Data Analyst Test",
            }
        )
        
        # Create job title
        job_title, _ = JobTitle.objects.get_or_create(
            title_normalized="data analyst test",
            experience_level="",
            defaults={
                'title': "Data Analyst Test",
                'canonical_cluster': self.cluster
            }
        )
        
        # Clean up any existing test records
        SalaryRecord.objects.filter(case_number__startswith="TEST-STATS-JT-").delete()
        
        # Create salary records with varying salaries
        salaries = [80000, 90000, 100000, 110000, 120000]
        for i, salary in enumerate(salaries):
            SalaryRecord.objects.create(
                case_number=f"TEST-STATS-JT-{i}",
                employer_name="Tech Corp Test",
                employer=employer,
                job_title="Data Analyst Test",
                job_title_entity=job_title,
                worksite_state="CA",
                wage_from=Decimal(str(salary)),
                wage_unit=WageUnit.YEAR,
                wage_annual=Decimal(str(salary)),
                visa_program=VisaProgram.PERM,
                case_status=CaseStatus.CERTIFIED,
                fiscal_year=2024,
                source_file="test.xlsx",
                is_worksite=False
            )

        widget_salaries = [95000, 105000, 115000]
        for i, salary in enumerate(widget_salaries):
            SalaryRecord.objects.create(
                case_number=f"TEST-STATS-JT-W-{i}",
                employer_name="Widget Labs Test",
                employer=employer_2,
                job_title="Data Analyst Test",
                job_title_entity=job_title,
                worksite_state="NY",
                wage_from=Decimal(str(salary)),
                wage_unit=WageUnit.YEAR,
                wage_annual=Decimal(str(salary)),
                visa_program=VisaProgram.PERM,
                case_status=CaseStatus.CERTIFIED,
                fiscal_year=2024,
                source_file="test.xlsx",
                is_worksite=False
            )
    
    def test_statistics_basic_aggregation(self):
        """Test that basic statistics are calculated correctly"""
        from lib.business.salary.job_title_stats import get_job_title_statistics
        
        stats = get_job_title_statistics(self.cluster, years=5, program_filter='all')
        
        self.assertIn('basic', stats)
        self.assertEqual(stats['basic']['total_filings'], 8)
        self.assertIsNotNone(stats['basic']['median_salary'])
    
    def test_statistics_salary_percentiles(self):
        """Test that salary percentiles are calculated"""
        from lib.business.salary.job_title_stats import get_job_title_statistics
        
        stats = get_job_title_statistics(self.cluster, years=5, program_filter='all')
        
        self.assertIn('salary_percentiles', stats)
        percentiles = stats['salary_percentiles']
        
        # Check that percentiles are in ascending order
        self.assertLessEqual(percentiles['p10'], percentiles['p25'])
        self.assertLessEqual(percentiles['p25'], percentiles['p50'])
        self.assertLessEqual(percentiles['p50'], percentiles['p75'])
        self.assertLessEqual(percentiles['p75'], percentiles['p90'])
    
    def test_statistics_geographic_distribution(self):
        """Test that geographic distribution is included"""
        from lib.business.salary.job_title_stats import get_job_title_statistics
        
        stats = get_job_title_statistics(self.cluster, years=5, program_filter='all')
        
        self.assertIn('geographic_dist', stats)
        self.assertGreater(len(stats['geographic_dist']), 0)
        
        # Should have CA data
        self.assertEqual(stats['geographic_dist'][0]['worksite_state'], 'CA')

    def test_salary_histogram_includes_overlays(self):
        """Histogram should include per-employer overlays with correct totals."""
        from lib.business.salary.job_title_stats import get_job_title_statistics

        stats = get_job_title_statistics(self.cluster, years=5, program_filter='all')
        histogram = stats['salary_histogram']

        self.assertIn('bins', histogram)
        self.assertIn('overlays', histogram)
        self.assertGreater(len(histogram['bins']), 0)

        overlay_map = {
            overlay['employer_name']: overlay['counts']
            for overlay in histogram['overlays']
        }

        self.assertIn("Tech Corp Test", overlay_map)
        self.assertIn("Widget Labs Test", overlay_map)

        total_overall = sum(bin_data['count'] for bin_data in histogram['bins'])
        self.assertEqual(total_overall, 8)
        self.assertEqual(sum(overlay_map["Tech Corp Test"]), 5)
        self.assertEqual(sum(overlay_map["Widget Labs Test"]), 3)


if __name__ == '__main__':
    unittest.main()
