from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes
from drf_spectacular.types import OpenApiTypes

login_schema = extend_schema(
    summary="Logs in user",
    description="Logs a user in using their username and password.",
    parameters=[
        OpenApiParameter(
            name='csrftoken',
            description='The CSRF token provided in the request header.',
            required=True,
            type=OpenApiTypes.STR,
            location=OpenApiParameter.COOKIE,
        ),
        OpenApiParameter(
            name='username',
            description='Name of user',
            required=True,
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
        ),
        OpenApiParameter(
            name='password',
            description='Password of user',
            required=True,
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
        )
    ],
    responses={
        200: {
            'description': 'Login successful.',
            'type': 'object',
            'properties': {
                'status': {
                    'type': 'string',
                    'description': 'Status of the login attempt.',
                },
                'message': {
                    'type': 'string',
                    'description': 'Message of the login attempt.',
                },
            },
            'example': {
                'status': 'success',
                'message': 'Logged in successfully'
            }
        },
        401: {
            'description': 'Invalid credentials or missing fields.',
            'type': 'object',
            'properties': {
                'status': {
                    'type': 'string',
                    'description': 'Status of the login attempt.',
                },
                'message': {
                    'type': 'string',
                    'description': 'Message of the login attempt.',
                },
            },
            'example': {
                'status': 'error',
                'message': 'Invalid username or password'
            }
        },
    },
)

register_schema = extend_schema(
    summary="Register a new user",
    description="Registers a new user with a username and password if not already registered/ "
                "username already exists. If the registration is successful, the user is logged in.",
    parameters=[
        OpenApiParameter(
            name='csrftoken',
            description='The CSRF token for authentication.',
            required=True,
            type=OpenApiTypes.STR,
            location=OpenApiParameter.COOKIE,
        ),
        OpenApiParameter(
            name='username',
            description='Name of user',
            required=True,
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
        ),
        OpenApiParameter(
            name='password',
            description='Password of user',
            required=True,
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
        ),
    ],
    responses={
        200: {
            'description': 'Registration successful.',
            'type': 'object',
            'properties': {
                'status': {
                    'type': 'string',
                    'description': 'Status of the registration attempt.',
                },
                'message': {
                    'type': 'string',
                    'description': 'Message of the registration attempt.',
                },
            },
            'example': {
                'status': 'success',
                'message': 'Registered and logged in successfully'
            }
        },
        401: {
            'description': 'Invalid credentials or missing fields.',
            'type': 'object',
            'properties': {
                'status': {
                    'type': 'string',
                    'description': 'Status of the registration attempt.',
                },
                'message': {
                    'type': 'string',
                    'description': 'Message of the registration attempt.',
                },
            },
            'example': {
                'status': 'error',
                'message': 'Username already exists'
            }
        },
    }
)

logout_schema = extend_schema(
    summary="Log out user",
    description="Logs the current user out if they are logged in using the provided CSRF token as credentials",
    parameters=[
        OpenApiParameter(
            name='csrftoken',
            description='The CSRF token for authentication.',
            required=True,
            type=OpenApiTypes.STR,
            location=OpenApiParameter.COOKIE,
        ),
        OpenApiParameter(
            name="sessionid",
            location=OpenApiParameter.COOKIE,
            required=True,
            description="Session cookie for authentication.",
            type=OpenApiTypes.STR,
        ),
    ],
    responses={
        200: {
            'description': 'Logout successful.',
            'type': 'object',
            'properties': {
                'status': {
                    'type': 'string',
                    'description': 'Status of the logout attempt.',
                },
                'message': {
                    'type': 'string',
                    'description': 'Message of the logout attempt.',
                },
            },
            'example': {
                'status': 'success',
                'message': 'Logged out successfully'
            }
        },
        400: {
            'description': 'No active session to log out from.',
            'type': 'object',
            'properties': {
                'status': {
                    'type': 'string',
                    'description': 'Status of the logout attempt.',
                },
                'message': {
                    'type': 'string',
                    'description': 'Message of the logout attempt.',
                },
            },
            'example': {
                'status': 'error',
                'message': 'No active session to log out from'
            }
        }
    }
)

check_login_schema = extend_schema(
    summary="Get the login status of the current user",
    description=(
        "Check the login status of the current user. The provided CSRF token by the client is checked "
        "to ensure the session is secure and if the user is logged in. (If so username is returned.) "
    ),
    parameters=[
        OpenApiParameter(
            name='csrftoken',
            description='The CSRF token for authentication.',
            required=True,
            type=OpenApiTypes.STR,
            location=OpenApiParameter.COOKIE,
        ),
        OpenApiParameter(
            name="sessionid",
            location=OpenApiParameter.COOKIE,
            required=True,
            description="Session cookie for authentication.",
            type=OpenApiTypes.STR,
        ),
    ],
    responses={
        200: {
            "description": "User is logged in.",
            "content": {
                "application/json": {
                    "example": {
                        "is_logged_in": True,
                        "username": "example_user"
                    }
                }
            }
        },
        401: {
            "description": "User is not logged in.",
            "content": {
                "application/json": {
                    "example": {
                        "is_logged_in": False
                    }
                }
            }
        }
    }
)
