import csv
import logging
import os
from collections import defaultdict

import environ
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

# Reverse mapping back to the vocabulary network.score_calculation.separate_cat_cont()
# expects - used only for DataManager.pheno_meta_label, which feeds the (untouched)
# contexts per-user scoring pipeline.
TYPE_TO_OLD_VOCAB = {
    "binary": "boolean",
    "nominal": "categorical",
    "ordinal": "categorical",
    "continuous": "float",
}


def _apply_literal_or_column(meta, column_or_literal, target_col, meta_path):
    """
    Rename `column_or_literal` to `target_col` if it is an existing column in `meta`.
    Otherwise, treat it as a literal value and assign it to every row, so a single
    fixed value (e.g. a type or a group name) can be used for an entire data source
    that has no per-row column for it. A falsy `column_or_literal` leaves `meta`
    unchanged (the attribute is simply not configured for this source).

    Meta files often already have their own, unrelated column literally named
    `target_col` (e.g. a protein meta file's own 'description' column, distinct from
    whichever column DATA_DESCRIPTION_COLUMNS points at) - that column is dropped
    first so the rename can't produce two columns sharing the same name.
    """
    if not column_or_literal:
        return meta
    if column_or_literal in meta.columns:
        if target_col in meta.columns and target_col != column_or_literal:
            meta = meta.drop(columns=[target_col])
        return meta.rename(columns={column_or_literal: target_col})
    meta = meta.copy()
    meta[target_col] = column_or_literal
    return meta


def _apply_type_column(meta, type_column, meta_path):
    """
    Rename `type_column` to 'type' if it is an existing column in `meta`. Otherwise,
    treat it as a literal type value (e.g. 'continuous') applied to every row.
    """
    if type_column not in meta.columns and type_column.lower() not in ALL_VALID_TYPES:
        logger.warning(
            f"{meta_path}: '{type_column}' is neither a column in this meta file nor one of "
            f"the recognized types {sorted(ALL_VALID_TYPES)}."
        )
    return _apply_literal_or_column(meta, type_column, "type", meta_path)


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
                             description_column=None, group_column=None):
    """
    Load one data/meta pair, restricting the (potentially huge) data file to the
    columns modina can actually use. The meta file is read first since it's tiny, so
    the relevant columns and their dtypes are known before the data file is touched:
    variables with an unrecognized type and any per-column dtype inference are
    skipped entirely via `usecols`/`dtype` instead of being parsed and then dropped.

    `description_column`/`group_column` are optional and, like `type_column`, may
    each be either the name of a column already in the meta file or a literal value
    applied to every row (e.g. a fixed group name for a data source that has no
    per-variable grouping of its own).

    Raises if `data_path` contains columns with no matching label in `meta_path`,
    since modina cannot assign those a type and would error out later anyway. Meta
    rows with no matching column in `data_path` (e.g. variables not simulated/
    collected) are dropped, logging how many.

    :return: tuple (data, meta) - meta has columns ['label', 'type'], plus
             'description'/'group' if the corresponding argument is given.
    """
    meta_sep = _infer_separator(meta_path)
    meta = pd.read_csv(meta_path, sep=meta_sep, low_memory=False)
    meta = meta.rename(columns={label_column: "label"})
    meta = _apply_type_column(meta, type_column, meta_path)
    meta = _apply_literal_or_column(meta, description_column, "description", meta_path)
    meta = _apply_literal_or_column(meta, group_column, "group", meta_path)
    keep_cols = ["label", "type"] + [c for c in ("description", "group") if c in meta.columns]
    meta = meta[keep_cols]
    all_meta_labels = set(meta["label"])

    meta = _normalize_meta_types(meta, meta_path)

    data_sep = _infer_separator(data_path)
    header_columns = pd.read_csv(data_path, sep=data_sep, nrows=0).columns.drop(patient_id_column)

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

    usecols = [patient_id_column] + meta["label"].tolist()
    dtype = {label: TYPE_TO_DTYPE[type_] for label, type_ in zip(meta["label"], meta["type"])}

    data = pd.read_csv(
        data_path,
        sep=data_sep,
        index_col=patient_id_column,
        usecols=usecols,
        dtype=dtype,
    )

    return data, meta


