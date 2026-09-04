# Here I want to add the user-context to the database
import io
import json
import os.path

from django.conf import settings
from django.core.cache import cache
from django.db import connection
import logging

from network.contexts.edge_sorting import add_edges, dataframe_to_buffer_arrow
from network.models import Context
from django.db.models import Max
import pandas as pd

from network.utils.db_utils import get_context
from network.utils.utils import extract_var_id, resolve_layer_selection

logger = logging.getLogger('network')

OPERATORS = {
    'less than (<)': lambda df, col, val: df[col] < float(val),
    'more than (>)': lambda df, col, val: df[col] > float(val),
    'in': lambda df, col, val: df[col].astype(str).isin([str(v) for v in val]),
    'equals (=)': lambda df, col, val: df[col].astype(str) == str(val),
    'unequals (!=)': lambda df, col, val: df[col].astype(str) != str(val),
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

    # create_context_id() assigns max(existing context_id) + 1, so once this context
    # is gone that same numeric id can be handed to a future context. Without this,
    # its still-live participants_context_/variables_context_/context_node_ids_ cache
    # entries would be silently served to that unrelated future context until their
    # timeout elapses.
    cache.delete_many([
        f'participants_context_{context_id}',
        f'variables_context_{context_id}',
        f'context_node_ids_{context_id}',
    ])


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


def restrict_variables(data: pd.DataFrame, selected_variables, variable_layers=None, variable_sub_layers=None,
                       missingness_variables=None, missingness_layers=None, missingness_sub_layers=None,
                       layers=None, layer_subgroups=None, removed_variable_ids=None) -> pd.DataFrame:
    """
    Restrict `data` to the context's selected variable columns, and (opt-in) drop rows
    missing a completeness-checked one. This is the sole source of truth for which
    variables/rows are actually part of a context -- Context.params has no top-level
    `layers`/`subLayers` selection field at all; the frontend's variable/missingness
    pickers work directly off `variables`/`variablesLayers`/`variablesSubLayers` (and the
    missingness equivalents) below, which is also all that's ever persisted.

    Both the variable selection itself and its missingness check are expressed the same
    compact way, resolved via resolve_layer_selection() against `layers`/`layer_subgroups`
    (group->labels dicts DataManager provides):
    - `selected_variables` / `missingness_variables`: explicit display identifiers
      (individual exceptions, or the whole set if the frontend never had layer metadata to
      compact it) -- mapped back to raw column ids via extract_var_id.
    - `variable_layers` / `variable_sub_layers` and `missingness_layers` /
      `missingness_sub_layers`: whole (sub)layers that were fully selected/checked, stored
      compactly by name instead of enumerating every variable in them -- self-sufficient,
      since the frontend only ever compacts a (sub)layer reference when literally every
      variable it refers to is selected.

    `removed_variable_ids` (raw column ids) subtracts out variables moDiNA flagged as not
    producing a meaningful statistical result (Context.params['removedVariables'], written
    by create_context_wrapper()) -- callers that want the context's saved selection as-is
    (context creation/filtering; a moDiNA differential comparison, which needs both contexts'
    original selections aligned so moDiNA's own reconciliation can resolve any per-context
    removal asymmetry -- see network/views/modina.py's _resolve_context_data) simply omit it;
    callers reflecting what's actually usable in a single context on its own (the overview
    page) pass it.

    Any row with a missing value in one of the resolved missingness columns is dropped,
    but every selected-variable column is still kept for the rows that survive, so the
    resulting complete-case sample set is used for the whole context, not just for the
    checked subset. Returns `data` unchanged if no variable selection was provided at all.
    """
    selected_ids = set()
    if selected_variables:
        selected_ids.update(extract_var_id(var) for var in selected_variables)
    selected_ids.update(resolve_layer_selection(variable_layers, variable_sub_layers, layers, layer_subgroups))

    if not selected_ids:
        return data
    if removed_variable_ids:
        selected_ids -= set(removed_variable_ids)
    keep_columns = [col for col in data.columns if col in selected_ids]
    if not keep_columns:
        raise ValueError('None of the selected variables are available.')
    data = data[keep_columns]

    keep_set = set(keep_columns)
    check_columns = set()

    if missingness_variables:
        missingness_ids = {extract_var_id(var) for var in missingness_variables}
        check_columns.update(col for col in keep_columns if col in missingness_ids)

    check_columns.update(
        col for col in resolve_layer_selection(missingness_layers, missingness_sub_layers, layers, layer_subgroups)
        if col in keep_set
    )

    if check_columns:
        data = data.dropna(subset=list(check_columns))
    return data


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


def load_context_scores(context_id: str, test_type: str) -> pd.DataFrame:
    """
    Load a context's already-computed association scores back out of its
    edges_{test_type}_{context_id} table, reshaped into the label1/label2/raw-P/raw-E/test_type
    frame moDiNA's differential-network functions expect -- the inverse of insert_context's
    rename. Used to build a differential network from two existing contexts without recomputing
    their (already corrected) association scores.
    """
    table_name = f"edges_{test_type}_{context_id}"
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT node_id_1, node_id_2, p_value, effect_size, test_type FROM {table_name}")
        rows = cursor.fetchall()
    return pd.DataFrame(rows, columns=['label1', 'label2', 'raw-P', 'raw-E', 'test_type'])


def _apply_context_restriction(df, context, layers, layer_subgroups):
    """
    Applies the missingness-driven row/column restriction a context defines (the "no
    missing samples" per-variable check set up in ContextSetup.vue) on top of the
    conditions-based `subset_patients` filter -- the same restrict_variables() call
    GetTableView uses to compute the context's true participant count. Without this,
    a context whose participant reduction comes mainly from that missingness check
    (rather than explicit rule conditions) would show its unfiltered row count in every
    plot despite reporting the correct, smaller count in the context summary.
    """
    try:
        return restrict_variables(
            df, context.params.get('variables'), context.params.get('variablesLayers'),
            context.params.get('variablesSubLayers'), context.params.get('missingnessVariables'),
            context.params.get('missingnessLayers'), context.params.get('missingnessSubLayers'),
            layers, layer_subgroups, context.params.get('removedVariables'),
        )
    except ValueError:
        # selected variables no longer resolve to any real column - fall back to the
        # rule-only subset rather than erroring out a plot
        return df


def context_subset(request, data, layers=None, layer_subgroups=None):
    # If the user requests a context, subset the data based on the context
    if request.GET.get("contextValue") and request.user.is_authenticated:
        # subset data based on context
        context = get_context(request.user, request.GET.get('contextValue'))
        if not context:
            return None

        df = subset_patients(data, context.params)
        df = _apply_context_restriction(df, context, layers, layer_subgroups)
    else:
        df = data.copy()
    return df


def context_compare_subsets(request, data, layers=None, layer_subgroups=None):
    """
    Resolves two contexts at once (contextValue1/contextValue2 GET params) and subsets
    `data` to each one's own participants via the same subset_patients() +
    restrict_variables() filtering context_subset() uses for one context. Shared by both
    callers that need a two-context comparison: context_compare_subset() (below)
    concatenates the two for callers that want one merged, context-grouped frame;
    GetDataHeatmapView keeps them separate since it needs each context's own contingency
    table before combining them into a difference.
    Returns (subset1, subset2, context1, context2), or (None, None, None, None) if the user
    isn't authenticated or either context isn't found.
    """
    if not request.user.is_authenticated:
        return None, None, None, None
    value1 = request.GET.get('contextValue1')
    value2 = request.GET.get('contextValue2')
    if not value1 or not value2:
        return None, None, None, None
    context1 = get_context(request.user, value1)
    context2 = get_context(request.user, value2)
    if not context1 or not context2:
        return None, None, None, None

    subset1 = subset_patients(data, context1.params)
    subset1 = _apply_context_restriction(subset1, context1, layers, layer_subgroups)
    subset2 = subset_patients(data, context2.params)
    subset2 = _apply_context_restriction(subset2, context2, layers, layer_subgroups)
    return subset1, subset2, context1, context2


def context_compare_subset(request, data, layers=None, layer_subgroups=None):
    """
    Tags each of context_compare_subsets()'s two subsets with a synthetic '__context__'
    column holding that context's display name, and concatenates them into one frame. A
    participant satisfying both contexts' filters appears once per context, same as
    querying each separately would give. Lets callers (plotDataBoxPlot/plotDataLine) reuse
    their existing c-grouping aggregation unchanged, with context as the group, instead of a
    bespoke merge path. Returns (combined_df, context1, context2), or (None, None, None).
    """
    subset1, subset2, context1, context2 = context_compare_subsets(request, data, layers, layer_subgroups)
    if subset1 is None:
        return None, None, None

    subset1 = subset1.copy()
    subset2 = subset2.copy()
    subset1['__context__'] = context1.params.get('contextName', 'Context 1')
    subset2['__context__'] = context2.params.get('contextName', 'Context 2')
    combined = pd.concat([subset1, subset2], ignore_index=True)
    return combined, context1, context2

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
