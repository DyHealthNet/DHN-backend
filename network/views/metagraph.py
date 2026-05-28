import json
import importlib
import os
import time
import timeit
from datetime import datetime
from collections import defaultdict

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dyhealthnet_project.settings')

import django
from django.apps import apps as django_apps

if not django_apps.ready:
    django.setup()

import igraph as ig
import pandas as pd
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

types = ["protein", "metabolite", "phenotype", "variant"]  # "disorders", "genes"
layers_to_source_table = {
    "proteomics": "cohort_protein",
    "metabolomics": "cohort_metabolite",
    "phenomics": "cohort_phenotype",
    "variants": "cohort_variant"
}

DEFAULT_LEIDEN_RESOLUTIONS = [0.2, 0.5, 1.0, 1.5, 2.0, 3.0]
SUPPORTED_COMMUNITY_METHODS = ('leiden', 'louvain', 'agglomerative', 'hsbm')
BENCHMARK_DEFAULT_LIMIT = None
BENCHMARK_DEFAULT_THRESHOLD = 0.05
BENCHMARK_DEFAULT_PER_NODE_LIMIT = None


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


def build_weighted_graph(selected_links, used_node_ids):
    """Build a simple igraph graph with summed edge weights."""
    sorted_nodes = sorted({str(node_id) for node_id in used_node_ids})
    node_to_idx = {node_id: idx for idx, node_id in enumerate(sorted_nodes)}

    edge_weights = defaultdict(float)
    for edge in selected_links:
        source = edge.get('source')
        target = edge.get('target')
        if not source or not target:
            continue

        source = str(source)
        target = str(target)
        if source not in node_to_idx or target not in node_to_idx:
            continue

        key = tuple(sorted((source, target)))
        edge_weights[key] = float(edge.get('weight', 1.0) or 1.0)

    edges = [(node_to_idx[source], node_to_idx[target]) for source, target in edge_weights.keys()]
    weights = list(edge_weights.values())

    graph = ig.Graph(n=len(sorted_nodes), edges=edges, directed=False)
    graph.vs['name'] = sorted_nodes
    if weights:
        graph.es['weight'] = weights

    return graph

    # using pandas for aggregation (fast and readable)
# TODO: do faster graph building??
# df = pd.DataFrame(selected_links)  # must have 'source','target', optional 'weight'
# df['source'] = df['source'].astype(str)
# df['target'] = df['target'].astype(str)
# # normalize undirected pair
# df[['u','v']] = pd.DataFrame(
#     np.sort(df[['source','target']].values, axis=1),
#     index=df.index
# )
# # choose aggregation policy: sum / max / existence
# df['weight'] = df.get('weight').fillna(1.0)
# agg = df.groupby(['u','v'], sort=False, as_index=False)['weight'].sum()

# triples = list(agg.itertuples(index=False, name=None))  # (u,v,weight)
# g = ig.Graph.TupleList(triples, directed=False, weights=True, vertex_name_attr='name')


def communities_from_mapping(node_to_community):
    grouped = defaultdict(set)
    for node_id, community_id in node_to_community.items():
        grouped[community_id].add(node_id)
    return [members for _, members in sorted(grouped.items(), key=lambda item: item[0]) if members]


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


def _assign_membership(graph, membership):
    return {graph.vs[idx]['name']: community_id for idx, community_id in enumerate(membership)}


def _singleton_membership(graph):
    return list(range(graph.vcount()))


def _run_leiden_like_clustering(graph, resolution=1.0, seed=42):
    """Run Leiden on an igraph graph, with Louvain fallback if leidenalg is unavailable."""
    if graph.vcount() == 0:
        return {}, 'none'

    try:
        import leidenalg

        start_just_leiden = time.perf_counter()
        partition = leidenalg.find_partition(
            graph,
            leidenalg.RBConfigurationVertexPartition,
            weights=graph.es['weight'] if graph.ecount() else None,
            resolution_parameter=resolution,
            seed=seed,
        )

        end = time.perf_counter()
        print(f"Just one Leiden runtime: {end - start_just_leiden:.4f} seconds")

        return _assign_membership(graph, partition.membership), 'leiden'
    except Exception as exc:
        logger.warning('Leiden unavailable, using igraph Louvain fallback: %s', exc)

    if graph.ecount() == 0:
        return _assign_membership(graph, _singleton_membership(graph)), 'louvain_fallback'

    communities = graph.community_multilevel(weights=graph.es['weight'])
    return _assign_membership(graph, communities.membership), 'louvain_fallback'


