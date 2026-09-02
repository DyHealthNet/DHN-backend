import time
from math import ceil
from collections import defaultdict

import numpy as np
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import Q, F
from django.apps import apps
from network.models import create_dynamic_model, EdgesContextBase
import logging

logger = logging.getLogger('network')


def apply_soft_limit(sorted_edges, limit):
    """
    Retrieve the top limit edges from a list of edges sorted by the 'p_value' column. If any edges are excluded
    due to the limit but share the same 'p_value' as the last included edge, they are also retained and returned.
    """
    top_edges = sorted_edges[:limit]

    # Extract the last p_value from the top edges
    last_edge_p_value = top_edges[-1]['p_value'] if top_edges else None

    # Get additional edges with the same p_value
    additional_overall_edges = [edge for edge in sorted_edges if edge['p_value'] == last_edge_p_value]

    # Filter additional edges that already exist in top_edges
    existing_ids = {edge['id'] for edge in top_edges}
    filtered_additional_edges = [
        edge for edge in additional_overall_edges if edge['id'] not in existing_ids
    ]

    # Combine top edges with additional edges
    top_edges = top_edges + filtered_additional_edges
    return top_edges

def _shape_edge_row(row, edge_type_label):
    """Build the common candidate-edge dict shape from one EdgesParametric/EdgesNonparametric row."""
    source = row.get('node_id_1')
    target = row.get('node_id_2')
    if not source or not target:
        return None
    return {
        'id': f"{edge_type_label}:{row['id']}",
        'source': source,
        'target': target,
        'edge_type': edge_type_label,
        'p_value': row.get('p_value'),
        'effect_size': row.get('effect_size'),
        'test_type': row.get('test_type'),
    }


# (stat_type, model name, edge_type label) for the flat schema's two edge tables.
STAT_TYPE_EDGE_MODELS = [
    ('parametric', 'EdgesParametric', 'edges_parametric'),
    ('nonparametric', 'EdgesNonparametric', 'edges_nonparametric'),
]


def _query_new_schema_nodes(node_ids):
    """
    Fetch node details for the new flat schema directly from the Nodes model.
    query_nodes()/ViewDescriptionFTS only cover the old per-node-type tables
    (cohort_protein/cohort_metabolite/cohort_phenotype/cohort_variant) and have no
    knowledge of the new `nodes` table. Shaped to match query_nodes()'s old output
    (id/display_name/description/source_table/xrefs) so callers don't need to care
    which schema a node came from.
    """
    node_model = apps.get_model('network', 'Nodes')
    rows = node_model.objects.filter(node_id__in=node_ids).values(
        'node_id', 'display_name', 'description', 'node_group', 'data_type', 'xrefs'
    )
    return [
        {
            'id': row['node_id'],
            'display_name': row['display_name'],
            'description': row['description'],
            'source_table': row['node_group'],
            'data_type': row['data_type'],
            'xrefs': row['xrefs'],
        }
        for row in rows
    ]


def query_node_annotation_details(node_ids):
    """
    Fetch the raw group/subgroup/description/xrefs fields for a list of node IDs, for use
    as LLM prompt context (e.g. the Gemini community-labeling feature). Unlike
    _query_new_schema_nodes, this does not rename node_group to source_table -- callers
    need the actual group/subgroup values.
    """
    node_model = apps.get_model('network', 'Nodes')
    return list(
        node_model.objects.filter(node_id__in=node_ids).values(
            'node_id', 'display_name', 'node_group', 'node_subgroup', 'description', 'xrefs'
        )
    )


def resolve_context_edge_table(context_id):
    """
    Validate context_id and return (table_name, test_type) for its per-context edge
    table (edges_{test_type}_{context_id}, created by insert_context). test_type is
    read from Context.params['testType'] — a context always has exactly one.
    Raises ValueError if the context doesn't exist or has no recorded testType.
    """
    context_model = apps.get_model('network', 'Context')
    try:
        context = context_model.objects.get(context_id=context_id)
    except context_model.DoesNotExist:
        raise ValueError(f"Context {context_id} not found.")
    test_type = context.params.get('testType')
    if test_type not in ('parametric', 'nonparametric'):
        raise ValueError(f"Context {context_id} has no valid testType recorded (got {test_type!r}).")
    return f'edges_{test_type}_{context_id}', test_type


