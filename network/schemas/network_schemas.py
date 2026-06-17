from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

typeahead_schema = extend_schema(
        summary="Returns node id/name recommendations depending on the input request typed by the user",
        description="""Returns a dictionary of node ids in JSON format containing a display name, description, and 
        source_table (/node_type) (as dictionary) depending on the input request typed by the user which is sent via
         (sub)string s. (Referring to function orm_queries/typeahead_query)
            """,
        parameters=[
            OpenApiParameter(
                name='s',
                description='typed query string',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            )
        ],
        responses={
            200: OpenApiResponse(
                description="Successfully retrieved node recommendations",
            ),
            400: OpenApiResponse(
                description="No context value provided",
                examples={
                    "application/json": {
                        'status': 'error',
                        'message': 'Search failed. User not authenticated and '
                                     'cannot inneract with a context'
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

all_externals_schema = extend_schema(
        summary="Returns all external edges and their nodes for a query node q",
        description="""Returns all external edges and their nodes for a query node q in JSON format. Maps external edges
            where the partner node exists as a chris node back otherwise returns external node.
            e.g. input: q="x0rd09"
            """,
        parameters=[
            OpenApiParameter(
                name='q',
                description='query id/ node id',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            )
        ],
        responses={
            200: OpenApiResponse(
                description="Successfully retrieved external nodes",
            )
        }
    )

get_network_schema = extend_schema(
        summary="Returns the top or all significant network edges and corresponding nodes that are connected to a "
                "query node q",
        description="""Returns for a query node q the top l (limit) significant network edges and corresponding nodes 
            if l is set, or all significant ones for each type (meaning protein, metabolite, phenotype 
            e.g. for limit 10 -> 30 edges)) in JSON format. Significance is determined depending on the given 
            significance threshold s and the selected test type's and multiple testing correction which are given with o
            in JSON fromat. 
            To efficiently query the correct tables the type of input node as a variable t is required. 
            (Referring to function orm_queries/network_query.)
            e.g. input: q="x0rd09",t="phenotype",l = "3", s = "0.05", o = "{
                catCat: {label: 'Chi-squared test', value: 'chi2'}, catContM: {label: 'ANOVA', value: 'anova'},
                multTest: {label: 'Benjamini Hochberg (FDR)', value: 'benjamini_hb'},
                catContB: {label: 'T-test', value: 'ttest'}, contCont: {label: 'Pearson correlation', value: 'pearson'}
              }"
            """,
        parameters=[
            OpenApiParameter(
                name='q',
                description='query id/ node id',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='t',
                description='query type/ node type',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='l',
                description='limit (concerning node retrieval)',
                required=False,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='s',
                description='significance threshold',
                required=True,
                type=OpenApiTypes.FLOAT,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='o',
                description='options of selected tests & testing correction',
                required=True,
                type=OpenApiTypes.OBJECT,
                location=OpenApiParameter.QUERY,
            )

        ],
        responses={
            200: OpenApiResponse(
                description="Successfully retrieved nodes and edges",
            ),
            405: OpenApiResponse(
                description=(
                    "Request was not processed due to one of the following reasons:\n"
                    "1. query nodes q, limit l or per type variable p was not provided.\n"
                    "2. Missing key in selected options parameter o.\n"
                    "3. l > 50 or p is neither true or false. "
                ),
            )
        }
    )

get_network_context_schema = extend_schema(
        summary="Returns the top or all significant network edges and corresponding nodes that are connected to a "
                "query node q for a given context",
        description="""Returns for a query node q the top l (limit) significant network edges and corresponding nodes 
            if l is set, or all significant ones for each type (meaning protein, metabolite, phenotype 
            e.g. for limit 10 -> 30 edges)) in JSON format. Significance is determined depending on the given 
            significance threshold s and the selected test type's and multiple testing correction which are given with o
            in JSON fromat. 
            To efficiently query the correct tables the type of input node as a variable t is required.
            The query is restricted to the currently selected context of the user which is derived from the users id, 
            which requires that a user is logged in (otherwise the request fails) and the context value c of the 
            selected context.
            (Referring to function orm_queries/network_query.)
            e.g. input: q="x0rd09",t="phenotype",l = "3", s = "0.05", c="3", o = "{
                catCat: {label: 'Chi-squared test', value: 'chi2'}, catContM: {label: 'ANOVA', value: 'anova'},
                multTest: {label: 'Benjamini Hochberg (FDR)', value: 'benjamini_hb'},
                catContB: {label: 'T-test', value: 'ttest'}, contCont: {label: 'Pearson correlation', value: 'pearson'}
              }"
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
                required=True,
                description="Session cookie for authentication.",
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name='c',
                description='The value of the context which specifies at which tab it is supposed to be shown '
                            'specific for the authenticated user.',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='q',
                description='query id/ node id',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='t',
                description='query type/ node type',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='l',
                description='limit (concerning node retrieval)',
                required=False,
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='s',
                description='significance threshold',
                required=True,
                type=OpenApiTypes.FLOAT,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='o',
                description='options of selected tests & testing correction',
                required=True,
                type=OpenApiTypes.OBJECT,
                location=OpenApiParameter.QUERY,
            )

        ],
        responses={
            200: OpenApiResponse(
                description="Successfully retrieved nodes and edges",
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
            405: OpenApiResponse(
                description=(
                    "Request was not processed due to one of the following reasons:\n"
                    "1. query node q, limit l, per type variable p or context value c was not provided.\n"
                    "2. Missing key in selected options parameter o.\n"
                    "3. l > 50 or p is neither true or false. "
                ),
            )
        }
    )

get_group_network_schema = extend_schema(
        summary="Returns the significant network edges connecting the input nodes q ",
        description="""Returns for set of query nodes q all significant network edges connecting them
            if parameter m is false. I m equals true a minimal spanning tree between the send set of nodes is requested 
            and returned if available. The returned message states that edges or the minimal spanning tree weren't 
            found if that is the case. 
            e.g. input: q=["x0so0038","x0so3127","x0so0548"], s = "0.05", m="true", o = "{
                catCat: {label: 'Chi-squared test', value: 'chi2'}, catContM: {label: 'ANOVA', value: 'anova'},
                multTest: {label: 'Benjamini Hochberg (FDR)', value: 'benjamini_hb'},
                catContB: {label: 'T-test', value: 'ttest'}, contCont: {label: 'Pearson correlation', value: 'pearson'}
              }"
            """,
        parameters=[
            OpenApiParameter(
                name='q',
                description='query ids list',
                required=True,
                type=OpenApiTypes.OBJECT,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='m',
                description='boolean string stating if a minimal spanning tree is requested',
                required=True,
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='s',
                description='significance threshold',
                required=True,
                type=OpenApiTypes.FLOAT,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='o',
                description='options of selected tests & testing correction',
                required=True,
                type=OpenApiTypes.OBJECT,
                location=OpenApiParameter.QUERY,
            )
        ],
        responses={
            200: OpenApiResponse(
                description="Successfully retrieved nodes and edges",
            ),
            405: OpenApiResponse(
                description=(
                    "Request was not processed due to one of the following reasons:\n"
                    "1. query nodes q was not provided.\n"
                    "2. Missing key in selected options parameter o."
                ),
            )
        }
    )
get_group_network_context_schema = extend_schema(
        summary="Returns the significant network edges connecting the input nodes q for a given context",
        description="""Returns for set of query nodes q all significant network edges connecting them
            if parameter m is false. I m equals true a minimal spanning tree between the send set of nodes is requested 
            and returned if available. The returned message states that edges or the minimal spanning tree weren't 
            found if that is the case.
            The query is restricted to the currently selected context of the user which is derived from the users id, 
            which requires that a user is logged in (otherwise the request fails) and the context value c of the 
            selected context.
            e.g. input: q=["x0so0038","x0so3127","x0so0548"], s = "0.05", m="true", c="3", o = "{
                catCat: {label: 'Chi-squared test', value: 'chi2'}, catContM: {label: 'ANOVA', value: 'anova'},
                multTest: {label: 'Benjamini Hochberg (FDR)', value: 'benjamini_hb'},
                catContB: {label: 'T-test', value: 'ttest'}, contCont: {label: 'Pearson correlation', value: 'pearson'}
              }"
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
            required=True,
            description="Session cookie for authentication.",
            type=OpenApiTypes.STR,
        ),
        OpenApiParameter(
            name='c',
            description='The value of the context which specifies at which tab it is supposed to be shown '
                        'specific for the authenticated user.',
            required=True,
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
        ),
        OpenApiParameter(
            name='q',
            description='query ids list',
            required=True,
            type=OpenApiTypes.OBJECT,
            location=OpenApiParameter.QUERY,
        ),
        OpenApiParameter(
            name='m',
            description='boolean string stating if a minimal spanning tree is requested',
            required=True,
            type=OpenApiTypes.BOOL,
            location=OpenApiParameter.QUERY,
        ),
        OpenApiParameter(
            name='s',
            description='significance threshold',
            required=True,
            type=OpenApiTypes.FLOAT,
            location=OpenApiParameter.QUERY,
        ),
        OpenApiParameter(
            name='o',
            description='options of selected tests & testing correction',
            required=True,
            type=OpenApiTypes.OBJECT,
            location=OpenApiParameter.QUERY,
        )
    ],
    responses={
        200: OpenApiResponse(
            description="Successfully retrieved nodes and edges",
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
        405: OpenApiResponse(
            description=(
                "Request was not processed due to one of the following reasons:\n"
                "1. query nodes q or context value c was not provided.\n"
                "2. Missing key in selected options parameter o."
            ),
        )
    }
)