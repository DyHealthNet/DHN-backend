# Here I want to add the user-context to the database
import io
import json
import hashlib
import os.path

from django.conf import settings
from django.db import connection
import logging

from network import models
from network.contexts.edge_sorting import process_file, add_edges, DB_COLUMNS
from network.models import Context
from django.db.models import Max
import pandas as pd

logger = logging.getLogger('network')

OPERATORS = {
    'less than (<)': lambda df, col, val: df[col] < val,
    'more than (>)': lambda df, col, val: df[col] > val,
    'in': lambda df, col, val: df[col].isin(val),
    'equals (=)': lambda df, col, val: df[col] == val,
    'in range': lambda df, col, val: (df[col] >= val[0]) & (df[col] <= val[1]),
}


EDGE_ORDER = {'variant': 3, 'protein': 2, 'metabolite': 1, 'phenotype': 0}


def create_table_structure(table_name, context_id, label_table1, label_table2):
    column_info = DB_COLUMNS[table_name]
    context_table_name = f"{table_name}_{context_id}"
    table_structure = f"""
    CREATE TABLE IF NOT EXISTS {context_table_name} (
    id SERIAL PRIMARY KEY,
    label1 VARCHAR REFERENCES {label_table1}(cohort_id),
    label2 VARCHAR REFERENCES {label_table2}(cohort_id),
    """
    for column in column_info[2:]:
        table_structure += f"{column} DOUBLE PRECISION,\n"

    table_structure = table_structure[:-2] + ");"
    return table_structure


def create_context_id() -> str:
    """
    Retrieves the biggest context_id from the context table and returns a new unique id
    """
    max_id = Context.objects.aggregate(Max('context_id'))['context_id__max']
    if max_id is None:
        max_id = 0
    unique_id = str(int(max_id) + 1)
    return unique_id


def subset_patients(variables: pd.DataFrame, params: dict) -> pd.DataFrame:
    masks = []
    inside_conn = params['connect']['inside'].lower()
    outside_conn = params['connect']['outside'].lower()

    if inside_conn not in ['and', 'or'] or outside_conn not in ['and', 'or']:
        raise ValueError(f"Unsupported connection types: {inside_conn}, {outside_conn}")

    outer_start = outside_conn == 'and'

    for param in params['conditions'].values():
        current_mask = pd.Series([not outer_start] * len(variables), index=variables.index)
        for con in param:
            op = con['operator']
            col = con['column']
            val = con['value']

            # for now, extract the column from the stuff in the brackets
            if '(' in col:
                col = col.split('(')[1].split(')')[0]
            elif '/' in col:
                col = col.split('/')[0].strip()

            if op not in OPERATORS:
                raise ValueError(f"Unsupported operator: {op}")

            if col not in variables.columns:
                raise ValueError(f"Column {col} not in available variables")

            condition = OPERATORS[op](variables, col, val)

            if inside_conn == 'and':
                current_mask &= condition
            elif inside_conn == 'or':
                current_mask |= condition

        masks.append(current_mask)

    overall_mask = pd.Series([outer_start] * len(variables), index=variables.index)
    for mask in masks:
        if outside_conn == 'and':
            overall_mask &= mask
        elif outside_conn == 'or':
            overall_mask |= mask

    return variables[overall_mask].copy()


def update_buffer(updates, conn, table_name: str = 'edges'):
    cursor = conn.cursor()

    cursor.execute(f"""
        CREATE TEMPORARY TABLE temp_updates_{table_name} (
            id INTEGER PRIMARY KEY,
            pval JSON,
            effsize JSON
        ) ON COMMIT DROP
    """)

    buffer = io.StringIO()
    for id, (pval, effsize) in updates.items():
        # escape double quotes in JSON strings so that internal commas don't break the CSV
        pval_str = json.dumps(pval).replace('"', '""')
        effsize_str = json.dumps(effsize).replace('"', '""')

        buffer.write(f'{id},"{pval_str}","{effsize_str}"\n')

    buffer.seek(0)

    cursor.copy_expert("COPY temp_updates (id, pval, effsize) FROM STDIN WITH CSV", buffer)

    cursor.execute(f"""
        UPDATE {table_name}
        SET pval = temp_updates_{table_name}.pval, effsize = temp_updates_{table_name}.effsize
        FROM temp_updates_{table_name}
        WHERE {table_name}.id = temp_updates_{table_name}.id
    """)

    conn.commit()


def create_context_tables(needed_tables: list[str], context_name: str, conn):
    cursor = conn.cursor()
    new_names = {}
    for table_name in needed_tables:
        first_table = table_name.split('_')[1]
        second_table = table_name.split('_')[2]
        if EDGE_ORDER[first_table] < EDGE_ORDER[second_table]:
            first_table, second_table = second_table, first_table

        cursor.execute(create_table_structure(table_name, context_name,
                                              f"cohort_{first_table}",
                                              f"cohort_{second_table}"))

        new_names[table_name] = f"{table_name}_{context_name}"
    logger.debug(f"Created tables for context {context_name}")
    conn.commit()
    return new_names


def insert_context(scores: pd.DataFrame, context_name: str, **kwargs):
    conn = connection

    # sort the file buffer into individual edge tables
    tables = process_file(scores, **kwargs)

    # create all needed tables in the database
    new_names = create_context_tables(list(tables.keys()), context_name, conn)

    # save the tables to CSV files
    if settings.LOW_MEMORY:
        logger.debug("In low memory mode, saving tables to CSV files")
        for k, v in tables.items():
            if os.path.exists(f"/tmp/dyhealthnet-{context_name}/{new_names[k]}.csv"):
                continue
            with open(f"/tmp/dyhealthnet-{context_name}/{new_names[k]}.csv", 'w') as f:
                f.write(v.getvalue())
        edge_info = list(new_names.values())
    else:
        edge_info = {new_names[k]: v for k, v in tables.items()}

    # insert the data into the database
    add_success = add_edges(conn, context_name, edge_info)
    return add_success


# Possible future implementation for updating multiple tables concurrently
# def update_multiple_tables(conn_pool):
#     # List of updates, each tuple contains (table_name, updates)
#     updates_data = [
#         ('table1', updates_for_table1),
#         ('table2', updates_for_table2),
#     ]
#
#     # Using ThreadPoolExecutor to run updates concurrently
#     with ThreadPoolExecutor() as executor:
#         futures = []
#         for table_name, updates in updates_data:
#             # Create a new connection for each table update
#             conn = conn_pool.getconn()
#             futures.append(executor.submit(update_table, table_name, updates, conn))
#
#         # Wait for all updates to complete
#         for future in futures:
#             future.result()