def load_data_sources(env):
    """
    Load each configured data source independently (unmerged).

    Sources are configured via the comma-separated env vars DATA_PATHS,
    DATA_META_PATHS, DATA_LABEL_COLUMNS and DATA_TYPE_COLUMNS, which must all have the
    same number of entries (one per source) and at least one entry. DATA_ROOT, if set,
    is prepended to any relative entry in DATA_PATHS/DATA_META_PATHS. DATA_DESCRIPTION_
    COLUMNS and DATA_GROUP_COLUMNS are optional and, like DATA_TYPE_COLUMNS, each entry
    may be either a column name in that source's meta file or a literal value applied
    to every row of that source (pad an entry with nothing to skip it for one source).

    :return: dict mapping data_path -> (data, meta), in DATA_PATHS order.
    """
    patient_id_column = env("PATIENT_ID_COLUMN")
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

    description_columns = _parse_aligned_list_env(env, "DATA_DESCRIPTION_COLUMNS", len(data_paths))
    group_columns = _parse_aligned_list_env(env, "DATA_GROUP_COLUMNS", len(data_paths))
    if len(description_columns) != len(data_paths):
        raise ValueError("DATA_DESCRIPTION_COLUMNS, if set, must have one entry per data source.")
    if len(group_columns) != len(data_paths):
        raise ValueError("DATA_GROUP_COLUMNS, if set, must have one entry per data source.")

    sources = {}
    for data_path, meta_path, label_column, type_column, description_column, group_column in zip(
        data_paths, meta_paths, label_columns, type_columns, description_columns, group_columns
    ):
        data, meta = _load_typed_data_source(
            data_path, meta_path, label_column, type_column, patient_id_column,
            description_column=description_column or None,
            group_column=group_column or None,
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


class DataManager:
    # The DATA_GROUP_COLUMNS values production is expected to configure so that the
    # legacy phenotypes/proteins/metabolites slots below (still depended on by
    # GetVariablesView, GetTableView and the contexts feature) get populated. Groups
    # are otherwise fully user-defined - see _load_typed_data_source's group_column.
    LEGACY_PHENOMICS_GROUP = "phenotype"
    LEGACY_PROTEOMICS_GROUP = "protein"
    LEGACY_METABOLOMICS_GROUP = "metabolite"

    def __init__(self):
        self._var_label_map: dict | None = None
        self._layers: dict | None = None
        self._all_cont: pd.DataFrame | None = None
        self._all_cat: pd.DataFrame | None = None
        self._all_data: pd.DataFrame | None = None
        self._meta_file: pd.DataFrame | None = None
        self._metabolites: pd.DataFrame | None = None
        self._proteins_meta: pd.DataFrame | None = None
        self._proteins: pd.DataFrame | None = None
        self._pheno_meta_label: pd.DataFrame | None = None
        self._pheno_meta: pd.DataFrame | None = None
        self._phenotypes: pd.DataFrame | None = None

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
            'metabolites': self._metabolites,
            'proteins_meta': self._proteins_meta,
            'proteins': self._proteins,
            'pheno_meta_label': self._pheno_meta_label,
            'pheno_meta': self._pheno_meta,
            'phenotypes': self._phenotypes,
            'var_label_map': self._var_label_map
            }

    def _slice_group(self, group_labels, meta_file, group_name):
        """Sub-dataframe of self._all_data restricted to columns/rows belonging to `group_name`."""
        labels = group_labels.get(group_name)
        if labels is None:
            return None, None
        data = self._all_data.loc[:, self._all_data.columns.isin(labels)].copy()
        meta = meta_file[meta_file["group"] == group_name].set_index("label", drop=False)
        if "description" not in meta.columns:
            # list_phenotype_variables/list_protein_variables always expect this column;
            # default to NaN when DATA_DESCRIPTION_COLUMNS wasn't configured for this group.
            meta = meta.copy()
            meta["description"] = None
        return data, meta

    def _load_and_combine(self):
        env = environ.Env()
        environ.Env.read_env()

        sources = load_data_sources(env)
        self._all_data = _join_all_data(sources)

        meta_file = pd.concat([meta for _data, meta in sources.values()], ignore_index=True)
        group_labels = _group_labels(meta_file)
        self._layers = {group: pd.Index(labels) for group, labels in group_labels.items()}

        self._phenotypes, self._pheno_meta = self._slice_group(
            group_labels, meta_file, self.LEGACY_PHENOMICS_GROUP)
        if self._pheno_meta is not None:
            pheno_meta_label = self._pheno_meta.copy()
            pheno_meta_label["type"] = pheno_meta_label["type"].map(TYPE_TO_OLD_VOCAB)
            self._pheno_meta_label = pheno_meta_label

        self._proteins, self._proteins_meta = self._slice_group(
            group_labels, meta_file, self.LEGACY_PROTEOMICS_GROUP)

        self._metabolites, _metabolites_meta = self._slice_group(
            group_labels, meta_file, self.LEGACY_METABOLOMICS_GROUP)

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
