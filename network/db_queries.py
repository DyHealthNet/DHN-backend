import os
import django
from django.db.models import Q
from django.apps import apps
from django.db import connection
import timeit

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
    parts = table.split('_')
    table = ''.join([part.capitalize() for part in parts])
    table_model = apps.get_model('network', table.capitalize())
    if table_model.__name__.startswith('Effects'):
        order = 'p_value'
    else:
        order = None

    queryset = table_model.objects.select_related(id_names[0]).select_related(id_names[1])
    results = queryset.filter(Q(**{id_names[0]: query_id}) | Q(**{id_names[1]: query_id}))
    if order:
        results = results.order_by(order)
    return results[:limit]

def get_remaining_tables(table, id_names, base_table, query_id, limit):
    parts = table.split('_')
    table = ''.join([part.capitalize() for part in parts])
    table_model = apps.get_model('network', table.capitalize())
    if table_model.__name__.startswith('Effects'):
        order = 'p_value'
    else:
        order = None

    table_parts = tuple([x for x in table.split('_') if x not in {'effects', 'associates', 'affects'}])
    table_keys = TABLE_IDS.get(table_parts)
    if not table_keys:
        return {}

    second_base = None
    for name, domain_id in zip(table_parts, table_keys):
        if domain_id != base_table[1]:
            # we need to use plural here
            second_base = (f"{name}s", domain_id)
            break
    if not second_base:
        return {}

    queryset = table_model.objects.select_related(id_names[0]).select_related(second_base[1])
    results = queryset.filter(Q(**{id_names[0]: query_id}))

    if order:
        results = results.order_by(order)
    return results[:limit]

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
    results = {}
    for table, id_names in identity_tables:
        result = query_identity_table(table, id_names, base_table, query_id, limit)
        results[table] = result

    for table, id_name in remaining_tables:
        result = get_remaining_tables(table, id_name, base_table, query_id, limit)
        results[table] = result

    # get the sum of the results
    total_results = sum([len(result) for result in results.values()])
    return results, total_results

if __name__ == '__main__':
    start = timeit.default_timer()
    edges, num_edges = get_edges('uniprot_id', 'uniprot.P31946', limit=10)
    print(f"Took {timeit.default_timer() - start:.2f} seconds to get {num_edges} edges")
    for objects in edges.values():
        for edges in objects:
            print(edges.p_value)
            print(edges.effect_size_type)
            print(edges.uniprot_id_1)
            print(edges.uniprot_id_2)