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
    nodes = {}
    metabolite_ids = set()
    protein_ids = set()
    phenotype_ids = set()
    mapping = {'metabolite_ids': metabolite_ids,
               'protein_ids': protein_ids,
               'phenotype_ids': phenotype_ids}

    for table in CHRIS_EDGES:

        # Distinguish between 'within-type' tables and 'between-type' tables
        count = table.lower().count(type.lower())
        if count == 0:
            continue

        elif count == 1:
            table_model = apps.get_model('network', table)
            # Filter for query_id, order by p-value and limit
            queryset = table_model.objects.filter(Q(**{type: query_id})
                                                  ).order_by('p_value')[:limit].values()

            # Find second type
            type_2 = str(table.split(type.capitalize(), 1)[1]).lower()
            # Collect unique node IDs
            for edge in queryset:
                mapping[f'{type}_ids'].add(edge[f'{type}_id'])
                mapping[f'{type_2}_ids'].add(edge[f'{type_2}_id'])

        else:

            table_model = apps.get_model('network', table)
            # Filter for query_id, order by p-value and limit
            queryset = table_model.objects.filter(Q(**{f'{type}_1': query_id}) | Q(**{f'{type}_2': query_id})
                                                  ).order_by('p_value')[:limit].values()

            # Collect unique node IDs
            for edge in queryset:
                mapping[f'{type}_ids'].add(edge[f'{type}_1_id'])
                mapping[f'{type}_ids'].add(edge[f'{type}_2_id'])

        edges[table] = queryset

    cohort_nodes = ['Protein', 'Metabolite', 'Phenotype']
    for node in cohort_nodes:
        node_model = apps.get_model('network', f'Cohort{node}')
        nodes[node] = node_model.objects.filter(cohort_id__in=mapping[f'{node.lower()}_ids']).values()

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
for table, results in nodes.items():
    print(table)
    print(results)
    for entry in results:
        num_nodes+=1

print(f"Took {time} seconds to get {num_edges} edges and {num_nodes} nodes.")