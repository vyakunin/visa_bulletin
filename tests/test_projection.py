"""Tests for projection logic"""

import unittest
from datetime import date

from lib.projection import (
    calculate_projection,
    calculate_months_between,
    add_months_to_date,
    calculate_historical_linear_regression
)


class TestCalculateMonthsBetween(unittest.TestCase):
    """Test month calculation"""
    
    def test_same_month(self):
        result = calculate_months_between(date(2024, 1, 1), date(2024, 1, 31))
        self.assertEqual(result, 0)
    
    def test_one_month(self):
        result = calculate_months_between(date(2024, 1, 1), date(2024, 2, 1))
        self.assertEqual(result, 1)
    
    def test_across_year_boundary(self):
        result = calculate_months_between(date(2023, 11, 1), date(2024, 2, 1))
        self.assertEqual(result, 3)
    
    def test_one_year(self):
        result = calculate_months_between(date(2023, 1, 1), date(2024, 1, 1))
        self.assertEqual(result, 12)


class TestAddMonthsToDate(unittest.TestCase):
    """Test month addition"""
    
    def test_add_one_month(self):
        result = add_months_to_date(date(2024, 1, 15), 1)
        # Approximately 30 days later
        self.assertEqual(result, date(2024, 2, 14))
    
    def test_add_three_months(self):
        result = add_months_to_date(date(2024, 1, 1), 3)
        # Approximately 90 days later
        self.assertEqual(result, date(2024, 3, 31))
    
    def test_add_zero_months(self):
        result = add_months_to_date(date(2024, 1, 15), 0)
        self.assertEqual(result, date(2024, 1, 15))


class TestCalculateProjection(unittest.TestCase):
    """Test projection calculation logic"""
    
    def test_insufficient_data_returns_none(self):
        dates = [date(2024, 1, 1)]
        cutoffs = [date(2020, 1, 1)]
        submission = date(2021, 1, 1)
        
        result = calculate_projection(dates, cutoffs, submission)
        self.assertIsNone(result)
    
    def test_all_none_cutoffs_returns_none(self):
        dates = [date(2024, 1, 1), date(2024, 2, 1)]
        cutoffs = [None, None]
        submission = date(2021, 1, 1)
        
        result = calculate_projection(dates, cutoffs, submission)
        self.assertIsNone(result)
    
    def test_already_current(self):
        dates = [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)]
        cutoffs = [date(2020, 1, 1), date(2021, 1, 1), date(2022, 1, 1)]
        submission = date(2021, 1, 1)
        
        result = calculate_projection(dates, cutoffs, submission)
        
        self.assertEqual(result['status'], 'current')
        self.assertIn('reached', result['message'])
        self.assertIsNone(result['estimated_date'])
        self.assertEqual(result['months_to_wait'], 0)
    
    def test_no_forward_movement(self):
        dates = [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)]
        cutoffs = [date(2020, 1, 1), date(2020, 1, 1), date(2020, 1, 1)]
        submission = date(2021, 1, 1)
        
        result = calculate_projection(dates, cutoffs, submission)
        
        self.assertEqual(result['status'], 'no_movement')
        self.assertIn('No forward progress', result['message'])
        self.assertIsNone(result['estimated_date'])
        self.assertIsNone(result['months_to_wait'])
    
    def test_backward_movement(self):
        dates = [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)]
        cutoffs = [date(2020, 3, 1), date(2020, 2, 1), date(2020, 1, 1)]
        submission = date(2021, 1, 1)
        
        result = calculate_projection(dates, cutoffs, submission)
        
        self.assertEqual(result['status'], 'no_movement')
    
    def test_projected_status(self):
        # 12 months of data, advancing 1 month per bulletin
        dates = [date(2024, i, 1) for i in range(1, 13)]
        cutoffs = [date(2020, i, 1) for i in range(1, 13)]
        submission = date(2021, 6, 1)
        
        result = calculate_projection(dates, cutoffs, submission)
        
        self.assertEqual(result['status'], 'projected')
        self.assertIsNotNone(result['estimated_date'])
        self.assertIsNotNone(result['months_to_wait'])
        self.assertIn('month', result['message'])
        self.assertGreater(result['avg_progress_days_per_month'], 0)
    
    def test_filters_none_values(self):
        dates = [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1), date(2024, 4, 1)]
        cutoffs = [date(2020, 1, 1), None, date(2020, 3, 1), date(2020, 4, 1)]
        submission = date(2021, 1, 1)
        
        result = calculate_projection(dates, cutoffs, submission)
        
        # Should work with valid points only
        self.assertIsNotNone(result)
        self.assertIn(result['status'], ['current', 'projected'])
    
    def test_slow_progress(self):
        # Very slow progress (1 day per month)
        dates = [date(2024, i, 1) for i in range(1, 13)]
        cutoffs = [date(2020, 1, i) for i in range(1, 13)]
        submission = date(2021, 1, 1)
        
        result = calculate_projection(dates, cutoffs, submission)
        
        self.assertEqual(result['status'], 'projected')
        # Should have a long wait time
        self.assertGreater(result['months_to_wait'], 100)


