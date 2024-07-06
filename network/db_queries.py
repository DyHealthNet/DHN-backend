import os
import django
from django.db.models import Q
from django.apps import apps
from django.db import connection
import timeit
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dyhealthnet_project.settings')
django.setup()

#from models import Proteins, Metabolites, Disorders, Phenotypes, Genes
#from models import ProteinAssociatesMetabolites, ProteinAssociatesProteins, DisorderAssociatesPhenotypes, GeneAssociatesDisorders, MetaboliteAssociatesDisorders
#from models import EffectsProteinProtein, EffectsProteinDisorder, EffectsProteinPhenotype, EffectsProteinMetabolite, EffectsPhenotypeDisorder, EffectsMetaboliteDisorder, EffectsDisorderDisorder, EffectsMetabolitePhenotype, EffectsMetaboliteMetabolite, EffectsPhenotypePhenotype

BASE_TABLES = {'proteins': 'uniprot_id', 'metabolites': 'hmdb_id',
               'disorders': 'mondo_id', 'phenotypes': 'hpo_id',
               'genes': 'entrez_id', 'genomic_variant': 'varinat_primaryDomainId'}

TABLE_IDS = {
    ('protein', 'phenotype'): ('uniprot_id', 'hpo_id'),
    ('phenotype', 'protein'): ('hpo_id', 'uniprot_id'),
    ('protein', 'disorder'): ('uniprot_id', 'mondo_id'),
    ('disorder', 'protein'): ('mondo_id', 'uniprot_id'),
    ('protein', 'metabolite'): ('uniprot_id', 'hmdb_id'),
    ('metabolite', 'protein'): ('hmdb_id', 'uniprot_id'),

    ('metabolite', 'disorder'): ('hmdb_id', 'mondo_id'),
    ('disorder', 'metabolite'): ('mondo_id', 'hmdb_id'),
    ('metabolite', 'phenotype'): ('hmdb_id', 'hpo_id'),
    ('phenotype', 'metabolite'): ('hpo_id', 'hmdb_id'),

    ('phenotype', 'disorder'): ('hpo_id', 'mondo_id'),
    ('disorder', 'phenotype'): ('mondo_id', 'hpo_id'),

    # this doesn't work at the moment since the table columns are not consistent...not my fault
    ('variant', 'gene'): ('genomic_variant', 'entrez_id'),
    ('gene', 'variant'): ('entrez_id', 'genomic_variant')
}

def get_tables(node_type):
    with connection.cursor() as cursor:
        tables_query = f"""
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE column_name LIKE '{node_type}%'
        AND table_schema = 'public';
        """
        cursor.execute(tables_query)
        result = cursor.fetchall()

    base_table = None
    # count how many times each table appears
    table_counts = {}
    for row in result:
        table_name = row[0]
        if table_name in BASE_TABLES.keys():
            base_table = (table_name, row[1])
            continue
        if table_name in table_counts:
            table_counts[table_name] += 1
        else:
            table_counts[table_name] = 1
    identity_tables = {table_name for table_name, count in table_counts.items() if count == 2}
    remaining_tables = set(table_counts.keys()) - set(BASE_TABLES.keys()) - identity_tables

    identity_tables = [(table_name, [row[1] for row in result if row[0] == table_name])
                       for table_name in identity_tables]
    remaining_tables = [(table_name, [row[1] for row in result if row[0] == table_name])
                        for table_name in remaining_tables]

    return base_table, identity_tables, remaining_tables


def query_identity_table(table, id_names, base_table, query_id, limit):
    # Account for differences in table names vs. model names
    parts = table.split('_')
    table = ''.join([part.capitalize() for part in parts])
    table_model = apps.get_model('network', table.capitalize())

    base_table_name = base_table[0].capitalize()
    base_table_model = apps.get_model('network', base_table_name.capitalize())

    # Filter for query ID
    edges_queryset = table_model.objects.filter(Q(**{id_names[0]: query_id}) | Q(**{id_names[1]: query_id}))

    # Optional: order by p-value
    if table_model.__name__.startswith('Effects'):
        edges_queryset = edges_queryset.order_by('p_value')

    # Limit and evaluate
    edges = edges_queryset[:limit].values()

    # Retrieve corresponding node information via primary keys
    unique_ids = set()
    for edge in edges:
        unique_ids.add(edge.get(f'{id_names[0]}_id'))
        unique_ids.add(edge.get(f'{id_names[1]}_id'))

    nodes = base_table_model.objects.filter(pk__in=unique_ids).values()

    return nodes, edges

