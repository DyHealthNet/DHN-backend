from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

variables_schema = extend_schema(
        summary="Returns all possible variables grouped by their type",
        description='Returns all possible phenotype variables grouped by their type. If a contextValue and a session '
                    'is provided, the endpoint will return the variables that are available for the given contxt. ',
        parameters=[
            OpenApiParameter(
                name='csrftoken',
                description='The CSRF token provided in the request header.',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.COOKIE,
            ),
            OpenApiParameter(
                name="sessionid",
                location=OpenApiParameter.COOKIE,
                required=False,
                description="Session cookie for authentication.",
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name='contextValue',
                description='The value of the context which specifies at which tab it is supposed to be shown.',
                required=False,
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
            ),
        ],
        responses={
            200: {
                'description': 'Returns all possible phenotype variables grouped by their type.',
                'type': 'object',
                'properties': {
                    'binaryCategorical': {
                        'type': 'array'
                    },
                    'continuous': {
                        'type': 'array'
                    },
                    'nonbinaryCategorical': {
                        'type': 'array'
                    },
                },
                'example': {
                    'binaryCategorical': ["a", "b", "c"],
                    'continuous': ["d", "e", "f"],
                    'nonbinaryCategorical': ["g", "h", "i"],
                }
            }
        }
    )