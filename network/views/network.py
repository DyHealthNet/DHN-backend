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
        query_id = request.GET.get("q")
        node_type = request.GET.get("t")
        limit = request.GET.get("l")
        per_type = request.GET.get("p")
        significance_thresh = request.GET.get("s")
        try:
            # Deserialize the JSON string into a Python dictionary
            selected_options = json.loads(request.GET.get("o"))
            logger.debug(f"Selected options: {selected_options}")
        except json.JSONDecodeError:
            logger.error("Failed to decode selected options JSON")
            return HttpResponseBadRequest('The selected Options are not send as a valid Json', status=405)
        logger.debug(selected_options)
        print(f"selected_options: {selected_options}")
        test_columns = {f'{selected_options["contCont"]["value"]}_p_{selected_options["multTest"]["value"]}',
                        f'{selected_options["catContB"]["value"]}_p_{selected_options["multTest"]["value"]}',
                        f'{selected_options["catContM"]["value"]}_p_{selected_options["multTest"]["value"]}',
                        f'{selected_options["catCat"]["value"]}_p_{selected_options["multTest"]["value"]}'}

        if query_id is None or query_id == "":
            return HttpResponseBadRequest('Query id q must be declared and non empty.', status=405)
        if node_type is None or node_type not in types:
            return HttpResponseBadRequest(
                'Query type t must be declared and either protein, metabolite, phenotype and variant', status=405)
        if limit is None or limit == "":
            limit = None
        else:
            try:
                limit = int(limit)
                if limit > 50:
                    return HttpResponseBadRequest(
                        f'Limit l takes a maximal value of 50, not {limit}', status=405)
            except ValueError:
                return HttpResponseBadRequest(
                    f'Limit l must be a valid integer, not {limit}', status=405)

        # retrieve chris nodes & edges + external edges using queries/network_queries function
        edges, nodes, externals = network_query(query_id, node_type, limit, per_type, significance_thresh, test_columns)
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
        #logger.debug(f"Combined Query {combined_query}")
        return JsonResponse(combined_query, safe=False, status=200)

@extend_schema_view(
    get=get_network_context_schema
)
class GetNetworkContextView(LoginRequiredMixin, generics.GenericAPIView):
    @staticmethod
    def get(request):
        # Get request vars and test valid input
        query_id = request.GET.get("q")
        node_type = request.GET.get("t")
        limit = request.GET.get("l")
        per_type = request.GET.get("p")
        significance_thresh = request.GET.get("s")
        context_value = request.GET.get("c")

        try:
            # Deserialize the JSON string into a Python dictionary
            selected_options = json.loads(request.GET.get("o"))
            logger.debug(f"Selected options: {selected_options}")
        except json.JSONDecodeError:
            logger.error("Failed to decode selected options JSON")
            return HttpResponseBadRequest('The selected Options are not send as a valid Json', status=405)
        logger.debug(selected_options)
        print(f"selected_options: {selected_options}")
        test_columns = {f'{selected_options["contCont"]["value"]}_p_{selected_options["multTest"]["value"]}',
                        f'{selected_options["catContB"]["value"]}_p_{selected_options["multTest"]["value"]}',
                        f'{selected_options["catContM"]["value"]}_p_{selected_options["multTest"]["value"]}',
                        f'{selected_options["catCat"]["value"]}_p_{selected_options["multTest"]["value"]}'}

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

        if query_id is None or query_id == "":
            return HttpResponseBadRequest('Query id q must be declared and non empty.', status=405)
        if node_type is None or node_type not in types:
            return HttpResponseBadRequest(
                'Query type t must be declared and either protein, metabolite, phenotype and variant', status=405)
        if limit is None or limit == "":
            limit = None
        else:
            try:
                limit = int(limit)
                if limit > 50:
                    return HttpResponseBadRequest(
                        f'Limit l takes a maximal value of 50, not {limit}', status=405)
            except ValueError:
                return HttpResponseBadRequest(
                    f'Limit l must be a valid integer, not {limit}', status=405)

        # retrieve chris nodes & edges + external edges using queries/network_queries function
        edges, nodes, externals = network_query(query_id, node_type, limit, per_type, significance_thresh,
                                                test_columns, context_id)
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
#@extend_schema_view(
 #   get=get_group_network_schema
