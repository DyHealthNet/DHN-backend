from drf_spectacular.utils import extend_schema, OpenApiTypes, OpenApiParameter, OpenApiExample, OpenApiResponse


create_comparison_schema = extend_schema(
    summary="Start a moDiNA differential network comparison between two contexts",
    description=(
        "Given two contextValues belonging to the logged in user, reuses each context's already-"
        "computed association scores and starts an asynchronous moDiNA differential network "
        "computation (STC node metric, diff-L-P edge metric, optional density-based filtering). "
        "The two contexts must share the same variable set and the same testType/correction (used "
        "when their scores were originally computed) -- these are not request parameters. Returns "
        "a runId to poll via comparisonStatus."
    ),
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
    ],
    request=OpenApiTypes.OBJECT,
    examples=[
        OpenApiExample(
            name="Example request body",
            value={
                "context1": 1,
                "context2": 2,
                "filterTarget": "differential",
                "filterMetric": None,
                "filterRule": None,
                "filterParam": 0.05,
            },
            description=(
                "testType/correction are not request parameters -- they're read from each "
                "context's own params and must match between the two. Only 'density' "
                "filtering is supported for filterMethod (implicit)."
            ),
            request_only=True,
        )
    ],
    responses={
        200: OpenApiResponse(
            description="Comparison started successfully",
            examples={
                "application/json": {
                    "status": "success",
                    "runId": "3f9c9e2e-2b3a-4e9a-9a3a-1a2b3c4d5e6f"
                }
            },
        ),
        400: OpenApiResponse(
            description=(
                "Request was not processed due to one of the following reasons:\n"
                "1. context1/context2 not provided.\n"
                "2. The two contexts do not share the same variables.\n"
                "3. One or both contexts have no recorded testType/correction.\n"
                "4. The two contexts use different testType or correction values."
            ),
        ),
        404: OpenApiResponse(
            description="One or both contexts were not found for the current user.",
        ),
        405: OpenApiResponse(
            description="No parameters provided, or invalid filterTarget.",
        ),
    }
)

comparison_status_schema = extend_schema(
    summary="Get the status of a moDiNA differential network comparison",
    description=(
        "Given a runId returned by createComparison, returns the Celery task status and, once "
        "'SUCCESS', the shaped result (points, links, edgeRanking)."
    ),
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
            name='runId',
            description='runId returned by createComparison',
            required=True,
            type=OpenApiTypes.STR,
        )
    ],
    responses={
        200: OpenApiResponse(
            description="Successfully retrieved the status of the comparison\n"
                        "Can be 'PENDING', 'SUCCESS', 'FAILURE' or 'null'",
        )
    }
)
