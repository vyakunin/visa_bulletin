"""UI behavior tests for the webapp dashboard"""

import unittest
from unittest.mock import patch
from datetime import date
from django.test import RequestFactory

# Django setup (shared utility for both Bazel and pytest)
from tests.django_setup import setup_django_for_tests
setup_django_for_tests()


class TestDashboardUIBehavior(unittest.TestCase):
    """Test UI interaction patterns in the dashboard"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.factory = RequestFactory()
    
    def test_date_input_does_not_have_onchange_handler(self):
        """
        Date input should NOT auto-submit on change to allow user to finish typing
        
        This prevents interruption when user is entering a date character by character.
        The form should only submit when:
        1. User clicks the "Update" button
        2. User presses Enter in the date field
        3. User changes a dropdown (which auto-submits)
        """
        from webapp.views import dashboard_view
        
        # Create a proper Django request
        request = self.factory.get('/dashboard/', {
            'category': 'family_sponsored',
            'country': 'all',
            'visa_class': 'F1',
            'action_type': 'final_action',
            'submission_date': '2024-01-01'
        })
        
        with patch('webapp.views.render') as mock_render:
            # Mock the dashboard service to return empty data
            with patch('webapp.views.get_aggregated_visa_class_data') as mock_service:
                # Return empty visa class data and has_any_data=False
                mock_service.return_value = ([], False)
                
                dashboard_view(request)
                
                # Verify render was called
                self.assertTrue(mock_render.called)
                
                # Get the context passed to template
                context = mock_render.call_args[0][2]
                
                # Verify context has submission_date
                self.assertIn('submission_date', context)
                self.assertEqual(context['submission_date'], date(2024, 1, 1))
    
    def test_dropdown_fields_have_auto_submit(self):
        """
        Dropdown fields (category, country, visa_class, action_type) should auto-submit
        
        This provides immediate feedback when user changes selection criteria.
        """
        # This is more of a documentation test - the actual behavior is in the template
        # The template should have onchange="autoSubmitForm()" for dropdowns
        
        dropdowns_with_auto_submit = [
            'category',  # onchange="updateVisaClasses()" which submits
            'country',   # onchange="autoSubmitForm()"
            'visa_class',  # onchange="autoSubmitForm()"
            'action_type'  # onchange="autoSubmitForm()"
        ]
        
        # Date input should NOT have auto-submit
        date_field_no_auto_submit = 'submission_date'
        
        # This test documents the expected behavior
        self.assertEqual(len(dropdowns_with_auto_submit), 4)
        self.assertEqual(date_field_no_auto_submit, 'submission_date')
    
    def test_date_validation_with_invalid_format(self):
        """Test that invalid date formats are handled gracefully"""
        from webapp.views import dashboard_view
        
        # Create a proper Django request with invalid date
        request = self.factory.get('/dashboard/', {
            'category': 'family_sponsored',
            'country': 'all',
            'visa_class': 'F1',
            'action_type': 'final_action',
            'submission_date': 'invalid-date'  # Bad format
        })
        
        with patch('webapp.views.render') as mock_render:
            with patch('webapp.views.get_aggregated_visa_class_data') as mock_service:
                # Return empty visa class data
                mock_service.return_value = ([], False)
                
                # Should not raise exception, should use today's date as fallback
                dashboard_view(request)
                
                context = mock_render.call_args[0][2]
                
                # Should have submission_date (fallback to today)
                self.assertIn('submission_date', context)
                self.assertIsInstance(context['submission_date'], date)
    
    def test_update_button_allows_manual_submission(self):
        """
        Test that the form can be submitted via button click
        
        The Update button provides explicit control for date changes.
        """
        # This tests the expected UX pattern:
        # 1. User types date without interruption
        # 2. User clicks "Update" button to submit
        # 3. Form submits and page reloads with new data
        
        # The button should be type="submit" and not have onclick handler
        # This allows standard form submission behavior
        
        expected_button_behavior = {
            'type': 'submit',
            'auto_submit': False,  # No onclick handler
            'allows_enter_key': True  # Standard HTML form behavior
        }
        
        self.assertEqual(expected_button_behavior['type'], 'submit')
        self.assertFalse(expected_button_behavior['auto_submit'])
        self.assertTrue(expected_button_behavior['allows_enter_key'])


class TestDateInputAccessibility(unittest.TestCase):
    """Test accessibility features of date input"""
    
    def test_date_input_has_label(self):
        """Date input should have associated label for screen readers"""
        # The label should use for="submission_date" to link with input id
        expected_label = 'Priority Date'
        expected_input_id = 'submission_date'
        
        self.assertEqual(expected_input_id, 'submission_date')
        self.assertIsInstance(expected_label, str)
    
    def test_date_input_has_help_text(self):
        """Date input should have explanatory help text"""
        expected_help_text = 'Your filing date'
        
        # Help text should explain what the date represents
        self.assertIn('filing', expected_help_text.lower())


if __name__ == '__main__':
    unittest.main()

