import re

from django.db.models import Q
from django.apps import apps
from django.db.models.functions import Coalesce
from django.db.models import F
from network.models import create_dynamic_model
from network.models import (
    EdgesProteinProtein, EdgesProteinMetabolite, EdgesProteinPhenotype,
    EdgesMetaboliteMetabolite, EdgesMetabolitePhenotype, EdgesPhenotypePhenotype,
    EdgesVariantMetabolite, EdgesVariantPhenotype, EdgesVariantProtein,
    EdgesProteinProteinContext, EdgesProteinMetaboliteContext, EdgesProteinPhenotypeContext,
    EdgesMetaboliteMetaboliteContext, EdgesMetabolitePhenotypeContext, EdgesPhenotypePhenotypeContext,
    EdgesVariantMetaboliteContext, EdgesVariantPhenotypeContext, EdgesVariantProteinContext
)


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
BASE_MODELS_CONTEXT = {
    'EdgesProteinProtein': EdgesProteinProteinContext,
    'EdgesProteinMetabolite': EdgesProteinMetaboliteContext,
    'EdgesProteinPhenotype': EdgesProteinPhenotypeContext,
    'EdgesMetaboliteMetabolite': EdgesMetaboliteMetaboliteContext,
    'EdgesMetabolitePhenotype': EdgesMetabolitePhenotypeContext,
    'EdgesPhenotypePhenotype': EdgesPhenotypePhenotypeContext,
    'EdgesVariantMetabolite': EdgesVariantMetaboliteContext,
    'EdgesVariantPhenotype': EdgesVariantPhenotypeContext,
    'EdgesVariantProtein': EdgesVariantProteinContext,
}

# standard_pvalue_dict = {
#     ('protein', 'protein'):'pearson_p_bonferroni',
#     ('protein','metabolite'):'pearson_p_bonferroni',
#     'phenotype':'',
#     'metabolite':'pearson_p_bonferroni',
#     'gene':'',
#     'vaiant':'',
#
# type_mapping={
#     'protein':'continous'
#
# }
#
# def getPvalueOfInterest(type1, type2, parametric=True, mult_test_corr= 'bh')


def network_query(query_id, type, limit, perType, thresh, test_columns, context_id=None):
    edges = {}
    all_edges = []
    node_ids = set()
    external_ids = set()
    print(f"test columns {test_columns}")
    print(f"significance thresh {thresh}")
    print(f"limit {limit}")
    print(f"perType {perType}")

    # Query edges
    for table in BASE_MODELS.keys():
        print(table.lower())
        # Distinguish between 'within-type' tables and 'between-type' tables
        count = table.lower().count(type.lower())
        if count == 0:
            continue

        # Split before each uppercase letter except the first
        split_name = re.sub(r'(?<!^)(?=[A-Z])', '_', table)
        if context_id:
            table_name = f"{split_name.lower()}_{context_id}"
            table_model = create_dynamic_model(BASE_MODELS_CONTEXT[table], table_name)
        else:
            table_name = f"{split_name.lower()}"
            table_model = create_dynamic_model(BASE_MODELS[table], table_name)

        row_count = table_model.objects.count()
        if row_count == 0:
            print(f"Skipping empty table: {table_name}")
            continue  # Skip processing for empty tables

        # Check which columns are available for the type and multiple testing correction
        valid_columns = []
        for field in table_model._meta.get_fields():
            if field.name in test_columns:
                valid_columns.append(field.name)

        # Sort valid_columns to prioritize binaryCatCont columns so that this columns value will be chosen if present
        valid_columns.sort(key=lambda col: not (col.startswith("ttest") or col.startswith("mwu")))

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

            # Filter for query_id, order by p-value and limit
            queryset = query.filter(Q(**{type: query_id})
                                    ).order_by('final_p_value').filter(final_p_value__lte=thresh)
            print(f"queryset: {queryset}")
            if limit is not None and perType:
                queryset = queryset[:limit]
            queryset = queryset.values()


            # Find second type
            substring = table.split('Edges')[1]
            if substring.index(type.capitalize()) == 0:
                type_2 = substring.split(type.capitalize())[1].lower()
            else:
                type_2 = substring.split(type.capitalize())[0].lower()

            node_ids.update(*zip(*queryset.values_list(f'{type}_id', f'{type_2}_id')))
        else:
            queryset = query.filter(Q(**{f'{type}_1': query_id}) | Q(**{f'{type}_2': query_id})
                                                  ).order_by('final_p_value').filter(final_p_value__lte=thresh)
            print(f"queryset: {queryset}")

            if limit is not None and perType:
                queryset = queryset[:limit]
            queryset = queryset.values()

            # Collect unique node IDs
            node_ids.update(*zip(*queryset.values_list(f'{type}_1_id', f'{type}_2_id')))

        if perType:
            edges[table] = queryset
        else:
            all_edges.extend(queryset)

    if not perType:
        all_edges_sorted = sorted(all_edges, key=lambda x: x['final_p_value'])

        top_edges = all_edges_sorted[:limit]

        # Sort the top edges back by table name
        for edge in top_edges:
            table_name = edge.get('table_name')  # Ensure 'table_name' is a field in the edge data
            if table_name not in edges:
                edges[table_name] = []
            edges[table_name].append(edge)

    # Query nodes
    # Retrieve django model corresponding to current node
    node_model = apps.get_model('network', 'ViewDescriptionFTS')
    # Filter for collected unique node IDs
    nodes = node_model.objects.filter(id__in=node_ids).values()

    # Query external edges
    # Retrieve all references from cohort nodes to external nodes
    ref_model = apps.get_model('network', 'ViewReferencesEdges')
    refs = ref_model.objects.filter(cohort_id__in=node_ids).values()
    external_ids.update(*zip(*refs.values_list('reference_id')))

    # Retrieve all edges between those referenced external nodes
    external_edges_model = apps.get_model('network', 'ViewAssociationsEdges')
    externals = external_edges_model.objects.filter(Q(source_id__in=external_ids) &
                                                    Q(target_id__in=external_ids)).values()

    # Map externals back to original nodes
    id_mapping = {ref['reference_id']: ref['cohort_id'] for ref in refs}
    mapped_externals = [
        {
            'source_id': external['source_id'],
            'target_id': external['target_id'],
            'source_cohort_id': id_mapping.get(external['source_id']),
            'target_cohort_id': id_mapping.get(external['target_id'])
        }
        for external in externals
    ]
    return edges, nodes, mapped_externals

