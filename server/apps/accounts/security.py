from django.http import HttpRequest
from ninja.security import SessionAuth


class _SessionAuth(SessionAuth):
    """Session-cookie auth with Ninja's CSRF enforcement (csrf=True in base)."""

    def authenticate(self, request: HttpRequest, key):
        return request.user if request.user.is_authenticated else None


class _AdminAuth(SessionAuth):
    def authenticate(self, request: HttpRequest, key):
        user = request.user
        if user.is_authenticated and getattr(user, "is_admin", False):
            return user
        return None


session_auth = _SessionAuth()
admin_auth = _AdminAuth()
