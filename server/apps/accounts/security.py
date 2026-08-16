from django.http import HttpRequest


def session_auth(request: HttpRequest):
    return request.user if request.user.is_authenticated else None


def admin_auth(request: HttpRequest):
    u = request.user
    return u if (u.is_authenticated and getattr(u, "is_admin", False)) else None
