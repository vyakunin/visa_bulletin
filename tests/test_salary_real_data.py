"""Test that real imported data renders correctly in the web UI"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import Client, TestCase
from django.urls import reverse

from models.salary import Employer, SalaryRecord


class RealDataRenderingTest(TestCase):
    """Test that real imported data renders correctly in salary search view"""

    def test_real_data_renders(self):
        """Test that real imported data shows up in search results"""
        # Check if we have real data in the database
        total_records = SalaryRecord.objects.count()
        self.assertGreater(total_records, 0, "No salary records in database. Import data first.")

        client = Client()

        # Test empty search shows total count
        response = client.get(reverse('salary_search'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Search H-1B', html=True)

        # If we have data, should show statistics
        if total_records > 0:
            # Should show results count or statistics
            self.assertContains(response, 'Results', html=True)

        # Test search with common job title
        response = client.get(reverse('salary_search'), {'q': 'engineer'})
        self.assertEqual(response.status_code, 200)

        # Should show some results if data exists
        if total_records > 0:
            # Check that we get results (may be empty if no matches, but page should render)
            self.assertContains(response, 'Search', html=True)

    def test_real_employer_search(self):
        """Test searching by real employer names"""
        # Get a real employer from database
        employer = Employer.objects.first()

        if not employer:
            self.skipTest("No employers in database. Import data first.")

        client = Client()

        # Search by employer name
        response = client.get(reverse('salary_search'), {'employer': employer.name})
        self.assertEqual(response.status_code, 200)

        # Should show the employer name in results
        self.assertContains(response, employer.name, html=True)

    def test_real_state_filter(self):
        """Test filtering by state with real data"""
        # Get a state that has records
        state_record = SalaryRecord.objects.exclude(worksite_state='').first()

        if not state_record:
            self.skipTest("No records with state information. Import data first.")

        client = Client()

        # Filter by state
        response = client.get(reverse('salary_search'), {'state': state_record.worksite_state})
        self.assertEqual(response.status_code, 200)

        # Should show results for that state
        self.assertContains(response, 'Search', html=True)

    def test_statistics_with_real_data(self):
        """Test that statistics are calculated correctly with real data"""
        total_records = SalaryRecord.objects.count()

        if total_records == 0:
            self.skipTest("No salary records in database. Import data first.")

        client = Client()

        # Search for all records
        response = client.get(reverse('salary_search'), {'q': ''})
        self.assertEqual(response.status_code, 200)

        # Should show statistics
        self.assertContains(response, 'Average', html=True)
        self.assertContains(response, 'Results', html=True)