def _run_louvain_clustering(graph, resolution=1.0, seed=42):
    if graph.vcount() == 0:
        return {}, 'none'

    if graph.ecount() == 0:
        return _assign_membership(graph, _singleton_membership(graph)), 'louvain'

    communities = graph.community_multilevel(weights=graph.es['weight'])
    return _assign_membership(graph, communities.membership), 'louvain'


def _run_agglomerative_clustering(graph):
    if graph.vcount() == 0:
        return {}, 'none'

    if graph.ecount() == 0:
        return _assign_membership(graph, _singleton_membership(graph)), 'agglomerative'

    communities = graph.community_fastgreedy(weights=graph.es['weight']).as_clustering()
    return _assign_membership(graph, communities.membership), 'agglomerative'


def _summarize_agglomerative_levels(graph):
    """Return the meaningful coarser-side cuts for the agglomerative merge tree."""
    if graph.vcount() == 0:
        return []

    if graph.ecount() == 0:
        membership = _singleton_membership(graph)
        return [{
            'level': 0,
            'node_to_community': _assign_membership(graph, membership),
            'community_count': len(set(membership)),
            'modularity': 0.0,
            'communities': [1] * graph.vcount(),
        }]

    dendrogram = graph.community_fastgreedy(weights=graph.es['weight'])
    optimal_count = int(dendrogram.optimal_count)

    # For agglomerative clustering, cuts above the modularity-optimal partition
    # quickly turn into singleton-heavy refinements. Benchmark only the coarser
    # side up to the optimal cut so the rows stay meaningful.
    cut_counts = list(range(1, optimal_count + 1))

    level_summaries = []
    total_levels = len(cut_counts)

    for level_index, cluster_count in enumerate(cut_counts):
        clustering = dendrogram.as_clustering(n=cluster_count)
        membership = list(clustering.membership)
        node_to_community = _assign_membership(graph, membership)

        size_map = {}
        for comm in membership:
            size_map[comm] = size_map.get(comm, 0) + 1

        level_summaries.append({
            'level': level_index,
            'node_to_community': node_to_community,
            'community_count': len(set(membership)) if membership else 0,
            'modularity': round(compute_modularity(graph, node_to_community), 6),
            'communities': sorted(size_map.values(), reverse=True),
            'hierarchy_label': f'cut {cluster_count} communities',
            'hierarchy_depth': total_levels,
            'cut_count': cluster_count,
        })

    return level_summaries


def _run_hsbm_like_clustering(graph, resolution=1.0, seed=42, max_depth=4, min_cluster_size=4):
    """Backward-compatible approximation built from recursive Louvain splits."""
    if graph.vcount() == 0:
        return {}, 'none'

    leaf_assignments = {}
    next_cluster_id = 0

    def assign_leaf(nodes):
        nonlocal next_cluster_id
        for node_id in nodes:
            leaf_assignments[node_id] = next_cluster_id
        next_cluster_id += 1

    def recurse(nodes, depth):
        indices = [graph.vs.find(name=node_id).index for node_id in nodes]
        subgraph = graph.subgraph(indices)
        if subgraph.vcount() <= min_cluster_size or depth >= max_depth or subgraph.ecount() == 0:
            assign_leaf(subgraph.vs['name'])
            return

        local_resolution = resolution * (1.0 + 0.25 * depth)
        communities = subgraph.community_multilevel(weights=subgraph.es['weight'])

        if len(communities) <= 1:
            assign_leaf(subgraph.vs['name'])
            return

        for community_indices in communities:
            community_names = [subgraph.vs[idx]['name'] for idx in community_indices]
            if len(community_names) <= min_cluster_size:
                assign_leaf(community_names)
            else:
                recurse(community_names, depth + 1)

    recurse(set(graph.vs['name']), 0)
    return leaf_assignments, 'hsbm_like'


def _run_hsbm_clustering(graph, seed=42):
    """Run a real hierarchical stochastic block model using graph-tool."""
    node_to_community, _, _ = _run_hsbm_clustering_with_levels(graph, seed=seed)
    return node_to_community, 'hsbm'


