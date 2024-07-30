import os
import django
from django.db.models import Q
from django.apps import apps
import timeit

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dyhealthnet_project.settings')
django.setup()

CHRIS_EDGES = {'EffectsProteinProtein', 'EffectsProteinMetabolite',
               'EffectsProteinPhenotype', 'EffectsMetaboliteMetabolite',
               'EffectsMetabolitePhenotype', 'EffectsPhenotypePhenotype'}

def network_query(query_id, type, limit):
    edges = {}
    node_ids = set()

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
            type_2 = str(table.split(type.capitalize(), 1)[1]).lower()
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

    return edges, nodes


start = timeit.default_timer()
edges, nodes = network_query('x0so1193', 'protein', 10)
time = timeit.default_timer() - start

num_edges = 0
for table, results in edges.items():
    print(table)
    print(results)
    for entry in results:
        num_edges+=1

num_nodes = 0
for results in nodes:
    print(results)
    num_nodes+=1

print(f"Took {time} seconds to get {num_edges} edges and {num_nodes} nodes.")
