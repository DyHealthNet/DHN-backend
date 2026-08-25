import csv
import logging
import os
from collections import defaultdict

import environ
import numpy as np
import pandas as pd

logger = logging.getLogger('network')


def _parse_list_env(env, name):
    """Parse a comma-separated env var into a list of stripped, non-empty strings."""
    raw = env(name, default="")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _parse_aligned_list_env(env, name, expected_length):
    """
    Like _parse_list_env, but for optional lists that must line up positionally with
    the required ones: unset entirely -> all entries empty; set -> entries are not
    stripped of blanks, since a blank entry deliberately means "skip this attribute
    for this source".
    """
    raw = env(name, default="")
    if not raw:
        return [""] * expected_length
    return [item.strip() for item in raw.split(",")]


def _infer_separator(path):
    """Infer the CSV separator from a file's extension (.tsv -> tab, else comma)."""
    return "\t" if path.lower().endswith(".tsv") else ","


def _resolve_path(path, root):
    """Join a relative path with `root` (if set); absolute paths are returned unchanged."""
    if root and not os.path.isabs(path):
        return os.path.join(root, path)
    return path


# Types accepted by modina's _separate_types().
VALID_VARIABLE_TYPES = {"ordinal", "nominal", "binary", "continuous"}

# Common alternative spellings, mapped to the canonical modina type they represent.
# Deliberately no "time" alias: those columns hold HH:MM:SS clock-time strings (e.g.
# '11:11:18'), not plain numbers, so treating them as continuous fails to parse as
# float. They're dropped, same as any other unrecognized type.
TYPE_ALIASES = {
    "boolean": "binary",
    "categorical": "nominal",
    "float": "continuous",
    "integer": "continuous",
}

ALL_VALID_TYPES = VALID_VARIABLE_TYPES | set(TYPE_ALIASES)

# Dtype passed to read_csv per modina variable type. Low-cardinality types are read
# as 'category' (1 byte/code instead of a full int64/object per cell); continuous
# stays float64 so reading doesn't change downstream numeric precision.
TYPE_TO_DTYPE = {
    "ordinal": "category",
    "nominal": "category",
    "binary": "category",
    "continuous": "float64",
}


def _rename_meta_columns(meta, meta_path, label_column, type_column, description_column, group_column,
                          subgroup_column=None):
    """
    Rename label_column/type_column/description_column/group_column/subgroup_column to
    their canonical names ('label'/'type'/'description'/'group'/'subgroup') in a single
    atomic `.rename()` call, rather than one sequential rename per attribute. Each is
    resolved against `meta`'s *original* column names at once, so no attribute can
    clobber a source column another attribute still needs regardless of which order
    they're processed in

    type_column/description_column/group_column/subgroup_column may each be either the
    name of an existing column or a literal value applied to every row (e.g. a fixed
    group name for a source with no per-row grouping of its own); a falsy value skips
    that attribute entirely. label_column must always be an existing column (checked by
    the caller before this is called).

    Raises if two attributes are configured to the same source column with different
    targets (ambiguous - a column can't become two different things, so there's no
    safe default).

    If a target name ('label'/'type'/'description'/'group'/'subgroup') is otherwise
    already occupied by an existing column that no attribute claims, that column is
    unrelated to this source's configuration - it's dropped, logging a warning, before
    the rename/literal assignment runs. Left in place it would otherwise either silently
    collide with the renamed column (pandas allows duplicate column names) or be
    silently overwritten by a literal value with no indication anything happened.
    """
    if type_column not in meta.columns and type_column.lower() not in ALL_VALID_TYPES:
        logger.warning(
            f"{meta_path}: '{type_column}' is neither a column in this meta file nor one of "
            f"the recognized types {sorted(ALL_VALID_TYPES)}."
        )

    targets = {"label": label_column, "type": type_column,
               "description": description_column, "group": group_column,
               "subgroup": subgroup_column}

    rename_map = {}
    literals = {}
    for target, column_or_literal in targets.items():
        if not column_or_literal:
            continue
        if column_or_literal not in meta.columns:
            literals[target] = column_or_literal
            continue
        if column_or_literal in rename_map and rename_map[column_or_literal] != target:
            raise ValueError(
                f"{meta_path}: column '{column_or_literal}' is configured as both "
                f"'{rename_map[column_or_literal]}' and '{target}' - each column can "
                f"only be used for one attribute."
            )
        rename_map[column_or_literal] = target

    claimed_targets = set(rename_map.values()) | set(literals.keys())
    unclaimed = (set(meta.columns) & claimed_targets) - set(rename_map.keys())
    if unclaimed:
        logger.warning(
            f"{meta_path}: dropping this file's own unrelated column(s) {sorted(unclaimed)}, "
            f"which would otherwise collide with a renamed or literal-assigned column of "
            f"the same name."
        )
        meta = meta.drop(columns=list(unclaimed))

    meta = meta.rename(columns=rename_map)
    for target, literal in literals.items():
        meta[target] = literal
    return meta


