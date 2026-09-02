import json
import importlib
from math import ceil
import time
import timeit
from datetime import datetime
from collections import defaultdict
from pathlib import Path

import igraph as ig
import leidenalg
import numpy as np
from django.apps import apps
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

DEFAULT_LEIDEN_RESOLUTIONS = [0.2, 0.5, 1.0, 1.5, 2.0, 3.0]
SUPPORTED_COMMUNITY_METHODS = ('louvain', 'leiden', 'recursive_leiden', 'agglomerative', 'infomap', 'hierarchical_infomap', 'hsbm')

def resolution_to_key(value):
    """Normalize resolution keys so 1.0 and 3.0 keep one decimal."""
    text = f"{float(value):.6f}".rstrip('0').rstrip('.')
    if '.' not in text:
        text = f"{text}.0"
    return text


def parse_resolution_values(request):
    """
    Parse comma-separated Leiden resolutions from `resolutions` query parameter.
    Falls back to the default slider-friendly resolution set.
    """
    raw = request.GET.get('resolutions', None)
    if raw in ['', 'null', None]:
        return DEFAULT_LEIDEN_RESOLUTIONS

    try:
        values = [float(part.strip()) for part in str(raw).split(',') if part.strip()]
    except ValueError:
        return HttpResponseBadRequest('resolutions must be a comma-separated list of numbers.', status=405)

    if not values:
        return HttpResponseBadRequest('resolutions must contain at least one value.', status=405)

    for value in values:
        if value <= 0:
            return HttpResponseBadRequest('all resolution values must be > 0.', status=405)

    # Deduplicate while preserving order.
    deduped = []
    seen = set()
    for value in values:
        key = resolution_to_key(value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped

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
    
    density = parse_param(request.GET.get('density'), float, 'density', min_val=0, max_val=1)
    if isinstance(density, HttpResponseBadRequest):
        return None, None, None, density
    
    limit = parse_param(request.GET.get('limit'), int, 'limit', min_val=1, max_val=20000)
    if isinstance(limit, HttpResponseBadRequest):
        return limit, None, None, None
    
    
    threshold = parse_param(request.GET.get('threshold'), float, 'threshold', min_val=0, max_val=1)
    if isinstance(threshold, HttpResponseBadRequest):
        return None, threshold, None, None
    
    per_node_limit = parse_param(request.GET.get('per_node_limit'), int, 'per_node_limit', min_val=1)
    if isinstance(per_node_limit, HttpResponseBadRequest):
        return None, None, per_node_limit, None
    
    # Ensure at least one parameter is provided
    if limit is None and threshold is None and per_node_limit is None and density is None:
        return HttpResponseBadRequest('At least one of limit, threshold, per_node_limit or density must be provided.', status=405), None, None, None

    return limit, threshold, per_node_limit, density


def parse_test_type(request):
    test_type = (request.GET.get('testType') or '').strip().lower()
    if test_type not in ('parametric', 'nonparametric'):
        return HttpResponseBadRequest(
            "testType must be 'parametric' or 'nonparametric'.",
            status=405,
        )
    return test_type


def parse_context_id(request):
    """
    Resolve the optional 'c' (context value) query param to a context_id for the
    requesting user, mirroring read_in_network_request()'s context resolution
    (network/views/network.py). Returns None when no context is selected --
    Cosmograph/Leiden then run against the global edges_parametric/nonparametric
    tables as before.
    """
    context_value = request.GET.get('c')
    if context_value in ('', 'null', None):
        return None
    if not request.user.is_authenticated:
        return HttpResponseBadRequest('Permission denied. User not authenticated.', status=400)
    try:
        user_context = UserContextLink.objects.get(user_id=request.user.id, context_value=context_value)
    except UserContextLink.DoesNotExist:
        return HttpResponseBadRequest('Context not found.', status=404)
    return user_context.context_id


def _compute_minus_log_p(p_value):
    """-log10(p), clamped so p<=0 stays a large finite number instead of 0/inf."""
    if p_value is None:
        return 0.0
    if p_value <= 0:
        p_value = np.finfo(float).tiny
    return -np.log10(p_value)


def _compute_edge_weight(edge):
    """Mirrors community_detection_benchmark's '-logp_e_abs_raw' mode: -log10(p) * |effect size|."""
    minus_log_p = _compute_minus_log_p(edge.get('p_value'))
    effect_size = edge.get('effect_size')
    abs_e_value = abs(effect_size) if effect_size is not None else 0.0
    return minus_log_p * abs_e_value


def build_weighted_graph(selected_links, used_node_ids):
    """Build an undirected igraph Graph, weighting edges by -log10(p) * |effect size|."""
    sorted_nodes = sorted(map(str, used_node_ids))
    node_to_idx = {n: i for i, n in enumerate(sorted_nodes)}

    edges = []
    weights = []
    for edge in selected_links:
        if edge['source'] not in node_to_idx or edge['target'] not in node_to_idx:
            continue
        edges.append((node_to_idx[edge['source']], node_to_idx[edge['target']]))
        weights.append(_compute_edge_weight(edge))

    graph = ig.Graph(n=len(sorted_nodes), edges=edges, directed=False)
    graph.vs["name"] = sorted_nodes
    graph.es["weight"] = weights

    return graph

def compute_modularity(graph, node_to_community):
    if graph.vcount() == 0:
        return 0.0

    try:
        membership = [node_to_community.get(vertex['name'], idx) for idx, vertex in enumerate(graph.vs)]
        if graph.ecount() == 0:
            return 0.0
        return float(graph.modularity(membership, weights=graph.es['weight']))
    except Exception:
        return 0.0

def compute_conductance(graph, node_to_community):
    if graph.vcount() == 0 or graph.ecount() == 0 or not node_to_community:
        return 0.0

    try:
        membership = [node_to_community.get(vertex['name'], idx) for idx, vertex in enumerate(graph.vs)]
        if not membership:
            return 0.0

        weights = graph.es['weight'] if 'weight' in graph.es.attributes() else None
        strengths = graph.strength(weights=weights)
        total_strength = float(sum(strengths))
        if total_strength <= 0:
            return 0.0

        community_vertices = defaultdict(list)
        for vertex_index, community_id in enumerate(membership):
            community_vertices[community_id].append(vertex_index)

        boundary_weights = defaultdict(float)
        for edge in graph.es:
            source = int(edge.source)
            target = int(edge.target)
            if membership[source] == membership[target]:
                continue
            weight = float(edge['weight']) if 'weight' in edge.attributes() else 1.0
            boundary_weights[membership[source]] += weight
            boundary_weights[membership[target]] += weight

        conductances = []
        for community_id, vertices in community_vertices.items():
            community_volume = float(sum(strengths[index] for index in vertices))
            other_volume = total_strength - community_volume
            denominator = min(community_volume, other_volume)
            if denominator <= 0:
                continue
            conductances.append(boundary_weights.get(community_id, 0.0) / denominator)

        if not conductances:
            return 0.0

        return float(sum(conductances) / len(conductances))
    except Exception:
        return 0.0

def _assign_membership(graph, membership):
    return {graph.vs[idx]['name']: community_id for idx, community_id in enumerate(membership)}

def _singleton_membership(graph):
    return list(range(graph.vcount()))

def run_community_clustering(graph, method='leiden', resolution=1.0, seed=42):
    method = (method or 'leiden').strip().lower()

    if method == 'leiden':
        return _run_leiden_clustering(graph, resolution=resolution, seed=seed)
    if method == 'louvain':
        return _run_louvain_clustering(graph)
    if method == 'infomap':
        return _run_infomap_clustering(graph)
    if method == 'hsbm':
        return _run_hsbm_clustering(graph, seed=seed)

    raise ValueError(f"Unsupported community detection method '{method}'. Choose from: {', '.join(SUPPORTED_COMMUNITY_METHODS)}.")

# Methods whose result doesn't depend on the resolution parameter -- computed
# once per request and reused across every requested resolution instead of
# being rerun (rerunning would be pure waste, and for hsbm's nested blockmodel
# inference it's expensive enough to matter).
RESOLUTION_INDEPENDENT_METHODS = frozenset({'louvain', 'infomap', 'hsbm'})

def _run_infomap_clustering(graph, trials=10):
    """Run flat Infomap via python-igraph's built-in community_infomap."""
    if graph.vcount() == 0:
        return {}, 'none'

    if graph.ecount() == 0:
        return _assign_membership(graph, _singleton_membership(graph)), 'infomap'

    communities = graph.community_infomap(edge_weights=graph.es['weight'] if graph.ecount() else None, trials=trials)
    return _assign_membership(graph, communities.membership), 'infomap'

def _run_hsbm_clustering(graph, seed=42):
    """Run a hierarchical stochastic block model (graph-tool) and return its finest-level blocks.

    Unlike Leiden/Louvain (modularity optimization), hsbm fits a generative
    block model to the graph -- a fundamentally different clustering approach.
    graph-tool is a heavy, non-pip-installable dependency (conda-forge/apt
    only), so it's imported lazily here rather than at module load, so
    environments without it can still serve every other algorithm.
    """
    if graph.vcount() == 0:
        return {}, 'none'

    try:
        import graph_tool.all as gt
    except ImportError as exc:
        raise ImportError(
            "The `graph-tool` package is required for hsbm clustering. Install it via conda "
            "(conda install -c conda-forge graph-tool) in the active environment."
        ) from exc

    if graph.ecount() == 0:
        return _assign_membership(graph, _singleton_membership(graph)), 'hsbm'

    gt.seed_rng(seed)

    edges = np.array([(edge.source, edge.target) for edge in graph.es], dtype="int32")
    weights = np.array(
        [edge['weight'] if 'weight' in edge.attributes() else 1.0 for edge in graph.es],
        dtype="float64",
    )

    gt_graph = gt.Graph(directed=False)
    gt_graph.add_vertex(graph.vcount())  # keep vertex indices aligned with `graph`, including isolated nodes
    gt_graph.add_edge_list(edges)
    gt_graph.ep.weight = gt_graph.new_edge_property("double")
    gt_graph.ep.weight.a = weights

    state = gt.minimize_nested_blockmodel_dl(
        gt_graph,
        base_state=gt.WeightedBlockState,
        state_args={'deg_corr': True},
        # Fit on the actual -log10(p)*|effect size| edge weights (real-valued
        # covariate), not just unweighted topology -- otherwise hsbm ignores
        # the same significance/effect-size signal that Leiden/Louvain/Infomap
        # all use.
        base_state_args={'rec': [gt_graph.ep.weight], 'rec_types': ['real-exponential']},
    )
    blocks = state.get_bs()[0]  # finest level, matching Leiden/Louvain's flat output
    raw_membership = [int(blocks[vertex]) for vertex in gt_graph.vertices()]

    # graph-tool's block ids are internal slots from its merge/split search --
    # e.g. {6, 100} instead of {0, 1} -- so remap to a compact 0..k-1 range to
    # match what Leiden/Louvain/Infomap already return.
    compact_id = {raw_id: idx for idx, raw_id in enumerate(sorted(set(raw_membership)))}
    membership = [compact_id[raw_id] for raw_id in raw_membership]

    return _assign_membership(graph, membership), 'hsbm'

def _run_leiden_clustering(graph, resolution=1.0, seed=42):
    """Run Leiden on an igraph graph."""
    if graph.vcount() == 0:
        return {}, 'none'

    if graph.ecount() == 0:
        return _assign_membership(graph, _singleton_membership(graph)), 'leiden'

    partition = leidenalg.find_partition(
        graph,
        leidenalg.RBConfigurationVertexPartition,
        weights=graph.es['weight'] if graph.ecount() else None,
        resolution_parameter=resolution,
        seed=seed,
    )

    return _assign_membership(graph, partition.membership), 'leiden'

def _run_louvain_clustering(graph):
    if graph.vcount() == 0:
        return {}, 'none'

    if graph.ecount() == 0:
        return _assign_membership(graph, _singleton_membership(graph)), 'louvain'

    communities = graph.community_multilevel(weights=graph.es['weight'])
    return _assign_membership(graph, communities.membership), 'louvain'


MAX_SIGNIFICANT_RANKING_RESULTS = 10000


def _edge_ranking_sort_key(edge):
    """p-value ascending, |effect size| descending tiebreak, missing values sort last on
    either key -- mirrors the frontend's rankEdges() (networkRanking.js) exactly, so the
    globally top-ranked edges computed here match what the client would have picked."""
    p_value = edge['p_value']
    p_key = (1, 0.0) if p_value is None else (0, float(p_value))
    effect_size = edge['effect_size']
    abs_effect = None if effect_size is None else abs(float(effect_size))
    effect_key = (1, 0.0) if abs_effect is None else (0, -abs_effect)
    return (p_key, effect_key)


def _compute_node_degree_stats(links):
    """
    {node_id: {'degree': int, 'weighted_degree': float}} for every node touched by links,
    where weighted_degree sums _compute_edge_weight over each node's incident edges.
    """
    degree = defaultdict(int)
    weighted_degree = defaultdict(float)
    for edge in links:
        weight = _compute_edge_weight(edge)
        for node_id in (edge['source'], edge['target']):
            degree[node_id] += 1
            weighted_degree[node_id] += weight
    return {
        node_id: {'degree': degree[node_id], 'weighted_degree': weighted_degree[node_id]}
        for node_id in degree
    }


def _rank_and_truncate_significant_network(candidate_links, max_edges=MAX_SIGNIFICANT_RANKING_RESULTS,
                                            max_nodes=MAX_SIGNIFICANT_RANKING_RESULTS):
    """
    Ranks the significant network matching the user given threshold and parameter and truncates the 
    Edges (and Nodes) to MAX_SIGNIFICANT_RANKING_RESULTS. Edges are ranked by p-value (ascending) and 
    effect size (descending), with missing values sorting last. Nodes are ranked by their weighted 
    degree (descending) and degree (descending), with missing values sorting last. The Weighted degree 
    and degree of the returned nodes are computed over the entire significant network, not just the truncated edges.
    Meta information (total significant edges etc. is returned for displayed in the frontend.)

    Returns (meta, node_stats_by_id, top_edges):
        - meta: total_significant_edges/nodes (true counts, pre-truncation),
          edges_truncated/nodes_truncated, max_edges/max_nodes.
        - node_stats_by_id: {node_id: {degree, weighted_degree, rank}} for the top nodes only.
        - top_edges: candidate_links truncated to max_edges, each with a 'rank' (1..N,
          global) attached.
    """
    degree_stats = _compute_node_degree_stats(candidate_links)
    weighted_degree = {node_id: stats['weighted_degree'] for node_id, stats in degree_stats.items()}
    degree = {node_id: stats['degree'] for node_id, stats in degree_stats.items()}

    total_significant_edges = len(candidate_links)
    total_significant_nodes = len(weighted_degree)

    candidate_links.sort(key=_edge_ranking_sort_key)
    top_edges = candidate_links[:max_edges]
    for rank, edge in enumerate(top_edges, start=1):
        edge['rank'] = rank

    ranked_node_ids = sorted(
        weighted_degree.keys(),
        key=lambda node_id: (-weighted_degree[node_id], -degree[node_id], node_id),
    )
    node_stats_by_id = {
        node_id: {'degree': degree[node_id], 'weighted_degree': weighted_degree[node_id], 'rank': rank}
        for rank, node_id in enumerate(ranked_node_ids[:max_nodes], start=1)
    }

    meta = {
        'total_significant_edges': total_significant_edges,
        'total_significant_nodes': total_significant_nodes,
        'edges_truncated': total_significant_edges > max_edges,
        'nodes_truncated': total_significant_nodes > max_nodes,
        'max_edges': max_edges,
        'max_nodes': max_nodes,
    }
    return meta, node_stats_by_id, top_edges


#TODO: add @extend_schema_view
class GetCosmographView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        limit, threshold, per_node_limit, density = parse_query_params(request)

        # Handle error responses
        if isinstance(limit, HttpResponseBadRequest):
            return limit
        if isinstance(threshold, HttpResponseBadRequest):
            return threshold
        if isinstance(per_node_limit, HttpResponseBadRequest):
            return per_node_limit
        if isinstance(density, HttpResponseBadRequest):
            return density

        context_id = parse_context_id(request)
        if isinstance(context_id, HttpResponseBadRequest):
            return context_id

        # A context has its own fixed testType (Context.params['testType']) --
        # only require/parse the request's testType when no context is selected.
        if context_id is None:
            test_type = parse_test_type(request)
            if isinstance(test_type, HttpResponseBadRequest):
                return test_type
        else:
            try:
                _, test_type = resolve_context_edge_table(context_id)
            except ValueError as ex:
                return HttpResponseBadRequest(str(ex), status=405)

        # Explicit opt-in from the "Full Network Statistics" panel (see
        # buildWholeNetworkByPvalThreshUrl in data-network.vue) -- ranking/truncation
        # below is gated on this flag rather than inferred from which of
        # limit/per_node_limit/density happen to be absent, so a future caller can't
        # accidentally get the truncated ranking view (or the stats panel silently stop
        # truncating) just because it does/doesn't happen to pass some other param.
        full_network_stats = request.GET.get('full_network_stats') in ('1', 'true', 'True')
        if full_network_stats and threshold is None:
            return HttpResponseBadRequest('threshold is required when full_network_stats is set.', status=405)

        logger.info(
            'Start Cosmograph request with limit=%s threshold=%s per_node_limit=%s density=%s '
            'full_network_stats=%s test_type=%s context_id=%s',
            limit,
            threshold,
            per_node_limit,
            density,
            full_network_stats,
            test_type,
            context_id,
        )

        # Extract candidate_links, selected_links, and nodes from the database
        candidate_links, selected_links, used_node_ids = get_whole_network(
            test_type=test_type,
            thresh=threshold,
            limit=limit,
            per_node_limit=per_node_limit,
            density=density,
            context_id=context_id,
        )

        # Only the explicit "Full Network Statistics" request (full_network_stats=true)
        # gets ranked and truncated: selected_links there is every edge matching threshold,
        # unsorted and unbounded, which doesn't scale to bigger cohorts -- rank and truncate
        # it (see _rank_and_truncate_significant_network) so the response stays bounded, and
        # restrict points to the top-ranked nodes instead of the whole cohort/context below.
        # Every other request -- including "Send Whole Network" building the graph itself,
        # even if it were ever called with threshold instead of density -- comes back
        # bounded (by density/limit/per_node_limit as given) and keeps its existing,
        # untruncated shape.
        ranking_meta = None
        node_stats_by_id = {}
        if full_network_stats:
            ranking_meta, node_stats_by_id, selected_links = _rank_and_truncate_significant_network(selected_links)

        response_links = selected_links

        # degree/weighted_degree for every node touched by the returned links -- the
        # ranking branch above already computed these (plus 'rank') for its top nodes;
        # otherwise (bounded "Send Whole Network"/search fetches) compute them fresh so
        # every point still carries degree/weighted_degree for e.g. rank-based coloring.
        degree_stats_by_id = node_stats_by_id if node_stats_by_id else _compute_node_degree_stats(response_links)

        node_model = apps.get_model('network', 'Nodes')
        if node_stats_by_id:
            cohort_nodes = node_model.objects.filter(node_id__in=node_stats_by_id.keys()).values(
                'node_id', 'display_name', 'node_group', 'node_subgroup', 'data_type', 'description', 'xrefs')
        else:
            cohort_nodes = node_model.objects.all().values('node_id', 'display_name', 'node_group', 'node_subgroup', 'data_type', 'description', 'xrefs')
            if context_id is not None:
                # Nodes/points are otherwise every row of the (context-independent) Nodes
                # table -- restrict to only the variables actually part of this context
                # (e.g. a protein-only context shouldn't surface phenotype/metabolite nodes).
                context_node_ids = get_context_node_ids(context_id)
                cohort_nodes = cohort_nodes.filter(node_id__in=context_node_ids)

        points = [
            {
                'id': node['node_id'],
                'label': node.get('display_name') or node['node_id'],
                'type': node.get('node_group') or '',
                'subtype': node.get('node_subgroup') or '',
                'source_table': node.get('node_group'),
                'data_type': node.get('data_type') or '',
                'description': node.get('description') or '',
                'xrefs': node.get('xrefs') or '',
                **degree_stats_by_id.get(node['node_id'], {}),
            }
            for node in cohort_nodes
            if node.get('node_id') and (not node_stats_by_id or node['node_id'] in node_stats_by_id)
        ]
        if node_stats_by_id:
            # The DB lookup above doesn't preserve order -- put points back in
            # weighted-degree rank order.
            points.sort(key=lambda point: point['rank'])

        logger.info(
            'Retrieval complete. points=%s links=%s candidates=%s',
            len(points),
            len(selected_links),
            len(candidate_links),
        )

        meta = {
            'point_count': len(points),
            'link_count': len(response_links),
            'candidate_link_count': len(candidate_links),
            'limit': limit,
            'threshold': threshold,
            'per_node_limit': per_node_limit,
            'test_type': test_type,
            'context_id': context_id,
            #'edge_weight': edge_weight,
        }
        if ranking_meta:
            meta.update(ranking_meta)

        response = JsonResponse(
            {
                'meta': meta,
                'points': points,
                'links': response_links,
            },
            status=200,
        )
        return response


#TODO: add @extend_schema_view
class GetLeidenMetagraphView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        # Measure runtime

        start_whole_request = time.perf_counter()
        limit, threshold, per_node_limit, density = parse_query_params(request)

        if isinstance(limit, HttpResponseBadRequest):
            return limit
        if isinstance(threshold, HttpResponseBadRequest):
            return threshold
        if isinstance(per_node_limit, HttpResponseBadRequest):
            return per_node_limit
        if isinstance(density, HttpResponseBadRequest):
            return density

        context_id = parse_context_id(request)
        if isinstance(context_id, HttpResponseBadRequest):
            return context_id

        # A context has its own fixed testType (Context.params['testType']) --
        # only require/parse the request's testType when no context is selected.
        if context_id is None:
            test_type = parse_test_type(request)
            if isinstance(test_type, HttpResponseBadRequest):
                return test_type
        else:
            try:
                _, test_type = resolve_context_edge_table(context_id)
            except ValueError as ex:
                return HttpResponseBadRequest(str(ex), status=405)

        # Parse resolutions parameter (defaults to all standard resolutions)
        resolutions = parse_resolution_values(request)
        if isinstance(resolutions, HttpResponseBadRequest):
            return resolutions

        seed_raw = request.GET.get('seed', None)
        if seed_raw in ['', 'null', None]:
            seed = 42
        else:
            try:
                seed = int(seed_raw)
            except ValueError:
                return HttpResponseBadRequest('seed must be an integer.', status=405)

        method = request.GET.get('algorithm', 'leiden')
        method = method.strip().lower()

        if method not in SUPPORTED_COMMUNITY_METHODS:
            return HttpResponseBadRequest(
                f"algorithm must be one of: {', '.join(SUPPORTED_COMMUNITY_METHODS)}.",
                status=405,
            )

        logger.info(
            'Start metagraph request with limit=%s threshold=%s per_node_limit=%s density=%s test_type=%s context_id=%s seed=%s algorithm=%s',
            limit,
            threshold,
            per_node_limit,
            density,
            test_type,
            context_id,
            seed,
            method,
        )

        candidate_links, selected_links, used_node_ids = get_whole_network(
            test_type=test_type,
            thresh=threshold,
            limit=limit,
            per_node_limit=per_node_limit,
            density=density,
            context_id=context_id,
        )

        # Run the selected community detection method for each resolution
        resolution_results = {}
        community_counts_by_resolution = {}
        modularity_by_resolution = {}
        conductance_by_resolution = {}
        clustering_algorithm = 'unknown'

        graph = build_weighted_graph(selected_links, used_node_ids)

        cached_result = None
        for resolution in resolutions:
            # Measure runtime

            start_one_leiden_run = time.perf_counter()
            try:
                if method in RESOLUTION_INDEPENDENT_METHODS:
                    if cached_result is None:
                        cached_result = run_community_clustering(graph, method=method, resolution=resolution, seed=seed)
                    node_to_community, algo = cached_result
                else:
                    node_to_community, algo = run_community_clustering(
                        graph,
                        method=method,
                        resolution=resolution,
                        seed=seed,
                    )
            except ImportError as ex:
                return HttpResponseBadRequest(str(ex), status=503)
            clustering_algorithm = algo  # Store algorithm (same for all)
            resolution_results[resolution] = node_to_community
            community_count = len(set(node_to_community.values())) if node_to_community else 0
            resolution_key = resolution_to_key(resolution)
            community_counts_by_resolution[resolution_key] = community_count
            modularity_by_resolution[resolution_key] = round(compute_modularity(graph, node_to_community), 6)
            conductance_by_resolution[resolution_key] = round(compute_conductance(graph, node_to_community), 6)
            end = time.perf_counter()
            print(f"One run {method} runtime: {end - start_one_leiden_run:.4f} seconds for resolution {resolution}")

        response_links = selected_links
        degree_stats_by_id = _compute_node_degree_stats(response_links)

        # All nodes, not just used_node_ids (the ones clustered) -- matches
        # GetCosmographView's node set, so switching between "Send Whole Network"
        # and "Run Leiden Clustering" doesn't change which nodes are shown, only
        # their coloring. A node outside used_node_ids has no entry in any
        # resolution_results dict, so its community_rX fields below come back
        # None/null -- the frontend already renders that as an "Unassigned" bucket.
        node_model = apps.get_model('network', 'Nodes')
        cohort_nodes = node_model.objects.all().values('node_id', 'display_name', 'node_group', 'node_subgroup', 'data_type', 'description', 'xrefs')
        if context_id is not None:
            # Restrict to this context's own variables (e.g. a protein-only context
            # shouldn't surface phenotype/metabolite nodes) -- see GetCosmographView.
            context_node_ids = get_context_node_ids(context_id)
            cohort_nodes = cohort_nodes.filter(node_id__in=context_node_ids)

        # Build points with community fields for each resolution
        points = []
        for node in cohort_nodes:
            if not node.get('node_id'):
                continue

            point = {
                'id': node['node_id'],
                'label': node.get('display_name') or node['node_id'],
                'type': node.get('node_group') or '',
                'subtype': node.get('node_subgroup') or '',
                'source_table': node.get('node_group'),
                'data_type': node.get('data_type') or '',
                'description': node.get('description') or '',
                'xrefs': node.get('xrefs') or '',
                **degree_stats_by_id.get(node['node_id'], {}),
            }

            # Add community field for each resolution
            for resolution in resolutions:
                field_key = f"community_r{resolution_to_key(resolution)}"
                point[field_key] = resolution_results[resolution].get(node['node_id'])

            points.append(point)

        logger.info(
            'Multi-resolution metagraph complete. points=%s links=%s resolutions=%s algorithm=%s',
            len(points),
            len(response_links),
            len(resolutions),
            clustering_algorithm,
        )
        end = time.perf_counter()
        print(f"Whole request {method} runtime: {end - start_whole_request:.4f} seconds")


        return JsonResponse(
            {
                'meta': {
                    'point_count': len(points),
                    'link_count': len(response_links),
                    'candidate_link_count': len(candidate_links),
                    'community_counts_by_resolution': community_counts_by_resolution,
                    'modularity_by_resolution': modularity_by_resolution,
                    'conductance_by_resolution': conductance_by_resolution,
                    'resolutions': [resolution_to_key(r) for r in resolutions],
                    'algorithm': clustering_algorithm,
                    'seed': seed,
                    'limit': limit,
                    'threshold': threshold,
                    'per_node_limit': per_node_limit,
                    'test_type': test_type,
                    'context_id': context_id,
                    #'edge_weight': edge_weight,
                },
                'points': points,
                'links': response_links,
            },
            status=200,
        )