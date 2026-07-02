# Here I want to add the user-context to the database
import io
import json
import os.path

from django.conf import settings
from django.db import connection
import logging

from network.contexts.edge_sorting import add_edges, dataframe_to_buffer_arrow
from network.models import Context
from django.db.models import Max
import pandas as pd

from network.utils.db_utils import get_context
from network.utils.utils import extract_var_id

logger = logging.getLogger('network')

OPERATORS = {
    'less than (<)': lambda df, col, val: df[col] < float(val),
    'more than (>)': lambda df, col, val: df[col] > float(val),
    'in': lambda df, col, val: df[col].astype(str).isin([str(v) for v in val]),
    'equals (=)': lambda df, col, val: df[col].astype(str) == str(val),
    'in range': lambda df, col, val: (df[col] >= float(val[0])) & (df[col] <= float(val[1])),
}


def _create_context_table(table_name: str, conn):
    cursor = conn.cursor()
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id SERIAL PRIMARY KEY,
            node_id_1 VARCHAR REFERENCES nodes(node_id),
            node_id_2 VARCHAR REFERENCES nodes(node_id),
            p_value DOUBLE PRECISION,
            effect_size DOUBLE PRECISION,
            test_type VARCHAR
        )
    """)
    conn.commit()
    logger.debug(f"Created context table {table_name}")


def delete_context_tables(context_id: str):
    conn = connection
    cursor = conn.cursor()
    cursor.execute(f"""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_name LIKE 'edges_%_{context_id}'
    """)
    tables = cursor.fetchall()
    logger.debug(f"Deleting {len(tables)} tables for context {context_id}")
    for table in tables:
        cursor.execute(f"DROP TABLE {table[0]}")
    conn.commit()


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

    if len(params['conditions']) == 0:
        return variables

    outer_start = outside_conn == 'and'

    for param in params['conditions'].values():
        current_mask = pd.Series([not outer_start] * len(variables), index=variables.index)
        for con in param:
            op = con['operator']
            col = con['column']
            val = con['value']

            # This is to handle user-friendly JSON input
            if isinstance(val, dict):
                val = val.get('value')

            if isinstance(val, list) and all(isinstance(v, dict) for v in val):
                val = [v.get('value') for v in val]

            col = extract_var_id(col)

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

    return variables[overall_mask]


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


def insert_context(scores: pd.DataFrame, context_name: str, test_type: str) -> bool:
    """Insert modina context scores into a single flat-schema table.

    scores columns: label1, label2, raw-P, raw-E, test_type
    table name:     edges_{test_type}_{context_name}
    """
    conn = connection
    table_name = f"edges_{test_type}_{context_name}"
    _create_context_table(table_name, conn)

    edges = scores[['label1', 'label2', 'raw-P', 'raw-E', 'test_type']].copy()
    edges = edges.rename(columns={
        'label1': 'node_id_1',
        'label2': 'node_id_2',
        'raw-P': 'p_value',
        'raw-E': 'effect_size',
    })

    if settings.LOW_MEMORY:
        csv_path = f"/tmp/dyhealthnet-{context_name}/{table_name}.csv"
        if not os.path.exists(csv_path):
            buf = dataframe_to_buffer_arrow(edges)
            with open(csv_path, 'wb') as f:
                f.write(buf.getvalue())
        edge_info = [table_name]
    else:
        edge_info = {table_name: dataframe_to_buffer_arrow(edges)}

    return add_edges(conn, context_name, edge_info)


def context_subset(request, data):
    # If the user requests a context, subset the data based on the context
    if request.GET.get("contextValue") and request.user.is_authenticated:
        # subset data based on context
        context = get_context(request.user, request.GET.get('contextValue'))
        if not context:
            return None

        df = subset_patients(data, context.params)
    else:
        df = data.copy()
    return df

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
