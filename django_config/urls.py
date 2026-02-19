"""URL configuration for visa_bulletin project"""

from django.urls import include, path

from webapp.views.seo.sitemaps import robots_view, sitemap_view

urlpatterns = [
    path('robots.txt', robots_view, name='robots'),
    path('sitemap.xml', sitemap_view, name='sitemap'),
    path('', include('webapp.urls')),
]
