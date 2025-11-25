"""Middleware for handling session-based location storage."""

class SessionLocationMiddleware:
    """Middleware to initialize session storage for locations.
    
    All users store locations in session only - no database persistence.
    Locations are cleared when session expires or browser closes.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Initialize session location storage if not present
        if 'location_ids' not in request.session:
            request.session['location_ids'] = []

        response = self.get_response(request)
        return response
