"""URL configuration for webapp"""

from django.urls import path

from webapp.views.blog_views import blog_detail, blog_list
from webapp.views.bulletin.dashboard import dashboard_view
from webapp.views.bulletin.vqs_api import VQSPredictView
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
from webapp.views.prediction_views import (
    prediction_detail,
    prediction_list,
    spaghetti_view,
)
from webapp.views.salary.search import salary_search_view, worksite_search_view
from webapp.views.static.pages import about_view, contact_view, faq_view, health_view

urlpatterns = [
    path("analysis/", blog_list, name="blog_list"),
    path("analysis/<slug:slug>/", blog_detail, name="blog_detail"),
    path("spaghetti/", spaghetti_view, name="spaghetti"),
    path("", dashboard_view, name="dashboard"),
    path("predictions/", prediction_list, name="prediction_list"),
    path(
        "predictions/<str:category>/<int:year>-<int:month>/",
        prediction_detail,
        name="prediction_detail_category",
    ),
    # Legacy URL defaults to employment_based
    path(
        "predictions/<int:year>-<int:month>/",
        prediction_detail,
        {"category": "employment_based"},
        name="prediction_detail",
    ),
    path("health/", health_view, name="health"),
    # Static pages
    path("faq/", faq_view, name="faq"),
    path("about/", about_view, name="about"),
    path("contact/", contact_view, name="contact"),
    # Salary Database
    path("salaries/", salary_search_view, name="salary_search"),
    path("worksites/", worksite_search_view, name="worksite_search"),
    path(
        "api/company-autocomplete/",
        company_autocomplete_view,
        name="company_autocomplete",
    ),
    path(
        "api/job-title-autocomplete/",
        job_title_autocomplete_view,
        name="job_title_autocomplete",
    ),
    path("api/vqs/predict/", VQSPredictView.as_view(), name="vqs_predict"),
    # Employer Pages
    path("employers/", employer_directory_view, name="employer_directory"),
    path("employer/<slug:slug>/", employer_profile_view, name="employer_profile"),
    # Job Title Pages (using cluster slug)
    path("job-titles/", job_title_directory_view, name="job_title_directory"),
    path("job-title/<slug:slug>/", job_title_profile_view, name="job_title_profile"),
    # SEO-friendly landing pages
    # Employment Based
    path(
        "employment-based/",
        dashboard_view,
        {"category": "employment_based"},
        name="employment_based",
    ),
    path(
        "employment-based/<str:country>/",
        dashboard_view,
        {"category": "employment_based"},
        name="employment_based_country",
    ),
    # Family Sponsored
    path(
        "family-sponsored/",
        dashboard_view,
        {"category": "family_sponsored"},
        name="family_sponsored",
    ),
    path(
        "family-sponsored/<str:country>/",
        dashboard_view,
        {"category": "family_sponsored"},
        name="family_sponsored_country",
    ),
]
