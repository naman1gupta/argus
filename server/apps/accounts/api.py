from django.contrib.auth import authenticate, login, logout
from django.views.decorators.csrf import ensure_csrf_cookie
from ninja import Router, Schema
from ninja.decorators import decorate_view
from ninja.errors import HttpError
from ninja.security import django_auth

router = Router(tags=["auth"])


class LoginIn(Schema):
    username: str
    password: str


class MeOut(Schema):
    username: str
    role: str


@router.post("/login", response=MeOut)
def login_view(request, payload: LoginIn):
    user = authenticate(request, username=payload.username, password=payload.password)
    if user is None:
        raise HttpError(401, "Invalid credentials")
    login(request, user)
    return MeOut(username=user.username, role=user.role)


@router.post("/logout", auth=django_auth)
def logout_view(request):
    logout(request)
    return {"ok": True}


# ensure_csrf_cookie: the SPA calls this first; the cookie it sets is echoed
# back as X-CSRFToken on subsequent session-authenticated POSTs.
@router.get("/me", response=MeOut, auth=django_auth)
@decorate_view(ensure_csrf_cookie)
def me(request):
    return MeOut(username=request.user.username, role=request.user.role)