def get_context_node_ids(context_id):
    """
    Full set of node_ids that belong to a context — every variable that was part
    of the context's pairwise test computation, regardless of any
    density/threshold/limit filtering a particular whole-network request applies
    to its edges. Mirrors get_whole_network()'s "show every node regardless of
    edge filtering" behavior for the global case (there it's every row of the
    Nodes table; here it's scoped down to the context's own variable set instead
    of the entire database).

    Result only changes if the context's edge table changes, which never happens
    after creation -- cached like participants_context_/variables_context_, and
    invalidated the same way by delete_context_tables() (network/contexts/contexts.py).
    Called on every keystroke of a context-scoped typeahead search (network/views/
    network.py's TypeaheadView), so this is the hottest of the three.
    """
    cache_key = f'context_node_ids_{context_id}'
    if not settings.NO_CACHE and cache_key in cache:
        return cache.get(cache_key)

    table_name, _ = resolve_context_edge_table(context_id)
    sql = (
        f"SELECT node_id_1 AS node_id FROM {table_name} "
        f"UNION SELECT node_id_2 AS node_id FROM {table_name}"
    )
    with connection.cursor() as cursor:
        cursor.execute(sql)
        node_ids = {row[0] for row in cursor.fetchall() if row[0]}

    if not settings.NO_CACHE:
        cache.set(cache_key, node_ids, timeout=3600 * 24 * 30)
    return node_ids


def _get_flat_edge_models(context_id=None, test_type=None):
    """
    Return (edge_type_label, edge_model) pairs for flat-schema edge queries.
    For the global schema: both EdgesParametric and EdgesNonparametric, unless
    test_type ('parametric' or 'nonparametric') is given — then only that table.
    For a context: the single table created by insert_context (parametric OR nonparametric),
    looked up from Context.params['testType'].
    """
    if context_id is None:
        all_models = [
            (stat, label, apps.get_model('network', name))
            for stat, name, label in STAT_TYPE_EDGE_MODELS
        ]
        if test_type:
            return [(label, model) for stat, label, model in all_models if stat == test_type]
        return [(label, model) for stat, label, model in all_models]

    table_name, _ = resolve_context_edge_table(context_id)
    return [(table_name, create_dynamic_model(EdgesContextBase, table_name))]


