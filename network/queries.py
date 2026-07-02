import re
import time

from django.db.models import Q, Value
from django.apps import apps
from django.db.models.functions import Coalesce
from django.db.models import F
from django.forms.models import model_to_dict
from network.models import create_dynamic_model, EdgesContextBase
from network.models import (
    EdgesProteinProtein, EdgesProteinMetabolite, EdgesProteinPhenotype,
    EdgesMetaboliteMetabolite, EdgesMetabolitePhenotype, EdgesPhenotypePhenotype,
    EdgesVariantMetabolite, EdgesVariantPhenotype, EdgesVariantProtein
)
from pprint import pformat
import logging

logger = logging.getLogger('network')


BASE_MODELS = {
    'EdgesProteinProtein': EdgesProteinProtein,
    'EdgesProteinMetabolite': EdgesProteinMetabolite,
    'EdgesProteinPhenotype': EdgesProteinPhenotype,
    'EdgesMetaboliteMetabolite': EdgesMetaboliteMetabolite,
    'EdgesMetabolitePhenotype': EdgesMetabolitePhenotype,
    'EdgesPhenotypePhenotype': EdgesPhenotypePhenotype,
    'EdgesVariantMetabolite': EdgesVariantMetabolite,
    'EdgesVariantPhenotype': EdgesVariantPhenotype,
    'EdgesVariantProtein': EdgesVariantProtein,
}

# A registry to track dynamic model names
# #TODO check if this can work somehow
#dynamic_model_registry = {}

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

def get_dynamic_model(table, context_id=None):
    """
    Retrieve the dynamic model for a given table and context.
    """
    table_base = re.sub(r'(?<!^)(?=[A-Z])', '_', table).lower()
    model_name = f"{table_base}_{context_id}" if context_id else table_base
    # logger.debug(f"dynamic_model_registry '{dynamic_model_registry}'")
    #
    # # Check if the model is already registered in the custom registry
    # if model_name in dynamic_model_registry:
    #     logger.debug(f"Model '{model_name}' is already registered.")
    #     return dynamic_model_registry[model_name]  # Return the already registered model

    # Create and register the dynamic model
    return create_dynamic_model(BASE_MODELS[table], model_name) # dynamic_model_registry

def get_valid_columns(model, test_columns):
    """
    Get valid test columns from the model's fields, prioritizing certain prefixes.
    """
    selected_options = selected_options or {}
    defaults = default_selected_options or DEFAULT_SELECTED_OPTIONS

    merged = {**defaults, **selected_options}
    mult_test = merged['multTest']['value']

    return {
        f'{merged["contCont"]["value"]}_p_{mult_test}',
        f'{merged["catContB"]["value"]}_p_{mult_test}',
        f'{merged["catContM"]["value"]}_p_{mult_test}',
        f'{merged["catCat"]["value"]}_p_{mult_test}',
    }

import numpy as np

def rescale_edges(edges, normalization="minmax"):
    edges = [e.copy() for e in edges]

    # group by test_type (you need to have it in edges!)
    from collections import defaultdict
    groups = defaultdict(list)

    for e in edges:
        groups[e["test_type"]].append(e)
    for test, group in groups.items():
        values = np.asarray([e["final_e_value"] for e in group], dtype=float)

        if normalization == "zscore":
            mean = np.nanmean(values)
            std = np.nanstd(values)

            if std == 0:
                for e in group:
                    e["final_e_value_rescaled"] = 0.0
            else:
                for i, e in enumerate(group):
                    if e["final_e_value"] is None:
                        e["final_e_value_rescaled"] = None
                        print(f"Warning: final_e_value is None for edge {e['id']} in test type {e['test_type']} and with pvalue {e['final_p_value']}.")
                    else:
                        e["final_e_value_rescaled"] = (e["final_e_value"] - mean) / std
        elif normalization == "minmax":
            min_val = np.nanmin(values)
            max_val = np.nanmax(values)

            if max_val == min_val:
                for e in group:
                    e["final_e_value_rescaled"] = 0.0
            else:
                for i, e in enumerate(group):
                    if e["final_e_value"] is None:
                        e["final_e_value_rescaled"] = None
                        print(f"Warning: final_e_value is None for edge {e['id']} in test type {e['test_type']} and with pvalue {e['final_p_value']}.")
                    else:
                        e["final_e_value_rescaled"] = (e["final_e_value"] - min_val) / (max_val - min_val)

    return edges

