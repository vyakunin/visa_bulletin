"""Django app configuration for webapp"""

from django.apps import AppConfig


class WebappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'webapp'
    verbose_name = 'Visa Bulletin Dashboard'

