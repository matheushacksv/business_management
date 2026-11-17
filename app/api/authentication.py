from ninja_jwt.authentication import JWTAuth

from api.endpoints.auth import ACCESS_COOKIE


class CookieJWTAuth(JWTAuth):
    """JWT from the httpOnly session cookie (browser) or `Authorization: Bearer` (scripts, tests)."""

    def __call__(self, request):
        token = request.COOKIES.get(ACCESS_COOKIE)
        if token:
            return self.authenticate(request, token)
        return super().__call__(request)
