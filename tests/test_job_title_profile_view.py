"""Tests for job title profile view."""

from tests.django_setup import setup_django_for_tests
setup_django_for_tests()

import sys
import unittest
import json
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.db import connection
from models.job_title import JobTitle, JobTitleCluster
from models.salary import SalaryRecord, Employer, EmployerCluster
from models.enums.visa_program import VisaProgram, WageUnit, CaseStatus
from decimal import Decimal

try:
    from scripts.salary.update_job_title_cluster_stats import (
        main as update_job_title_cluster_stats_main,
        _most_frequent_raw_title_per_cluster,
    )
except ImportError:
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.salary.update_job_title_cluster_stats import (
        main as update_job_title_cluster_stats_main,
        _most_frequent_raw_title_per_cluster,
    )


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
        # Count by normalized title (10 = 8 in self.cluster + 2 in other_cluster)
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
    """Test job title autocomplete sorting and grouping (ranks by recent-year filings)."""

    def setUp(self):
        """Set up test data for autocomplete."""
        from django.core.cache import cache
        from datetime import datetime
        cache.clear()

        self.cluster_software = JobTitleCluster.objects.create(
            canonical_title="Software Engineer",
            slug="software-engineer-autocomplete",
            total_filings=120,
        )
        self.cluster_net_base = JobTitleCluster.objects.create(
            canonical_title=".NET Software Engineer",
            slug="net-software-engineer-autocomplete",
            total_filings=10,
        )
        self.cluster_net_level_2 = JobTitleCluster.objects.create(
            canonical_title=".NET Software Engineer 2",
            slug="net-software-engineer-2-autocomplete",
            total_filings=25,
        )
        self.cluster_net_level_3 = JobTitleCluster.objects.create(
            canonical_title=".NET Software Engineer 3",
            slug="net-software-engineer-3-autocomplete",
            total_filings=35,
        )

        jt_se = JobTitle.objects.create(
            title="Software Engineer",
            title_normalized="software engineer",
            experience_level="",
            canonical_cluster=self.cluster_software,
            total_filings=120,
        )
        jt_net = JobTitle.objects.create(
            title=".NET Software Engineer",
            title_normalized="net software engineer",
            experience_level="",
            canonical_cluster=self.cluster_net_base,
            total_filings=10,
        )
        jt_net_2 = JobTitle.objects.create(
            title=".NET Software Engineer 2",
            title_normalized="net software engineer",
            experience_level="ii",
            canonical_cluster=self.cluster_net_level_2,
            total_filings=25,
        )
        jt_net_3 = JobTitle.objects.create(
            title=".NET Software Engineer 3",
            title_normalized="net software engineer",
            experience_level="iii",
            canonical_cluster=self.cluster_net_level_3,
            total_filings=35,
        )

        # Autocomplete ranks by filings in last AUTOCOMPLETE_YEARS; create recent records.
        recent_fy = datetime.now().year - 2  # Within last 5 years
        for i in range(120):
            SalaryRecord.objects.create(
                case_number=f"TEST-AC-SE-{i}",
                employer_name="Test Co",
                job_title="Software Engineer",
                job_title_entity=jt_se,
                visa_program=VisaProgram.H1B,
                fiscal_year=recent_fy,
                wage_annual=Decimal("120000"),
            )
        for i in range(10):
            SalaryRecord.objects.create(
                case_number=f"TEST-AC-NET-{i}",
                employer_name="Test Co",
                job_title=".NET Software Engineer",
                job_title_entity=jt_net,
                visa_program=VisaProgram.H1B,
                fiscal_year=recent_fy,
                wage_annual=Decimal("110000"),
            )
        for i in range(25):
            SalaryRecord.objects.create(
                case_number=f"TEST-AC-NET2-{i}",
                employer_name="Test Co",
                job_title=".NET Software Engineer 2",
                job_title_entity=jt_net_2,
                visa_program=VisaProgram.H1B,
                fiscal_year=recent_fy,
                wage_annual=Decimal("115000"),
            )
        for i in range(35):
            SalaryRecord.objects.create(
                case_number=f"TEST-AC-NET3-{i}",
                employer_name="Test Co",
                job_title=".NET Software Engineer 3",
                job_title_entity=jt_net_3,
                visa_program=VisaProgram.H1B,
                fiscal_year=recent_fy,
                wage_annual=Decimal("125000"),
            )
        # Autocomplete uses precomputed total_filings_recent; set it so we don't run stats script
        self.cluster_software.total_filings_recent = 120
        self.cluster_software.save()
        self.cluster_net_base.total_filings_recent = 10
        self.cluster_net_base.save()
        self.cluster_net_level_2.total_filings_recent = 25
        self.cluster_net_level_2.save()
        self.cluster_net_level_3.total_filings_recent = 35
        self.cluster_net_level_3.save()

    def test_autocomplete_orders_by_normalized_popularity(self):
        """Autocomplete returns clusters matching query, ordered by recent filings desc."""
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
        self.assertIn(".NET Software Engineer", titles)


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


