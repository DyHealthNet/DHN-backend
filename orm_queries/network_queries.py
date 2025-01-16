import os
import django
import timeit
import network.queries as queries

# This script is not an essential part of the django backend. It was only used for testing the network query.

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dyhealthnet_project.settings')
django.setup()

CHRIS_EDGES = {'EdgesProteinProtein', 'EdgesProteinMetabolite',
               'EdgesProteinPhenotype', 'EdgesMetaboliteMetabolite',
               'EdgesMetabolitePhenotype', 'EdgesPhenotypePhenotype',
               'EdgesVariantMetabolite', 'EdgesVariantPhenotype',
               'EdgesVariantProtein'}

if __name__ == '__main__':
    start = timeit.default_timer()
    edges, nodes, externals = queries.network_query('x0rd09', 'phenotype', 10)
    time = timeit.default_timer() - start

    num_edges = 0
    for table, results in edges.items():
        print(table)
        print(results)
        for entry in results:
            num_edges += 1

    num_nodes = 0
    for results in nodes:
        print(results)
        num_nodes += 1
    print("\nExternals\n")
    num_externals = 0
    for results in externals:
        print(results)
        num_externals += 1

    print(f"Took {time} seconds to get {num_edges} edges, {num_nodes} nodes and {num_externals} externals.")
    print("")

    start = timeit.default_timer()
    externals, cohort_nodes, external_nodes = queries.external_query('PC ae C34:1', True)
    time = timeit.default_timer() - start

    num_edges = 0
    print("Edges:")
    for results in externals:
        print(results)
        num_edges += 1

    print("Cohort Nodes:")
    num_nodes = 0
    for results in cohort_nodes:
        for entry in results:
            print(entry)
            num_nodes += 1

    print("External Nodes:")
    num_external_nodes = 0
    for results in external_nodes:
        for entry in results:
            print(entry)
            num_external_nodes += 1

    print(f"Took {time} seconds to get {num_edges} edges, {num_nodes} nodes and {num_external_nodes} external nodes.")