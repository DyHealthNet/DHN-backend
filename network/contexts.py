# Here I want to add the user-context to the database
import io
import json
import hashlib

import pandas as pd

operator_funcs = {
    'less': lambda df, col, val: df[col] < val,
    'more': lambda df, col, val: df[col] > val,
    'in': lambda df, col, val: df[col].isin(val),
    'equal': lambda df, col, val: df[col] == val
}


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

    return variables[overall_mask]


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
