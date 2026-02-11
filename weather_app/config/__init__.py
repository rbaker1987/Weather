try:
    from .celery import app as celery_app

    __all__ = ("celery_app",)
except (ImportError, OSError):
    # Handle cases where celery or its dependencies (e.g., gssapi) are not available
    # This can happen in test environments or CI/CD without Kerberos
    celery_app = None
    __all__ = ()
