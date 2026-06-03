import json
import importlib
from math import ceil
import os
import time
import timeit
from datetime import datetime
from collections import defaultdict
from pathlib import Path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dyhealthnet_project.settings')

import django
from django.apps import apps as django_apps

if not django_apps.ready:
    django.setup()

import igraph as ig
import pandas as pd
import numpy as np
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score, rand_score
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
SUPPORTED_COMMUNITY_METHODS = ('louvain', 'leiden', 'recursive_leiden', 'agglomerative', 'infomap', 'hierarchical_infomap', 'hsbm')
BENCHMARK_DEFAULT_LIMIT = None
BENCHMARK_DEFAULT_THRESHOLD = 0.999
BENCHMARK_DEFAULT_DENSITY = None
BENCHMARK_DEFAULT_PER_NODE_LIMIT = None
BENCHMARK_DEFAULT_EDGE_WEIGHT = 'final_p_value'


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
    if limit is None and threshold is None and per_node_limit is None:
        return HttpResponseBadRequest('At least one of limit, threshold or per_node_limit must be provided.', status=405), None, None
    
    return limit, threshold, per_node_limit, density


def parse_edge_weight_mode(request):
    raw_value = request.GET.get('weight', request.GET.get('edge_weight', BENCHMARK_DEFAULT_EDGE_WEIGHT))
    weight_mode = (raw_value or BENCHMARK_DEFAULT_EDGE_WEIGHT).strip().lower()
    allowed_modes = {'final_p_value', 'raw_p', 'raw_e', 'pre_ls', 'post_ls'}
    if weight_mode not in allowed_modes:
        return HttpResponseBadRequest(
            f"weight must be one of: {', '.join(sorted(allowed_modes))}.",
            status=405,
        )
    return weight_mode

def compute_edge_weight(p_value, e_value):

    if p_value is None or p_value <= 0:

        return 0.0  # or raise depending on strictness

    return -np.log10(p_value) * e_value

def build_edge_dict(selected_links, edge_weight="final_p_value"):
    selectors = {
        "raw-E": lambda e: e["final_e_value"],
        "rescaled-E": lambda e: e["final_e_value_rescaled"],
        "final_p_value": lambda e: e["final_p_value"],
        "pre-LS": lambda e: compute_edge_weight(e["final_p_value"], e["final_e_value"]),
        "post-LS": lambda e: compute_edge_weight(e["final_p_value"], e["final_e_value_rescaled"]),
    }

    if edge_weight not in selectors:
        raise ValueError(f"Invalid edge_weight '{edge_weight}'")

    select = selectors[edge_weight]
    edge_map = {}

    for edge in selected_links:
        s = edge.get("source")
        t = edge.get("target")

        if s is None or t is None:
            continue

        key = tuple(sorted((str(s), str(t))))

        if key in edge_map:
            raise ValueError(f"Duplicate edge detected for pair {key}")

        try:
            value = select(edge)
        except KeyError as e:
            raise ValueError(f"Missing required field for mode '{edge_weight}': {e}")

        edge_map[key] = value

    return edge_map

def build_weighted_graph(selected_links, used_node_ids, edge_weight="final_p_value"):
    sorted_nodes = sorted(map(str, used_node_ids))
    node_to_idx = {n: i for i, n in enumerate(sorted_nodes)}

    edge_map = build_edge_dict(selected_links, edge_weight=edge_weight)

    edges = []
    weights = []

    for (s, t), w in edge_map.items():
        if s not in node_to_idx or t not in node_to_idx:
            continue
        edges.append((node_to_idx[s], node_to_idx[t]))
        weights.append(w)

    graph = ig.Graph(n=len(sorted_nodes), edges=edges, directed=False)
    graph.vs["name"] = sorted_nodes
    graph.es["weight"] = weights

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


def _membership_vector(graph, node_to_community):
    return [node_to_community.get(vertex['name'], idx) for idx, vertex in enumerate(graph.vs)]


