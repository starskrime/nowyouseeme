from rest_framework import authentication, exceptions
from django.utils import timezone
from .models import APIKey


class APIKeyAuthentication(authentication.BaseAuthentication):
    """
    Custom authentication class for API key-based authentication.
    Expects the API key in the Authorization header as: Authorization: Bearer <api_key>
    """
    keyword = 'Bearer'

    def authenticate(self, request):
        auth = request.META.get('HTTP_AUTHORIZATION', '')

        if not auth:
            return None

        try:
            parts = auth.split()
            if len(parts) != 2 or parts[0].lower() != self.keyword.lower():
                return None

            api_key = parts[1]
        except (ValueError, UnicodeDecodeError):
            raise exceptions.AuthenticationFailed('Invalid API key header')

        return self.authenticate_credentials(api_key)

    def authenticate_credentials(self, key):
        try:
            api_key = APIKey.objects.select_related('site').get(key=key, is_active=True)
        except APIKey.DoesNotExist:
            raise exceptions.AuthenticationFailed('Invalid or inactive API key')

        # Update last_used timestamp
        api_key.last_used = timezone.now()
        api_key.save(update_fields=['last_used'])

        # Return (user, auth) tuple - we use site as the user equivalent
        return (api_key.site, api_key)

    def authenticate_header(self, request):
        return self.keyword
