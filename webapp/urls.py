"""URL configuration for webapp"""

from django.urls import path

from webapp.views.bulletin.dashboard import dashboard_view
from webapp.views.employers.directory import (
    company_autocomplete_view,
    employer_directory_view,
)
from webapp.views.employers.profile import employer_profile_view
from webapp.views.job_titles.directory import (
    job_title_autocomplete_view,
    job_title_directory_view,
)
from webapp.views.job_titles.profile import job_title_profile_view
from webapp.views.salary.search import salary_search_view, worksite_search_view
from webapp.views.static.pages import about_view, contact_view, faq_view

urlpatterns = [
    path('', dashboard_view, name='dashboard'),

    # Static pages
    path('faq/', faq_view, name='faq'),
    path('about/', about_view, name='about'),
    path('contact/', contact_view, name='contact'),

    # Salary Database
    path('salaries/', salary_search_view, name='salary_search'),
    path('worksites/', worksite_search_view, name='worksite_search'),
    path('api/company-autocomplete/', company_autocomplete_view, name='company_autocomplete'),
    path('api/job-title-autocomplete/', job_title_autocomplete_view, name='job_title_autocomplete'),

    # Employer Pages
    path('employers/', employer_directory_view, name='employer_directory'),
    path('employer/<slug:slug>/', employer_profile_view, name='employer_profile'),

    # Job Title Pages (using cluster slug)
    path('job-titles/', job_title_directory_view, name='job_title_directory'),
    path('job-title/<slug:slug>/', job_title_profile_view, name='job_title_profile'),

    # SEO-friendly landing pages
    # Employment Based
    path('employment-based/', dashboard_view, {'category': 'employment_based'}, name='employment_based'),
    path('employment-based/<str:country>/', dashboard_view, {'category': 'employment_based'}, name='employment_based_country'),

    # Family Sponsored
    path('family-sponsored/', dashboard_view, {'category': 'family_sponsored'}, name='family_sponsored'),
    path('family-sponsored/<str:country>/', dashboard_view, {'category': 'family_sponsored'}, name='family_sponsored_country'),
]