def get_node_network_new(query_id, thresh=None, limit=None, per_type=None, context_id=None, test_type=None):
    """
    Extract the neighborhood of a single node from the flat table structure.
    When context_id is given, queries the single per-context edge table instead of
    the global EdgesParametric/EdgesNonparametric tables.
    Mirrors network_query()'s old tuple shape so GetNetworkView's response-shaping
    code needs no changes.

    :return: tuple (edges, nodes, mapped_externals, message) - edges keyed by
             edge_type_label.
    """
    candidate_links = []
    for edge_type_label, edge_model in _get_flat_edge_models(context_id, test_type=test_type):
        queryset = edge_model.objects.filter(Q(node_id_1=query_id) | Q(node_id_2=query_id))
        if thresh is not None:
            queryset = queryset.filter(p_value__lte=thresh)
        queryset = queryset.values('id', 'node_id_1', 'node_id_2', 'p_value', 'effect_size', 'test_type')

        for row in queryset:
            shaped = _shape_edge_row(row, edge_type_label)
            if shaped is not None:
                candidate_links.append(shaped)

    candidate_links.sort(
        key=lambda edge: float(edge['p_value']) if edge['p_value'] is not None else 1.0
    )

    message = ""
    if limit is not None:
        if per_type:
            # Apply the limit separately within each neighbor node's node_group, so that
            # nodes from less-significant groups aren't crowded out by a single group's
            # strongest hits (see get_node_network_new docstring).
            neighbor_ids = {
                edge['target'] if edge['source'] == query_id else edge['source']
                for edge in candidate_links
            }
            node_model = apps.get_model('network', 'Nodes')
            group_by_id = dict(
                node_model.objects.filter(node_id__in=neighbor_ids).values_list('node_id', 'node_group')
            )
            grouped_links = defaultdict(list)
            for edge in candidate_links:
                neighbor_id = edge['target'] if edge['source'] == query_id else edge['source']
                grouped_links[group_by_id.get(neighbor_id)].append(edge)

            candidate_links = []
            truncated = False
            for group_edges in grouped_links.values():
                limited_group = apply_soft_limit(group_edges, limit)
                if len(limited_group) > limit:
                    truncated = True
                candidate_links.extend(limited_group)
            if truncated:
                message = (f"More than {limit} edges have been returned for some node groups because "
                           f"some edges share the same significance level")
        else:
            candidate_links = apply_soft_limit(candidate_links, limit)

    node_ids = {query_id}
    for edge in candidate_links:
        node_ids.add(edge['source'])
        node_ids.add(edge['target'])

    nodes = _query_new_schema_nodes(node_ids)

    edges = {}
    for edge in candidate_links:
        edges.setdefault(edge['edge_type'], []).append(edge)

    if not edges and nodes:
        message = "No edges are found by the request"

    return edges, nodes, [], message


def get_group_network_new(query_ids, thresh=None, limit=None, context_id=None, test_type=None):
    """
    Extract the subgraph among a group of nodes from the flat table structure.
    When context_id is given, queries the single per-context edge table instead of
    the global EdgesParametric/EdgesNonparametric tables.

    :return: tuple (edges, nodes, mapped_externals) - edges keyed by edge_type_label.
    """
    candidate_links = []
    for edge_type_label, edge_model in _get_flat_edge_models(context_id, test_type=test_type):
        queryset = edge_model.objects.filter(node_id_1__in=query_ids, node_id_2__in=query_ids)
        if thresh is not None:
            queryset = queryset.filter(p_value__lte=thresh)
        queryset = queryset.values('id', 'node_id_1', 'node_id_2', 'p_value', 'effect_size', 'test_type')

        for row in queryset:
            shaped = _shape_edge_row(row, edge_type_label)
            if shaped is not None:
                candidate_links.append(shaped)

    candidate_links.sort(
        key=lambda edge: float(edge['p_value']) if edge['p_value'] is not None else 1.0
    )

    if limit is not None:
        candidate_links = apply_soft_limit(candidate_links, limit)

    node_ids = set(query_ids)
    for edge in candidate_links:
        node_ids.add(edge['source'])
        node_ids.add(edge['target'])

    nodes = _query_new_schema_nodes(node_ids)

    edges = {}
    for edge in candidate_links:
        edges.setdefault(edge['edge_type'], []).append(edge)

    return edges, nodes, []


