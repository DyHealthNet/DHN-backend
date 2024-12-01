import io
import sys
import time
import timeit
from io import StringIO
import logging
import pyarrow as pa
import pyarrow.csv as pc

import numpy as np
import pandas as pd
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


def dataframe_to_buffer_arrow(df):
    buffer = io.BytesIO()
    df = df.reset_index()
    table = pa.Table.from_pandas(df, preserve_index=False)
    pc.write_csv(table, buffer, write_options=pc.WriteOptions(include_header=False, quoting_style=None))
    buffer.seek(0)
    return buffer


def process_file(edges: pd.DataFrame, protein_set: set, phenotype_set: set, metabolite_set: set,
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
    logger.debug("Starting processing edges")
    # ObJeCt oF TyPe SeT iS NoT JSON sErIaLiZaBlE
    combined_mapping = {
        **{item: 'protein' for item in set(protein_set)},
        **{item: 'phenotype' for item in set(phenotype_set)},
        **{item: 'metabolite' for item in set(metabolite_set)},
        **{item: 'variant' for item in set(variant_set)},
    }

    # Precompute as much as possible to avoid recomputing in the loop
    columns = edges.columns
    column_index_map = {col: idx for idx, col in enumerate(columns)}
    # some columns might be missing, so we need to fill them with None
    table_column_indices = {
        table: [column_index_map[col] if col in column_index_map else None for col in DB_COLUMNS[table]]
        for table in DB_COLUMNS
    }

    edges["map1"] = edges["label1"].map(combined_mapping)
    edges["map2"] = edges["label2"].map(combined_mapping)

    edges = edges.dropna(subset=["map1", "map2"])

    # Swap label1 and label2 to ensure db order
    swap_condition = edges["map1"].map(EDGE_ORDER) < edges["map2"].map(EDGE_ORDER)
    edges.loc[swap_condition, ["label1", "label2"]] = edges.loc[swap_condition, ["label2", "label1"]].values

    # Add the table column based on the tuple of mapped values
    edges["table"] = list(zip(edges["map1"], edges["map2"]))
    edges["table"] = edges["table"].map(DB_EDGES)

    # Drop the intermediate mapping columns
    edges = edges.drop(columns=["map1", "map2"])

    result_dfs = {}
    for table, group in edges.groupby("table"):
        indices = table_column_indices[table]

        new_df = pd.DataFrame(index=group.index, columns=range(len(indices)))

        for col_idx, df_col_idx in enumerate(indices):
            if df_col_idx is not None:
                new_df[col_idx] = group.iloc[:, df_col_idx]
            else:
                new_df[col_idx] = None

        result_dfs[table] = new_df

    all_edge_types = {edge_type: dataframe_to_buffer_arrow(result_dfs[edge_type]) for edge_type in result_dfs}
    # update all_edge_types with missing edge types to avoid key errors
    for edge_type in DB_EDGES.values():
        if edge_type not in all_edge_types:
            all_edge_types[edge_type] = io.BytesIO()

    logger.debug("Finished processing edges")
    return all_edge_types


def copy_from_buffer(cursor, edge_type, edge_file):
    edge_file.seek(0)
    copy_sql = f"COPY {edge_type} FROM STDIN WITH (FORMAT CSV, DELIMITER ',', QUOTE '\"')"
    cursor.copy_expert(copy_sql, edge_file)


def copy_from_file(cursor, edge_type, name):
    file = f"/tmp/dyhealthnet-{name}/{edge_type}.csv"
    with open(file, 'r') as f:
        copy_sql = f"COPY {edge_type} FROM STDIN WITH (FORMAT CSV, DELIMITER ',', QUOTE '\"')"
        cursor.copy_expert(copy_sql,f)


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
                else:
                    logger.debug(f"No {edge_type} edges to add")
            cursor.execute(f"ALTER TABLE {edge_type} ENABLE TRIGGER ALL")
    except Exception as e:
        conn.rollback()
        logger.error(f"A problem occurred while adding edges: {e}")
        return False
    del edges
    return True