class TestHistoricalLinearRegression(unittest.TestCase):
    """Test historical linear regression fallback"""
    
    def test_historical_regression_with_steady_progress(self):
        """Test that historical regression works with steady long-term progress"""
        # Create historical data with steady progress
        valid_points = []
        start_pub = date(2020, 1, 1)
        start_cutoff = date(2010, 1, 1)
        
        for i in range(24):  # 24 months of data
            pub = date(start_pub.year, start_pub.month + i % 12, 1) if i < 12 else date(start_pub.year + 1, (start_pub.month + i) % 12 or 12, 1)
            cutoff = date(start_cutoff.year, start_cutoff.month + i % 12, 1) if i < 12 else date(start_cutoff.year + 1, (start_cutoff.month + i) % 12 or 12, 1)
            valid_points.append((pub, cutoff))
        
        submission_date = date(2012, 1, 1)
        last_pub = valid_points[-1][0]
        
        result = calculate_historical_linear_regression(valid_points, submission_date, last_pub)
        
        self.assertIsNotNone(result)
        self.assertIn(result['status'], ['projected_historical', 'current'])
        self.assertEqual(result['method'], 'historical_regression')
    
    def test_historical_regression_insufficient_data(self):
        """Test that historical regression returns None with insufficient data"""
        valid_points = [
            (date(2020, 1, 1), date(2010, 1, 1)),
            (date(2020, 2, 1), date(2010, 2, 1)),
        ]
        submission_date = date(2012, 1, 1)
        last_pub = date(2020, 2, 1)
        
        result = calculate_historical_linear_regression(valid_points, submission_date, last_pub)
        
        self.assertIsNone(result)
    
    def test_fallback_to_historical_when_no_recent_movement(self):
        """Test that calculate_projection falls back to historical regression"""
        # Create data with historical progress but recent stagnation
        dates = []
        cutoffs = []
        
        # Historical progress (2020-2023): advancing steadily
        for i in range(36):
            dates.append(date(2020 + i // 12, 1 + i % 12, 1))
            cutoffs.append(date(2010 + i // 12, 1 + i % 12, 1))
        
        # Recent stagnation (2024): stuck at same cutoff
        for i in range(12):
            dates.append(date(2024, 1 + i, 1))
            cutoffs.append(date(2013, 1, 1))  # Stuck
        
        submission_date = date(2015, 1, 1)
        
        result = calculate_projection(dates, cutoffs, submission_date)
        
        # Should use historical regression fallback
        self.assertIsNotNone(result)
        # Either projected_historical or already current
        self.assertIn(result['status'], ['projected_historical', 'current'])


if __name__ == '__main__':
    unittest.main()

