"""Tests for chart builder logic"""

import unittest
from datetime import date

from lib.chart_builder import build_chart_with_projection


class TestChartBuilder(unittest.TestCase):
    """Test chart HTML generation"""
    
    def test_builds_html_with_valid_data(self):
        dates = [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)]
        cutoffs = [date(2020, 1, 1), date(2020, 2, 1), date(2020, 3, 1)]
        submission = date(2021, 1, 1)
        projection = None
        
        html = build_chart_with_projection(
            dates, cutoffs, submission, projection, 'F1', 'all'
        )
        
        self.assertIsInstance(html, str)
        self.assertIn('plotly', html.lower())
        self.assertIn('priority-date-chart', html)
    
    def test_includes_projection_when_available(self):
        dates = [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)]
        cutoffs = [date(2020, 1, 1), date(2020, 2, 1), date(2020, 3, 1)]
        submission = date(2021, 1, 1)
        projection = {
            'status': 'projected',
            'estimated_date': date(2025, 1, 1),
            'months_to_wait': 12,
        }
        
        html = build_chart_with_projection(
            dates, cutoffs, submission, projection, 'F1', 'china'
        )
        
        self.assertIn('Projection', html)
        self.assertIn('F1', html)
    
    def test_handles_none_cutoff_dates(self):
        dates = [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)]
        cutoffs = [date(2020, 1, 1), None, date(2020, 3, 1)]
        submission = date(2021, 1, 1)
        projection = None
        
        html = build_chart_with_projection(
            dates, cutoffs, submission, projection, 'EB2', 'india'
        )
        
        self.assertIsInstance(html, str)
        self.assertIn('plotly', html.lower())
    
    def test_includes_visa_class_in_title(self):
        dates = [date(2024, 1, 1), date(2024, 2, 1)]
        cutoffs = [date(2020, 1, 1), date(2020, 2, 1)]
        submission = date(2021, 1, 1)
        
        html = build_chart_with_projection(
            dates, cutoffs, submission, None, 'EB3', 'mexico'
        )
        
        self.assertIn('EB3', html)
        self.assertIn('Priority Date Progress', html)
    
    def test_includes_submission_date_line(self):
        dates = [date(2024, 1, 1), date(2024, 2, 1)]
        cutoffs = [date(2020, 1, 1), date(2020, 2, 1)]
        submission = date(2021, 6, 15)
        
        html = build_chart_with_projection(
            dates, cutoffs, submission, None, 'F2A', 'all'
        )
        
        self.assertIn('Your Submission Date', html)
    
    def test_projection_without_estimated_date(self):
        dates = [date(2024, 1, 1), date(2024, 2, 1)]
        cutoffs = [date(2020, 1, 1), date(2020, 2, 1)]
        submission = date(2021, 1, 1)
        projection = {
            'status': 'current',
            'estimated_date': None,
        }
        
        html = build_chart_with_projection(
            dates, cutoffs, submission, projection, 'F1', 'all'
        )
        
        # Should not crash, projection line not added
        self.assertIsInstance(html, str)
        self.assertIn('plotly', html.lower())


if __name__ == '__main__':
    unittest.main()

