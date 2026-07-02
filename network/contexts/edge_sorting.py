import io
import logging

import pyarrow as pa
import pyarrow.csv as pc

from django.conf import settings

logger = logging.getLogger("network")


def dataframe_to_buffer_arrow(df):
    buffer = io.BytesIO()
    df = df.reset_index()
    table = pa.Table.from_pandas(df, preserve_index=False)
    pc.write_csv(table, buffer, write_options=pc.WriteOptions(include_header=False, quoting_style=None))
    buffer.seek(0)
    return buffer


def copy_from_buffer(cursor, edge_type, edge_file):
    edge_file.seek(0)
    copy_sql = f"COPY {edge_type} FROM STDIN WITH (FORMAT CSV, DELIMITER ',', QUOTE '\"')"
    cursor.copy_expert(copy_sql, edge_file)


def copy_from_file(cursor, edge_type, name):
    file = f"/tmp/dyhealthnet-{name}/{edge_type}.csv"
    with open(file, 'r') as f:
        copy_sql = f"COPY {edge_type} FROM STDIN WITH (FORMAT CSV, DELIMITER ',', QUOTE '\"')"
        cursor.copy_expert(copy_sql, f)


def count_rows(buffer):
    buffer.seek(0)
    row_count = buffer.getvalue().count(b'\n')
    return row_count


def add_edges(conn, context_name, edges: list | dict) -> bool:
    """
    Add the given edges to the database in bulk via COPY.
    :param conn: Django database connection
    :param context_name: used only for the LOW_MEMORY file path
    :param edges: dict of {table_name: BytesIO buffer} or list of table names (LOW_MEMORY mode)
    :return: True if successful
    """
    cursor = conn.cursor()
    try:
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