def _community_family_name(method_name):
    method_name = (method_name or '').strip().lower()
    if method_name.startswith('hsbm_level_'):
        return 'hsbm'
    if method_name.startswith('agglomerative_cut_'):
        return 'agglomerative'
    if method_name.startswith('recursive_leiden_level_'):
        return 'recursive_leiden'
    if method_name.startswith('hierarchical_infomap_level_'):
        return 'hierarchical_infomap'
    return method_name


def _select_best_rows_for_comparison(benchmark_df):
    if benchmark_df.empty:
        return pd.DataFrame(columns=benchmark_df.columns)

    temp = benchmark_df.copy()
    temp['family'] = temp['method'].map(_community_family_name)

    selected_rows = []
    for _, group in temp.groupby('family', sort=False):
        best_idx = group['modularity'].astype(float).idxmax()
        selected_rows.append(temp.loc[best_idx])

    return pd.DataFrame(selected_rows).reset_index(drop=True)


def _build_pairwise_comparison_table(graph, benchmark_df, benchmark_assignments):
    selected_rows = _select_best_rows_for_comparison(benchmark_df)
    if selected_rows.empty:
        return pd.DataFrame(columns=['comparison'])

    selected_entries = []
    for _, row in selected_rows.iterrows():
        selected_entries.append({
            'method': row['method'],
            'family': _community_family_name(row['method']),
            'display_name': row['method'] if _community_family_name(row['method']) == row['method'] else f"{_community_family_name(row['method'])} (best modularity)",
            'modularity': float(row['modularity']) if row['modularity'] is not None else 0.0,
            'community_count': int(row['community_count']) if row['community_count'] is not None else 0,
        })

    labels = [entry['display_name'] for entry in selected_entries]
    memberships = {
        entry['method']: _membership_vector(graph, benchmark_assignments[entry['method']])
        for entry in selected_entries
    }

    rows = []
    for left in selected_entries:
        left_label = left['display_name']
        left_membership = memberships[left['method']]
        for metric_name, scorer in (
            ('RI', rand_score),
            ('ARI', adjusted_rand_score),
            ('NMI', normalized_mutual_info_score),
        ):
            row = {'comparison': f'{metric_name} {left_label}'}
            for right in selected_entries:
                right_label = right['display_name']
                right_membership = memberships[right['method']]
                row[right_label] = round(float(scorer(left_membership, right_membership)), 4)
            rows.append(row)

    comparison_df = pd.DataFrame(rows)
    ordered_columns = ['comparison'] + labels
    comparison_df = comparison_df.loc[:, ordered_columns]
    return comparison_df


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


def _summarize_recursive_leiden_levels(graph, resolution=1.0, seed=42, max_depth=4, min_cluster_size=4):
    """Recursively split the graph with Leiden and report each level summary."""
    if graph.vcount() == 0:
        return []

    level_summaries = []

    current_clusters = [list(graph.vs['name'])]
    total_levels = 0

    for depth in range(max_depth):
        next_clusters = []
        node_to_community = {}
        split_occurred = False

        for cluster_names in current_clusters:
            indices = [graph.vs.find(name=node_id).index for node_id in cluster_names]
            subgraph = graph.subgraph(indices)

            if subgraph.vcount() <= min_cluster_size or subgraph.ecount() == 0:
                for node_id in cluster_names:
                    node_to_community[node_id] = len(next_clusters)
                next_clusters.append(cluster_names)
                continue

            try:
                import leidenalg
                partition = leidenalg.find_partition(
                    subgraph,
                    leidenalg.RBConfigurationVertexPartition,
                    weights=subgraph.es['weight'] if subgraph.ecount() else None,
                    resolution_parameter=resolution,
                    seed=seed,
                )
                membership = list(partition.membership)
            except Exception:
                if subgraph.ecount() == 0:
                    membership = _singleton_membership(subgraph)
                else:
                    membership = list(subgraph.community_multilevel(weights=subgraph.es['weight']).membership)

            unique_communities = sorted(set(membership))
            if len(unique_communities) <= 1:
                for node_id in cluster_names:
                    node_to_community[node_id] = len(next_clusters)
                next_clusters.append(cluster_names)
                continue

            split_occurred = True
            for community_id in unique_communities:
                community_names = [subgraph.vs[idx]['name'] for idx, comm in enumerate(membership) if comm == community_id]
                for node_id in community_names:
                    node_to_community[node_id] = len(next_clusters)
                next_clusters.append(community_names)

        if not node_to_community:
            break

        size_map = {}
        for comm in node_to_community.values():
            size_map[comm] = size_map.get(comm, 0) + 1

        level_summaries.append({
            'level': depth,
            'node_to_community': node_to_community,
            'community_count': len(size_map),
            'modularity': round(compute_modularity(graph, node_to_community), 6),
            'communities': sorted(size_map.values(), reverse=True),
            'hierarchy_label': f'level {depth + 1}',
            'hierarchy_depth': max_depth,
        })

        total_levels = depth + 1
        current_clusters = next_clusters
        if not split_occurred:
            break

    for level_summary in level_summaries:
        level_summary['hierarchy_depth'] = total_levels
    return level_summaries


