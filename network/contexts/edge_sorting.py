import io
import sys
from io import StringIO
import logging
from django.conf import settings
from network.models import *

logger = logging.getLogger("network")

DB_EDGES = {
    ('phenotype', 'variant'): "edges_variant_phenotype",
    ('variant', 'phenotype'): "edges_variant_phenotype",
    ('variant', 'metabolite'): "edges_variant_metabolite",
    ('metabolite', 'variant'): "edges_variant_metabolite",
    ('variant', 'protein'): "edges_variant_protein",
    ('protein', 'variant'): "edges_variant_protein",

    ('protein', 'protein'): "edges_protein_protein",
    ('protein', 'phenotype'): "edges_protein_phenotype",
    ('phenotype', 'protein'): "edges_protein_phenotype",
    ('protein', 'metabolite'): "edges_protein_metabolite",
    ('metabolite', 'protein'): "edges_protein_metabolite",

    ('metabolite', 'metabolite'): "edges_metabolite_metabolite",
    ('metabolite', 'phenotype'): "edges_metabolite_phenotype",
    ('phenotype', 'metabolite'): "edges_metabolite_phenotype",

    ('phenotype', 'phenotype'): "edges_phenotype_phenotype",
}

# Define the columns we need for each table so that we can order them later when we read the file
DB_COLUMNS = {
    "edges_variant_phenotype": ['label1', 'label2'] +
                               [field.name for field in EffectsVariantPhenotype._meta.get_fields()][3:],
    "edges_variant_metabolite": ['label1', 'label2'] +
                                [field.name for field in EffectsVariantMetabolite._meta.get_fields()][3:],

    "edges_variant_protein": ['label1', 'label2'] +
                             [field.name for field in EffectsVariantProtein._meta.get_fields()][3:],

    "edges_protein_protein": ['label1', 'label2'] +
                             [field.name for field in EffectsProteinProtein._meta.get_fields()][3:],

    "edges_protein_metabolite": ['label1', 'label2'] +
                                [field.name for field in EffectsProteinMetabolite._meta.get_fields()][3:],

    "edges_metabolite_metabolite": ['label1', 'label2'] +
                                   [field.name for field in EffectsMetaboliteMetabolite._meta.get_fields()][3:],

    "edges_protein_phenotype": ['label1', 'label2'] +
                               [field.name for field in EffectsProteinPhenotype._meta.get_fields()][3:],

    "edges_metabolite_phenotype": ['label1', 'label2'] +
                                  [field.name for field in EffectsMetabolitePhenotype._meta.get_fields()][3:],

    "edges_phenotype_phenotype": ['label1', 'label2'] +
                                 [field.name for field in EffectsPhenotypePhenotype._meta.get_fields()][3:]
}


# this gives us information which data type comes first in the column order
EDGE_ORDER = {'variant': 3, 'protein': 2, 'metabolite': 1, 'phenotype': 0}


def map_edge(edge: tuple, protein_set: set, pheno_set: set, metabo_set: set, variant_set: set) \
        -> tuple[str, str, bool] | None:
    """
    Map the source and target of an edge to the appropriate data type given an id and the cohort sets
    :param variant_set: set of unique variant IDs from the cohort data
    :param edge: Pandas Series containing the source and target of the edge
    :param protein_set: set of unique protein IDs from the cohort data
    :param pheno_set: set of unique phenotype labels from the cohort data
    :param metabo_set: set of unique metabolite names from the cohort data
    :return: Tuple containing the mapped source and target, and their respective data types
    """
    maps_and_types = [(protein_set, 'protein'), (pheno_set, 'phenotype'),
                      (metabo_set, 'metabolite'), (variant_set, 'variant')]

    mapped_source = mapped_target = source_type = target_type = None

    for cohort_set, data_type in maps_and_types:
        if not mapped_source:
            if edge[0] in cohort_set:
                source_type = data_type
                mapped_source = edge[0]

        if not mapped_target:
            if edge[1] in cohort_set:
                target_type = data_type
                mapped_target = edge[1]

        if source_type and target_type:
            break

    if not source_type or not target_type:
        return None

    swap = False
    if EDGE_ORDER[source_type] < EDGE_ORDER[target_type]:
        swap = True
    return source_type, target_type, swap


