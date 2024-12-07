import json
from django.http import JsonResponse, HttpResponseBadRequest
from rest_framework import generics
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes, extend_schema_view
from network.queries import *
from network.schemas.network_schemas import *


types = ["protein", "metabolite", "phenotype", "variant"]  # "disorders", "genes"


@extend_schema_view(
    get=get_network_schema
)
class GetNetworkView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        # Get request vars and test valid input
        query_id = request.GET.get("q")
        node_type = request.GET.get("t")
        limit = request.GET.get("l")

        if query_id is None or query_id == "":
            return HttpResponseBadRequest('Query id q must be declared and non empty.', status=405)
        if node_type is None or node_type not in types:
            return HttpResponseBadRequest(
                'Query type t must be declared and either protein, metabolite, phenotype and variant', status=405)
        if limit is None or limit == "":
            limit = 10
        else:
            try:
                limit = int(limit)
            except ValueError:
                return HttpResponseBadRequest(
                    f'Limit l must be a valid integer, not {limit}', status=405)

        if limit > 50:
            return HttpResponseBadRequest(
                f'Limit l takes a maximal value of 50, not {limit}', status=405)
        # retrieve chris nodes & edges + external edges using queries/network_queries function
        edges, nodes, externals = network_query(query_id, node_type, limit)
        # reformat Edges and Nodes and return as json
        result_edges = {}
        for table, results in edges.items():
            result_edges[table] = list(results)
        result_nodes = {}
        for results in nodes:
            # strip xrefs of db names -> currently not used
            # results["xrefs"] = strip_db_name(results["xrefs"])
            # group by source_table
            if results['source_table'] in result_nodes:
                result_nodes[results['source_table']].append(results)
            else:
                result_nodes[results['source_table']] = [results]

        combined_query = {
            'Nodes': result_nodes,
            'Edges': result_edges,
            'External Edges': list(externals)
        }
        return JsonResponse(combined_query, safe=False, status=200)


# TODO make this compatible for external nodes as input (use and set parameter cohort_node=False in external_query())
@extend_schema_view(
    get=all_externals_schema
)
class GetAllExternalsView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        # Get request var and test valid input
        query_id = request.GET.get("q")
        if query_id is None or query_id == "":
            return HttpResponseBadRequest('Query id q must be declared and non empty.', status=405)
        # retrieve external edges and their chris nodes (if available) or external nodes using queries/external_query
        # function
        externals, cohort_nodes, external_nodes = external_query(query_id)
        # reformat CHRIS and External Nodes and return as json
        nodes = {}
        for results in cohort_nodes:
            for result in results:
                # Strip db name from xrefs (everything until first dot) if xrefs a key of the node -> currently not used
                # if "xrefs" in result:
                #    result["xrefs"] = strip_db_name(result["xrefs"])
                # group by source_table
                if result['source_table'] in nodes:
                    nodes[result['source_table']].append(result)
                else:
                    nodes[result['source_table']] = [result]
        external_nodes = {}
        for results in external_nodes:
            for result in results:
                if "xrefs" in result:
                    # Strip db name from xrefs (everything until first dot) if xrefs a key of the node ->
                    # currently not used
                    # result["xrefs"] = strip_db_name("|".join(result["xrefs"]))
                    result["xrefs"] = "|".join(result["xrefs"])
                # group by source_table
                if result['source_table'] in external_nodes:
                    external_nodes[result['source_table']].append(result)
                else:
                    external_nodes[result['source_table']] = [result]
        combined_query = {
            'External Edges': list(externals),
            'Chris Nodes': nodes,
            'External Nodes': external_nodes
        }
        return JsonResponse(combined_query, safe=False, status=200)


@extend_schema_view(
    get=typeahead_schema
)
class TypeaheadView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        # Get request var and test valid input
        s = request.GET.get("s")
        if s is None or s == "":
            return HttpResponseBadRequest('Query string s must be declared and non empty.', status=405)
        # retrieve recommendations using the queries/typeahead_query function
        res = typeahead_query(s)
        # reformat and return as json
        res_filtered = res.values('id', 'description', 'display_name', 'source_table')
        dict_from_queryset = {item['id']: {'display_name': item['display_name'], 'description': item['description'],
                                           'source_table': item['source_table']} for item in res_filtered}
        return JsonResponse(dict_from_queryset, safe=True)