def _summarize_hsbm_levels(graph, gt_graph, state):
    """Return per-level community counts and modularity for the nested HSBM tree."""
    level_summaries = []
    for level_index, blocks in enumerate(state.get_bs()):
        projected_state = state.project_level(level_index)
        membership = [int(block_id) for block_id in projected_state.get_blocks()]
        node_to_community = {
            graph.vs[idx]['name']: membership[idx]
            for idx in range(len(membership))
        }

        size_map = {}
        for comm in membership:
            size_map[comm] = size_map.get(comm, 0) + 1

        level_summaries.append({
            'level': level_index,
            'node_to_community': node_to_community,
            'community_count': len(set(membership)) if membership else 0,
            'modularity': round(compute_modularity(graph, node_to_community), 6),
            'communities': sorted(size_map.values(), reverse=True),
        })

        # Once the projection collapses to a single community, coarser levels are
        # redundant for benchmarking because they will remain identical.
        if level_summaries[-1]['community_count'] <= 1:
            break

    return level_summaries


def _run_hsbm_clustering_with_levels(graph, seed=42):
    """Run a real hierarchical stochastic block model using graph-tool."""
    if graph.vcount() == 0:
        return {}, 'none', []

    gt = importlib.import_module('graph_tool.all')

    gt_graph = gt.Graph(directed=False)
    gt_graph.add_vertex(graph.vcount())
    gt_graph.vp.name = gt_graph.new_vertex_property('string')
    gt_graph.ep.weight = gt_graph.new_edge_property('double')

    for idx, vertex in enumerate(graph.vs):
        gt_graph.vp.name[vertex.index] = vertex['name']

    for edge in graph.es:
        source = int(edge.source)
        target = int(edge.target)
        gt_edge = gt_graph.add_edge(source, target)
        gt_graph.ep.weight[gt_edge] = float(edge['weight'])

    state = gt.minimize_nested_blockmodel_dl(gt_graph, state_args={'deg_corr': True})
    blocks = state.get_bs()[0]  # lowest level keeps the existing flat clustering behaviour.
    membership = [int(blocks[v]) for v in gt_graph.vertices()]
    hierarchy_levels = _summarize_hsbm_levels(graph, gt_graph, state)
    return _assign_membership(graph, membership), 'hsbm', hierarchy_levels


def run_community_clustering(selected_links, used_node_ids, method='leiden', resolution=1.0, seed=42):
    graph = build_weighted_graph(selected_links, used_node_ids)
    method = (method or 'leiden').strip().lower()

    if method == 'leiden':
        return _run_leiden_like_clustering(graph, resolution=resolution, seed=seed)
    if method == 'louvain':
        return _run_louvain_clustering(graph, seed=seed)
    if method == 'agglomerative':
        return _run_agglomerative_clustering(graph)
    if method == 'hsbm':
        node_to_community, algorithm_name, _ = _run_hsbm_clustering_with_levels(graph, seed=seed)
        return node_to_community, algorithm_name

    raise ValueError(f"Unsupported community detection method '{method}'. Choose from: {', '.join(SUPPORTED_COMMUNITY_METHODS)}.")