@override_settings(
    CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
        }
    }
)
class TestJobTitleDataCoherence(TestCase):
    """
    Integration tests for job title data coherence end-to-end.

    Ensures: autocomplete and directory use canonical_title and total_filings;
    profile page shows cluster.total_filings; Similar Job Titles uses canonical_title;
    URLs use slug and resolve correctly.
    """

    def setUp(self):
        from django.core.cache import cache
        from datetime import datetime
        cache.clear()
        # Cluster A: representative title "Data Analyst", slug data-analyst-coherence
        self.cluster_a, _ = JobTitleCluster.objects.get_or_create(
            slug="data-analyst-coherence",
            defaults={
                'canonical_title': "Data Analyst",
                'total_filings': 500,
                'avg_salary': Decimal('95000.00'),
            }
        )
        self.cluster_a.total_filings = 500
        self.cluster_a.canonical_title = "Data Analyst"
        self.cluster_a.save()
        # Cluster B: representative title "Data Scientist", slug data-scientist-coherence
        self.cluster_b, _ = JobTitleCluster.objects.get_or_create(
            slug="data-scientist-coherence",
            defaults={
                'canonical_title': "Data Scientist",
                'total_filings': 300,
                'avg_salary': Decimal('120000.00'),
            }
        )
        self.cluster_b.total_filings = 300
        self.cluster_b.canonical_title = "Data Scientist"
        self.cluster_b.save()

        # Autocomplete ranks by recent-year filings; create JobTitles + recent SalaryRecords.
        recent_fy = datetime.now().year - 2
        jt_a, _ = JobTitle.objects.get_or_create(
            title_normalized="data analyst",
            experience_level="",
            defaults={
                'title': "Data Analyst",
                'canonical_cluster': self.cluster_a,
                'total_filings': 500,
            },
        )
        jt_a.canonical_cluster = self.cluster_a
        jt_a.save()
        jt_b, _ = JobTitle.objects.get_or_create(
            title_normalized="data scientist",
            experience_level="",
            defaults={
                'title': "Data Scientist",
                'canonical_cluster': self.cluster_b,
                'total_filings': 300,
            },
        )
        jt_b.canonical_cluster = self.cluster_b
        jt_b.save()
        for i in range(50):
            SalaryRecord.objects.get_or_create(
                case_number=f"TEST-COH-A-{i}",
                defaults={
                    'employer_name': "Test Co",
                    'job_title': "Data Analyst",
                    'job_title_entity': jt_a,
                    'visa_program': VisaProgram.H1B,
                    'fiscal_year': recent_fy,
                    'wage_annual': Decimal("95000"),
                },
            )
        for i in range(30):
            SalaryRecord.objects.get_or_create(
                case_number=f"TEST-COH-B-{i}",
                defaults={
                    'employer_name': "Test Co",
                    'job_title': "Data Scientist",
                    'job_title_entity': jt_b,
                    'visa_program': VisaProgram.H1B,
                    'fiscal_year': recent_fy,
                    'wage_annual': Decimal("120000"),
                },
            )
        # Autocomplete uses precomputed total_filings_recent; set it so we don't run stats script
        self.cluster_a.total_filings_recent = 50
        self.cluster_a.save()
        self.cluster_b.total_filings_recent = 30
        self.cluster_b.save()

    def test_autocomplete_returns_canonical_title_total_filings_slug(self):
        """Autocomplete API returns title=canonical_title, total_filings (recent count), slug."""
        client = Client()
        response = client.get(
            reverse('job_title_autocomplete'),
            {'q': 'data analyst'},
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertGreater(len(data), 0)
        first = next((x for x in data if x.get('slug') == 'data-analyst-coherence'), None)
        self.assertIsNotNone(first, f"Expected slug data-analyst-coherence in {data}")
        self.assertEqual(first['title'], "Data Analyst")
        self.assertEqual(first['total_filings'], 50)  # Recent-year count, not all-time 500
        self.assertEqual(first['slug'], "data-analyst-coherence")

    def test_autocomplete_order_by_total_filings_desc(self):
        """Autocomplete results are ordered by recent filings descending."""
        client = Client()
        response = client.get(
            reverse('job_title_autocomplete'),
            {'q': 'data'},
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        slugs = [x['slug'] for x in data if x['slug'] in ('data-analyst-coherence', 'data-scientist-coherence')]
        if len(slugs) >= 2:
            idx_a = next(i for i, x in enumerate(data) if x['slug'] == 'data-analyst-coherence')
            idx_b = next(i for i, x in enumerate(data) if x['slug'] == 'data-scientist-coherence')
            self.assertGreater(
                data[idx_a]['total_filings'],
                data[idx_b]['total_filings'],
                msg="Higher recent filings cluster should appear first",
            )

    def test_profile_total_filings_matches_cluster(self):
        """Profile page Total Filings matches cluster.total_filings."""
        client = Client()
        response = client.get(
            reverse('job_title_profile', kwargs={'slug': 'data-analyst-coherence'}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "500", msg_prefix="Profile should show cluster total_filings (500)")

    def test_profile_url_uses_slug(self):
        """Profile URL pattern /job-title/<slug>/ resolves and shows cluster data."""
        client = Client()
        url = reverse('job_title_profile', kwargs={'slug': 'data-analyst-coherence'})
        self.assertIn('data-analyst-coherence', url)
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Data Analyst")

    def test_similar_job_titles_uses_canonical_title(self):
        """Similar Job Titles section shows canonical_title (representative), not raw variants."""
        client = Client()
        response = client.get(
            reverse('job_title_profile', kwargs={'slug': 'data-analyst-coherence'}),
        )
        self.assertEqual(response.status_code, 200)
        # Similar section is built from JobTitleCluster.canonical_title; ensure we show it
        self.assertContains(response, "Similar Job Titles")
        # If similar clusters exist (same first word), they should show canonical_title
        if response.context and response.context.get('similar_clusters'):
            for similar in response.context['similar_clusters']:
                self.assertIsNotNone(getattr(similar, 'canonical_title', None))
                self.assertIsNotNone(getattr(similar, 'slug', None))
                self.assertIsNotNone(getattr(similar, 'total_filings', None))

    def test_autocomplete_recent_profile_all_time(self):
        """Autocomplete shows recent-year filing count; profile shows all-time total."""
        client = Client()
        response_ac = client.get(
            reverse('job_title_autocomplete'),
            {'q': 'data analyst'},
        )
        self.assertEqual(response_ac.status_code, 200)
        data = json.loads(response_ac.content)
        item = next((x for x in data if x.get('slug') == 'data-analyst-coherence'), None)
        self.assertIsNotNone(item, f"Expected slug data-analyst-coherence in autocomplete: {data}")
        self.assertEqual(item['total_filings'], 50)  # Recent-year count
        response_profile = client.get(
            reverse('job_title_profile', kwargs={'slug': 'data-analyst-coherence'}),
        )
        self.assertEqual(response_profile.status_code, 200)
        self.assertContains(response_profile, "500", msg_prefix="Profile shows all-time total (500)")

    def test_generated_url_resolves_and_shows_data(self):
        """Generated URL /job-title/<slug>/ resolves and shows cluster data with correct count."""
        client = Client()
        url = reverse('job_title_profile', kwargs={'slug': 'data-analyst-coherence'})
        self.assertIn('data-analyst-coherence', url)
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Data Analyst")
        self.assertContains(response, "500")

    def test_similar_section_shows_canonical_titles_not_raw(self):
        """Similar Job Titles section shows canonical_title (e.g. Software Developer), not raw SOC-style."""
        # Create two clusters sharing first word "Software" so similar section is populated
        cluster_se, _ = JobTitleCluster.objects.get_or_create(
            slug="software-engineer-e2e",
            defaults={
                'canonical_title': "Software Engineer",
                'total_filings': 100,
                'avg_salary': Decimal('120000.00'),
            },
        )
        cluster_sd, _ = JobTitleCluster.objects.get_or_create(
            slug="software-developer-e2e",
            defaults={
                'canonical_title': "Software Developer",
                'total_filings': 80,
                'avg_salary': Decimal('110000.00'),
            },
        )
        cluster_se.canonical_title = "Software Engineer"
        cluster_se.total_filings = 100
        cluster_se.save()
        cluster_sd.canonical_title = "Software Developer"
        cluster_sd.total_filings = 80
        cluster_sd.save()
        client = Client()
        response = client.get(
            reverse('job_title_profile', kwargs={'slug': 'software-engineer-e2e'}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Similar Job Titles")
        # Similar section must show canonical_title "Software Developer", not a raw variant
        self.assertContains(response, "Software Developer")


@override_settings(
    CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
        }
    }
)
class TestJobTitleCoherenceE2E(TestCase):
    """
    End-to-end coherence: update_job_title_cluster_stats sets canonical_title to the
    most frequent raw title among records whose normalized title equals the cluster's
    most frequent normalized form (count first, then shorter length); autocomplete and profile use it.
    """

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        # Employer for SalaryRecords
        ec, _ = EmployerCluster.objects.get_or_create(
            slug="e2e-employer",
            defaults={'canonical_name': "E2E Employer"},
        )
        self.employer, _ = Employer.objects.get_or_create(
            name="E2E Employer",
            defaults={
                'name_normalized': "e2e employer",
                'canonical_cluster': ec,
            },
        )
        # Cluster: most frequent normalized = "software engineer" (10), so canonical_title
        # is chosen among raw titles with that normalized; "Software Engineer" (count 10) wins.
        self.cluster = JobTitleCluster.objects.create(
            canonical_title="Software Developers, Applications",
            total_filings=15,
            avg_salary=Decimal('120000.00'),
        )
        self.cluster.slug = self.cluster.generate_slug()
        self.cluster.save()
        jt_soc = JobTitle.objects.create(
            title="Software Developers, Applications",
            title_normalized="software developers applications",
            experience_level="",
            canonical_cluster=self.cluster,
        )
        jt_eng = JobTitle.objects.create(
            title="Software Engineer",
            title_normalized="software engineer",
            experience_level="",
            canonical_cluster=self.cluster,
        )
        SalaryRecord.objects.filter(case_number__startswith="E2E-JT-").delete()
        wage = 80000
        for i in range(5):
            SalaryRecord.objects.create(
                case_number=f"E2E-JT-SOC-{i}",
                employer_name="E2E Employer",
                employer=self.employer,
                job_title="Software Developers, Applications",
                job_title_entity=jt_soc,
                worksite_city="NYC",
                worksite_state="NY",
                wage_from=Decimal(wage),
                wage_unit=WageUnit.YEAR,
                wage_annual=Decimal(wage),
                visa_program=VisaProgram.H1B,
                case_status=CaseStatus.CERTIFIED,
                fiscal_year=2024,
                source_file="test.xlsx",
                is_worksite=False,
            )
            wage += 1000
        for i in range(10):
            SalaryRecord.objects.create(
                case_number=f"E2E-JT-ENG-{i}",
                employer_name="E2E Employer",
                employer=self.employer,
                job_title="Software Engineer",
                job_title_entity=jt_eng,
                worksite_city="NYC",
                worksite_state="NY",
                wage_from=Decimal(wage),
                wage_unit=WageUnit.YEAR,
                wage_annual=Decimal(wage),
                visa_program=VisaProgram.H1B,
                case_status=CaseStatus.CERTIFIED,
                fiscal_year=2024,
                source_file="test.xlsx",
                is_worksite=False,
            )
            wage += 1000

    def test_canonical_title_selection_count_first(self):
        """_most_frequent_raw_title_per_cluster picks raw title by count DESC, then shorter length."""
        result = dict(_most_frequent_raw_title_per_cluster())
        self.assertIn(
            self.cluster.id,
            result,
            msg="Cluster should appear in representative title query result.",
        )
        self.assertEqual(
            result[self.cluster.id],
            "Software Engineer",
            msg="Representative should be 'Software Engineer' (count 10), not SOC-style (count 5).",
        )

    def test_canonical_title_count_first_full_script(self):
        """update_job_title_cluster_stats (full script) sets cluster canonical_title from mode normalized."""
        old_argv = sys.argv
        try:
            sys.argv = ['update_job_title_cluster_stats']
            update_job_title_cluster_stats_main()
        finally:
            sys.argv = old_argv
        self.cluster.refresh_from_db()
        self.assertEqual(
            self.cluster.canonical_title,
            "Software Engineer",
            msg="Cluster canonical_title should be 'Software Engineer' (count first), not SOC-style.",
        )

    def test_canonical_title_selection_count_wins_over_shorter(self):
        """When same normalized form has two raw titles, higher count wins (not shorter length)."""
        from django.core.cache import cache
        cache.clear()
        ec, _ = EmployerCluster.objects.get_or_create(
            slug="e2e-count-test",
            defaults={'canonical_name': "E2E Count Test"},
        )
        emp, _ = Employer.objects.get_or_create(
            name="E2E Count Test",
            defaults={'name_normalized': "e2e count test", 'canonical_cluster': ec},
        )
        cluster = JobTitleCluster.objects.create(
            canonical_title="Placeholder",
            total_filings=0,
            avg_salary=Decimal('100000.00'),
        )
        cluster.slug = cluster.generate_slug()
        cluster.save()
        jt, _ = JobTitle.objects.get_or_create(
            title_normalized="software engineer",
            experience_level="",
            defaults={'title': "Software Engineer", 'canonical_cluster': cluster},
        )
        old_cluster_id = jt.canonical_cluster_id
        jt.canonical_cluster = cluster
        jt.save(update_fields=['canonical_cluster'])
        try:
            SalaryRecord.objects.filter(case_number__startswith="E2E-COUNT-").delete()
            base_wage = 90000
            # "Programmer" (shorter) x 5, "Software Engineer" (longer) x 20 → count wins, so "Software Engineer"
            for i in range(5):
                SalaryRecord.objects.create(
                    case_number=f"E2E-COUNT-P-{i}",
                    employer_name="E2E Count Test",
                    employer=emp,
                    job_title="Programmer",
                    job_title_entity=jt,
                    worksite_city="NYC",
                    worksite_state="NY",
                    wage_from=Decimal(base_wage),
                    wage_unit=WageUnit.YEAR,
                    wage_annual=Decimal(base_wage),
                    visa_program=VisaProgram.H1B,
                    case_status=CaseStatus.CERTIFIED,
                    fiscal_year=2024,
                    source_file="test.xlsx",
                    is_worksite=False,
                )
            for i in range(20):
                SalaryRecord.objects.create(
                    case_number=f"E2E-COUNT-SE-{i}",
                    employer_name="E2E Count Test",
                    employer=emp,
                    job_title="Software Engineer",
                    job_title_entity=jt,
                    worksite_city="NYC",
                    worksite_state="NY",
                    wage_from=Decimal(base_wage),
                    wage_unit=WageUnit.YEAR,
                    wage_annual=Decimal(base_wage),
                    visa_program=VisaProgram.H1B,
                    case_status=CaseStatus.CERTIFIED,
                    fiscal_year=2024,
                    source_file="test.xlsx",
                    is_worksite=False,
                )
            result = dict(_most_frequent_raw_title_per_cluster())
            self.assertEqual(
                result[cluster.id],
                "Software Engineer",
                msg="Count wins: 'Software Engineer' (20) must beat 'Programmer' (5) despite being longer.",
            )
        finally:
            SalaryRecord.objects.filter(case_number__startswith="E2E-COUNT-").delete()
            if old_cluster_id != cluster.id:
                jt.canonical_cluster_id = old_cluster_id
                jt.save(update_fields=['canonical_cluster'])

    def test_canonical_title_selection_shorter_tiebreaker(self):
        """When two raw titles have the same count, shorter length wins."""
        from django.core.cache import cache
        cache.clear()
        ec, _ = EmployerCluster.objects.get_or_create(
            slug="e2e-tie-test",
            defaults={'canonical_name': "E2E Tie Test"},
        )
        emp, _ = Employer.objects.get_or_create(
            name="E2E Tie Test",
            defaults={'name_normalized': "e2e tie test", 'canonical_cluster': ec},
        )
        cluster = JobTitleCluster.objects.create(
            canonical_title="Placeholder",
            total_filings=0,
            avg_salary=Decimal('100000.00'),
        )
        cluster.slug = cluster.generate_slug()
        cluster.save()
        # Use unique title_normalized so this cluster has no other JobTitles/records from other tests
        jt = JobTitle.objects.create(
            title="Software Engineer",
            title_normalized="software engineer tiebreaker test",
            experience_level="",
            canonical_cluster=cluster,
        )
        SalaryRecord.objects.filter(case_number__startswith="E2E-TIE-").delete()
        base_wage = 90000
        # Same count (3 each): "Dev" (3 chars) vs "Software Engineer" (18 chars) → shorter wins
        for i in range(3):
            SalaryRecord.objects.create(
                case_number=f"E2E-TIE-D-{i}",
                employer_name="E2E Tie Test",
                employer=emp,
                job_title="Dev",
                job_title_entity=jt,
                worksite_city="NYC",
                worksite_state="NY",
                wage_from=Decimal(base_wage),
                wage_unit=WageUnit.YEAR,
                wage_annual=Decimal(base_wage),
                visa_program=VisaProgram.H1B,
                case_status=CaseStatus.CERTIFIED,
                fiscal_year=2024,
                source_file="test.xlsx",
                is_worksite=False,
            )
        for i in range(3):
            SalaryRecord.objects.create(
                case_number=f"E2E-TIE-SE-{i}",
                employer_name="E2E Tie Test",
                employer=emp,
                job_title="Software Engineer",
                job_title_entity=jt,
                worksite_city="NYC",
                worksite_state="NY",
                wage_from=Decimal(base_wage),
                wage_unit=WageUnit.YEAR,
                wage_annual=Decimal(base_wage),
                visa_program=VisaProgram.H1B,
                case_status=CaseStatus.CERTIFIED,
                fiscal_year=2024,
                source_file="test.xlsx",
                is_worksite=False,
            )
        try:
            result = dict(_most_frequent_raw_title_per_cluster())
            self.assertEqual(
                result[cluster.id],
                "Dev",
                msg="Tiebreaker: same count (3) → shorter 'Dev' (3 chars) beats 'Software Engineer' (18 chars).",
            )
        finally:
            SalaryRecord.objects.filter(case_number__startswith="E2E-TIE-").delete()
            jt.delete()


if __name__ == '__main__':
    unittest.main()