def _run_recursive_leiden_clustering(graph, resolution=1.0, seed=42, max_depth=4, min_cluster_size=4):
    """Return the deepest recursive Leiden split for the API."""
    if graph.vcount() == 0:
        return {}, 'none'

    level_summaries = _summarize_recursive_leiden_levels(
        graph,
        resolution=resolution,
        seed=seed,
        max_depth=max_depth,
        min_cluster_size=min_cluster_size,
    )
    if not level_summaries:
        return _assign_membership(graph, _singleton_membership(graph)), 'recursive_leiden'

    return level_summaries[-1]['node_to_community'], 'recursive_leiden'


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


def _run_infomap_clustering(graph, trials=10):
    """Run flat Infomap via python-igraph's community_infomap (if available)."""
    if graph.vcount() == 0:
        return {}, 'none'

    if graph.ecount() == 0:
        return _assign_membership(graph, _singleton_membership(graph)), 'infomap'

    try:
        communities = graph.community_infomap(edge_weights=graph.es['weight'] if graph.ecount() else None, trials=trials)
        return _assign_membership(graph, communities.membership), 'infomap'
    except Exception:
        # Fallback: use louvain as a simple alternative when Infomap is unavailable
        communities = graph.community_multilevel(weights=graph.es['weight'])
        return _assign_membership(graph, communities.membership), 'infomap_fallback'


def _summarize_infomap_levels(graph, seed=42, trials=10):
    """Run the official Infomap bindings and return per-level hierarchy summaries."""
    if graph.vcount() == 0:
        return []

    try:
        from infomap import Infomap
    except ImportError as exc:
        raise ImportError(
            'The `infomap` package is required for hierarchical Infomap. Install it in the active environment.'
        ) from exc

    infomap_instance = Infomap(
        seed=seed,
        silent=True,
        no_file_output=True,
        num_trials=trials,
        two_level=False,
    )

    for edge in graph.es:
        source_id = int(edge.source)
        target_id = int(edge.target)
        weight = float(edge['weight']) if 'weight' in edge.attributes() else 1.0
        infomap_instance.addLink(source_id, target_id, weight)

    infomap_instance.run()

    multilevel_modules = infomap_instance.get_multilevel_modules()
    if not multilevel_modules:
        return []

    max_depth = max(len(path) for path in multilevel_modules.values())
    level_summaries = []
    for level_index in range(max_depth):
        membership = []
        for vertex in graph.vs:
            path = multilevel_modules.get(vertex.index, ())
            if not path:
                membership.append(0)
                continue
            prefix = path[: level_index + 1] if level_index < len(path) else path
            membership.append(tuple(prefix))

        # Make tuple prefixes hashable community labels in a compact integer space.
        prefix_to_id = {}
        compact_membership = []
        for prefix in membership:
            if prefix not in prefix_to_id:
                prefix_to_id[prefix] = len(prefix_to_id)
            compact_membership.append(prefix_to_id[prefix])

        node_to_community = _assign_membership(graph, compact_membership)

        size_map = {}
        for community_id in compact_membership:
            size_map[community_id] = size_map.get(community_id, 0) + 1

        level_summaries.append({
            'level': level_index,
            'node_to_community': node_to_community,
            'community_count': len(size_map),
            'modularity': round(compute_modularity(graph, node_to_community), 6),
            'communities': sorted(size_map.values(), reverse=True),
            'hierarchy_label': f'level {level_index + 1} of {max_depth}',
            'hierarchy_depth': max_depth,
        })

    return level_summaries


