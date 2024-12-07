from drf_spectacular.utils import extend_schema, OpenApiTypes, OpenApiParameter, OpenApiExample


create_context_schema = extend_schema(
    summary="Provided a combination of parameters, lets a user create a context-specific network",
    description="Provided a combination of parameters with which the patients are subsampled, this endpoint will "
                "start the calculation of a context-specific network.",
    parameters=[
        OpenApiParameter(
            name='X-CSRFToken',
            description='The CSRF token provided in the request header',
            required=True,
            type=OpenApiTypes.STR,
            location=OpenApiParameter.HEADER,
        ),
        OpenApiParameter(
            name='subset_params',
            description='Custom filtering parameters as a JSON',
            required=True,
            type=OpenApiTypes.OBJECT,
            location=OpenApiParameter.QUERY,
            examples=[
                OpenApiExample(
                    name="Example of test_params_format",
                    value={
                        "connect": {
                            "inside": "and",
                            "outside": "or"
                        },
                        "conditions": {
                            "0": [
                                {
                                    "column": "x0so5385",
                                    "operator": "less",
                                    "value": 4000
                                },
                                {
                                    "column": "x0_sex",
                                    "operator": "equal",
                                    "value": 1
                                }
                            ],
                            "1": [
                                {
                                    "column": "x0so5385",
                                    "operator": "more",
                                    "value": 6000
                                }
                            ]
                        },
                        "tests": {
                            "cont_cont": "pearson",
                            "cat_cat": "chi2",
                            "cat_cont_m": "anova",
                            "cat_cont_b": "ttest",
                        },
                        "layers": ['metabolomics', 'phenomics']
                    },
                    description="An example of the filtering parameters passed as a JSON string."
                )
            ]
        ),
    ]
)

context_status_schema = extend_schema(
    summary="Get the status of a context-specific network calculation",
    description="Given a context_value, and the logged in user, this endpoint will return the status of the "
                "context-specific network calculation.",
    parameters=[
        OpenApiParameter(
            name='X-CSRFToken',
            description='The CSRF token provided in the request header',
            required=True,
            type=OpenApiTypes.STR,
            location=OpenApiParameter.HEADER,
        ),
        OpenApiParameter(
            name='context_value',
            description='context_value of the user-specific context',
            required=True,
            type=OpenApiTypes.STR,
        )
    ]
)

filter_context_schema = extend_schema(
    summary="Provided a combination of parameters, returns a number with the remaining users after subsetting",
    description="Provided a combination of parameters with which the patients are subsetted, this endpoint will "
                "return the number of patients, a context-specific network would include.",
    parameters=[
        OpenApiParameter(
            name='X-CSRFToken',
            description='The CSRF token provided in the request header',
            required=True,
            type=OpenApiTypes.STR,
            location=OpenApiParameter.HEADER,
        ),
        OpenApiParameter(
            name='subset_params',
            description='Custom filtering parameters as a JSON',
            required=True,
            location=OpenApiParameter.QUERY,
            type=OpenApiTypes.OBJECT,
            examples=[
                OpenApiExample(
                    name="Example of test_params_format",
                    value={
                        "connect": {
                            "inside": "and",
                            "outside": "or"
                        },
                        "conditions": {
                            "0": [
                                {
                                    "column": "x0so5385",
                                    "operator": "less",
                                    "value": 4000
                                },
                                {
                                    "column": "x0_sex",
                                    "operator": "equal",
                                    "value": 1
                                }
                            ],
                            "1": [
                                {
                                    "column": "x0so5385",
                                    "operator": "more",
                                    "value": 6000
                                }
                            ]
                        }
                    },
                    description="An example of the filtering parameters passed as a JSON string."
                )
            ]
        )
    ]
)

delete_context_schema = extend_schema(
        summary="Delete a context of a user",
        description=(
                "Delete a context of a user from all related tables given its Tab value."
        ),
        parameters=[
            OpenApiParameter(
                name='X-CSRFToken',
                description='The CSRF token provided in the request header.',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
            ),
            OpenApiParameter(
                name='contextValue',
                description='The value of the context which specifies at which tab it is supposed to be shown.',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
            ),
        ],
    )

variable_info_schema = extend_schema(
        summary="Get distribution statistics for the given variable",
        description=(
                "Get distribution statistics for the given variable Id to be shown to "
                "the user during context creation and filtering"
        ),
        parameters=[
            OpenApiParameter(
                name='variableId',
                description='The variable ID for which the distribution is required',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
            ),
        ],
    )

retrieve_context_schema = extend_schema(
        summary="Retrieve Contexts for the current user",
        description=(
                "Get all (for the configured values / tabs [1,MAX_CONTEXT_PER_USER]) Contexts saved in the database "
                "for the current user using the provided CSRF as user credentials. "
        ),
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


