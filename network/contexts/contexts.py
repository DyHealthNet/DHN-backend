# Here I want to add the user-context to the database
import io
import json
import hashlib
from django.conf import settings
import logging
from network.contexts.edge_sorting import process_file, add_edges
import pandas as pd

logger = logging.getLogger('django')

operator_funcs = {
    'less': lambda df, col, val: df[col] < val,
    'more': lambda df, col, val: df[col] > val,
    'in': lambda df, col, val: df[col].isin(val),
    'equal': lambda df, col, val: df[col] == val
}

TABLE_STRUCTURE = """
CREATE TABLE IF NOT EXISTS {table_name} (
    id SERIAL PRIMARY KEY,
    label1 TEXT FOREIGN KEY REFERENCES {label_table1}(cohort_id),
    label2 TEXT FOREIGN KEY REFERENCES {label_table2}(cohort_id),
    np_p_value JSON,
    np_effect_size JSON,
    np_test_statistic TEXT,
    p_value JSON,
    effect_size JSON,
    test_statistic TEXT,
)
"""

EDGE_ORDER = {'variant': 3, 'protein': 2, 'metabolite': 1, 'phenotype': 0}


def create_context_id(patient_list: list[str], column_list: list[str]) -> str:
    """
    Creates a unique 10-character ID for a given set of patients.
    Retains the same ID for the same set of patients regardless of order.
    :param column_list: List of column names available for the context
    :param patient_list: List of patient IDs
    :return: Unique ID
    """
    sorted_patients = sorted(patient_list + column_list)
    combined_patients = ''.join(sorted_patients)
    hash_object = hashlib.sha256(combined_patients.encode('utf-8'))
    unique_id = hash_object.hexdigest()[:10]
    return unique_id


def subset_patients(variables: pd.DataFrame, params: dict) -> pd.DataFrame:
    masks = []
    inside_conn = params['connect']['inside']
    outside_conn = params['connect']['outside']

    if inside_conn not in ['and', 'or'] or outside_conn not in ['and', 'or']:
        raise ValueError(f"Unsupported connection types: {inside_conn}, {outside_conn}")

    outer_start = outside_conn == 'and'

    for param in params['conditions'].values():
        current_mask = pd.Series([not outer_start] * len(variables), index=variables.index)
        for con in param:
            op = con['operator']
            col = con['column']
            val = con['value']

            if op not in operator_funcs:
                raise ValueError(f"Unsupported operator: {op}")

            condition = operator_funcs[op](variables, col, val)

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


def get_rows(conn, table_name):
    cursor = conn.cursor()
    cursor.execute(f"SELECT id, label1, label2, pval, effsize FROM {table_name}")
    existing_rows = cursor.fetchall()
    cursor.close()
    return existing_rows


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

        cursor.execute(TABLE_STRUCTURE.format(
            table_name=f"{table_name}_{context_name}",
            label_table1=f"cohort_{first_table}",
            label_table2=f"cohort_{second_table}"
        ))
        new_names[table_name] = f"{table_name}_{context_name}"
    logger.debug(f"Created tables for context {context_name}")
    conn.commit()
    return new_names


def insert_context(scores: pd.DataFrame, context_name: str, **kwargs):
    all_scores = io.StringIO()
    conn = settings.CONN_POOL.getconn()
    scores.to_csv(all_scores, sep=',', index=True, header=False, lineterminator='\n')
    all_scores.seek(0)

    # sort the file buffer into individual edge tables
    tables = process_file(all_scores, **kwargs)

    # create all needed tables in the database
    new_names = create_context_tables(list(tables.keys()), context_name, conn)
    # change the names of tables based on new names
    tables = {new_names[k]: v for k, v in tables.items()}

    # insert the data into the database
    add_edges(conn, tables)


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
