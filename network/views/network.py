import json

import networkx as nx
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, HttpResponseBadRequest
from rest_framework import generics
from drf_spectacular.utils import extend_schema_view

from network.models import UserContextLink, Context
from network.queries import *
from network.schemas.network_schemas import *

import logging

logger = logging.getLogger('network')

types = ["protein", "metabolite", "phenotype", "variant"]  # "disorders", "genes"
layers_to_source_table = {
    "proteomics": "cohort_protein",
    "metabolomics": "cohort_metabolite",
    "phenomics": "cohort_phenotype",
    "variants": "cohort_variant"
}

######### Individual Nodes Network Queries ###########
@extend_schema_view(
    get=get_network_schema
)
class GetNetworkView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        # Get request vars and test valid input
        request_load = read_in_network_request(request, get_node_type=True, get_limit=True, get_per_type=True)

        # retrieve chris nodes & edges + external edges using queries/network_queries function
        edges, nodes, externals = network_query(request_load["query_id"], request_load["node_type"],
                                                request_load["limit"], request_load["per_type"],
                                                request_load["significance_thresh"], request_load["test_columns"])

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
        # logger.debug(f"Combined Query {combined_query}")
        return JsonResponse(combined_query, safe=False, status=200)


@extend_schema_view(
    get=get_network_context_schema
)
class GetNetworkContextView(LoginRequiredMixin, generics.GenericAPIView):
    @staticmethod
    def get(request):
        # Get request vars and test valid input
        request_load = read_in_network_request(request, get_node_type=True, get_limit=True, get_per_type=True,
                                               get_context_value=True)

        # retrieve chris nodes & edges + external edges using queries/network_queries function
        edges, nodes, externals = network_query(request_load["query_id"], request_load["node_type"],
                                                request_load["limit"], request_load["per_type"],
                                                request_load["significance_thresh"], request_load["test_columns"],
                                                request_load["context_id"])
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
        logger.debug(f"Combined Query {combined_query}")
        return JsonResponse(combined_query, safe=False, status=200)


######### Group of Nodes Network Queries ###########
# @extend_schema_view(
#   get=get_group_network_schema
# )
class GetGroupNetworkView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        # Get request vars and test valid input
        request_load = read_in_network_request(request, query_indiv_node=False, get_spanning_tree=True)

        # retrieve chris nodes & edges + external edges using queries/network_queries function
        edges, nodes, externals = network_group_query(request_load["query_ids"], request_load["significance_thresh"],
                                                      request_load["test_columns"])
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

        message = ""
        if request_load["spanning_tree"] == "true":
            result_edges, message = calculate_minium_spanning_tree(result_nodes=result_nodes, result_edges=result_edges)

        combined_query = {
            'Nodes': result_nodes,
            'Edges': result_edges,
            'External Edges': list(externals),
            'message': message,
        }
        logger.debug(f"Combined Query {combined_query}")
        return JsonResponse(combined_query, safe=False, status=200)


# @extend_schema_view(
#    get=get_group_network_context_schema
# )
class GetGroupNetworkContextView(LoginRequiredMixin, generics.GenericAPIView):
    @staticmethod
    def get(request):
        request_load = read_in_network_request(request, query_indiv_node=False,
                                               get_context_value=True, get_spanning_tree=True)
        # retrieve chris nodes & edges + external edges using queries/network_queries function
        edges, nodes, externals = network_group_query(request_load["query_ids"], request_load["significance_thresh"],
                                                      request_load["test_columns"], request_load["context_id"])
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

        message = ""
        if request_load["spanning_tree"] == "true":
            result_edges, message = calculate_minium_spanning_tree(result_nodes=result_nodes, result_edges=result_edges)

        combined_query = {
            'Nodes': result_nodes,
            'Edges': result_edges,
            'External Edges': list(externals),
            'message': message,
        }
        logger.debug(f"Combined Query {combined_query}")
        return JsonResponse(combined_query, safe=False, status=200)


######### External Nodes Network Queries ###########

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


######### Typeahead Query ###########

@extend_schema_view(
    get=typeahead_schema
)
class TypeaheadView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        # Get request var and test valid input
        s = request.GET.get("s")
        context_value = request.GET.get("c")

        if s is None or s == "":
            return HttpResponseBadRequest('Query string s must be declared and non empty.', status=405)

        if context_value is not None and context_value != "" and context_value != "null":
            if not request.user.is_authenticated:
                print(f"context_value: {context_value}")
                return JsonResponse({'status': 'error', 'message': 'Search failed. User not authenticated and '
                                                                   'cannot inneract with a context'},
                                    status=400)  # 401?
            try:
                user_context = UserContextLink.objects.get(user_id=request.user.id, context_value=context_value)
                context_id = user_context.context_id
                context = Context.objects.get(context_id=int(context_id))
                context_layers = context.params['layers']
                logger.debug(f"layer: {context_layers}")
                tables = [layers_to_source_table[value] for value in context_layers if value in layers_to_source_table]
            except UserContextLink.DoesNotExist:
                return HttpResponseBadRequest('Context not found.', status=404)
        else:
            tables = None

        # retrieve recommendations using the queries/typeahead_query function
        res = typeahead_query(s, tables)
        # reformat and return as json
        res_filtered = res.values('id', 'description', 'display_name', 'source_table', 'xrefs')
        dict_from_queryset = {item['id']: {'display_name': item['display_name'], 'description': item['description'],
                                           'source_table': item['source_table'], 'x_refs': item['xrefs']} for item in
                              res_filtered}
        return JsonResponse(dict_from_queryset, safe=True)


