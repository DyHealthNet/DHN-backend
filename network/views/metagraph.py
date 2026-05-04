import json
import timeit
from collections import defaultdict

import networkx as nx
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, HttpResponseBadRequest
from django.db.models import Value
from django.db.models.functions import Least, Coalesce
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

def parse_query_params(request):
    """
    Parse and validate query parameters for Cosmograph view.
    
    Returns:
        tuple: (limit, threshold, per_node_limit) or HttpResponseBadRequest on error
    """
    def parse_param(value, param_type, param_name, min_val=None, max_val=None):
        """Helper to parse, convert, and validate individual parameters."""
        if value in ['', 'null', None]:
            return None
        
        try:
            converted = param_type(value)
        except (ValueError, TypeError):
            return HttpResponseBadRequest(f'{param_name} must be a {param_type.__name__}.', status=405)
        
        if min_val is not None and converted < min_val:
            return HttpResponseBadRequest(f'{param_name} must be > {min_val - 1}.', status=405)
        
        if max_val is not None and converted > max_val:
            # Special case: cap limit at max instead of error
            if param_name == 'limit':
                return max_val
            return HttpResponseBadRequest(f'{param_name} must be <= {max_val}.', status=405)
        
        return converted
    
    limit = parse_param(request.GET.get('limit'), int, 'limit', min_val=1, max_val=20000)
    if isinstance(limit, HttpResponseBadRequest):
        return limit, None, None
    
    threshold = parse_param(request.GET.get('threshold'), float, 'threshold', min_val=0, max_val=1)
    if isinstance(threshold, HttpResponseBadRequest):
        return None, threshold, None
    
    per_node_limit = parse_param(request.GET.get('per_node_limit'), int, 'per_node_limit', min_val=1)
    if isinstance(per_node_limit, HttpResponseBadRequest):
        return None, None, per_node_limit
    
    # Ensure at least one parameter is provided
    if limit is None and threshold is None and per_node_limit is None:
        return HttpResponseBadRequest('At least one of limit, threshold or per_node_limit must be provided.', status=405), None, None
    
    return limit, threshold, per_node_limit


def run_leiden_clustering(selected_links, used_node_ids, resolution=1.0, seed=42):
    """
    Run Leiden clustering on the filtered graph.
    Falls back to Louvain if Leiden dependencies are not installed.
    """
    if not used_node_ids:
        return {}, 'none'

    # Preferred implementation: build igraph directly for lower overhead.
    try:
        import igraph as ig
        import leidenalg

        sorted_nodes = sorted(used_node_ids)
        node_to_idx = {node_id: idx for idx, node_id in enumerate(sorted_nodes)}
        idx_to_node = {idx: node_id for node_id, idx in node_to_idx.items()}

        ig_graph = ig.Graph()
        ig_graph.add_vertices(len(sorted_nodes))

        ig_edges = []
        ig_weights = []
        for edge in selected_links:
            source = edge.get('source')
            target = edge.get('target')
            if not source or not target:
                continue
            if source not in node_to_idx or target not in node_to_idx:
                continue
            ig_edges.append((node_to_idx[source], node_to_idx[target]))
            ig_weights.append(edge.get('weight', 1.0) or 1.0)

        if ig_edges:
            ig_graph.add_edges(ig_edges)

        partition = leidenalg.find_partition(
            ig_graph,
            leidenalg.RBConfigurationVertexPartition,
            weights=ig_weights if ig_weights else None,
            resolution_parameter=resolution,
            seed=seed,
        )

        node_to_community = {}
        for community_id, members in enumerate(partition):
            for member_idx in members:
                node_to_community[idx_to_node[member_idx]] = community_id

        return node_to_community, 'leiden'
    except Exception as exc:
        logger.warning('Leiden unavailable, using Louvain fallback: %s', exc)

    # Fallback keeps endpoint functional without extra dependencies.
    graph = nx.Graph()
    graph.add_nodes_from(used_node_ids)

    for edge in selected_links:
        source = edge.get('source')
        target = edge.get('target')
        if not source or not target:
            continue
        graph.add_edge(source, target, weight=edge.get('weight', 1.0) or 1.0)

    communities = nx.community.louvain_communities(graph, weight='weight', resolution=resolution, seed=seed)
    node_to_community = {}
    for community_id, members in enumerate(communities):
        for node_id in members:
            node_to_community[node_id] = community_id

    return node_to_community, 'louvain_fallback'

