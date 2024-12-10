from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes
from drf_spectacular.types import OpenApiTypes

login_schema = extend_schema(
    summary="Logs in user",
    description="Logs a user in using their username and password.",
    request={
        'application/json': {
            'type': 'object',
            'properties': {
                'username': {
                    'type': 'string',
                    'description': 'Name of the user.',
                },
                'password': {
                    'type': 'string',
                    'description': 'Password of the user.',
                },
            },
            'required': ['username', 'password'],
            'example': {
                'username': 'example_user',
                'password': 'example_password',
            }
        },
    },
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
    parameters=[
        OpenApiParameter(
            name='X-CSRFToken',
            description='The CSRF token provided in the request header.',
            required=True,
            type=OpenApiTypes.STR,
            location=OpenApiParameter.HEADER,
        ),
    ],
)

register_schema = extend_schema(
    summary="Register a new user",
    description="Registers a new user with a username and password if not already registered/ "
                "username already exists. If the registration is successful, the user is logged in.",
    parameters=[
        OpenApiParameter(
            name='X-CSRFToken',
            description='The CSRF token provided in the request header',
            required=True,
            type=OpenApiTypes.STR,
            location=OpenApiParameter.HEADER,
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
)

logout_schema = extend_schema(
    summary="Log out user",
    description="Logs the current user out if they are logged in using the provided CSRF token as credentials",
    parameters=[
        OpenApiParameter(
            name='X-CSRFToken',
            description='The CSRF token provided in the request header',
            required=True,
            type=OpenApiTypes.STR,
            location=OpenApiParameter.HEADER,
        ),
    ],
)

check_login_schema = extend_schema(
    summary="Get the login status of the current user",
    description=(
        "Check the login status of the current user. The provided CSRF token by the client is checked "
        "to ensure the session is secure and if the user is logged in. (If so username is returned.) "
    ),
    parameters=[
        OpenApiParameter(
            name='X-CSRFToken',
            description='The CSRF token provided in the request header.',
            required=True,
            type=OpenApiTypes.STR,
            location=OpenApiParameter.HEADER,
        )
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