############# Helper Function ###############


def parse_json_param(request, param_name, default=None):
    """Helper function to safely parse JSON parameters from GET request."""
    value = request.GET.get(param_name, default)
    if value is None:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        logger.error(f"Failed to decode JSON for parameter: {param_name}")
        return HttpResponseBadRequest(f"Invalid JSON format for '{param_name}'", status=405)


def read_in_network_request(request, query_indiv_node=True, get_node_type=False, get_limit=False, get_per_type=False,
                            get_context_value=False, get_spanning_tree=False):
    """Extracts and validates network request parameters."""
    response_data = {}

    # Get query id(s)
    if query_indiv_node:
        query_id = request.GET.get("q")
        if query_id is None or query_id == "":
            return HttpResponseBadRequest('Query id q must be declared and non empty.', status=405)
        response_data["query_id"] = query_id
    else:
        query_ids = parse_json_param(request, "q", default=[])
        if isinstance(query_ids, HttpResponseBadRequest):
            return query_ids
        if query_ids is None or query_ids == "":
            return HttpResponseBadRequest('Query ids q must be a list of node ids and non empty.', status=405)
        response_data["query_ids"] = set(query_ids)

    # Get significance threshold
    response_data["significance_thresh"] = request.GET.get("s")

    # Get Test configurations
    selected_options = parse_json_param(request, "o", default={})
    if isinstance(selected_options, HttpResponseBadRequest):
        return selected_options
    try:
        test_columns = {
            f'{selected_options["contCont"]["value"]}_p_{selected_options["multTest"]["value"]}',
            f'{selected_options["catContB"]["value"]}_p_{selected_options["multTest"]["value"]}',
            f'{selected_options["catContM"]["value"]}_p_{selected_options["multTest"]["value"]}',
            f'{selected_options["catCat"]["value"]}_p_{selected_options["multTest"]["value"]}',
        }
        response_data["test_columns"] = test_columns
    except KeyError as e:
        logger.error(f"Missing key in selected_options: {e}")
        return HttpResponseBadRequest(f"Missing key in selected_options: {e}", status=405)

    # Optional parameters
    # Get Node Type
    if get_node_type:
        response_data["node_type"] = request.GET.get("t")
    # Get Limit for node count retrival
    if get_limit:
        limit = request.GET.get("l")
        if limit:
            try:
                limit = int(limit)
                if limit > 50:
                    return HttpResponseBadRequest(f"Limit 'l' can be at most 50, not {limit}", status=405)
            except ValueError:
                return HttpResponseBadRequest(f"Limit 'l' must be an integer, not {limit}", status=405)
        response_data["limit"] = limit
    # Get option for node count retrival (per node type or overall)
    if get_per_type:
        response_data["per_type"] = request.GET.get("p")
    # Get context value -> context Id
    if get_context_value:
        context_value = request.GET.get("c")
        if context_value is not None and context_value != "" and context_value != "null":
            if not request.user.is_authenticated:
                print(f"context_value: {context_value}")
                return JsonResponse({'status': 'error', 'message': 'Permission denied. User not authenticated'},
                                    status=400)  # 401?
            try:
                user_context = UserContextLink.objects.get(user_id=request.user.id, context_value=context_value)
                context_id = user_context.context_id
            except UserContextLink.DoesNotExist:
                return HttpResponseBadRequest('Context not found.', status=404)
        else:
            return HttpResponseBadRequest('Context value not sent', status=405)
        response_data["context_id"] = context_id
    # Get spanning_tree option in case of group of nodes
    if get_spanning_tree:
        response_data["spanning_tree"] = request.GET.get("m")

    return response_data


def calculate_minium_spanning_tree(result_nodes, result_edges):
    message = ""
    # Create a graph
    graph = nx.Graph()

    # Add nodes to the graph
    for node_group in result_nodes:
        for node in result_nodes[node_group]:
            logger.debug(f"node {node}")
            graph.add_node(node['id'], description=node['description'], display_name=node['display_name'])

    logger.debug(f"result_edges {result_edges}")
    # Add edges to the graph (use 'final_p_value' as the weight)
    edge_lookup = {}
    edge_group_lookup = {}
    filtered_edges = {}
    for edge_group in result_edges:
        logger.debug(f"edge_group {edge_group}")
        filtered_edges[edge_group] = []
        for edge in result_edges[edge_group]:
            node_ids = [value for key, value in edge.items() if key.endswith('_id')]
            if len(node_ids) == 2:  # Ensure there are exactly two nodes (for an undirected edge)
                node_1, node_2 = node_ids
                edge_key = tuple(sorted([node_1, node_2]))
                edge_lookup[edge_key] = edge
                edge_group_lookup[edge_key] = edge_group
                weight = edge['final_p_value']  # Using final_p_value as the weight
                graph.add_edge(node_1, node_2, weight=weight)

    # Calculate the minimum spanning tree (MST)
    mst = nx.minimum_spanning_tree(graph)
    logger.debug(f"mst {mst}")

    # Prepare the filtered edges
    for u, v, weight in mst.edges(data=True):
        edge_key = tuple(sorted([u, v]))
        orig_edge = edge_lookup[edge_key]
        orig_edge_group = edge_group_lookup[edge_key]
        filtered_edges[orig_edge_group].append(orig_edge)
    if filtered_edges == result_edges:
        message = "No Minimal Spanning Tree found"
    return filtered_edges, message