def process_file(edges: io.StringIO, protein_set: set, phenotype_set: set, metabolite_set: set,
                 variant_set: set) -> dict:
    """
    Process a chunk of edges by mapping and filtering the source and target of the edge, and creating SQLAlchemy objects
    that represent the edge to add to the database.
    Also returns the list of edge types that were added to the database
    :param edges: string buffer containing the edges
    :param protein_set: set of unique protein IDs from the cohort data
    :param phenotype_set: set of unique phenotype labels from the cohort data
    :param metabolite_set: set of unique metabolite names from the cohort data
    :param variant_set: set of unique variant IDs from the cohort data
    :return: Tuple containing the list of formatted edges and the list of edge types
    """
    all_edge_types = {edge_type: StringIO() for edge_type in DB_EDGES.values()}
    # ObJeCt oF TyPe SeT iS NoT JSON sErIaLiZaBlE
    protein_cols = set(protein_set)
    phenotype_cols = set(phenotype_set)
    metabolite_cols = set(metabolite_set)
    variant_cols = set(variant_set)

    def map_and_filter(edge: tuple) -> tuple[tuple[str, str], tuple[str, str], bool] | tuple[None, None, bool]:
        mapped, types, swap = map_edge(edge, protein_cols, phenotype_cols, metabolite_cols, variant_cols)
        return mapped, types if types else None, swap

    columns = edges.readline().strip().split(',')
    # we need to find the order of the columns and then map it to the table columns that we have for any given table
    for line in edges.readlines():
        if "nan" in line:
            continue
        line_split = line.strip().split(',')
        source, dest = line_split[1], line_split[2]
        source_map, dest_map, swap = map_and_filter((source, dest))
        if source_map is None or dest_map is None:
            continue
        edge_map = (source_map, dest_map)
        # swap the labels to match the order in the database
        if swap:
            line_split[1], line_split[2] = line_split[2], line_split[1]
        table = DB_EDGES[edge_map]
        # sort the line split depending on the order of the columns in the database needed for the table,
        # if we didn't do the test, we add a blank string
        new_line = []
        for col in DB_COLUMNS[table]:
            if col in columns:
                new_line.append(line_split[columns.index(col)])
            else:
                new_line.append("")
        new_line = line_split[0] + "," + ','.join(new_line) + "\n"

        all_edge_types[table].write(new_line)

    logger.debug("Finished processing edges")
    return all_edge_types


def copy_from_buffer(cursor, edge_type, edge_file):
    edge_file.seek(0)
    copy_sql = f"COPY {edge_type} FROM STDIN WITH (FORMAT CSV, DELIMITER ',', QUOTE '\"')"
    cursor.copy_expert(copy_sql, edge_file)


def copy_from_file(cursor, edge_type, name):
    file = f"/tmp/dyhealthnet-{name}/{edge_type}.csv"
    # check if the file is empty
    with open(file, 'r') as f:
        if f.readline() == '':
            return
    copy_sql = f"COPY {edge_type} FROM '{file}' WITH (FORMAT CSV, DELIMITER ',', QUOTE '\"')"
    cursor.execute(copy_sql)


def count_rows(buffer):
    buffer.seek(0)
    row_count = buffer.getvalue().count('\n')
    return row_count


def add_edges(conn, context_name, edges: list | dict) -> bool:
    """
    Add the given list of edges to the database in bulk
    :param context_name:
    :param conn: Django database connection
    :param edges: dictionary containing the edge types and the corresponding file buffers
    :return: bool - True if the edges were added successfully, False otherwise
    """
    cursor = conn.cursor()
    try:
        if settings.DEBUG:
            pass
            # clear the tables
            # for edge_type in edges.keys():
            #     cursor.execute(f"TRUNCATE TABLE {edge_type};")
            # conn.commit()
        # if edges are a list, then we are in low memory mode
        for edge_type in edges:
            cursor.execute(f"ALTER TABLE {edge_type} DISABLE TRIGGER ALL")
            if settings.LOW_MEMORY:
                copy_from_file(cursor, edge_type, context_name)
                logger.debug(f"Finished adding {edge_type} edges")
            else:
                copy_from_buffer(cursor, edge_type, edges[edge_type])
                edge_count = count_rows(edges[edge_type])
                if edge_count > 0:
                    conn.commit()
                    logger.debug(f"Finished adding {edge_count} {edge_type} edges")
                    # freeing up memory as soon as possible
                    del edges[edge_type]
                else:
                    logger.debug(f"No {edge_type} edges to add")
            cursor.execute(f"ALTER TABLE {edge_type} ENABLE TRIGGER ALL")
    except Exception as e:
        conn.rollback()
        logger.error(f"A problem occurred while adding edges: {e}")
        return False
    return True
