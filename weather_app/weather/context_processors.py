"""
Context processors for making settings available in templates.
"""

from django.conf import settings


def settings_context(request):
    """
    Add selected settings to template context.
    """
    return {
        "OPENWEATHERMAP_API_KEY": settings.OPENWEATHERMAP_API_KEY,
    }
