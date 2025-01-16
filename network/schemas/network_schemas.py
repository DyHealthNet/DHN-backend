from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, OpenApiParameter

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
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='o',
                description='options of selected tests & testing correction',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            )

        ],
    )

get_network_context_schema = extend_schema(
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
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='o',
                description='options of selected tests & testing correction',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            )

        ],
    )