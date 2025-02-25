import re

from django.db.models import Q, Value
from django.apps import apps
from django.db.models.functions import Coalesce
from django.db.models import F
from django.forms.models import model_to_dict
from network.models import create_dynamic_model
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

def check_table_name_key(edges):
    """
    Check if each element in the list has the 'table_name' key.

    Parameters:
    edges (list): List of dictionaries to check.

    Returns:
    bool: True if all elements have the 'table_name' key, False otherwise.
    """
    for edge in edges:
        if 'table_name' not in edge:
            return False
    return True

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
    valid_columns = [field.name for field in model._meta.get_fields() if field.name in test_columns]
    return sorted(valid_columns, key=lambda col: not (col.startswith("ttest") or col.startswith("mwu")))

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
    node_ids = set()
    all_edges = []
    if limit is None:
        logger.info(f"limit is None")
        return
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
            logger.info(f"Table {table} irrelevant for this node")
            continue

        logger.info(f"Table {table}")

        table_model = get_dynamic_model(table, context_id=context_id)
        if not table_model.objects.exists():
            continue
        row_count = table_model.objects.count()
        if row_count == 0:
            logger.info(f"Skipping empty table: {table}")
            continue  # Skip processing for empty tables

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
        evaluated_queryset = queryset.values()  # This retrieves all filtered and ordered records
        logger.debug("evaluated queryset: " + str(evaluated_queryset))

        # Apply limit if given
        if limit is not None and per_type:
            evaluated_queryset = evaluated_queryset[:limit]  # Now slice the evaluated list

        logger.debug("limited evaluated queryset: " + str(evaluated_queryset))

        # Collect node IDs
        if count == 1:
            node_ids.update(*zip(*[(item[f'{node_type}_id'], item[f'{type_2}_id']) for item in evaluated_queryset]))
        else:
            node_ids.update(*zip(*[(item[f'{node_type}_1_id'], item[f'{node_type}_2_id']) for item in evaluated_queryset]))


        logger.debug(f"node_ids: {node_ids}")

        # Add results to the correct container
        if per_type:
            edges[table] = evaluated_queryset
        else:
            new_queryset = new_queryset.annotate(table_name=Value(table)) # attention: two times applied something to new_queryset
            all_edges.extend(new_queryset.values())

            # Extend all_edges with the modified edges
            all_edges.extend(modified_edges)

    node_ids = set()
    if not per_type:
        all_edges_sorted = sorted(all_edges, key=lambda x: x['final_p_value'])

        has_table_name = check_table_name_key(all_edges_sorted)
        logger.debug(f"All elements of all_edges_sorted have 'table_name' key: {has_table_name}")

        top_edges = all_edges_sorted[:limit]

        # Extract the last final_p_value from the top edges
        last_edge_final_p_value = top_edges[-1]['final_p_value'] if top_edges else None

        # Get additional edges with the same final_p_value
        additional_overall_edges = [edge for edge in all_edges if edge['final_p_value'] == last_edge_final_p_value]

        has_table_name = check_table_name_key(additional_overall_edges)
        logger.debug(f"All elements of additional_overall_edges have 'table_name' key: {has_table_name}")

        # Combine top edges with additional edges
        top_edges = top_edges + additional_overall_edges

        # TODO somehow remove dublicates because this wouldn't work different tables have their own id col its not unique
        #top_edges = list({v['id']: v for v in top_edges}.values())

        has_table_name = check_table_name_key(top_edges)
        logger.debug(f"All elements of top_edges have 'table_name' key: {has_table_name}")
        # Sort the top edges back by table name
        for edge in top_edges:
            table_name = edge.get('table_name')  # Ensure 'table_name' is a field in the edge data
            if table_name is None:
                logger.debug(f"table_name of the following edge is None: {edge}")
                continue
            logger.debug(f"edge: {edge}")
            logger.debug(f"table list: {table_name}")
            count = table_name.lower().count(node_type.lower())
            if count == 1:
                type_2 = table_name.split('Edges')[1].replace(node_type.capitalize(), '').lower()
                node_ids.add(edge.get(f'{node_type}_id'))
                node_ids.add(edge.get(f'{type_2}_id'))
            else:
                node_ids.add(edge.get(f'{node_type}_1_id'))
                node_ids.add(edge.get(f'{node_type}_2_id'))

            if table_name not in edges:
                edges[table_name] = []
            edge.pop('table_name')
            edges[table_name].append(edge)

    nodes = query_nodes(node_ids)
    mapped_externals = query_refs(node_ids)
    return edges, nodes, mapped_externals

def network_group_query(query_ids, thresh, test_columns, context_id=None):
    print(f"query_ids: {query_ids}")
    edges = {}
    print(f"test columns {test_columns}")
    print(f"significance thresh {thresh}")

    # Query edges
    for table in BASE_MODELS.keys():
        print(table.lower())
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

# Search for 'query' in all fields of all cohort node tables
def typeahead_query(query, tables=None, limit=20):
    model = apps.get_model('network', 'ViewDescriptionFTS')
    if tables:
        return model.objects.filter((Q(description__icontains=query) |
                                    Q(display_name__icontains=query) |
                                    Q(id__icontains=query) |
                                    Q(xrefs__icontains=query)) &
                                    Q(source_table__in=tables))[:limit].values()
    else:
        return model.objects.filter(Q(description__icontains=query) |
                                    Q(display_name__icontains=query) |
                                    Q(id__icontains=query) |
                                    Q(xrefs__icontains=query))[:limit].values()
