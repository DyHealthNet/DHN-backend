from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, OpenApiParameter

get_table_schema = extend_schema(
        summary="Returns data statistics to be plotted in the Overview Table",
        description='Returns data statistics (of phenotype, metabolite and protein data) to be plotted in the Overview '
                    'Table in JSON format.'
                    'e.g. '
    )

get_data_schema = extend_schema(
        summary="Returns averaged data for the given variables x and y grouped by c (optional) to produce a Line Plot",
        description="""Returns averaged data for the given variables x (e.g. time) and y (e.g. dosage) in JSON format 
            to produce a Line Plot. The optional parameter c (e.g. sex) allows for comparisons between different groups 
            such as males and females.
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
            )
        ],
    )

get_bar_count_schema = extend_schema(
        summary="Returns the count for the given variables x grouped by c (optional) to produce a Variable Count "
                "Bar Plot",
        description="""Returns averaged data for the given variables x (e.g. time) in JSON format to produce a 
            Variable Count Bar Plot. The optional parameter c (e.g. sex) allows for comparisons between different groups 
            such as males and females.
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
            )
        ],
    )

get_box_plot_schema = extend_schema(
        summary="Returns boxplot statistics for the given variables x and y grouped by c (optional) to produce a Box "
                "Plot",
        description="""Returns boxplot statistics for the given variables x (e.g. time) and y (e.g. dosage) in JSON 
            format to produce a Box Plot. The optional parameter c (e.g. sex) allows for comparisons between different 
            groups such as males and females.
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
            )
        ],
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
            )
        ],
    )