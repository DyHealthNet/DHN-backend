import io
import sys
from io import StringIO
import logging
from django.conf import settings


logger = logging.getLogger("django")


DB_EDGES = {
    ('phenotype', 'variant'): "effects_variant_phenotype",
    ('variant', 'phenotype'): "effects_variant_phenotype",
    ('variant', 'metabolite'): "effects_variant_metabolite",
    ('metabolite', 'variant'): "effects_variant_metabolite",
    ('variant', 'protein'): "effects_variant_protein",
    ('protein', 'variant'): "effects_variant_protein",

    ('protein', 'protein'): "effects_protein_protein",
    ('protein', 'phenotype'): "effects_protein_phenotype",
    ('phenotype', 'protein'): "effects_protein_phenotype",
    ('protein', 'metabolite'): "effects_protein_metabolite",
    ('metabolite', 'protein'): "effects_protein_metabolite",

    ('metabolite', 'metabolite'): "effects_metabolite_metabolite",
    ('metabolite', 'phenotype'): "effects_metabolite_phenotype",
    ('phenotype', 'metabolite'): "effects_metabolite_phenotype",

    ('phenotype', 'phenotype'): "effects_phenotype_phenotype",
}

# this gives us information which data type comes first in the column order
EDGE_ORDER = {'variant': 3, 'protein': 2, 'metabolite': 1, 'phenotype': 0}


def swap_labels(s, label1, label2):
    index1 = s.find(label1)
    index2 = s.find(label2)

    if index1 == -1 or index2 == -1:
        return s

    before = s[:min(index1, index2)]
    between = s[min(index1 + len(label1), index2 + len(label2)):max(index1, index2)]
    after = s[max(index1 + len(label1), index2 + len(label2)):]

    if index1 < index2:
        return before + label2 + between + label1 + after
    return before + label1 + between + label2 + after


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

    def map_and_filter(edge: tuple) -> tuple[tuple[str, str], tuple[str, str], bool] | tuple[None, None, bool]:
        mapped, types, swap = map_edge(edge, protein_set, phenotype_set, metabolite_set, variant_set)
        return mapped, types if types else None, swap

    edges.readline()
    for line in edges.readlines():
        if "nan" in line:
            continue
        line_split = line.split(',')
        source, dest = line_split[1], line_split[2]
        source_map, dest_map, swap = map_and_filter((source, dest))
        if source_map is None or dest_map is None:
            continue
        edge_map = (source_map, dest_map)
        # swap the labels to match the order in the database
        if swap:
            line = swap_labels(line, source, dest)
        all_edge_types[DB_EDGES[edge_map]].write(line)

    logger.debug("Finished processing edges")
    return all_edge_types


def format_edges(session, edges, protein_set: set, phenotype_set: set, metabolite_set: set,
                 variant_set: set) -> None:
    """
    Format the edges and add them to the database in chunks. Deletes the formatted edges after adding them to the
    database to save memory. The chunk size can be adjusted in the settings.
    :param session: SQLAlchemy session
    :param edges: Pandas DataFrame containing the edges
    :param protein_set: set of unique protein IDs from the cohort data
    :param phenotype_set: set of unique phenotype labels from the cohort data
    :param metabolite_set: set of unique metabolite names from the cohort data
    :param variant_set: set of unique variant IDs from the cohort data
    :return: None
    """
    formatted_edges = process_file(edges, protein_set, phenotype_set, metabolite_set, variant_set)

    add_success = add_edges(session, formatted_edges)
    del formatted_edges
    if not add_success:
        logger.error("There was a problem adding the edges to the database, exiting...")
        return
    logger.info(f"File added successfully")

    # for edge_type, count in num_edge_types.items():
    #    logger.debug(f"Added {count} edges of type {edge_type.__name__}")
    return


def copy_from_buffer(cursor, edge_type, edge_file):
    edge_file.seek(0)
    copy_sql = f"COPY {edge_type} FROM STDIN WITH (FORMAT CSV, DELIMITER ',', QUOTE '\"')"
    cursor.copy_expert(copy_sql, edge_file)


def count_rows(buffer):
    buffer.seek(0)
    row_count = buffer.getvalue().count('\n')
    return row_count


def add_edges(conn, edges: dict) -> bool:
    """
    Add the given list of edges to the database in bulk
    :param conn: Django database connection
    :param edges: dictionary containing the edge types and the corresponding file buffers
    :return: bool - True if the edges were added successfully, False otherwise
    """
    cursor = conn.connection().connection.cursor()
    try:
        if settings.DEBUG:
            # clear the tables
            for edge_type in DB_EDGES.values():
                cursor.execute(f"TRUNCATE TABLE {edge_type}")
        for edge_type, edge_file in edges.items():
            if edge_file is None:
                continue
            copy_from_buffer(cursor, edge_type, edge_file)
            edge_count = count_rows(edge_file)
            if edge_count > 0:
                conn.commit()
                logger.debug(f"Finished adding {edge_count} {edge_type} edges")
    except Exception as e:
        conn.rollback()
        logger.error(f"A problem occurred while adding edges: {e}")
        return False
    return True