def get_whole_network_new(stat_type=None, thresh=None, limit=None, sort=True, context_id=None):
    """
    Extract the complete network from the flat table structure.

    Args:
        stat_type: Which edge table to query — 'parametric' or 'nonparametric'.
            Ignored when context_id is given.
        thresh: Significance threshold for filtering edges (optional)
        limit: Overall limit on the number of edges to return (optional)
        sort: Whether candidate_links must come back ordered by ascending p_value.
            When limit is given, the SQL query already returns rows in that order
            (ORDER BY p_value LIMIT), so this only matters for the unbounded case.
            Pass False there when nothing downstream depends on order (e.g. no
            per_node_limit filtering afterward) - skips the Python-side sort and
            builds the output in a single pass over DB fetch order instead of two.
        context_id: When given, reads the single precomputed per-context edge table
            (edges_{test_type}_{context_id}) instead of the global
            edges_parametric/edges_nonparametric tables — test_type is then taken
            from the context itself (see resolve_context_edge_table), not from the
            stat_type argument.

    Returns:
        tuple: (candidate_links, nodes)
            - candidate_links: All edges matching the threshold and/or limit,
              ordered by ascending p_value if sort=True (or if limit was given -
              SQL sorts that case regardless of the sort argument); DB fetch
              order otherwise.
            - nodes: Set of all node IDs from the selected edges
    """
    from math import ceil
    from collections import defaultdict

    if context_id is not None:
        edge_type_label, stat_type = resolve_context_edge_table(context_id)
    elif stat_type == 'parametric':
        edge_type_label = 'edges_parametric'
    elif stat_type == 'nonparametric':
        edge_type_label = 'edges_nonparametric'
    else:
        raise ValueError(f"stat_type must be 'parametric' or 'nonparametric', got '{stat_type}'")

    start = time.perf_counter()

    # Raw SQL + fetchall() instead of the ORM: profiling showed the ORM's per-row
    # queryset iteration (values_list().iterator()) was ~58% of total time for the
    # unbounded ~35M-row case. connection.cursor()/fetchall() is the same pattern
    # already used for bulk reads elsewhere (see contexts.py::load_context_scores);
    # edge_type_label is either one of the two literal global table names, or a
    # per-context table name built from a context_id already validated to exist by
    # resolve_context_edge_table() above — never raw user input either way.
    sql = f"SELECT id, node_id_1, node_id_2, p_value, effect_size, test_type FROM {edge_type_label}"
    params = []
    if thresh is not None:
        sql += " WHERE p_value <= %s"
        params.append(thresh)
    # Only order in SQL when there's a limit to pair it with - ORDER BY + LIMIT lets
    # Postgres use the p_value index for a cheap top-N scan. Without a limit, results
    # get re-sorted in Python below anyway, so an unbounded SQL-side ORDER BY would
    # just force a full sort (or a much worse full-table index scan) for nothing.
    if limit is not None:
        sql += " ORDER BY p_value LIMIT %s"
        params.append(limit)

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    t_extract = time.perf_counter() - start

    t0 = time.perf_counter()
    if sort:
        ids = []
        sources = []
        targets = []
        p_values = []
        effect_sizes = []
        test_types = []
        for edge_id, source, target, p_value, effect_size, test_type in rows:
            if not source or not target:
                continue
            ids.append(edge_id)
            sources.append(source)
            targets.append(target)
            p_values.append(p_value)
            effect_sizes.append(effect_size)
            test_types.append(test_type)

        # Sort by index instead of sorting a list of dicts: a numpy argsort over a plain
        # float array is one vectorized C-level pass, versus Python calling a key lambda
        # on every comparison of a Timsort over ~35M dicts (~n*log(n) Python calls).
        # None sorts last, matching the previous per-row `float(...) if ... else 1.0` key.
        sort_keys = [1.0 if p is None else p for p in p_values]
        order = np.argsort(np.asarray(sort_keys, dtype=float), kind='stable')

        candidate_links = [
            {
                'id': f"{edge_type_label}:{ids[i]}",
                'source': sources[i],
                'target': targets[i],
                'edge_type': edge_type_label,
                'p_value': p_values[i],
                'effect_size': effect_sizes[i],
                'test_type': test_types[i],
            }
            for i in order
        ]
        nodes = set(sources) | set(targets)
    else:
        # No downstream step needs sorted order (e.g. unbounded whole-network fetch with
        # no per_node_limit filtering after this) - build the output in a single pass over
        # DB fetch order instead of unpacking into parallel lists and revisiting them in
        # sorted order. Same edges/nodes as the sort=True path, just not p_value-ordered.
        candidate_links = []
        nodes = set()
        for edge_id, source, target, p_value, effect_size, test_type in rows:
            if not source or not target:
                continue
            candidate_links.append({
                'id': f"{edge_type_label}:{edge_id}",
                'source': source,
                'target': target,
                'edge_type': edge_type_label,
                'p_value': p_value,
                'effect_size': effect_size,
                'test_type': test_type,
            })
            nodes.add(source)
            nodes.add(target)
    t_format = time.perf_counter() - t0

    elapsed = time.perf_counter() - start
    logger.info(
        f"get_whole_network_new ({stat_type}) retrieved {len(candidate_links)} candidate edges "
        f"and {len(nodes)} nodes in {elapsed:.3f}s "
        f"[extract_from_db={t_extract:.3f}s format_output={t_format:.3f}s]"
    )

    return candidate_links, nodes


