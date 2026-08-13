import secrets

from django.conf import settings
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import generics

from network.middleware import PlatformBasicAuthMiddleware

# Platform-wide login page: an in-app replacement for the browser's native
# Basic-Auth popup used by PlatformBasicAuthMiddleware (network/middleware.py).
# Self-contained on purpose (no drf_spectacular schema, separate url module)
# so the whole feature can be removed easily if the platform gate turns out
# to be a dev/staging-only thing. See network/middleware.py for the other
# half (the "/platform-auth/" path bypass and the session check).


class PlatformLoginView(generics.GenericAPIView):
    @staticmethod
    def post(request, *args, **kwargs):
        params = request.data
        username = params.get('username', '')
        password = params.get('password', '')

        expected_password = settings.PLATFORM_BASIC_AUTH_USERS.get(username)
        if expected_password is not None and secrets.compare_digest(password, expected_password):
            request.session['platform_authenticated'] = True
            return JsonResponse({'status': 'success', 'message': 'Logged in successfully'}, status=200)

        return JsonResponse({'status': 'error', 'message': 'Invalid username or password'}, status=401)


@method_decorator(ensure_csrf_cookie, name='dispatch')
class PlatformCheckStatusView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        enabled = settings.PLATFORM_BASIC_AUTH_ENABLED
        # Recognize a request already authorized via cached Basic Auth (e.g. the
        # native browser popup on the initial page load), not just the session
        # flag this page's own form sets - otherwise a request that already
        # satisfies the middleware still gets redirected here redundantly.
        is_authenticated = (not enabled) or PlatformBasicAuthMiddleware._is_authorized(request)
        return JsonResponse({'platform_auth_enabled': enabled, 'is_authenticated': is_authenticated}, status=200)
