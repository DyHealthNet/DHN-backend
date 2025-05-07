from drf_spectacular.utils import extend_schema, OpenApiTypes, OpenApiParameter, OpenApiExample, OpenApiResponse

get_table_schema = extend_schema(
        summary="Returns data statistics to be plotted in the Overview Table",
        description='Returns data counts of the different omics data types found in the cohort. If a sessionid and '
                    'contextValue is provided, the data will be filtered by the respective context.',
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
            200: OpenApiResponse(
                description="Data statistics returned successfully",
            ),
            405: OpenApiResponse(
                description="Context not found",
            ),
        }
    )

get_data_schema = extend_schema(
        summary="Returns averaged data for the given variables x and y grouped by c (optional) to produce a Line Plot",
        description="""Returns averaged data for the given variables x (e.g. time) and y (e.g. dosage) in JSON format 
            to produce a Line Plot. The optional parameter c (e.g. sex) allows for comparisons between different groups 
            such as males and females. If a sessionid and contextValue is provided, the data will be filtered by the
            respective context.
            """,
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
            OpenApiParameter(
                name='x',
                description='variable x',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='y',
                description='variable y',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='c',
                description='colour variable',
                required=False,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            )
        ],
        responses={
            200: OpenApiResponse(
                description="Data returned successfully",
            ),
            405: OpenApiResponse(
                description="The data could not be returned, possible errors:\n"
                            "- No appropriate context found\n"
                            "- x and y are not valid\n"
                            "- y is not numerical and cannot be visualized in a line plot\n"
                            "- c is not valid\n"
                            "- x and y are the same"
            )
        }
    )

get_bar_count_schema = extend_schema(
        summary="Returns the count for the given variables x grouped by c (optional) to produce a Variable Count "
                "Bar Plot",
        description="""Returns averaged data for the given variables x (e.g. time) in JSON format to produce a 
            Variable Count Bar Plot. The optional parameter c (e.g. sex) allows for comparisons between different groups 
            such as males and females. If a sessionid and contextValue is provided, the data will be filtered by the
            respective context.
            """,
        parameters=[
            OpenApiParameter(
                name='x',
                description='variable x',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='c',
                description='colour variable',
                required=False,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
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
            200: OpenApiResponse(
                description="Data returned successfully",
            ),
            405: OpenApiResponse(
                description="The data could not be returned, possible errors:\n"
                            "- No appropriate context found\n"
                            "- x is not valid\n"
                            "- c is not valid\n"
                            "- x and c are the same"
            )
        }
    )

get_density_plot_schema = extend_schema(
        summary="Returns gaussian kde density values for the variable x grouped by c (optional) to produce a "
                "Density Plot",
        description="""Returns gaussian kde density values for the given variable x (e.g. bmi) in JSON format 
            to produce a Density Plot. The optional parameter c (e.g. sex) allows for comparisons between different 
            groups such as males and females and the optional parameter bandwidth allows adjusting the smoothness of 
            the curves. If a sessionid and contextValue is provided, the data will be filtered by the respective 
            context.
            """,
        parameters=[
            #TODO is this required though?
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
            OpenApiParameter(
                name='x',
                description='variable x',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='c',
                description='colour variable',
                required=False,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='bandwidth',
                description='bandwidth is used to scale the standard deviation of the kernel, it expects a positive '
                            'float while a higher number results in a smoother curve',
                required=False,
                type=OpenApiTypes.FLOAT,
                location=OpenApiParameter.QUERY,
            ),
        ],
        responses={
            200: OpenApiResponse(
                description="Data returned successfully",
            ),
            405: OpenApiResponse(
                description="The data could not be returned, possible errors:\n"
                            "- No appropriate context found\n"
                            "- x is not valid\n"
                            "- c is not valid"
            )
        }
    )


get_box_plot_schema = extend_schema(
        summary="Returns boxplot statistics for the given variables x and y grouped by c (optional) to produce a Box "
                "Plot",
        description="""Returns boxplot statistics for the given variables x (e.g. time) and y (e.g. dosage) in JSON 
            format to produce a Box Plot. The optional parameter c (e.g. sex) allows for comparisons between different 
            groups such as males and females. If a sessionid and contextValue is provided, the data will be filtered by
            the respective context.
            """,
        parameters=[
            OpenApiParameter(
                name='x',
                description='variable x',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='y',
                description='variable y',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='c',
                description='colour variable',
                required=False,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
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
            200: OpenApiResponse(
                description="Data returned successfully",
            ),
            405: OpenApiResponse(
                description="The data could not be returned, possible errors:\n"
                            "- No appropriate context found\n"
                            "- y is not numerical and cannot be visualized in a box plot\n"
                            "- x and y are not valid\n"
                            "- c is not valid\n"
                            "- x and y are the same"
            )
        }
    )

heatmap_schema = extend_schema(
        summary="Returns contingency table for the given variables x and y for plotting a Heatmap",
        description="""Returns contingency table for the given categorical variables x (e.g. sex) and y (e.g. desease 
            stage) for plotting a Heatmap in JSON format. """,
        parameters=[
            OpenApiParameter(
                name='x',
                description='variable x',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='y',
                description='variable y',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
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
            200: OpenApiResponse(
                description="Data returned successfully",
            ),
            405: OpenApiResponse(
                description="The data could not be returned, possible errors:\n"
                            "- No appropriate context found\n"
                            "- x and y are not valid\n"
                            "- x and y are the same"
            )
        }
    )