def get_whole_network(test_type=None, thresh=None, limit=None, per_node_limit=None, density=None, context_id=None):
    """
    Extract the complete network for a single stat type (parametric or nonparametric)
    from the flat table structure, built on top of get_whole_network_new().

    Args:
        test_type: Which edge table to query - 'parametric' or 'nonparametric'.
            Ignored when context_id is given.
        thresh: Significance threshold for filtering edges (optional)
        limit: Overall limit on the number of edges to return (optional)
        per_node_limit: Limit the number of edges per node (optional)
        density: Desired network density (optional, overrides thresh and limit)
        context_id: When given, restricts the whole network to a single precomputed
            per-context edge table instead of the global tables (see
            get_whole_network_new/resolve_context_edge_table). The node universe
            (all patients' variables) is unaffected by context — only which
            patient subset the edge statistics were computed over.

    Returns:
        tuple: (candidate_links, selected_links, nodes)
            - candidate_links: All edges matching the threshold or density
            - selected_links: Filtered edges (after applying limit and per_node_limit)
            - nodes: Set of all node IDs from the selected edges
    """
    if density is not None:
        node_count = apps.get_model('network', 'Nodes').objects.count()
        possible_edge_count = node_count * (node_count - 1) / 2 if node_count > 1 else 0
        if not possible_edge_count:
            logger.debug("Not enough nodes to form edges. Returning empty network.")
            return [], [], set()
        limit = ceil(density * possible_edge_count)
        thresh = None
        per_node_limit = None

    # per_node_limit's per-node top-K selection below depends on candidate_links being
    # ordered by ascending p_value. When limit is given, SQL already sorts (ORDER BY
    # p_value LIMIT) regardless of the sort argument, so this only needs to force a
    # Python-side sort for the unbounded (limit=None) + per_node_limit combination.
    needs_sort = limit is None and per_node_limit is not None
    candidate_links, _ = get_whole_network_new(
        stat_type=test_type, thresh=thresh, limit=limit, sort=needs_sort, context_id=context_id,
    )

    # Apply per_node_limit filtering if specified
    if per_node_limit is not None:
        edge_lookup = {edge['id']: edge for edge in candidate_links}
        node_incident_edges = defaultdict(list)

        for edge in candidate_links:
            node_incident_edges[edge['source']].append(edge)
            node_incident_edges[edge['target']].append(edge)

        selected_edge_ids = set()
        for incident_edges in node_incident_edges.values():
            for edge in incident_edges[:per_node_limit]:
                selected_edge_ids.add(edge['id'])

        selected_links = [edge_lookup[edge_id] for edge_id in selected_edge_ids]
        selected_links.sort(
            key=lambda edge: float(edge['p_value']) if edge['p_value'] is not None else 1.0,
        )
    else:
        selected_links = candidate_links

    if limit is not None and len(selected_links) > limit:
        selected_links = selected_links[:limit]

    # Extract nodes from selected links and filter to only those present in edges
    nodes = set()
    for edge in selected_links:
        nodes.add(edge['source'])
        nodes.add(edge['target'])
    
    return candidate_links, selected_links, nodes

