from django.contrib.auth.models import User
from django.db import IntegrityError
from django.http import JsonResponse
from django.contrib.auth import authenticate, login, logout
from rest_framework import generics
from drf_spectacular.utils import extend_schema_view

from network.schemas.authentication_schemas import *


@extend_schema_view(
    post=login_schema
)
class LoginView(generics.GenericAPIView):
    @staticmethod
    def post(request, *args, **kwargs):
        params = request.data
        username = params['username']
        password = params['password']
        print(f'username: {username}')

        user = authenticate(request, username=username, password=password)
        print(f'user: {user}')
        if user is not None:
            login(request, user)
            print(f'Log in worked')
            return JsonResponse({'status': 'success', 'message': 'Logged in successfully'}, status=200)

        print(f'Not logged in')
        return JsonResponse({'status': 'error', 'message': 'Invalid username or password'}, status=401)


@extend_schema_view(
    post=register_schema
)
class RegisterView(generics.GenericAPIView):
    @staticmethod
    def post(request, *args, **kwargs):
        params = request.data
        username = params['username']
        password = params['password']
        print(f'username: {username}')
        print(f'password: {password}')

        try:
            User.objects.create_user(username=username, password=password)
            print("User created successfully")
        except IntegrityError:
            print(f'Not logged in')
            return JsonResponse({'status': 'error', 'message': 'Username already exists'}, status=401)

        authenticated_user = authenticate(username=username, password=password)
        print(f'user: {authenticated_user}')
        if authenticated_user is not None:
            login(request, authenticated_user)
            print(f'Sign up worked')
            return JsonResponse({'status': 'success', 'message': 'Signed up and logged in successfully'}, status=200)

        print(f'Not logged in')
        return JsonResponse({'status': 'error', 'message': 'Invalid username or password'}, status=401)


@extend_schema_view(
    post=logout_schema
)
class LogoutView(generics.GenericAPIView):
    @staticmethod
    def post(request):
        if not request.user.is_authenticated:
            return JsonResponse(
                {'status': 'error', 'message': 'No active session to log out from.'},
                status=400
            )
        logout(request)
        return JsonResponse({'status': 'success', 'message': 'Logged out successfully'}, status=200)


@extend_schema_view(
    get=check_login_schema
)
class CheckLoginStatusView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        print(f"Received CSRF token header: {request.headers.get('X-CSRFToken')}")
        print(f"Cookie CSRF token: {request.COOKIES.get('csrftoken')}")
        if request.user.is_authenticated:
            return JsonResponse({"is_logged_in": True, "username": request.user.username}, status=200)
        else:
            return JsonResponse({"is_logged_in": False}, status=401)
