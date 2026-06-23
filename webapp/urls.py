"""URL configuration for webapp"""

from django.urls import path, re_path
from django.views.generic import RedirectView

from webapp.views.blog_views import blog_detail, blog_list
from webapp.views.bulletin.dashboard import dashboard_view
from webapp.views.bulletin.prediction_month_forecast import (
    prediction_month_forecast_view,
)
from webapp.views.bulletin.priority_date_landing import priority_date_landing_view
from webapp.views.bulletin.vqs_api import VQSPredictView
from webapp.views.employers.directory import (
    company_autocomplete_view,
    employer_directory_view,
)
from webapp.views.employers.profile import employer_profile_view
from webapp.views.employers.rankings import employer_rankings_view
from webapp.views.job_titles.directory import (
    job_title_autocomplete_view,
    job_title_directory_view,
)
from webapp.views.job_titles.profile import job_title_profile_view
from webapp.views.prediction_views import (
    metric_report_view,
    prediction_category_landing,
    prediction_detail,
    prediction_list,
    spaghetti_view,
)
from webapp.views.salary.by_state import salary_by_state_view
from webapp.views.salary.search import salary_search_view, worksite_search_view
from webapp.views.static.pages import (
    about_view,
    contact_view,
    faq_view,
    health_view,
    next_bulletin_view,
    spanish_landing_view,
)

urlpatterns = [
    path("analysis/", blog_list, name="blog_list"),
    path("analysis/<slug:slug>/", blog_detail, name="blog_detail"),
    path("spaghetti/", spaghetti_view, name="spaghetti"),
    path("metric-report/", metric_report_view, name="metric_report"),
    path("", dashboard_view, name="dashboard"),
    path("predictions/", prediction_list, name="prediction_list"),
    # Evergreen per-month FORECAST landing (e.g. /predictions/october-2026/).
    # Tight pattern (monthname-20YY) so it never shadows the category/legacy
    # routes below; MUST precede predictions/<str:category>/ which would
    # otherwise capture the slug. Renders only future months from stored
    # predictions; published months 301 to the accuracy archive.
    re_path(
        r"^predictions/(?P<slug>[a-z]+-20\d{2})/$",
        prediction_month_forecast_view,
        name="prediction_month_forecast",
    ),
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
    # After legacy YYYY-M so /predictions/2024-3/ is not captured as a category
    path(
        "predictions/<str:category>/",
        prediction_category_landing,
        name="prediction_category_landing",
    ),
    path("health/", health_view, name="health"),
    # Static pages
    path("faq/", faq_view, name="faq"),
    path("when-is-the-next-visa-bulletin/", next_bulletin_view, name="next_bulletin"),
    path("about/", about_view, name="about"),
    path("contact/", contact_view, name="contact"),
    # Spanish landing — single-page explainer for "boletín de visas" search demand
    path("es/", spanish_landing_view, name="spanish_landing"),
    # Salary Database
    path("salaries/", salary_search_view, name="salary_search"),
    # Deep salary URLs — role/employer redirects to canonical profile pages,
    # by-state has its own per-state landing page.
    path(
        "salaries/role/<slug:slug>/",
        RedirectView.as_view(url="/job-title/%(slug)s/", permanent=True),
        name="salary_role_redirect",
    ),
    path(
        "salaries/employer/<slug:slug>/",
        RedirectView.as_view(url="/employer/%(slug)s/", permanent=True),
        name="salary_employer_redirect",
    ),
    path(
        "salaries/by-state/<slug:state>/",
        salary_by_state_view,
        name="salary_by_state",
    ),
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
    path("employers/rankings/", employer_rankings_view, name="employer_rankings"),
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
    # Priority-date landing pages (per EB class x per country, SEO)
    path(
        "priority-date/<slug:eb_class>/<slug:country>/",
        priority_date_landing_view,
        name="priority_date_landing",
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
