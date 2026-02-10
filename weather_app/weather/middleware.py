"""Middleware for handling session-based location storage."""

from .models import Location


class SessionLocationMiddleware:
    """Middleware to initialize session storage for locations.

    All users store locations in session only - no database persistence.
    Locations are cleared when session expires or browser closes.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Keep session location storage for anonymous users.
        if "location_ids" not in request.session:
            request.session["location_ids"] = []

        # For authenticated users, mirror owned locations into session.
        if request.user.is_authenticated:
            owner_ids = list(
                Location.objects.filter(owner=request.user, is_active=True).values_list(
                    "id", flat=True
                )
            )
            owner_ids_str = [str(location_id) for location_id in owner_ids]
            if request.session.get("location_ids") != owner_ids_str:
                request.session["location_ids"] = owner_ids_str
                request.session.modified = True

        return self.get_response(request)