def network_group_query(query_ids, thresh, test_columns, context_id=None):
    print(f"query_ids: {query_ids}")
    edges = {}
    external_ids = set()
    print(f"test columns {test_columns}")
    print(f"significance thresh {thresh}")

    # Query edges
    for table in BASE_MODELS.keys():
        print(table.lower())

        # Split before each uppercase letter except the first
        split_name = re.sub(r'(?<!^)(?=[A-Z])', '_', table)
        if context_id:
            table_name = f"{split_name.lower()}_{context_id}"
            table_model = create_dynamic_model(BASE_MODELS_CONTEXT[table], table_name)
        else:
            table_name = f"{split_name.lower()}"
            table_model = create_dynamic_model(BASE_MODELS[table], table_name)

        row_count = table_model.objects.count()
        if row_count == 0:
            print(f"Skipping empty table: {table_name}")
            continue  # Skip processing for empty tables

        # Check which columns are available for the type and multiple testing correction
        valid_columns = []
        for field in table_model._meta.get_fields():
            if field.name in test_columns:
                valid_columns.append(field.name)

        # Sort valid_columns to prioritize binaryCatCont columns so that this columns value will be chosen if present
        valid_columns.sort(key=lambda col: not (col.startswith("ttest") or col.startswith("mwu")))

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

        count = table.lower().count(table_name.split("_")[1].lower())
        # Create filter kwargs to search for edges between the given node IDs
        if count == 1:
            filter_by_nodes = {
                f'{table_name.split("_")[1]}_id__in': query_ids,
                f'{table_name.split("_")[2]}_id__in': query_ids
            }
        else:
            filter_by_nodes = {
                f'{table_name.split("_")[1]}_1_id__in': query_ids,
                f'{table_name.split("_")[2]}_2_id__in': query_ids
        }

        # Query the edge tables for both node types
        queryset = query.filter(**filter_by_nodes).order_by('final_p_value').filter(final_p_value__lte=thresh).values()

        edges[table] = queryset

    # Query nodes
    # Retrieve django model corresponding to current node
    node_model = apps.get_model('network', 'ViewDescriptionFTS')
    # Filter for collected unique node IDs
    nodes = node_model.objects.filter(id__in=query_ids).values()

    # Query external edges
    # Retrieve all references from cohort nodes to external nodes
    ref_model = apps.get_model('network', 'ViewReferencesEdges')
    refs = ref_model.objects.filter(cohort_id__in=query_ids).values()
    external_ids.update(*zip(*refs.values_list('reference_id')))

    # Retrieve all edges between those referenced external nodes
    external_edges_model = apps.get_model('network', 'ViewAssociationsEdges')
    externals = external_edges_model.objects.filter(Q(source_id__in=external_ids) &
                                                    Q(target_id__in=external_ids)).values()

    # Map externals back to original nodes
    id_mapping = {ref['reference_id']: ref['cohort_id'] for ref in refs}
    mapped_externals = [
        {
            'source_id': external['source_id'],
            'target_id': external['target_id'],
            'source_cohort_id': id_mapping.get(external['source_id']),
            'target_cohort_id': id_mapping.get(external['target_id'])
        }
        for external in externals
    ]
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
            type = external_nodes_model.objects.filter(Q(node_id=ext_id)).values()[0]['source_table']
            type_model = apps.get_model('network', type.capitalize())
            # Retrieve the external node using the primary key
            unknown_nodes = type_model.objects.filter(Q(pk=ext_id)).values()
            for node in unknown_nodes:
                node["source_table"] = "external_" + type
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
    print(query)
    print(tables)
    if tables:
        print("here")
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