def query_nodes(node_ids):
    """
    Retrieve nodes corresponding to the given IDs.
    """
    node_model = apps.get_model('network', 'ViewDescriptionFTS')
    return list(node_model.objects.filter(id__in=node_ids).values())

def query_refs(node_ids):
    """
    Query references and external edges for given node IDs.
    """
    ref_model = apps.get_model('network', 'ViewReferencesEdges')
    external_edges_model = apps.get_model('network', 'ViewAssociationsEdges')

    refs = ref_model.objects.filter(cohort_id__in=node_ids).values()
    external_ids = {ref['reference_id'] for ref in refs}
    externals = external_edges_model.objects.filter(
        Q(source_id__in=external_ids) & Q(target_id__in=external_ids)
    ).values()

    id_mapping = {ref['reference_id']: ref['cohort_id'] for ref in refs}
    mapped_externals = [
        {
            'source_id': ext['source_id'],
            'target_id': ext['target_id'],
            'source_cohort_id': id_mapping.get(ext['source_id']),
            'target_cohort_id': id_mapping.get(ext['target_id']),
        }
        for ext in externals
    ]
    return mapped_externals

def network_query(query_id, node_type, limit, per_type, thresh, test_columns, context_id=None):
    edges = {}
    node_ids = {query_id}
    all_edges = []
    message = ""
    #if limit is None:
     #   logger.info(f"limit is None")
      #  return {}, {}, {}, ""
    logger.debug(f"node_type {node_type}")
    logger.debug(f"test columns {test_columns}")
    logger.debug(f"significance thresh {thresh}")
    logger.debug(f"limit {limit}")
    logger.debug(f"per_type {per_type}")

    # Query edges
    for table in BASE_MODELS.keys():
        if table is None:
            continue
        # Distinguish between 'within-type' tables and 'between-type' tables
        count = table.lower().count(node_type.lower())
        if count == 0:
            logger.debug(f"Table {table} irrelevant for this node")
            continue

        logger.debug(f"Table {table}")

        table_model = get_dynamic_model(table, context_id=context_id)
        if not table_model.objects.exists():
            continue

        # Check which columns are available for the node_type and multiple testing correction
        valid_columns = get_valid_columns(table_model, test_columns)
        if not valid_columns:
            continue
        elif len(valid_columns) == 1:
            query = table_model.objects.annotate(
                final_p_value=F(valid_columns[0])  # Alias the single column as `merged_column`
            )
        else:
            query = table_model.objects.all().annotate(
                final_p_value=Coalesce(*[F(col) for col in valid_columns])
            )

        if count == 1:
            filter_query = Q(**{node_type: query_id})
            type_2 = table.split('Edges')[1].replace(node_type.capitalize(), '').lower()
        else:
            filter_query = Q(**{f'{node_type}_1': query_id}) | Q(**{f'{node_type}_2': query_id})

        # Apply filters, order, and threshold
        queryset = query.filter(filter_query).order_by('final_p_value').filter(final_p_value__lte=thresh)

        # Evaluate the queryset to apply filters and order
        evaluated_queryset = list(queryset.values())  # This retrieves all filtered and ordered records

        # Cut evaluated_edges by limit (while being aware of same significance nodes)
        if limit is not None:
            evaluated_queryset = apply_soft_limit(evaluated_queryset, limit)
            if per_type and len(evaluated_queryset) > limit:
                message = (f"For certain types, more than {limit} nodes have been returned because some nodes share the "
                           f"same significance level")

        # Add results to the correct container
        if per_type or limit is None:
            # Collect node IDs
            for item in evaluated_queryset:
                if count == 1:
                    node_ids.update({item[f'{node_type}_id'], item[f'{type_2}_id']})
                else:
                    node_ids.update({item[f'{node_type}_1_id'], item[f'{node_type}_2_id']})
            logger.debug(f"node_ids: {node_ids}")
            edges[table] = evaluated_queryset
        else:
            # Add table type to results to split overall results back into right format/ per type dictionary
            modified_edges = [{'table_name': table, **edge} for edge in evaluated_queryset]
            # Save all edges together for overall option
            all_edges.extend(modified_edges)

    if not per_type and limit is not None:
        all_edges_sorted = sorted(all_edges, key=lambda x: x['final_p_value'])

        # Cut evaluated_edges by limit (while being aware of same significance nodes)
        top_edges = apply_soft_limit(all_edges_sorted, limit)
        if len(top_edges) > limit:
            message = (f"More than {limit} nodes have been returned because some nodes share the same "
                   f"significance level")

        # Sort the top edges back by table name
        for edge in top_edges:
            table_name = edge.get('table_name')  # Ensure 'table_name' is a field in the edge data
            if table_name is None:
                logger.debug(f"table_name of the following edge is None: {edge}")
                continue
            count = table_name.lower().count(node_type.lower())
            if count == 1:
                type_2 = table_name.split('Edges')[1].replace(node_type.capitalize(), '').lower()
                node_ids.update({edge.get(f'{node_type}_id'), edge.get(f'{type_2}_id')})
            else:
                node_ids.update({edge.get(f'{node_type}_1_id'), edge.get(f'{node_type}_2_id')})

            edge.pop('table_name')
            edges.setdefault(table_name, []).append(edge)

    nodes = query_nodes(node_ids)
    mapped_externals = query_refs(node_ids)
    return edges, nodes, mapped_externals, message

