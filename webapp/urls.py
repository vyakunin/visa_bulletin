"""URL configuration for webapp"""

from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    
    # Static pages
    path('faq/', views.faq_view, name='faq'),
    path('about/', views.about_view, name='about'),
    path('contact/', views.contact_view, name='contact'),
    
    # Salary Database
    path('salaries/', views.salary_search_view, name='salary_search'),
    path('worksites/', views.worksite_search_view, name='worksite_search'),
    path('api/company-autocomplete/', views.company_autocomplete_view, name='company_autocomplete'),
    
    # SEO-friendly landing pages
    # Employment Based
    path('employment-based/', views.dashboard_view, {'category': 'employment_based'}, name='employment_based'),
    path('employment-based/<str:country>/', views.dashboard_view, {'category': 'employment_based'}, name='employment_based_country'),
    
    # Family Sponsored
    path('family-sponsored/', views.dashboard_view, {'category': 'family_sponsored'}, name='family_sponsored'),
    path('family-sponsored/<str:country>/', views.dashboard_view, {'category': 'family_sponsored'}, name='family_sponsored_country'),
]
