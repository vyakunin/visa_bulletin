"""URL configuration for webapp"""

from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    
    # Static pages
    path('faq/', views.faq_view, name='faq'),
    path('about/', views.about_view, name='about'),
    path('contact/', views.contact_view, name='contact'),
    
    # SEO-friendly landing pages
    # Employment Based
    path('employment-based/', views.dashboard_view, {'category': 'employment_based'}, name='employment_based'),
    path('employment-based/<str:country>/', views.dashboard_view, {'category': 'employment_based'}, name='employment_based_country'),
    
    # Family Sponsored
    path('family-sponsored/', views.dashboard_view, {'category': 'family_sponsored'}, name='family_sponsored'),
    path('family-sponsored/<str:country>/', views.dashboard_view, {'category': 'family_sponsored'}, name='family_sponsored_country'),
]
