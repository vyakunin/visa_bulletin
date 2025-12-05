"""Tests for chart builder logic"""

import unittest
from datetime import date

from lib.chart_builder import (
    build_chart_with_projection,
    build_multi_class_chart_with_projections
)


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
        self.assertIn('Mexico', html)  # Country label in title
    
    def test_includes_submission_date_line(self):
        dates = [date(2024, 1, 1), date(2024, 2, 1)]
        cutoffs = [date(2020, 1, 1), date(2020, 2, 1)]
        submission = date(2021, 6, 15)
        
        html = build_chart_with_projection(
            dates, cutoffs, submission, None, 'F2A', 'all'
        )
        
        self.assertIn('Your Priority Date', html)
    
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


class TestMultiClassChartBuilder(unittest.TestCase):
    """Test multi-class chart generation (main dashboard feature)"""
    
    def test_builds_chart_with_multiple_visa_classes(self):
        """Chart should include all visa classes with their data"""
        visa_class_data = [
            {
                'visa_class': 'F1',
                'visa_class_label': 'F1: Unmarried Sons/Daughters',
                'dates': [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)],
                'cutoff_dates': [date(2020, 1, 1), date(2020, 2, 1), date(2020, 3, 1)],
                'projection': None,
                'bulletin_urls': ['url1', 'url2', 'url3']
            },
            {
                'visa_class': 'F2A',
                'visa_class_label': 'F2A: Spouses and Children',
                'dates': [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)],
                'cutoff_dates': [date(2021, 1, 1), date(2021, 2, 1), date(2021, 3, 1)],
                'projection': None,
                'bulletin_urls': ['url1', 'url2', 'url3']
            }
        ]
        submission_date = date(2022, 1, 1)
        
        result = build_multi_class_chart_with_projections(
            visa_class_data, submission_date, 'all', 'Family-Sponsored'
        )
        
        # Returns dict with chart_json and trace_info
        self.assertIsInstance(result, dict)
        self.assertIn('chart_json', result)
        self.assertIn('trace_info', result)
        self.assertIn('F1', result['chart_json'])
        self.assertIn('F2A', result['chart_json'])
        
        # Check trace_info structure
        self.assertEqual(len(result['trace_info']), 2)
        self.assertEqual(result['trace_info'][0]['visa_class'], 'F1')
        self.assertEqual(result['trace_info'][1]['visa_class'], 'F2A')
    
    def test_handles_empty_visa_class_data(self):
        """Chart should handle empty data gracefully"""
        result = build_multi_class_chart_with_projections(
            [], date(2022, 1, 1), 'all', 'Family-Sponsored'
        )
        
        self.assertIsInstance(result, dict)
        self.assertIn('chart_json', result)
        self.assertEqual(result['trace_info'], [])
    
    def test_includes_projections_when_available(self):
        """Chart should show projection lines for each visa class"""
        visa_class_data = [
            {
                'visa_class': 'EB2',
                'visa_class_label': 'EB-2: Advanced Degree',
                'dates': [date(2024, 1, 1), date(2024, 2, 1)],
                'cutoff_dates': [date(2018, 1, 1), date(2018, 2, 1)],
                'projection': {
                    'status': 'projected',
                    'estimated_date': date(2026, 1, 1),
                    'months_to_wait': 24
                },
                'bulletin_urls': []
            }
        ]
        
        result = build_multi_class_chart_with_projections(
            visa_class_data, date(2020, 1, 1), 'india', 'Employment-Based'
        )
        
        # Check label appears in chart (not visa_class code)
        self.assertIn('EB-2: Advanced Degree', result['chart_json'])
        # Should include projection data
        self.assertIn('2026', result['chart_json'])
        # Should have 2 trace indices (historical + projection)
        self.assertEqual(len(result['trace_info'][0]['trace_indices']), 2)
    
    def test_handles_mixed_projections(self):
        """Some visa classes have projections, others don't"""
        visa_class_data = [
            {
                'visa_class': 'EB2',
                'dates': [date(2024, 1, 1)],
                'cutoff_dates': [date(2018, 1, 1)],
                'projection': {'status': 'projected', 'estimated_date': date(2025, 1, 1)},
            },
            {
                'visa_class': 'EB3',
                'dates': [date(2024, 1, 1)],
                'cutoff_dates': [date(2019, 1, 1)],
                'projection': None,  # No projection
            }
        ]
        
        result = build_multi_class_chart_with_projections(
            visa_class_data, date(2020, 1, 1), 'china', 'Employment-Based'
        )
        
        self.assertIsInstance(result, dict)
        self.assertIn('EB2', result['chart_json'])
        self.assertIn('EB3', result['chart_json'])
        # EB2 has projection (2 traces), EB3 doesn't (1 trace)
        self.assertEqual(len(result['trace_info'][0]['trace_indices']), 2)
        self.assertEqual(len(result['trace_info'][1]['trace_indices']), 1)
    
    def test_handles_none_cutoff_dates_in_multi_class(self):
        """None values in cutoff_dates should not break chart"""
        visa_class_data = [
            {
                'visa_class': 'F1',
                'dates': [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)],
                'cutoff_dates': [date(2020, 1, 1), None, date(2020, 3, 1)],
                'projection': None,
            }
        ]
        
        result = build_multi_class_chart_with_projections(
            visa_class_data, date(2021, 1, 1), 'all', 'Family-Sponsored'
        )
        
        self.assertIsInstance(result, dict)
        self.assertIn('chart_json', result)
    
    def test_submission_date_line_extends_to_projections(self):
        """Submission date line should extend to furthest projection"""
        visa_class_data = [
            {
                'visa_class': 'EB2',
                'dates': [date(2024, 1, 1)],
                'cutoff_dates': [date(2018, 1, 1)],
                'projection': {
                    'status': 'projected',
                    'estimated_date': date(2030, 1, 1),  # Far future
                },
            }
        ]
        
        result = build_multi_class_chart_with_projections(
            visa_class_data, date(2020, 1, 1), 'india', 'Employment-Based'
        )
        
        self.assertIn('Your Priority Date', result['chart_json'])
        # Should reference 2030 in chart data
        self.assertIn('2030', result['chart_json'])
    
    def test_trace_info_includes_colors(self):
        """Each trace_info entry should include color for checkbox styling"""
        visa_class_data = [
            {
                'visa_class': 'F1',
                'visa_class_label': 'F1: Test',
                'dates': [date(2024, 1, 1)],
                'cutoff_dates': [date(2020, 1, 1)],
                'projection': None,
            }
        ]
        
        result = build_multi_class_chart_with_projections(
            visa_class_data, date(2021, 1, 1), 'all', 'Family-Sponsored'
        )
        
        self.assertIn('color', result['trace_info'][0])
        self.assertTrue(result['trace_info'][0]['color'].startswith('#'))


if __name__ == '__main__':
    unittest.main()