def network_group_query(query_ids, thresh, test_columns, context_id=None):
    logger.debug(f"query_ids: {query_ids}")
    edges = {}
    logger.debug(f"test columns {test_columns}")
    logger.debug(f"significance thresh {thresh}")

    # Query edges
    for table in BASE_MODELS.keys():
        logger.debug(table.lower())
        # Distinguish between 'within-type' tables and 'between-type' tables
        splitted_table = re.findall(r'[A-Z][a-z]*', table)
        count = table.lower().count(splitted_table[1].lower())
        if count == 0:
            continue

        table_model = get_dynamic_model(table, context_id=context_id)
        if not table_model.objects.exists():
            continue
        row_count = table_model.objects.count()
        if row_count == 0:
            print(f"Skipping empty table: {table}")
            continue  # Skip processing for empty tables

        # Check which columns are available for the type and multiple testing correction
        valid_columns = get_valid_columns(table_model, test_columns)
        if not valid_columns:
            continue
        elif len(valid_columns) == 1:
            query = table_model.objects.annotate(
                final_p_value=F(valid_columns[0])  # Alias the single column as `merged_column`
            )
        else:
            query = table_model.objects.all().annotate(
                final_p_value=Coalesce(*[F(col) for col in valid_columns])
            )

        # Create filter to search for edges between the given node IDs
        if count == 1:
            filter_by_nodes = {
                f'{splitted_table[1].lower()}_id__in': query_ids,
                f'{splitted_table[2].lower()}_id__in': query_ids
            }
        else:
            filter_by_nodes = {
                f'{splitted_table[1].lower()}_1_id__in': query_ids,
                f'{splitted_table[2].lower()}_2_id__in': query_ids
            }

        # Query the edge tables for both node types
        queryset = query.filter(**filter_by_nodes).order_by('final_p_value').filter(final_p_value__lte=thresh).values()

        edges[table] = queryset

    nodes = query_nodes(query_ids)
    mapped_externals = query_refs(query_ids)
    return edges, nodes, mapped_externals

