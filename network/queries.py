import time
from math import ceil
from collections import defaultdict

from django.db.models import Q, F
from django.apps import apps
from network.models import create_dynamic_model, EdgesContextBase
import logging

logger = logging.getLogger('network')


def apply_soft_limit(sorted_edges, limit):
    """
    Retrieve the top limit edges from a list of edges sorted by the 'final_p_value' column. If any edges are excluded
    due to the limit but share the same 'final_p_value' as the last included edge, they are also retained and returned.
    """
    top_edges = sorted_edges[:limit]

    # Extract the last final_p_value from the top edges
    last_edge_final_p_value = top_edges[-1]['final_p_value'] if top_edges else None

    # Get additional edges with the same final_p_value
    additional_overall_edges = [edge for edge in sorted_edges if edge['final_p_value'] == last_edge_final_p_value]

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
        'final_p_value': row.get('p_value'),
        'final_e_value': row.get('effect_size'),
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
        'node_id', 'display_name', 'description', 'node_group', 'xrefs'
    )
    return [
        {
            'id': row['node_id'],
            'display_name': row['display_name'],
            'description': row['description'],
            'source_table': row['node_group'],
            'xrefs': row['xrefs'],
        }
        for row in rows
    ]


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

    context_model = apps.get_model('network', 'Context')
    try:
        context = context_model.objects.get(context_id=context_id)
    except context_model.DoesNotExist:
        raise ValueError(f"Context {context_id} not found.")
    test_type = context.params.get('testType')
    if test_type not in ('parametric', 'nonparametric'):
        raise ValueError(f"Context {context_id} has no valid testType recorded (got {test_type!r}).")

    table_name = f'edges_{test_type}_{context_id}'
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
        key=lambda edge: float(edge['final_p_value']) if edge['final_p_value'] is not None else 1.0
    )

    message = ""
    if limit is not None:
        candidate_links = apply_soft_limit(candidate_links, limit)
        if per_type and len(candidate_links) > limit:
            message = (f"More than {limit} edges have been returned because some edges share the "
                       f"same significance level")

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
        key=lambda edge: float(edge['final_p_value']) if edge['final_p_value'] is not None else 1.0
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


def get_whole_network_new(stat_type, thresh=None, limit=None):
    """
    Extract the complete network from the flat table structure.

    Args:
        stat_type: Which edge table to query — 'parametric' or 'nonparametric'.
        thresh: Significance threshold for filtering edges (optional)
        limit: Overall limit on the number of edges to return (optional)


    Returns:
        tuple: (candidate_links, nodes)
            - candidate_links: All edges matching the threshold and/or limit
            - nodes: Set of all node IDs from the selected edges
    """
    from math import ceil
    from collections import defaultdict

    if stat_type == 'parametric':
        edge_model_name = 'EdgesParametric'
        edge_type_label = 'edges_parametric'
    elif stat_type == 'nonparametric':
        edge_model_name = 'EdgesNonparametric'
        edge_type_label = 'edges_nonparametric'
    else:
        raise ValueError(f"stat_type must be 'parametric' or 'nonparametric', got '{stat_type}'")

    start = time.perf_counter()

    node_model = apps.get_model('network', 'Nodes')
    edge_model = apps.get_model('network', edge_model_name)

    queryset = edge_model.objects.all()
    if thresh is not None:
        queryset = queryset.filter(p_value__lte=thresh)

    queryset = queryset.order_by('p_value').values(
        'id', 'node_id_1', 'node_id_2', 'p_value', 'effect_size', 'test_type'
    )
    if limit is not None:
        queryset = queryset[:limit]

    candidate_links = []
    for row in queryset:
        shaped = _shape_edge_row(row, edge_type_label)
        if shaped is not None:
            candidate_links.append(shaped)

    candidate_links.sort(
        key=lambda edge: float(edge['final_p_value']) if edge['final_p_value'] is not None else 1.0,
    )

    # Extract nodes from selected links and filter to only those present in edges
    nodes = set()
    for edge in candidate_links:
        nodes.add(edge['source'])
        nodes.add(edge['target'])

    elapsed = time.perf_counter() - start
    logger.info(
        f"get_whole_network_new ({stat_type}) retrieved {len(candidate_links)} candidate edges "
        f"and {len(nodes)} nodes in {elapsed:.3f}s"
    )

    return candidate_links, nodes


def get_whole_network(test_type, thresh=None, limit=None, per_node_limit=None, density=None):
    """
    Extract the complete network for a single stat type (parametric or nonparametric)
    from the flat table structure, built on top of get_whole_network_new().

    Args:
        test_type: Which edge table to query - 'parametric' or 'nonparametric'.
        thresh: Significance threshold for filtering edges (optional)
        limit: Overall limit on the number of edges to return (optional)
        per_node_limit: Limit the number of edges per node (optional)
        density: Desired network density (optional, overrides thresh and limit)

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

    candidate_links, _ = get_whole_network_new(stat_type=test_type, thresh=thresh, limit=limit)

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
            key=lambda edge: float(edge['final_p_value']) if edge['final_p_value'] is not None else 1.0,
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
def typeahead_query(query, groups=None, limit=20):
    """
    Search Nodes by display_name/description/node_id/xrefs, optionally restricted to
    a set of node_group values. Replaces the old ViewDescriptionFTS-based lookup,
    which only covers the old per-node-type tables and has no knowledge of `nodes`.
    Returns values aliased to the old view's field names (id/source_table) so
    TypeaheadView's response shape doesn't change.
    """
    model = apps.get_model('network', 'Nodes')
    filters = (Q(description__icontains=query) |
              Q(display_name__icontains=query) |
              Q(node_id__icontains=query) |
              Q(xrefs__icontains=query))
    if groups:
        filters &= Q(node_group__in=groups)
    return model.objects.filter(filters)[:limit].values(
        'description', 'display_name', 'xrefs', id=F('node_id'), source_table=F('node_group')
    )
