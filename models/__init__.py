# Models package
# 
# IMPORTANT: Do NOT import models at module level here!
# Model imports are handled in models/apps.py in the ready() method.
# Importing models here causes AppRegistryNotReady errors during django.setup().
#
# Models are still discoverable by Django because:
# - AppConfig.ready() imports all models (see models/apps.py)
# - makemigrations can import models directly from their modules (e.g., from models.salary import Employer)
# - System checks run after Django is fully initialized, so models are available then
#
# Explicitly make models available at package level (but don't import them here)
__all__ = ['DataSource', 'IngestRun', 'IngestVersion', 'IngestRejectionStats', 'RejectionReason']

# Ensure Django can discover the app config
default_app_config = 'models.apps.ModelsConfig'