def _normalize_meta_types(meta, meta_path):
    """
    Lowercase the 'type' column and map alternative spellings (TYPE_ALIASES, e.g.
    'boolean' -> 'binary', 'categorical' -> 'nominal', 'float'/'integer'/'time' ->
    'continuous') to the canonical types modina expects. Rows whose type still isn't
    one of VALID_VARIABLE_TYPES are dropped, since modina cannot assign them to a test
    and the matching data column never needs to be read.
    """
    meta = meta.copy()
    normalized = meta["type"].astype(str).str.lower().map(lambda t: TYPE_ALIASES.get(t, t))
    meta["type"] = normalized

    invalid_mask = ~normalized.isin(VALID_VARIABLE_TYPES)
    if invalid_mask.any():
        dropped = meta.loc[invalid_mask, ["label", "type"]]
        logger.info(
            f"{meta_path}: dropping {len(dropped)} variable(s) with unrecognized type "
            f"(expected one of {sorted(VALID_VARIABLE_TYPES)} or aliases {sorted(TYPE_ALIASES)}): "
            f"{list(dropped.itertuples(index=False, name=None))}"
        )
        meta = meta[~invalid_mask].reset_index(drop=True)

    return meta


def _sample_ids(ids, limit=20):
    """Sorted ids for a log message, capped so a huge mismatch can't blow up the log."""
    values = sorted(ids)
    if len(values) <= limit:
        return values
    return values[:limit] + [f"...and {len(values) - limit} more"]