def get_remaining_tables(table, id_names, base_table, query_id, limit):
    # Account for differences in table names vs. model names
    parts = table.split('_')
    table_new = ''.join([part.capitalize() for part in parts])
    table_model = apps.get_model('network', table_new.capitalize())

    # Find second base_table
    if 'associates' in table: # fixed a weird error, probably some inconsistency in the database
        table = table[:-1]
    table_parts = tuple([x for x in table.split('_') if x not in {'effects', 'associates', 'affects'}])
    table_keys = TABLE_IDS.get(table_parts)
    if not table_keys:
        return [], []

    second_base = None
    for name, domain_id in zip(table_parts, table_keys):
        if domain_id != base_table[1]:
            # we need to use plural here
            second_base = (f"{name}s", domain_id)
            break
    if not second_base:
        return [], []

    first_base_table_name = base_table[0].capitalize()
    first_base_table_model = apps.get_model('network', first_base_table_name.capitalize())
    second_base_table_name = second_base[0].capitalize()
    second_base_table_model = apps.get_model('network', second_base_table_name.capitalize())

    # Filter for query ID
    edges_queryset = table_model.objects.filter(Q(**{id_names[0]: query_id}) | Q(**{second_base[1]: query_id}))

    # Optional: order by p-value
    if table_model.__name__.startswith('Effects'):
        edges_queryset = edges_queryset.order_by('p_value')

    # Limit and evaluate
    edges = edges_queryset[:limit].values()

    # Retrieve corresponding node information via primary keys
    unique_ids_first_base = set()
    unique_ids_second_base = set()
    for edge in edges:
        unique_ids_first_base.add(edge.get(f'{id_names[0]}_id'))
        unique_ids_second_base.add(edge.get(f'{second_base[1]}_id'))

    nodes = []
    nodes += first_base_table_model.objects.filter(pk__in=unique_ids_first_base).values()
    nodes += second_base_table_model.objects.filter(pk__in=unique_ids_second_base).values()

    return nodes, edges

def get_edges(node_type, query_id, limit=100):
    # we differentiate between the base table, identity tables, and remaining tables
    # the base table is the table that contains information about the query id (i.e. information about the protein)
    # the identity tables are edges that connect the query id to other nodes of the same type (protein-protein)
    # the remaining tables are edges that connect the query id to other nodes of a different type (protein-metabolite)
    base_table, identity_tables, remaining_tables = get_tables(node_type)

    # base table is like ('proteins', 'uniprot_id')
    # identity tables is like [('effects_protein_protein', ['uniprot_id_1', 'uniprot_id_2']), ...]
    # remaining tables is like [('effects_protein_metabolite', ['uniprot_id']), ...]

    # query the identity tables
    nodes_results = {}
    edges_results = {}
    #results = {}
    for table, id_names in identity_tables:
        nodes, edges = query_identity_table(table, id_names, base_table, query_id, limit)
        nodes_results[table] = nodes
        edges_results[table] = edges

    for table, id_name in remaining_tables:
        nodes, edges = get_remaining_tables(table, id_name, base_table, query_id, limit)
        nodes_results[table] = nodes
        edges_results[table] = edges

    # get the sum of the results
    total_edges_results = sum(len(edges) for edges in edges_results.values())
    total_nodes_results = sum(len(nodes) for nodes in nodes_results.values())
    return nodes_results, edges_results, total_edges_results, total_nodes_results

if __name__ == '__main__':
    start = timeit.default_timer()
    nodes, edges, num_edges, num_nodes = get_edges('uniprot_id', 'uniprot.P31946', limit=100)
    print(f"Took {timeit.default_timer() - start:.2f} seconds to get {num_edges} edges and {num_nodes} nodes.")

    print('Edges:')
    for table, objects in edges.items():
        print(table, objects)
        #for result in table:
        #    print(result)

    print('Nodes:')
    for table in nodes.values():
        for result in table:
            print(result)