def get_whole_network(thresh=None, limit=None, per_node_limit=None, density=None, test_columns=None, edge_norm="minmax"):
    """
    Extract the complete network with edges and nodes from all edge models.
    
    Args:
        thresh: Significance threshold for filtering edges (optional)
        limit: Overall limit on the number of edges to return (optional)
        per_node_limit: Limit the number of edges per node (optional)
        density: Desired network density (optional, overrides thresh and limit)
        test_columns: Set of valid test columns to consider for edge scoring (optional)
    
    Returns:
        tuple: (candidate_links, selected_links, nodes)
            - candidate_links: All edges matching the threshold or density
            - selected_links: Filtered edges (after applying limit and per_node_limit)
            - nodes: Set of all node IDs from the selected edges
    """
    if test_columns is None:
        test_columns = build_test_columns()

    if density is not None:
        node_count = apps.get_model('network', 'ViewDescriptionFTS').objects.filter(
            source_table__startswith='cohort_'
        ).count()
        possible_edge_count = node_count * (node_count - 1) / 2 if node_count > 1 else 0
        if not possible_edge_count:
            logger.debug("Not enough nodes to form edges. Returning empty network.")
            return [], [], set()
        limit = ceil(density * possible_edge_count)
        thresh = None
        per_node_limit = None

    candidate_links = []
    
    for model_name in BASE_MODELS.keys():
        table_model = get_dynamic_model(model_name)
        relation_fields = get_relation_fields(table_model)
        if len(relation_fields) != 2:
            continue

        # score_columns = get_valid_p_columns(table_model, test_columns)
        # if not score_columns:
        #     continue

        # score_expression = Coalesce(*[F(column) for column in score_columns], Value(1.0))
        # queryset = (
        #     table_model.objects
        #     .annotate(final_p_value=score_expression)
        #     .filter(final_p_value__isnull=False)
        # )
        valid_p_columns = get_valid_p_columns(table_model, test_columns)
        valid_e_columns = get_valid_e_columns(valid_p_columns)
        if not valid_p_columns:
            continue
        elif len(valid_p_columns) == 1:
            queryset = table_model.objects.annotate(
                final_p_value=F(valid_p_columns[0]),  # Alias the single column as `merged_column`
                final_e_value=F(valid_e_columns[0])
            )
        else:
            queryset = table_model.objects.all().annotate(
                final_p_value=Coalesce(*[F(col) for col in valid_p_columns]),
                final_e_value=Coalesce(*[F(col) for col in valid_e_columns])
            )
        if thresh is not None:
            queryset = queryset.filter(final_p_value__lte=thresh)

        # Order by score and fetch values. Only apply an overall slice when an explicit limit is provided.
        queryset = queryset.order_by('final_p_value').values('id', *relation_fields, 'final_p_value', 'final_e_value')
        if limit is not None:
            queryset = queryset[:limit]

        for row in queryset:
            source = row.get(relation_fields[0])
            target = row.get(relation_fields[1])
            if not source or not target:
                continue
            candidate_links.append({
                'id': f"{table_model._meta.db_table}:{row['id']}",
                'source': source,
                'target': target,
                'edge_type': table_model._meta.db_table,
                'final_p_value': row.get('final_p_value'),
                'final_e_value': row.get('final_e_value'),
                'test_type': valid_p_columns[0].split('_')[0]  # Extract test type from table name
            })

    candidate_links.sort(
        key=lambda edge: float(edge['final_p_value']) if edge['final_p_value'] is not None else 1.0,
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
            key=lambda edge: float(edge['final_p_value']) if edge['final_p_value'] is not None else 1.0,
        )
    else:
        selected_links = candidate_links

    selected_links = rescale_edges(selected_links, normalization=edge_norm)

    if limit is not None and len(selected_links) > limit:
        selected_links = selected_links[:limit]

    # Extract nodes from selected links and filter to only those present in edges
    nodes = set()
    for edge in selected_links:
        nodes.add(edge['source'])
        nodes.add(edge['target'])
    
    return candidate_links, selected_links, nodes

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
            (label, apps.get_model('network', name))
            for _stat, name, label in STAT_TYPE_EDGE_MODELS
        ]
        if test_type:
            return [(label, model) for label, model in all_models if test_type in label]
        return all_models

    context_model = apps.get_model('network', 'Context')
    try:
        context = context_model.objects.get(context_id=context_id)
        test_type = context.params.get('testType', 'parametric')
    except context_model.DoesNotExist:
        test_type = 'parametric'

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
    Mirrors network_group_query()'s old tuple shape.

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


def get_relation_fields(model):
    """
    Extract relation fields (many-to-one) from a model.
    """
    return [
        field.attname for field in model._meta.fields
        if field.is_relation and getattr(field, 'many_to_one', False)
    ]

def get_score_columns(model):
    preferred_suffixes = [
        '_p_benjamini_hb',
        '_p_bonferroni',
        '_p_unadjusted',
        '_p_benjamini_yek',
    ]
    columns = []
    for suffix in preferred_suffixes:
        columns.extend([
            field.name for field in model._meta.fields
            if field.name.endswith(suffix)
        ])
    return list(dict.fromkeys(columns))

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