def external_query(query_id, cohort_node=True):
    id_mapping = {}
    external_ids = set()
    ref_ids = set()
    ref_model = apps.get_model('network', 'ViewReferencesEdges')

    # If the query node is a cohort node, we need to first retrieve all references to external nodes
    if cohort_node is True:
        refs = ref_model.objects.filter(cohort_id=query_id).values()
        ref_ids.update(*zip(*refs.values_list('reference_id')))
        id_mapping = {ref['reference_id']: [ref['cohort_id']] for ref in refs}

    else:
        ref_ids.update(query_id)

    # Retrieve all edges that contain a referenced external node
    external_edges_model = apps.get_model('network', 'ViewAssociationsEdges')
    external_edges = external_edges_model.objects.filter(Q(source_id__in=ref_ids) | Q(target_id__in=ref_ids)).values()
    # Collect all source and target ids of the external_edges
    external_ids.update(*zip(*external_edges.values_list('source_id')))
    external_ids.update(*zip(*external_edges.values_list('target_id')))

    # Remove ref_ids that are associated with the query node
    # This avoids that extra cohort nodes are returned mapping to the same external references
    for entry in ref_ids:
        if entry in external_ids:
            external_ids.remove(entry)

    # Map externals back to cohort nodes if available, otherwise retrieve external node
    cohort_nodes_model = apps.get_model('network', 'ViewDescriptionFTS')
    external_nodes_model = apps.get_model('network', 'ViewExternalNodes')
    cohort_nodes = []
    external_nodes = []

    for ext_id in external_ids:
        ref_ids = set()
        refs = ref_model.objects.filter(reference_id=ext_id).values()
        ref_ids.update(*zip(*refs.values_list('cohort_id')))

        if not ref_ids:
            # If no cohort node can be mapped, it must be a purely external node
            # Get the node type of the external node
            node_type = external_nodes_model.objects.filter(Q(node_id=ext_id)).values()[0]['source_table']
            type_model = apps.get_model('network', node_type.capitalize())
            # Retrieve the external node using the primary key
            unknown_nodes = type_model.objects.filter(Q(pk=ext_id)).values()
            for node in unknown_nodes:
                node["source_table"] = "external_" + node_type
            external_nodes.append(unknown_nodes)
            id_mapping.update({ext_id: [ext_id]})  # map to itself if no cohort node is available
        else:
            mapped_nodes = cohort_nodes_model.objects.filter(Q(id__in=ref_ids)).values()
            cohort_nodes.append(mapped_nodes)
            # Mapping to cohort nodes is not unambiguous => mapped_nodes might have more than one entry
            cohort_ids = [node_id[0] for node_id in mapped_nodes.values_list('id')]
            id_mapping.update({ext_id: cohort_ids})  # map the external id to a list of cohort ids

    # Map the external edges
    mapped_externals = [
        {
            'source_id': external['source_id'],
            'target_id': external['target_id'],
            'mapping_source_id': id_mapping.get(external['source_id']),
            'mapping_target_id': id_mapping.get(external['target_id'])
        }
        for external in external_edges
    ]

    return mapped_externals, cohort_nodes, external_nodes

# Search for 'query' in all fields of the flat nodes table.
def typeahead_query(query, groups=None, node_ids=None, limit=20):
    """
    Search Nodes by display_name/description/node_id/xrefs, optionally restricted to
    a set of node_group values and/or an explicit set of node_ids (e.g. a context's
    ground-truth node set from get_context_node_ids()). Replaces the old
    ViewDescriptionFTS-based lookup, which only covers the old per-node-type tables and
    has no knowledge of `nodes`. Returns values aliased to the old view's field names
    (id/source_table) so TypeaheadView's response shape doesn't change.
    """
    model = apps.get_model('network', 'Nodes')
    filters = (Q(description__icontains=query) |
              Q(display_name__icontains=query) |
              Q(node_id__icontains=query) |
              Q(xrefs__icontains=query))
    if groups:
        filters &= Q(node_group__in=groups)
    if node_ids is not None:
        filters &= Q(node_id__in=node_ids)
    return model.objects.filter(filters)[:limit].values(
        'description', 'display_name', 'xrefs', 'data_type', id=F('node_id'), source_table=F('node_group')
    )
