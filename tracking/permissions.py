from rest_framework import permissions


class HasAPIKeyOrIsStaff(permissions.BasePermission):
    """
    Custom permission to only allow API key authenticated users or staff users.
    """
    def has_permission(self, request, view):
        # Allow staff users (for Django admin browsable API)
        if request.user and request.user.is_staff:
            return True

        # Check if authenticated via API key
        return request.auth is not None


class IsAPISiteOwner(permissions.BasePermission):
    """
    Object-level permission to only allow access to objects belonging to the authenticated site.
    """
    def has_object_permission(self, request, view, obj):
        # Staff users can access everything
        if request.user and request.user.is_staff:
            return True

        # For API key authentication, check if object belongs to the same site
        if hasattr(request, 'auth') and request.auth:
            # request.user should be the Site object from our custom authentication
            if hasattr(obj, 'site'):
                return obj.site == request.user
            # If the object IS a site, check if it matches
            if hasattr(obj, 'id') and hasattr(request.user, 'id'):
                return obj.id == request.user.id

        return False
