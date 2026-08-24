from drf_spectacular.utils import extend_schema, OpenApiTypes, OpenApiParameter, OpenApiExample, OpenApiResponse


context_status_schema = extend_schema(
    summary="Get the status of a context-specific network calculation",
    description="Given a context_value, and the logged in user, this endpoint will return the status of the "
                "context-specific network calculation.",
    parameters=[
        OpenApiParameter(
            name='csrftoken',
            description='CSRF token for authentication.',
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
        OpenApiParameter(
            name='context_value',
            description='context_value of the user-specific context',
            required=True,
            type=OpenApiTypes.INT,
        )
    ],
    responses={
        200: OpenApiResponse(
            description="Successfully retrieved the status of the context\n"
                        "Can either be 'PENDING', 'SUCCESS', 'ERROR' or 'null'.\n"
                        "On 'SUCCESS', 'result' is an object with 'success' (bool), "
                        "'removed_variables' (list of raw variable ids moDiNA dropped because "
                        "they had no usable variation in this context) and "
                        "'dropped_edge_count' (number of pairwise associations moDiNA could not "
                        "compute a valid test statistic for).",
        )
    }
)

create_context_schema = extend_schema(
    summary="Provided a combination of parameters, lets a user create a context-specific network",
    description="Provided a combination of parameters with which the patients are subsampled, this endpoint will "
                "start the calculation of a context-specific network.",
    parameters=[
        OpenApiParameter(
            name="sessionid",
            location=OpenApiParameter.COOKIE,
            required=True,
            description="Session cookie for authentication.",
            type=OpenApiTypes.STR,
        ),
        OpenApiParameter(
            name="csrftoken",
            location=OpenApiParameter.COOKIE,
            required=True,
            description="CSRF token for authentication.",
            type=OpenApiTypes.STR,
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
                        "inside": "AND",
                        "outside": "OR"
                      },
                      "conditions": {
                        "group-0": [
                          {
                            "column": "Peptic/duodenal ulcer (treated last 12 months) (x0cd03d)",
                            "operator": "equals (=)",
                            "value": {
                              "label": "Yes",
                              "value": 1
                            }
                          },
                          {
                            "column": "Sex (x0_sex)",
                            "operator": "equals (=)",
                            "value": {
                              "label": "Male",
                              "value": 1
                            }
                          }
                        ],
                        "group-1": [
                          {
                            "column": "Type of diabetes (x0dm02)",
                            "operator": "in",
                            "value": [
                              {
                                "label": "Juvenile diabetes (type 1)",
                                "value": 1
                              },
                              {
                                "label": "Adult diabetes (type 2)",
                                "value": 2
                              }
                            ]
                          }
                        ]
                      },
                      "contextName": "example",
                      "layers": [
                        "phenotype",
                        "metabolite"
                      ],
                      "subLayers": {
                        "phenotype": [
                          "cardio"
                        ]
                      },
                      "variables": [
                        "Sex (x0_sex)",
                        "Type of diabetes (x0dm02)"
                      ],
                      "missingnessVariables": [
                        "Sex (x0_sex)"
                      ],
                      "missingnessLayers": [
                        "metabolite"
                      ],
                      "missingnessSubLayers": {},
                      "tests": {
                        "catCat": {
                          "label": "Chi-squared test",
                          "value": "chi2"
                        },
                        "catContM": {
                          "label": "ANOVA",
                          "value": "anova"
                        },
                        "catContB": {
                          "label": "T-test",
                          "value": "ttest"
                        },
                        "contCont": {
                          "label": "Pearson correlation",
                          "value": "pearson"
                        }
                      },
                      "contextValue": 2
                    },
                    description="An example of the filtering parameters passed as a JSON string."
                )
            ]
        ),
    ],
    responses={
        200: OpenApiResponse(
            description="Context-specific network calculation started successfully",
            examples={
                "application/json": {
                    "status": "success",
                    "message": "Context creation started"
                }
            },
        ),
        405: OpenApiResponse(
            description=(
                "Request was not processed due to one of the following reasons:\n"
                "1. No context parameters were provided.\n"
                "2. Invalid context parameters were provided."
            ),
            examples={
                "No parameters": {
                    "value": {
                        "status": "error",
                        "message": "No context parameters provided"
                    }
                },
                "Invalid parameters": {
                    "value": {
                        "status": "error",
                        "message": "Invalid context parameters provided"
                    }
                },
            },
        ),
        429: OpenApiResponse(
            description="Request was not processed due to one of the following reasons:\n"
                        "1. Only one context calculation is allowed at a time.\n"
                        "2. Max number of contexts reached.",
            examples={
                "Only one context": {
                    "value": {
                        "status": "error",
                        "message": "You can only start one context creation at a time."
                    }
                },
                "Max number of contexts": {
                    "value": {
                        "status": "error",
                        "message": "You can only create up to 5 objects."
                    }
                },
            }
        )
    }
)