#)
class GetGroupNetworkView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        # Get request vars and test valid input
        significance_thresh = request.GET.get("s")
        try:
            # Deserialize the JSON string into a Python dictionary
            query_ids = set(json.loads(request.GET.get("q")))
            logger.debug(f"Selected options: {query_ids}")
        except json.JSONDecodeError:
            logger.error("Failed to decode query node ids JSON")
            return HttpResponseBadRequest('The query node ids are not send as a valid Json', status=405)
        try:
            # Deserialize the JSON string into a Python dictionary
            selected_options = json.loads(request.GET.get("o"))
            logger.debug(f"Selected options: {selected_options}")
        except json.JSONDecodeError:
            logger.error("Failed to decode selected options JSON")
            return HttpResponseBadRequest('The selected Options are not send as a valid Json', status=405)
        logger.debug(selected_options)
        print(f"selected_options: {selected_options}")
        test_columns = {f'{selected_options["contCont"]["value"]}_p_{selected_options["multTest"]["value"]}',
                        f'{selected_options["catContB"]["value"]}_p_{selected_options["multTest"]["value"]}',
                        f'{selected_options["catContM"]["value"]}_p_{selected_options["multTest"]["value"]}',
                        f'{selected_options["catCat"]["value"]}_p_{selected_options["multTest"]["value"]}'}

        if query_ids is None or query_ids == "":
            return HttpResponseBadRequest('Query ids q must be a list of node ids and non empty.', status=405)

        # retrieve chris nodes & edges + external edges using queries/network_queries function
        edges, nodes, externals = network_group_query(query_ids, significance_thresh, test_columns)
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

#@extend_schema_view(
#    get=get_group_network_context_schema
#)
class GetGroupNetworkContextView(LoginRequiredMixin, generics.GenericAPIView):
    @staticmethod
    def get(request):
        # Get request vars and test valid input
        significance_thresh = request.GET.get("s")
        context_value = request.GET.get("c")
        spanning_tree = request.GET.get("m")
        try:
            # Deserialize the JSON string into a Python dictionary
            query_ids = set(json.loads(request.GET.get("q")))
            logger.debug(f"Selected options: {query_ids}")
        except json.JSONDecodeError:
            logger.error("Failed to decode query node ids JSON")
            return HttpResponseBadRequest('The query node ids are not send as a valid Json', status=405)
        try:
            # Deserialize the JSON string into a Python dictionary
            selected_options = json.loads(request.GET.get("o"))
            logger.debug(f"Selected options: {selected_options}")
        except json.JSONDecodeError:
            logger.error("Failed to decode selected options JSON")
            return HttpResponseBadRequest('The selected Options are not send as a valid Json', status=405)
        logger.debug(selected_options)
        print(f"selected_options: {selected_options}")
        test_columns = {f'{selected_options["contCont"]["value"]}_p_{selected_options["multTest"]["value"]}',
                        f'{selected_options["catContB"]["value"]}_p_{selected_options["multTest"]["value"]}',
                        f'{selected_options["catContM"]["value"]}_p_{selected_options["multTest"]["value"]}',
                        f'{selected_options["catCat"]["value"]}_p_{selected_options["multTest"]["value"]}'}

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

        if query_ids is None or query_ids == "":
            return HttpResponseBadRequest('Query ids q must be a list of node ids and non empty.', status=405)

        # retrieve chris nodes & edges + external edges using queries/network_queries function
        edges, nodes, externals = network_group_query(query_ids, significance_thresh, test_columns, context_id)
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

        logger.debug(f"result_edges {result_edges}")
        if spanning_tree == "true":
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

            # Prepare the filtered edges
            for u, v, weight in mst.edges(data=True):
                edge_key = tuple(sorted([u, v]))
                orig_edge = edge_lookup[edge_key]
                orig_edge_group = edge_group_lookup[edge_key]
                filtered_edges[orig_edge_group].append(orig_edge)
            logger.debug(f"filtered_edges {filtered_edges}")
            result_edges = filtered_edges

        combined_query = {
            'Nodes': result_nodes,
            'Edges': result_edges,
            'External Edges': list(externals)
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
                                           'source_table': item['source_table'], 'x_refs': item['xrefs']} for item in res_filtered}
        return JsonResponse(dict_from_queryset, safe=True)