#TODO: add @extend_schema_view
class GetCosmographView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        limit, threshold, per_node_limit = parse_query_params(request)
        
        # Handle error responses
        if isinstance(limit, HttpResponseBadRequest):
            return limit
        if isinstance(threshold, HttpResponseBadRequest):
            return threshold
        if isinstance(per_node_limit, HttpResponseBadRequest):
            return per_node_limit
        
        logger.info(
            'Start Cosmograph request with limit=%s threshold=%s per_node_limit=%s',
            limit,
            threshold,
            per_node_limit,
        )

        # Extract candidate_links, selected_links, and nodes from the database
        candidate_links, selected_links, used_node_ids = get_whole_network(
            thresh=threshold,
            limit=limit,
            per_node_limit=per_node_limit
        )

        # Format response links (remove final_p_value which is internal)
        response_links = [
            {key: value for key, value in edge.items() if key != 'final_p_value'}
            for edge in selected_links
        ]

        node_model = apps.get_model('network', 'ViewDescriptionFTS')
        cohort_nodes = node_model.objects.filter(
            source_table__startswith='cohort_',
            id__in=used_node_ids,
        ).values('id', 'display_name', 'source_table')

        points = [
            {
                'id': node['id'],
                'label': node.get('display_name') or node['id'],
                'type': (node.get('source_table') or '').replace('cohort_', ''),
                'source_table': node.get('source_table'),
            }
            for node in cohort_nodes
            if node.get('id')
        ]

        logger.info(
            'Retrieval complete. points=%s links=%s candidates=%s',
            len(points),
            len(selected_links),
            len(candidate_links),
        )

        return JsonResponse(
            {
                'points': points,
                'links': response_links,
                'meta': {
                    'point_count': len(points),
                    'link_count': len(response_links),
                    'candidate_link_count': len(candidate_links),
                    'limit': limit,
                    'threshold': threshold,
                    'per_node_limit': per_node_limit,
                },
            },
            status=200,
        )


#TODO: add @extend_schema_view
class GetLeidenMetagraphView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        limit, threshold, per_node_limit = parse_query_params(request)

        if isinstance(limit, HttpResponseBadRequest):
            return limit
        if isinstance(threshold, HttpResponseBadRequest):
            return threshold
        if isinstance(per_node_limit, HttpResponseBadRequest):
            return per_node_limit

        resolution_raw = request.GET.get('resolution', None)
        if resolution_raw in ['', 'null', None]:
            resolution = 1.0
        else:
            try:
                resolution = float(resolution_raw)
            except ValueError:
                return HttpResponseBadRequest('resolution must be a number.', status=405)
            if resolution <= 0:
                return HttpResponseBadRequest('resolution must be > 0.', status=405)

        seed_raw = request.GET.get('seed', None)
        if seed_raw in ['', 'null', None]:
            seed = 42
        else:
            try:
                seed = int(seed_raw)
            except ValueError:
                return HttpResponseBadRequest('seed must be an integer.', status=405)

        logger.info(
            'Start Leiden request with limit=%s threshold=%s per_node_limit=%s resolution=%s seed=%s',
            limit,
            threshold,
            per_node_limit,
            resolution,
            seed,
        )

        candidate_links, selected_links, used_node_ids = get_whole_network(
            thresh=threshold,
            limit=limit,
            per_node_limit=per_node_limit,
        )

        node_to_community, clustering_algorithm = run_leiden_clustering(
            selected_links=selected_links,
            used_node_ids=used_node_ids,
            resolution=resolution,
            seed=seed,
        )

        response_links = [
            {key: value for key, value in edge.items() if key != 'final_p_value'}
            for edge in selected_links
        ]

        node_model = apps.get_model('network', 'ViewDescriptionFTS')
        cohort_nodes = node_model.objects.filter(
            source_table__startswith='cohort_',
            id__in=used_node_ids,
        ).values('id', 'display_name', 'source_table')

        points = [
            {
                'id': node['id'],
                'label': node.get('display_name') or node['id'],
                'type': (node.get('source_table') or '').replace('cohort_', ''),
                'source_table': node.get('source_table'),
                'community': node_to_community.get(node['id']),
            }
            for node in cohort_nodes
            if node.get('id')
        ]

        community_count = len(set(node_to_community.values())) if node_to_community else 0

        logger.info(
            'Leiden complete. points=%s links=%s communities=%s algorithm=%s',
            len(points),
            len(response_links),
            community_count,
            clustering_algorithm,
        )

        return JsonResponse(
            {
                'points': points,
                'links': response_links,
                'meta': {
                    'point_count': len(points),
                    'link_count': len(response_links),
                    'candidate_link_count': len(candidate_links),
                    'community_count': community_count,
                    'algorithm': clustering_algorithm,
                    'resolution': resolution,
                    'seed': seed,
                    'limit': limit,
                    'threshold': threshold,
                    'per_node_limit': per_node_limit,
                },
            },
            status=200,
        )