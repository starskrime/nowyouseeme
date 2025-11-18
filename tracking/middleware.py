from django.utils.deprecation import MiddlewareMixin


class DisableCSRFForTrackingMiddleware(MiddlewareMixin):
    """
    Disable CSRF protection for the tracking endpoint
    since it receives requests from external websites
    """
    def process_request(self, request):
        if request.path.startswith('/api/track'):
            setattr(request, '_dont_enforce_csrf_checks', True)
        return None
