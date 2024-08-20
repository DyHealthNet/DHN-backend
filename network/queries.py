from django.db.models import Q
from django.apps import apps
from functools import reduce
from operator import or_

CHRIS_EDGES = {'EffectsProteinProtein', 'EffectsProteinMetabolite',
               'EffectsProteinPhenotype', 'EffectsMetaboliteMetabolite',
               'EffectsMetabolitePhenotype', 'EffectsPhenotypePhenotype'}


def network_query(query_id, type, limit):
    edges = {}
    node_ids = set()
    external_ids = set()

    # Query edges
    for table in CHRIS_EDGES:
        # Distinguish between 'within-type' tables and 'between-type' tables
        count = table.lower().count(type.lower())
        if count == 0:
            continue

        elif count == 1:
            # Retrieve django model corresponding to current table
            table_model = apps.get_model('network', table)
            # Filter for query_id, order by p-value and limit
            queryset = table_model.objects.filter(Q(**{type: query_id})
                                                  ).order_by('p_value')[:limit].values()

            # Find second type
            substring = table.split('Effects')[1]
            if substring.index(type.capitalize()) == 0:
                type_2 = substring.split(type.capitalize())[1].lower()
            else:
                type_2 = substring.split(type.capitalize())[0].lower()

            # Collect unique node IDs
            node_ids.update(*zip(*queryset.values_list(f'{type}_id', f'{type_2}_id')))

        else:
            # Retrieve django model corresponding to current table
            table_model = apps.get_model('network', table)
            # Filter for query_id, order by p-value and limit
            queryset = table_model.objects.filter(Q(**{f'{type}_1': query_id}) | Q(**{f'{type}_2': query_id})
                                                  ).order_by('p_value')[:limit].values()

            # Collect unique node IDs
            node_ids.update(*zip(*queryset.values_list(f'{type}_1_id', f'{type}_2_id')))

        edges[table] = queryset

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
    externals = external_edges_model.objects.filter(Q(source_id__in=external_ids) & Q(target_id__in=external_ids)).values()

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


def external_query(query_id):
    external_ids = set()
    ref_ids = set()

    # Query external edges
    # Retrieve all references from the query node to external nodes
    ref_model = apps.get_model('network', 'ViewReferencesEdges')
    refs = ref_model.objects.filter(cohort_id=query_id).values() # Evtl weglassen
    ref_ids.update(*zip(*refs.values_list('reference_id')))
    id_mapping = {ref['reference_id']: ref['cohort_id'] for ref in refs}

    # Retrieve all edges from referenced external nodes
    external_edges_model = apps.get_model('network', 'ViewAssociationsEdges')
    externals = external_edges_model.objects.filter(Q(source_id__in=ref_ids) | Q(target_id__in=ref_ids)).values()
    external_ids.update(*zip(*externals.values_list('source_id')))
    external_ids.update(*zip(*externals.values_list('target_id')))

    # Map externals back to cohort nodes if available, otherwise retrieve external node
    cohort_nodes_model = apps.get_model('network', 'ViewDescriptionFTS')
    external_nodes_model = apps.get_model('network', 'ViewExternalNodes')
    cohort_nodes = []
    external_nodes = []

    for ext_id in external_ids:
        ext_id = ext_id.split(".")[1] # delete later
        mapped_nodes = cohort_nodes_model.objects.filter(Q(xrefs__icontains=ext_id)).values()

        if not mapped_nodes:
            type = external_nodes_model.objects.filter(Q(node_id__icontains=ext_id)).values()[0]['source_table']
            type_model = apps.get_model('network', type.capitalize())
            unknown_nodes = type_model.objects.filter(Q(pk__icontains=ext_id)).values()
            external_nodes.append(unknown_nodes)
            id_mapping.update({ext_id: ext_id})

        else:
            cohort_nodes.append(mapped_nodes)
            id_mapping.update({ext_id: node_id[0] for node_id in mapped_nodes.values_list('id')})

    mapped_externals = [
        {
            'source_id': external['source_id'],
            'target_id': external['target_id'],
            'mapping_source_id': id_mapping.get(external['source_id']),
            'mapping_target_id': id_mapping.get(external['target_id'])
        }
        for external in externals
    ]

    return mapped_externals, cohort_nodes, external_nodes


def typeahead_query(query):
    model = apps.get_model('network', 'ViewDescriptionFTS')
    return model.objects.filter(Q(description__icontains=query) |
                                Q(display_name__icontains=query) |
                                Q(id__icontains=query) |
                                Q(xrefs__icontains=query)).values()
