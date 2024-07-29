import os
import django
from django.db.models import Q
from django.apps import apps
from django.db import connection
import timeit
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dyhealthnet_project.settings')
django.setup()

CHRIS_EDGES = {'EffectsProteinProtein', 'EffectsProteinMetabolite',
               'EffectsProteinPhenotype', 'EffectsMetaboliteMetabolite',
               'EffectsMetabolitePhenotype', 'EffectsPhenotypePhenotype'}

def network_query(query_id, type, threshold=0.01):
    edges = {}
    for table in CHRIS_EDGES:
        count = table.lower().count(type.lower())

        if count == 0:
            continue

        elif count == 1:
            table_model = apps.get_model('network', table)
            edges[table] = table_model.objects.filter(Q(**{f'{type}_id': query_id}), p_value__lte=threshold).values()

        elif count == 2:
            table_model = apps.get_model('network', table)
            edges[table] = table_model.objects.filter(Q(**{f'{type}_id_1': query_id}) | Q(**{f'{type}_id_2': query_id}),
                                                      p_value__lte=threshold).values()
        else:
            print("Something is wrong!")

    return edges


start = timeit.default_timer()
edges = network_query('x0so0034', 'protein')
num_edges = len(edges.values())
time = timeit.default_timer() - start


count = 0
for table, results in edges.items():
    print(table, ": ")
    print(results, "\n")
    count += len(results)

print(f"Took {time} seconds to get {count} edges.")