def benchmark_community_detection(selected_links, used_node_ids, methods=None, resolution=1.0, seed=42):
    graph = build_weighted_graph(selected_links, used_node_ids)
    methods = methods or SUPPORTED_COMMUNITY_METHODS
    node_count = graph.vcount()
    edge_count = graph.ecount()

    benchmark_rows = []
    for method in methods:
        start = time.perf_counter()
        if method == 'hsbm':
            node_to_community, algorithm_name, hierarchy_levels = _run_hsbm_clustering_with_levels(
                graph,
                seed=seed,
            )
            runtime = time.perf_counter() - start

            total_levels = len(hierarchy_levels)
            for level_summary in hierarchy_levels:
                level_number = level_summary['level'] + 1
                row = {
                    'method': f'hsbm_level_{level_number}_of_{total_levels}',
                    'algorithm': algorithm_name,
                    'hierarchy_level': level_number,
                    'hierarchy_depth': total_levels,
                    'hierarchy_label': f'level {level_number} of {total_levels}',
                    'runtime_seconds': round(runtime, 6),
                    'modularity': level_summary['modularity'],
                    'community_count': level_summary['community_count'],
                    'node_count': node_count,
                    'edge_count': edge_count,
                    # JSON-encode the community id/size list so it fits cleanly into CSV
                    'communities': json.dumps(level_summary['communities']),
                }
                benchmark_rows.append(row)
                print(
                    f"{row['method']}: runtime={row['runtime_seconds']:.6f}s modularity={row['modularity']:.6f}"
                )

            continue
        if method == 'agglomerative':
            node_to_community, algorithm_name = _run_agglomerative_clustering(graph)
            runtime = time.perf_counter() - start
            hierarchy_levels = _summarize_agglomerative_levels(graph)

            total_levels = len(hierarchy_levels)
            for level_summary in hierarchy_levels:
                level_number = level_summary['level'] + 1
                row = {
                    'method': f'agglomerative_cut_{level_summary["cut_count"]}',
                    'algorithm': algorithm_name,
                    'hierarchy_level': level_number,
                    'hierarchy_depth': total_levels,
                    'hierarchy_label': level_summary['hierarchy_label'],
                    'runtime_seconds': round(runtime, 6),
                    'modularity': level_summary['modularity'],
                    'community_count': level_summary['community_count'],
                    'node_count': node_count,
                    'edge_count': edge_count,
                    'communities': json.dumps(level_summary['communities']),
                }
                benchmark_rows.append(row)
                print(
                    f"{row['method']}: runtime={row['runtime_seconds']:.6f}s modularity={row['modularity']:.6f}"
                )

            continue
        else:
            node_to_community, algorithm_name = run_community_clustering(
                selected_links=selected_links,
                used_node_ids=used_node_ids,
                method=method,
                resolution=resolution,
                seed=seed,
            )
            runtime = time.perf_counter() - start
        modularity = compute_modularity(graph, node_to_community)
        community_count = len(set(node_to_community.values())) if node_to_community else 0

        # Build a compact representation: ordered community sizes (largest first)
        if node_to_community:
            size_map = {}
            for comm in node_to_community.values():
                size_map[comm] = size_map.get(comm, 0) + 1
            communities_with_size = sorted(size_map.values(), reverse=True)
        else:
            communities_with_size = []

        row = {
            'method': method,
            'algorithm': algorithm_name,
            'hierarchy_level': None,
            'hierarchy_depth': None,
            'hierarchy_label': None,
            'runtime_seconds': round(runtime, 6),
            'modularity': round(modularity, 6),
            'community_count': community_count,
            'node_count': node_count,
            'edge_count': edge_count,
            # JSON-encode the community id/size list so it fits cleanly into CSV
            'communities': json.dumps(communities_with_size),
        }
        benchmark_rows.append(row)
        print(
            f"{method}: runtime={row['runtime_seconds']:.6f}s modularity={row['modularity']:.6f}"
        )

    return pd.DataFrame(benchmark_rows)


def run_benchmark_from_whole_network(
    limit=BENCHMARK_DEFAULT_LIMIT,
    threshold=BENCHMARK_DEFAULT_THRESHOLD,
    per_node_limit=BENCHMARK_DEFAULT_PER_NODE_LIMIT,
    methods=None,
    resolution=1.0,
    seed=42,
    output_dir='.',
):
    candidate_links, selected_links, used_node_ids = get_whole_network(
        thresh=threshold,
        limit=limit,
        per_node_limit=per_node_limit,
    )

    selected_node_count = len(used_node_ids)
    selected_edge_count = len(selected_links)
    candidate_edge_count = len(candidate_links)
    used_network_node_count = selected_node_count
    used_network_edge_count = selected_edge_count
    possible_edge_count = selected_node_count * (selected_node_count - 1) / 2 if selected_node_count > 1 else 0
    network_density = (selected_edge_count / possible_edge_count) if possible_edge_count else 0.0

    print(
        f"Benchmark network size: {selected_node_count} nodes, {selected_edge_count} edges "
        f"(density: {network_density:.6f})"
    )

    benchmark_df = benchmark_community_detection(
        selected_links=selected_links,
        used_node_ids=used_node_ids,
        methods=methods or SUPPORTED_COMMUNITY_METHODS,
        resolution=resolution,
        seed=seed,
    )

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    file_name = f'benchmarking_cm_detection_{timestamp}.csv'
    output_path = os.path.join(output_dir, file_name)

    # Shared metadata is written once above the table to keep method rows compact.
    metadata_rows = [
        ('selected_node_count', selected_node_count),
        ('selected_edge_count', selected_edge_count),
        ('candidate_edge_count', candidate_edge_count),
        ('used_network_node_count', used_network_node_count),
        ('used_network_edge_count', used_network_edge_count),
        ('network_density', round(network_density, 6)),
        ('threshold', threshold),
        ('limit', limit),
        ('per_node_limit', per_node_limit),
    ]

    table_columns = [
        'method',
        'algorithm',
        'hierarchy_level',
        'hierarchy_depth',
        'hierarchy_label',
        'runtime_seconds',
        'modularity',
        'community_count',
        'communities',
    ]
    method_table_df = benchmark_df.loc[:, table_columns].copy()

    with open(output_path, 'w', encoding='utf-8') as output_file:
        output_file.write('metric,value\n')
        for key, value in metadata_rows:
            output_file.write(f'{key},{"" if value is None else value}\n')
        output_file.write('\n')
        method_table_df.to_csv(output_file, index=False)

    print(f"Benchmark results written to: {output_path}")
    print('Shared benchmark metadata:')
    for key, value in metadata_rows:
        print(f'  {key}: {value}')
    return method_table_df, output_path

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
            #id__in=used_node_ids,
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
                'meta': {
                    'point_count': len(points),
                    'link_count': len(response_links),
                    'candidate_link_count': len(candidate_links),
                    'limit': limit,
                    'threshold': threshold,
                    'per_node_limit': per_node_limit,
                },
                'points': points,
                'links': response_links,
            },
            status=200,
        )