def _load_typed_data_source(data_path, meta_path, label_column, type_column, patient_id_column,
                             description_column=None, group_column=None, subgroup_column=None):
    """
    Load one data/meta pair, restricting the (potentially huge) data file to the
    columns modina can actually use. The meta file is read first since it's tiny, so
    the relevant columns and their dtypes are known before the data file is touched:
    variables with an unrecognized type and any per-column dtype inference are
    skipped entirely via `usecols`/`dtype` instead of being parsed and then dropped.

    `description_column`/`group_column`/`subgroup_column` are optional and, like
    `type_column`, may each be either the name of a column already in the meta file or
    a literal value applied to every row (e.g. a fixed group name for a data source
    that has no per-variable grouping of its own). `subgroup_column` values are scoped
    to their `group` - the same subgroup value under two different groups is treated
    as two independent subgroups.

    `patient_id_column` may be None, in which case the file's default RangeIndex is
    used in place of a real patient id. This is only sound when this is the only data
    source being loaded, since there is then nothing to join against; callers combining
    multiple sources must supply a real patient_id_column (enforced in load_data_sources).

    Raises if `label_column` isn't a column in `meta_path`, or if renaming
    label_column/type_column/description_column/group_column/subgroup_column to their
    canonical names is ambiguous - see _rename_meta_columns.

    Raises if `data_path` contains columns with no matching label in `meta_path`,
    since modina cannot assign those a type and would error out later anyway. Meta
    rows with no matching column in `data_path` (e.g. variables not simulated/
    collected) are dropped, logging how many.

    :return: tuple (data, meta) - meta has columns ['label', 'type'], plus
             'description'/'group'/'subgroup' if the corresponding argument is given.
    """
    meta_sep = _infer_separator(meta_path)
    meta = pd.read_csv(meta_path, sep=meta_sep, low_memory=False)
    if label_column not in meta.columns:
        raise ValueError(
            f"{meta_path}: configured label column '{label_column}' not found in file "
            f"(available columns: {list(meta.columns)})"
        )
    meta = _rename_meta_columns(meta, meta_path, label_column, type_column, description_column, group_column,
                                 subgroup_column)
    keep_cols = ["label", "type"] + [c for c in ("description", "group", "subgroup") if c in meta.columns]
    meta = meta[keep_cols]
    all_meta_labels = set(meta["label"])

    meta = _normalize_meta_types(meta, meta_path)

    data_sep = _infer_separator(data_path)
    header_columns = pd.read_csv(data_path, sep=data_sep, nrows=0).columns
    if patient_id_column is not None:
        if patient_id_column not in header_columns:
            raise ValueError(
                f"{data_path}: configured patient id column '{patient_id_column}' not found "
                f"in file (available columns: {list(header_columns)})"
            )
        header_columns = header_columns.drop(patient_id_column)

    missing_in_meta = set(header_columns) - all_meta_labels
    if missing_in_meta:
        raise ValueError(
            f"{data_path}: {len(missing_in_meta)} column(s) have no matching label in "
            f"{meta_path}: {sorted(missing_in_meta)}"
        )

    missing_in_data = set(meta["label"]) - set(header_columns)
    if missing_in_data:
        logger.info(
            f"{meta_path}: dropping {len(missing_in_data)} label(s) with no matching "
            f"column in {data_path}: {sorted(missing_in_data)}"
        )
        meta = meta[meta["label"].isin(header_columns)].reset_index(drop=True)

    usecols = ([patient_id_column] if patient_id_column is not None else []) + meta["label"].tolist()
    # Only 'continuous' is passed as a read_csv dtype: 'category' dtype must NOT be
    # requested from read_csv directly, since pandas then categorizes the raw CSV
    # text (categories end up as strings, e.g. '-99') instead of first inferring a
    # numeric dtype (categories as int/float, e.g. -99). That string/number mismatch
    # breaks modina's nan_value sentinel comparisons downstream. Category columns are
    # cast after reading instead, so pandas' normal type inference runs first.
    dtype = {
        label: TYPE_TO_DTYPE[type_]
        for label, type_ in zip(meta["label"], meta["type"])
        if TYPE_TO_DTYPE[type_] != "category"
    }
    category_labels = [
        label for label, type_ in zip(meta["label"], meta["type"])
        if TYPE_TO_DTYPE[type_] == "category"
    ]

    data = pd.read_csv(
        data_path,
        sep=data_sep,
        index_col=patient_id_column,
        usecols=usecols,
        dtype=dtype,
    )
    if category_labels:
        data[category_labels] = data[category_labels].astype("category")

    return data, meta


