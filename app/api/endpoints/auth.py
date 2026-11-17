"""Session in httpOnly cookies: JavaScript never sees the tokens (an XSS can't steal them).

- ge_access  (path /api)      short-lived JWT read by CookieJWTAuth on every request
- ge_refresh (path /api/auth) long-lived JWT, only sent to the refresh/logout endpoints
SameSite=Strict keeps other sites from sending them (CSRF): the app and the API share
one origin (Traefik in prod, Nitro proxy in dev), so it never needs cross-site cookies.
"""

from django.conf import settings
from django.contrib.auth import authenticate
from django.http import HttpResponse
from ninja import Router, Schema
from ninja_jwt.exceptions import TokenError
from ninja_jwt.settings import api_settings as jwt_settings
from ninja_jwt.tokens import RefreshToken

from apps.users.models import User

router = Router(tags=['Auth'])

ACCESS_COOKIE = 'ge_access'
REFRESH_COOKIE = 'ge_refresh'
REFRESH_PATH = '/api/auth'


class LoginIn(Schema):
    email: str
    password: str


def _set_session(response: HttpResponse, user: User) -> None:
    refresh = RefreshToken.for_user(user)  # every refresh rotates: the 7 days count from the last use
    common = {'httponly': True, 'secure': not settings.DEBUG, 'samesite': 'Strict'}
    response.set_cookie(
        ACCESS_COOKIE, str(refresh.access_token), path='/api',
        max_age=int(jwt_settings.ACCESS_TOKEN_LIFETIME.total_seconds()), **common,
    )
    response.set_cookie(
        REFRESH_COOKIE, str(refresh), path=REFRESH_PATH,
        max_age=int(jwt_settings.REFRESH_TOKEN_LIFETIME.total_seconds()), **common,
    )


def _clear_session(response: HttpResponse) -> None:
    response.delete_cookie(ACCESS_COOKIE, path='/api', samesite='Strict')
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH, samesite='Strict')


# ponytail: no login rate limit yet; add django-axes (or a per-IP counter) if brute force becomes a concern
@router.post('/auth/login', auth=None, response={204: None, 401: dict})
def login_endpoint(request, response: HttpResponse, data: LoginIn):
    user = authenticate(request, email=data.email.strip().lower(), password=data.password)
    if user is None:  # wrong credentials or inactive user
        return 401, {'detail': 'Invalid email or password'}
    _set_session(response, user)
    return 204, None


@router.post('/auth/refresh', auth=None, response={204: None, 401: dict})
def refresh_endpoint(request, response: HttpResponse):
    try:
        token = RefreshToken(request.COOKIES.get(REFRESH_COOKIE, ''))
        user = User.objects.get(pk=token[jwt_settings.USER_ID_CLAIM], is_active=True)
    except (TokenError, User.DoesNotExist):
        _clear_session(response)
        return 401, {'detail': 'Session expired'}
    # ponytail: old refresh tokens stay valid until they expire (no blacklist); add
    # ninja_jwt.token_blacklist if a stolen-refresh scenario must be revocable
    _set_session(response, user)
    return 204, None


@router.post('/auth/logout', auth=None, response={204: None})
def logout_endpoint(request, response: HttpResponse):
    _clear_session(response)
    return 204, None