def _run_hierarchical_infomap_clustering(graph, seed=42, trials=10):
    """Run the official Infomap hierarchy and return the deepest-level assignment."""
    if graph.vcount() == 0:
        return {}, 'none'

    level_summaries = _summarize_infomap_levels(graph, seed=seed, trials=trials)
    if not level_summaries:
        return _assign_membership(graph, _singleton_membership(graph)), 'hierarchical_infomap'

    return level_summaries[-1]['node_to_community'], 'hierarchical_infomap'


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
    if method == 'recursive_leiden':
        return _run_recursive_leiden_clustering(graph, resolution=resolution, seed=seed)
    if method == 'infomap':
        return _run_infomap_clustering(graph)
    if method == 'hierarchical_infomap':
        return _run_hierarchical_infomap_clustering(graph, seed=seed)

    raise ValueError(f"Unsupported community detection method '{method}'. Choose from: {', '.join(SUPPORTED_COMMUNITY_METHODS)}.")

def benchmark_community_detection(selected_links, used_node_ids, methods=None, resolution=1.0, edge_weight=None, seed=42):
    graph = build_weighted_graph(selected_links, used_node_ids, edge_weight)
    methods = methods or SUPPORTED_COMMUNITY_METHODS
    node_count = graph.vcount()
    edge_count = graph.ecount()

    benchmark_rows = []
    benchmark_assignments = {}
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
                    'conductance': round(compute_conductance(graph, level_summary['node_to_community']), 6),
                    'community_count': level_summary['community_count'],
                    'node_count': node_count,
                    'edge_count': edge_count,
                    # JSON-encode the community id/size list so it fits cleanly into CSV
                    'communities': json.dumps(level_summary['communities']),
                }
                benchmark_rows.append(row)
                benchmark_assignments[row['method']] = level_summary['node_to_community']
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
                    'conductance': round(compute_conductance(graph, level_summary['node_to_community']), 6),
                    'community_count': level_summary['community_count'],
                    'node_count': node_count,
                    'edge_count': edge_count,
                    'communities': json.dumps(level_summary['communities']),
                }
                benchmark_rows.append(row)
                benchmark_assignments[row['method']] = level_summary['node_to_community']
                print(
                    f"{row['method']}: runtime={row['runtime_seconds']:.6f}s modularity={row['modularity']:.6f}"
                )

            continue
        if method == 'hierarchical_infomap':
            node_to_community, algorithm_name = _run_hierarchical_infomap_clustering(graph, seed=seed)
            runtime = time.perf_counter() - start
            hierarchy_levels = _summarize_infomap_levels(graph, seed=seed)

            total_levels = len(hierarchy_levels)
            for level_summary in hierarchy_levels:
                level_number = level_summary['level'] + 1
                row = {
                    'method': f'hierarchical_infomap_level_{level_number}_of_{total_levels}',
                    'algorithm': algorithm_name,
                    'hierarchy_level': level_number,
                    'hierarchy_depth': total_levels,
                    'hierarchy_label': level_summary['hierarchy_label'],
                    'runtime_seconds': round(runtime, 6),
                    'modularity': level_summary['modularity'],
                    'conductance': round(compute_conductance(graph, level_summary['node_to_community']), 6),
                    'community_count': level_summary['community_count'],
                    'node_count': node_count,
                    'edge_count': edge_count,
                    'communities': json.dumps(level_summary['communities']),
                }
                benchmark_rows.append(row)
                benchmark_assignments[row['method']] = level_summary['node_to_community']
                print(
                    f"{row['method']}: runtime={row['runtime_seconds']:.6f}s modularity={row['modularity']:.6f}"
                )

            continue
        if method == 'recursive_leiden':
            node_to_community, algorithm_name = _run_recursive_leiden_clustering(
                graph,
                resolution=resolution,
                seed=seed,
            )
            runtime = time.perf_counter() - start
            hierarchy_levels = _summarize_recursive_leiden_levels(
                graph,
                resolution=resolution,
                seed=seed,
            )

            total_levels = len(hierarchy_levels)
            for level_summary in hierarchy_levels:
                level_number = level_summary['level'] + 1
                row = {
                    'method': f'recursive_leiden_level_{level_number}_of_{total_levels}',
                    'algorithm': algorithm_name,
                    'hierarchy_level': level_number,
                    'hierarchy_depth': total_levels,
                    'hierarchy_label': level_summary['hierarchy_label'],
                    'runtime_seconds': round(runtime, 6),
                    'modularity': level_summary['modularity'],
                    'conductance': round(compute_conductance(graph, level_summary['node_to_community']), 6),
                    'community_count': level_summary['community_count'],
                    'node_count': node_count,
                    'edge_count': edge_count,
                    'communities': json.dumps(level_summary['communities']),
                }
                benchmark_rows.append(row)
                benchmark_assignments[row['method']] = level_summary['node_to_community']
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
            'conductance': round(compute_conductance(graph, node_to_community), 6),
            'community_count': community_count,
            'node_count': node_count,
            'edge_count': edge_count,
            # JSON-encode the community id/size list so it fits cleanly into CSV
            'communities': json.dumps(communities_with_size),
        }
        benchmark_rows.append(row)
        benchmark_assignments[row['method']] = node_to_community
        print(
            f"{method}: runtime={row['runtime_seconds']:.6f}s modularity={row['modularity']:.6f}"
        )

    return pd.DataFrame(benchmark_rows), benchmark_assignments