def load_data_sources(env):
    """
    Load each configured data source independently (unmerged).

    Sources are configured via the comma-separated env vars DATA_PATHS,
    DATA_META_PATHS, DATA_LABEL_COLUMNS and DATA_TYPE_COLUMNS, which must all have the
    same number of entries (one per source) and at least one entry. DATA_ROOT, if set,
    is prepended to any relative entry in DATA_PATHS/DATA_META_PATHS. DATA_DESCRIPTION_
    COLUMNS, DATA_GROUP_COLUMNS and DATA_SUBGROUP_COLUMNS are optional and, like
    DATA_TYPE_COLUMNS, each entry may be either a column name in that source's meta file
    or a literal value applied to every row of that source (pad an entry with nothing
    to skip it for one source). DATA_SUBGROUP_COLUMNS values are scoped to their group -
    the same subgroup value under two different groups is treated as two independent
    subgroups.

    PATIENT_ID_COLUMN may be left unset only when a single data source is configured,
    in which case that file's row order is used as the patient id. With more than one
    source it is required, since it's the only way to match records across files.

    :return: dict mapping data_path -> (data, meta), in DATA_PATHS order.
    """
    patient_id_column = env("PATIENT_ID_COLUMN", default=None) or None
    data_root = env("DATA_ROOT", default=None)

    data_paths = _parse_list_env(env, "DATA_PATHS")
    meta_paths = _parse_list_env(env, "DATA_META_PATHS")
    label_columns = _parse_list_env(env, "DATA_LABEL_COLUMNS")
    type_columns = _parse_list_env(env, "DATA_TYPE_COLUMNS")

    data_paths = [_resolve_path(path, data_root) for path in data_paths]
    meta_paths = [_resolve_path(path, data_root) for path in meta_paths]

    if not (len(data_paths) == len(meta_paths) == len(label_columns) == len(type_columns)):
        raise ValueError(
            "DATA_PATHS, DATA_META_PATHS, DATA_LABEL_COLUMNS and DATA_TYPE_COLUMNS "
            "must all have the same number of comma-separated entries."
        )

    if not data_paths:
        raise ValueError(
            "No data source configured. Set DATA_PATHS, DATA_META_PATHS, "
            "DATA_LABEL_COLUMNS and DATA_TYPE_COLUMNS."
        )

    if patient_id_column is None and len(data_paths) > 1:
        raise ValueError(
            "PATIENT_ID_COLUMN must be set when combining more than one data source, "
            "since it's the join key used to match records across files."
        )

    description_columns = _parse_aligned_list_env(env, "DATA_DESCRIPTION_COLUMNS", len(data_paths))
    group_columns = _parse_aligned_list_env(env, "DATA_GROUP_COLUMNS", len(data_paths))
    subgroup_columns = _parse_aligned_list_env(env, "DATA_SUBGROUP_COLUMNS", len(data_paths))
    if len(description_columns) != len(data_paths):
        raise ValueError("DATA_DESCRIPTION_COLUMNS, if set, must have one entry per data source.")
    if len(group_columns) != len(data_paths):
        raise ValueError("DATA_GROUP_COLUMNS, if set, must have one entry per data source.")
    if len(subgroup_columns) != len(data_paths):
        raise ValueError("DATA_SUBGROUP_COLUMNS, if set, must have one entry per data source.")

    sources = {}
    for data_path, meta_path, label_column, type_column, description_column, group_column, subgroup_column in zip(
        data_paths, meta_paths, label_columns, type_columns, description_columns, group_columns, subgroup_columns
    ):
        data, meta = _load_typed_data_source(
            data_path, meta_path, label_column, type_column, patient_id_column,
            description_column=description_column or None,
            group_column=group_column or None,
            subgroup_column=subgroup_column or None,
        )
        logger.info(f"Loaded {data_path}: {data.shape[0]} patients, {data.shape[1]} variables.")
        sources[data_path] = (data, meta)

    return sources


def _join_all_data(sources):
    """Inner-join every source's data on the patient-id index, logging dropped patients."""
    combined_data = None
    for data_path, (data, _meta) in sources.items():
        if combined_data is None:
            combined_data = data
            continue

        dropped_existing = combined_data.index.difference(data.index)
        dropped_incoming = data.index.difference(combined_data.index)
        if len(dropped_existing):
            logger.info(
                f"{data_path}: dropping {len(dropped_existing)} patient(s) not present "
                f"in this source: {_sample_ids(dropped_existing)}"
            )
        if len(dropped_incoming):
            logger.info(
                f"{data_path}: dropping {len(dropped_incoming)} patient(s) from this "
                f"source not present in previously loaded data: {_sample_ids(dropped_incoming)}"
            )
        combined_data = combined_data.join(data, how="inner")
    return combined_data


def combine_data(env):
    """
    Load and combine any number of data sources into one merged dataframe + meta
    dataframe, ready for modina's compute_context_scores. See load_data_sources() for
    the env var configuration contract.

    :return: tuple (combined_data, meta_file) ready for modina's compute_context_scores.
    """
    sources = load_data_sources(env)
    combined_data = _join_all_data(sources)
    meta_file = pd.concat([meta for _data, meta in sources.values()], ignore_index=True)
    logger.info(f"Combined data: {combined_data.shape[0]} patients, {combined_data.shape[1]} variables.")
    return combined_data, meta_file


