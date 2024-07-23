import json
import os
import timeit
# we were using the sqlalchemy library to connect to the database, but you should probably change it to
# the django ORM
from sqlalchemy import select, func, text
from sqlalchemy.engine import URL, create_engine
from sqlalchemy.orm import sessionmaker


url = url_object = URL.create(
    "postgresql",
    username="postgres",
    password="password",  # plain (unescaped) text
    host="0.0.0.0",
    port=9852,
    database="postgres",
)
engine = create_engine(url)


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


def query_identity_table(session, table, id_names, base_table, query_id, limit):
    # to best understand this query, you should print it out or look at it in the debugger
    # open a psql terminal and convince yourself that this query works
    order = f"ORDER BY {table}.p_value ASC" if table.startswith('effects') else ""
    identity_query = f"""
    SELECT
        {table}.*,
        part1.*,
        part2.*
    FROM
        {table}
    JOIN
        {base_table[0]} AS part1 ON {table}."{id_names[0]}" = part1.{base_table[1]}
    JOIN
        {base_table[0]} AS part2 ON {table}."{id_names[1]}" = part2.{base_table[1]}
    WHERE
        {table}."{id_names[0]}" = '{query_id}'
        OR {table}."{id_names[1]}" = '{query_id}'
    {order}
    LIMIT {limit};
    """
    result = session.execute(text(identity_query)).fetchall()
    return result


def get_remaining_tables(session, table, id_names, base_table, query_id, limit):
    # Determine the edge type from the table name
    # check if the table name is in the table_ids
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

    order = f"ORDER BY {table}.p_value ASC" if table.startswith('effects') else ""

    remaining_sql = f"""
            SELECT
                {table}.*,
                base.*,
                second_base.*
            FROM
                {table}
            JOIN
                {base_table[0]} AS base ON {table}."{id_names[0]}" = base."{base_table[1]}"
            JOIN
                {second_base[0]} AS second_base ON {table}."{second_base[1]}" = second_base.{second_base[1]}
            WHERE
                {table}."{id_names[0]}" = '{query_id}'
            {order}
            LIMIT {limit};
            """
    result = session.execute(text(remaining_sql)).fetchall()
    return result


def get_tables(session, node_type):
    tables_query = f"""
    SELECT table_name, column_name
    FROM information_schema.columns
    WHERE column_name LIKE '{node_type}%'
    AND table_schema = 'public';
    """
    result = session.execute(text(tables_query)).fetchall()
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


def get_edges(session, node_type, query_id, limit=10):
    # we differentiate between the base table, identity tables, and remaining tables
    # the base table is the table that contains information about the query id (i.e. information about the protein)
    # the identity tables are edges that connect the query id to other nodes of the same type (protein-protein)
    # the remaining tables are edges that connect the query id to other nodes of a different type (protein-metabolite)
    base_table, identity_tables, remaining_tables = get_tables(session, node_type)

    # base table is like ('proteins', 'uniprot_id')
    # identity tables is like [('effects_protein_protein', ['uniprot_id_1', 'uniprot_id_2']), ...]
    # remaining tables is like [('effects_protein_metabolite', ['uniprot_id']), ...]

    # query the identity tables
    results = {}
    for table, id_names in identity_tables:
        result = query_identity_table(session, table, id_names, base_table, query_id, limit)
        results[table] = result

    for table, id_name in remaining_tables:
        result = get_remaining_tables(session, table, id_name, base_table, query_id, limit)
        results[table] = result
    # get the sum of the results
    total_results = sum([len(result) for result in results.values()])
    return results, total_results


if __name__ == '__main__':
    # this is also SQLAlchemy code, you should change it to Django ORM
    Session = sessionmaker(bind=engine)
    session = Session()

    start = timeit.default_timer()
    edges, num_edges = get_edges(session, 'uniprot_id', 'uniprot.P31946', limit=10)
    print(f"Took {timeit.default_timer() - start:.2f} seconds to get {num_edges} edges")
    print(type(edges))
    for table, edge in edges.items():
        print(table)
        print(edge)