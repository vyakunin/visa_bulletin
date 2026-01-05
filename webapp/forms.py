"""Django forms for search filters"""

from django import forms
from lib.utils.location_utils import US_STATES


class SalarySearchForm(forms.Form):
    """Form for salary search filters"""
    q = forms.CharField(
        required=False,
        label='Job Title / Keywords',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., Software Engineer, Data Scientist'
        })
    )
    employer = forms.CharField(
        required=False,
        label='Employer Name',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., Google, Amazon, Microsoft',
            'autocomplete': 'off'
        })
    )
    state = forms.ChoiceField(
        required=False,
        label='State',
        choices=[('', 'All States')] + list(US_STATES),
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    program = forms.ChoiceField(
        required=False,
        label='Visa Program',
        choices=[
            ('', 'All Programs'),
            ('h1b', 'H-1B'),
            ('perm', 'PERM')
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    year = forms.ChoiceField(
        required=False,
        label='Fiscal Year',
        choices=[],  # Will be populated dynamically in view
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    page = forms.IntegerField(
        required=False,
        initial=1,
        min_value=1,
        widget=forms.HiddenInput()
    )

    def clean_state(self):
        """Normalize state to uppercase"""
        state = self.cleaned_data.get('state')
        return state.upper() if state else ''

    def clean_program(self):
        """Normalize program to lowercase"""
        program = self.cleaned_data.get('program')
        return program.lower() if program else ''


class WorksiteSearchForm(forms.Form):
    """Form for worksite search filters"""
    q = forms.CharField(
        required=False,
        label='Job Title / Keywords',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., Software Engineer, Data Scientist'
        })
    )
    state = forms.ChoiceField(
        required=False,
        label='State',
        choices=[('', 'All States')] + list(US_STATES),
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    city = forms.CharField(
        required=False,
        label='City',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., San Francisco, New York'
        })
    )
    program = forms.ChoiceField(
        required=False,
        label='Visa Program',
        choices=[
            ('', 'All Programs'),
            ('h1b', 'H-1B'),
            ('perm', 'PERM')
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    year = forms.ChoiceField(
        required=False,
        label='Fiscal Year',
        choices=[],  # Will be populated dynamically in view
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    page = forms.IntegerField(
        required=False,
        initial=1,
        min_value=1,
        widget=forms.HiddenInput()
    )

    def clean_state(self):
        """Normalize state to uppercase"""
        state = self.cleaned_data.get('state')
        return state.upper() if state else ''

    def clean_program(self):
        """Normalize program to lowercase"""
        program = self.cleaned_data.get('program')
        return program.lower() if program else ''