def _split_cat_cont(all_data, meta_file):
    """
    Split `all_data` into categorical and continuous frames using `meta_file`'s
    modina-vocabulary 'type' column, which spans every configured data source
    (unlike the old, phenotype-only network.score_calculation.separate_cat_cont()).
    """
    cat_labels = set(meta_file.loc[meta_file["type"].isin(["binary", "nominal", "ordinal"]), "label"])
    cont_labels = set(meta_file.loc[meta_file["type"] == "continuous", "label"])
    cat_data = all_data.loc[:, all_data.columns.isin(cat_labels)].copy()
    cont_data = all_data.loc[:, all_data.columns.isin(cont_labels)].copy()
    return cat_data, cont_data


def _group_labels(meta_file):
    """dict mapping each distinct 'group' value to its list of labels, or {} if no source configured a group."""
    if "group" not in meta_file.columns:
        return {}
    return meta_file.groupby("group")["label"].apply(list).to_dict()


def _group_subgroup_labels(meta_file):
    """
    dict mapping each 'group' value to {subgroup: [labels]}, or {} if no source
    configured a group/subgroup. A group with no non-null subgroup values among its own
    labels simply has no key - callers should treat that as "this group has no
    subgroups". Subgroup values are scoped to their group: the same subgroup name under
    two different groups is kept independent (never merged).
    """
    if "group" not in meta_file.columns or "subgroup" not in meta_file.columns:
        return {}
    with_subgroup = meta_file.dropna(subset=["subgroup"])
    if with_subgroup.empty:
        return {}
    return {
        group: grp.groupby("subgroup")["label"].apply(list).to_dict()
        for group, grp in with_subgroup.groupby("group")
    }


