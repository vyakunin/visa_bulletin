"""URL configuration for visa_bulletin project"""

from django.urls import path, include

urlpatterns = [
    path('', include('webapp.urls')),
]

