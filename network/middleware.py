import base64
import secrets

from django.conf import settings
from django.http import HttpResponse


class PlatformBasicAuthMiddleware:
    """Gates the whole backend behind HTTP Basic Auth, checked against
    settings.PLATFORM_BASIC_AUTH_USERS (a {username: password} dict).

    Placed right after CorsMiddleware (which must stay first) so that even a
    401 from here still gets Access-Control-* headers attached on the way
    out -- otherwise the browser reports a same-origin-looking auth failure
    as an opaque CORS error instead. Independent of per-user login
    (django-allauth) and DRF permission classes.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not settings.PLATFORM_BASIC_AUTH_ENABLED:
            return self.get_response(request)

        # CORS preflight requests never carry credentials (browsers omit
        # Authorization on OPTIONS), so gating them here would block
        # CorsMiddleware from ever attaching Access-Control-* headers.
        # Preflights carry no data, so it's safe to let them pass through.
        if request.method == "OPTIONS":
            return self.get_response(request)

        if self._is_authorized(request):
            return self.get_response(request)

        response = HttpResponse("Authentication required", status=401)
        response["WWW-Authenticate"] = 'Basic realm="DyHealthNet"'
        return response

    @staticmethod
    def _is_authorized(request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        scheme, _, credentials = header.partition(" ")
        if scheme.lower() != "basic" or not credentials:
            return False

        try:
            decoded = base64.b64decode(credentials).decode("utf-8")
            username, _, password = decoded.partition(":")
        except (ValueError, UnicodeDecodeError):
            return False

        expected_password = settings.PLATFORM_BASIC_AUTH_USERS.get(username)
        if expected_password is None:
            return False
        return secrets.compare_digest(password, expected_password)