#TODO: add @extend_schema_view
class GetLeidenMetagraphView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        # Measure runtime

        start_whole_request = time.perf_counter()
        limit, threshold, per_node_limit = parse_query_params(request)

        if isinstance(limit, HttpResponseBadRequest):
            return limit
        if isinstance(threshold, HttpResponseBadRequest):
            return threshold
        if isinstance(per_node_limit, HttpResponseBadRequest):
            return per_node_limit

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
            'Start metagraph request with limit=%s threshold=%s per_node_limit=%s resolutions=%s seed=%s algorithm=%s',
            limit,
            threshold,
            per_node_limit,
            resolutions,
            seed,
            method,
        )

        candidate_links, selected_links, used_node_ids = get_whole_network(
            thresh=threshold,
            limit=limit,
            per_node_limit=per_node_limit,
        )

        # Run the selected community detection method for each resolution
        resolution_results = {}
        community_counts_by_resolution = {}
        clustering_algorithm = 'unknown'
        
        for resolution in resolutions:
            # Measure runtime

            start_one_leiden_run = time.perf_counter()
            node_to_community, algo = run_community_clustering(
                selected_links=selected_links,
                used_node_ids=used_node_ids,
                method=method,
                resolution=resolution,
                seed=seed,
            )
            clustering_algorithm = algo  # Store algorithm (same for all)
            resolution_results[resolution] = node_to_community
            community_count = len(set(node_to_community.values())) if node_to_community else 0
            community_counts_by_resolution[resolution_to_key(resolution)] = community_count
            end = time.perf_counter()
            print(f"One run {method} runtime: {end - start_one_leiden_run:.4f} seconds for resolution {resolution}")

        response_links = [
            {key: value for key, value in edge.items() if key != 'final_p_value'}
            for edge in selected_links
        ]

        node_model = apps.get_model('network', 'ViewDescriptionFTS')
        cohort_nodes = node_model.objects.filter(
            source_table__startswith='cohort_',
            id__in=used_node_ids,
        ).values('id', 'display_name', 'source_table')

        # Build points with community fields for each resolution
        points = []
        for node in cohort_nodes:
            if not node.get('id'):
                continue
            
            point = {
                'id': node['id'],
                'label': node.get('display_name') or node['id'],
                'type': (node.get('source_table') or '').replace('cohort_', ''),
                'source_table': node.get('source_table'),
            }
            
            # Add community field for each resolution
            for resolution in resolutions:
                field_key = f"community_r{resolution_to_key(resolution)}"
                point[field_key] = resolution_results[resolution].get(node['id'])
            
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
                    'resolutions': [resolution_to_key(r) for r in resolutions],
                    'algorithm': clustering_algorithm,
                    'seed': seed,
                    'limit': limit,
                    'threshold': threshold,
                    'per_node_limit': per_node_limit,
                },
                'points': points,
                'links': response_links,
            },
            status=200,
        )


if __name__ == '__main__':
    # Allows running this module directly for local benchmarking without using the API endpoint.
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dyhealthnet_project.settings')
    import django

    django.setup()

    run_benchmark_from_whole_network(
        limit=BENCHMARK_DEFAULT_LIMIT,
        threshold=BENCHMARK_DEFAULT_THRESHOLD,
        per_node_limit=BENCHMARK_DEFAULT_PER_NODE_LIMIT,
        methods=SUPPORTED_COMMUNITY_METHODS,
        resolution=1.0,
        seed=42,
        output_dir='.',
    )