class DataManager:
    # Groups are fully user-defined via DATA_GROUP_COLUMNS - see _load_typed_data_source's
    # group_column. Every group present in the data gets a slot in _group_data/_group_meta,
    # consumed generically by GetVariablesView, GetTableView and the contexts feature.
    # Subgroups (DATA_SUBGROUP_COLUMNS) work the same way, one level deeper: every group's
    # subgroups (if any) get a slot in _layer_subgroups, keyed first by group then subgroup.

    def __init__(self):
        self._var_label_map: dict | None = None
        self._layers: dict | None = None
        self._all_cont: pd.DataFrame | None = None
        self._all_cat: pd.DataFrame | None = None
        self._all_data: pd.DataFrame | None = None
        self._meta_file: pd.DataFrame | None = None
        self._group_data: dict[str, pd.DataFrame] = {}
        self._group_meta: dict[str, pd.DataFrame] = {}
        self._layer_subgroups: dict[str, dict[str, pd.Index]] = {}

        self._data_loaded = False
        self.switch = {}

    def load_data(self):
        """
        Loads all the data from the given paths and creates the necessary combinations. Can only be called once.
        :return: None
        """
        if self._data_loaded:
            raise RuntimeError("Data has already been loaded and should not be loaded again.")

        try:
            self._load_and_combine()
            self._initialize_switch()
            self._data_loaded = True
        except Exception:
            logger.exception("An error occurred while loading the data, make sure everything is loaded properly.")

    def _initialize_switch(self):
        self.switch = {
            'layers': self._layers,
            'all_cont': self._all_cont,
            'all_cat': self._all_cat,
            'all_data': self._all_data,
            'meta_file': self._meta_file,
            'group_data': self._group_data,
            'group_meta': self._group_meta,
            'layer_subgroups': self._layer_subgroups,
            'var_label_map': self._var_label_map
            }

    def _slice_group(self, group_labels, meta_file, group_name):
        """Sub-dataframe of self._all_data restricted to columns/rows belonging to `group_name`."""
        labels = group_labels.get(group_name)
        if labels is None:
            return None, None
        data = self._all_data.loc[:, self._all_data.columns.isin(labels)].copy()
        meta = meta_file[meta_file["group"] == group_name].set_index("label", drop=False)
        meta = meta.copy()
        if "description" not in meta.columns:
            # list_group_variables always expects this column; default to NaN when
            # DATA_DESCRIPTION_COLUMNS wasn't configured for this group.
            meta["description"] = None
        if "subgroup" not in meta.columns:
            meta["subgroup"] = None
        return data, meta

    def _load_and_combine(self):
        env = environ.Env()
        environ.Env.read_env()

        sources = load_data_sources(env)
        self._all_data = _join_all_data(sources)

        # NAN_VALUE is the sentinel modina's own stats code (network/tasks.py) already
        # treats as missing; replaced here too so every API view built on this data
        # (plots, context filters, tables) sees real NaNs instead of the raw integer.
        # Category columns go through cat.remove_categories() rather than .replace():
        # besides .replace() being deprecated for CategoricalDtype value changes, it
        # would still leave -89 as an unused category, which value_counts() (used e.g.
        # by VariableInfoView for the context page's variable distribution) reports
        # with a count of 0 - i.e. the sentinel would still show up as a bin/label.
        # remove_categories() drops the category itself and sets its values to NaN.
        nan_value = env("NAN_VALUE", cast=int, default=-89)
        cat_cols = self._all_data.select_dtypes(include="category").columns
        other_cols = self._all_data.columns.difference(cat_cols)
        self._all_data[other_cols] = self._all_data[other_cols].replace(nan_value, np.nan)
        for col in cat_cols:
            if nan_value in self._all_data[col].cat.categories:
                self._all_data[col] = self._all_data[col].cat.remove_categories(nan_value)

        meta_file = pd.concat([meta for _data, meta in sources.values()], ignore_index=True)
        group_labels = _group_labels(meta_file)
        self._layers = {group: pd.Index(labels) for group, labels in group_labels.items()}
        group_subgroup_labels = _group_subgroup_labels(meta_file)
        self._layer_subgroups = {
            group: {subgroup: pd.Index(labels) for subgroup, labels in subgroups.items()}
            for group, subgroups in group_subgroup_labels.items()
        }

        for group_name in group_labels:
            data, meta = self._slice_group(group_labels, meta_file, group_name)
            self._group_data[group_name] = data
            self._group_meta[group_name] = meta

        self._meta_file = meta_file
        self._all_cat, self._all_cont = _split_cat_cont(self._all_data, meta_file)

        var_label_path = env('VAR_LABEL_MAPPING', default=None)
        if var_label_path and os.path.isfile(var_label_path):
            self._var_label_map = self._load_label_map(var_label_path)

    @staticmethod
    def _load_label_map(file_path: str):
        full_map = defaultdict(dict)
        with open(file_path, 'r') as file:
            lines = file.readlines()
            for key, subkey, value in csv.reader(lines):
                full_map[key][subkey] = value
        return full_map

    def is_loaded(self) -> bool:
        """
        Gives info if the data has been loaded properly.
        :return: True if the data has been loaded, False otherwise.
        """
        return self._data_loaded

    def get_valid_keys(self) -> list[str]:
        """
        Returns the keys for the available dataframes.
        :return: A list of keys for the available dataframes.
        """
        return list(self.switch.keys())

    def is_available(self, key: str) -> bool:
        """
        Checks if the requested dataframe is available.
        :param key: The key to check.
        :return: True if the dataframe is available, False otherwise.
        """
        return key in self.switch and not isinstance(self.switch[key], type(None))

    def get_df_copy(self, df: str | list) -> pd.DataFrame | dict | None:
        """
        Returns a copy of the requested dataframe(s) ensuring thread safety.
        All data should be retrieved through here and never directly accessed.
        :param df: The name of the dataframe to retrieve or a list of names.
        :return: A copy of the requested dataframe(s) or None if the dataframe does not exist. As a list in the same
                 order as the input list when requesting multiple dataframes.
        """

        if isinstance(df, str):
            dataframe = self.switch.get(df, None)
            return dataframe.copy() if isinstance(dataframe, pd.DataFrame) else None
        elif isinstance(df, list):
            return [self.switch[key].copy() if not isinstance(self.switch.get(key), type(None)) else None for key in df]
        else:
            raise ValueError("The input should be a string or a list of strings.")