def run_benchmark_from_whole_network(
    limit=BENCHMARK_DEFAULT_LIMIT,
    threshold=BENCHMARK_DEFAULT_THRESHOLD,
    per_node_limit=BENCHMARK_DEFAULT_PER_NODE_LIMIT,
    density=BENCHMARK_DEFAULT_DENSITY,
    edge_weight=BENCHMARK_DEFAULT_EDGE_WEIGHT,
    methods=None,
    resolution=1.0,
    seed=42,
    output_dir='./benchmarking/runs',
):
    candidate_links, selected_links, used_node_ids = get_whole_network(
        thresh=threshold,
        limit=limit,
        per_node_limit=per_node_limit,
        density=density,
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

    benchmark_df, benchmark_assignments = benchmark_community_detection(
        selected_links=selected_links,
        used_node_ids=used_node_ids,
        methods=methods or SUPPORTED_COMMUNITY_METHODS,
        resolution=resolution,
        edge_weight=edge_weight,
        seed=seed,
    )

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_output_dir = Path(output_dir)
    run_output_dir.mkdir(parents=True, exist_ok=True)
    file_name = f'benchmarking_cm_detection_{timestamp}.csv'
    output_path = run_output_dir / file_name
    comparison_file_name = f'benchmarking_cm_detection_pairwise_{timestamp}.csv'
    comparison_output_path = run_output_dir / comparison_file_name

    # Shared metadata is written once above the table to keep method rows compact.
    metadata_rows = [
        ('selected_node_count', selected_node_count),
        ('selected_edge_count', selected_edge_count),
        ('candidate_edge_count', candidate_edge_count),
        ('used_network_node_count', used_network_node_count),
        ('used_network_edge_count', used_network_edge_count),
        ('network_density', round(network_density, 6)),
        ('edge_weight', edge_weight),
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
        'conductance',
        'community_count',
        'communities',
    ]
    method_table_df = benchmark_df.loc[:, table_columns].copy()

    pairwise_table_df = _build_pairwise_comparison_table(
        graph=build_weighted_graph(selected_links, used_node_ids),
        benchmark_df=benchmark_df,
        benchmark_assignments=benchmark_assignments,
    )

    with open(output_path, 'w', encoding='utf-8') as output_file:
        output_file.write('metric,value\n')
        for key, value in metadata_rows:
            output_file.write(f'{key},{"" if value is None else value}\n')
        output_file.write('\n')
        method_table_df.to_csv(output_file, index=False)

    pairwise_table_df.to_csv(comparison_output_path, index=False)

    try:
        from benchmarking.benchmark_plotting import generate_plots

        benchmark_root_dir = Path(output_dir).resolve().parent
        plots_output_dir = benchmark_root_dir / 'plots' / timestamp

        heatmap_path, metrics_path, runtime_path = generate_plots(
            benchmark_csv=Path(output_path),
            pairwise_csv=Path(comparison_output_path),
            output_dir=plots_output_dir,
        )
        print(f"Pairwise heatmap written to: {heatmap_path}")
        print(f"Modularity/conductance plot written to: {metrics_path}")
        print(f"Runtime plot written to: {runtime_path}")
    except Exception as exc:
        print(f'Plot generation skipped: {exc}')

    print(f"Benchmark results written to: {output_path}")
    print(f"Pairwise comparison results written to: {comparison_output_path}")
    print('Shared benchmark metadata:')
    for key, value in metadata_rows:
        print(f'  {key}: {value}')
    return method_table_df, output_path, pairwise_table_df, comparison_output_path

#TODO: add @extend_schema_view
class GetCosmographView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        limit, threshold, per_node_limit, density = parse_query_params(request)
        edge_weight = parse_edge_weight_mode(request)
        
        # Handle error responses
        if isinstance(limit, HttpResponseBadRequest):
            return limit
        if isinstance(threshold, HttpResponseBadRequest):
            return threshold
        if isinstance(per_node_limit, HttpResponseBadRequest):
            return per_node_limit
        if isinstance(density, HttpResponseBadRequest):
            return density
        if isinstance(edge_weight, HttpResponseBadRequest):
            return edge_weight
        
        logger.info(
            'Start Cosmograph request with limit=%s threshold=%s per_node_limit=%s density=%s weight=%s',
            limit,
            threshold,
            per_node_limit,
            density,
            edge_weight,
            density
        )

        # Extract candidate_links, selected_links, and nodes from the database
        candidate_links, selected_links, used_node_ids = get_whole_network(
            thresh=threshold,
            limit=limit,
            per_node_limit=per_node_limit,
            density=density,
            edge_weight=edge_weight,
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
                    'edge_weight': edge_weight,
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
        limit, threshold, per_node_limit, density = parse_query_params(request)
        edge_weight = parse_edge_weight_mode(request)

        if isinstance(limit, HttpResponseBadRequest):
            return limit
        if isinstance(threshold, HttpResponseBadRequest):
            return threshold
        if isinstance(per_node_limit, HttpResponseBadRequest):
            return per_node_limit
        if isinstance(density, HttpResponseBadRequest):
            return density
        if isinstance(edge_weight, HttpResponseBadRequest):
            return edge_weight

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
            'Start metagraph request with limit=%s threshold=%s per_node_limit=%s density=%s weight=%s seed=%s algorithm=%s',
            limit,
            threshold,
            per_node_limit,
            density,
            edge_weight,
            seed,
            method,
        )

        candidate_links, selected_links, used_node_ids = get_whole_network(
            thresh=threshold,
            limit=limit,
            per_node_limit=per_node_limit,
            density=density,
            edge_weight=edge_weight,
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
                    'edge_weight': edge_weight,
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
        edge_weight=BENCHMARK_DEFAULT_EDGE_WEIGHT,
        methods=SUPPORTED_COMMUNITY_METHODS,
        resolution=1.0,
        seed=42,
        output_dir='./benchmarking/runs',
    )