filter_context_schema = extend_schema(
    summary="Provided a combination of parameters, returns a number with the remaining users after subsetting",
    description="Provided a combination of parameters with which the patients are subsetted, this endpoint will "
                "return the number of patients, a context-specific network would include. Note that if, in the backend,"
                "the option 'PRESERVE_PRIVACY' is set, the number of patients returned will be an approximation.",
    parameters=[
        OpenApiParameter(
            name='csrftoken',
            description='The CSRF token provided in the request header',
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
                            "inside": "AND",
                            "outside": "OR"
                        },
                        "conditions": {
                            "group-0": [
                                {
                                    "column": "Peptic/duodenal ulcer (treated last 12 months) (x0cd03d)",
                                    "operator": "equals (=)",
                                    "value": {
                                        "label": "Yes",
                                        "value": 1
                                    }
                                },
                                {
                                    "column": "Sex (x0_sex)",
                                    "operator": "equals (=)",
                                    "value": {
                                        "label": "Male",
                                        "value": 1
                                    }
                                }
                            ],
                            "group-1": [
                                {
                                    "column": "Type of diabetes (x0dm02)",
                                    "operator": "in",
                                    "value": [
                                        {
                                            "label": "Juvenile diabetes (type 1)",
                                            "value": 1
                                        },
                                        {
                                            "label": "Adult diabetes (type 2)",
                                            "value": 2
                                        }
                                    ]
                                }
                            ]
                        },
                        "contextName": "example",
                        "layers": [
                            "phenotype",
                            "metabolite"
                        ],
                        "tests": {
                            "catCat": {
                                "label": "Chi-squared test",
                                "value": "chi2"
                            },
                            "catContM": {
                                "label": "ANOVA",
                                "value": "anova"
                            },
                            "catContB": {
                                "label": "T-test",
                                "value": "ttest"
                            },
                            "contCont": {
                                "label": "Pearson correlation",
                                "value": "pearson"
                            }
                        },
                        "contextValue": 2
                    },
                    description="An example of the filtering parameters passed as a JSON string."
                )
            ]
        )
    ],
    responses={
        200: OpenApiResponse(
            description="Successfully retrieved the number of patients after subsetting",
            examples={
                "application/json": {
                    "result": 100
                }
            }
        ),
        405: OpenApiResponse(
            description=(
                "Request was not processed due to one of the following reasons:\n"
                "1. No context parameters were provided.\n"
                "2. Invalid context parameters were provided."
            ),
            examples={
                "No parameters": {
                    "value": {
                        "status": "error",
                        "message": "No context parameters provided"
                    }
                },
                "Invalid parameters": {
                    "value": {
                        "status": "error",
                        "message": "Invalid context parameters provided"
                    }
                },
            },
        ),
    }
)

delete_context_schema = extend_schema(
        summary="Delete a context of a user",
        description=(
                "Delete a context of a user from all related tables given the context value. User must be logged in."
        ),
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
                required=True,
                description="Session cookie for authentication.",
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name='contextValue',
                description='The value of the context which specifies at which tab it is supposed to be shown.',
                required=True,
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
            ),
        ],
        responses={
            200: OpenApiResponse(
                description="Successfully deleted the context",
                examples={
                    "application/json": {
                        "status": "success",
                        "message": "Context deleted successfully"
                    }
                }
            ),
            400: OpenApiResponse(
                description="No context value provided",
                examples={
                    "application/json": {
                        "status": "error",
                        "message": "Bad request"
                    }
                }
            ),
            401: OpenApiResponse(
                description="Unauthorized",
                examples={
                    "application/json": {
                        "status": "error",
                        "message": "Permission denied. User not authenticated"
                    }
                }
            ),
            404: OpenApiResponse(
                description="Context not found",
                examples={
                    "application/json": {
                        "status": "error",
                        "message": "Context not found"
                    }
                }
            ),
        }
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
                location=OpenApiParameter.QUERY,
            ),
        ],
        responses={
            200: OpenApiResponse(
                description="Successfully retrieved the distribution statistics",
                examples={
                    "application/json": {
                        "result": [0, 5],
                        "type": "bar",
                        "distribution": {
                            'values': [0, 1, 2, 3, 4, 5],
                            'labels': ['0', '1', '2', '3', '4', '5']
                        }
                    }
                }
            ),
            400: OpenApiResponse(
                description="No variable ID provided",
            ),
            404: OpenApiResponse(
                description="Variable not found",
            )
        }
    )

retrieve_context_schema = extend_schema(
        summary="Retrieve Contexts for the current user",
        description=(
                "Get all (for the configured values / tabs [1,MAX_CONTEXT_PER_USER]) Contexts saved in the database "
                "for the current user using the provided CSRF as user credentials. "
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
    )


