from network.score_calculation import separate_cat_cont
from network.utils.startup_utils import *
from django.conf import settings
import csv
from collections import defaultdict


def _load_single_file(file_path: str, id_column: str, column_list: list[str] = None) -> pd.DataFrame:
    return check_files_and_return(file_path, id_column=id_column, column_list=column_list, return_dataset=True)


class DataManager:
    def __init__(self):
        self._var_label_map: dict | None = None
        self._layers: dict | None = None
        self._all_cont: pd.DataFrame | None = None
        self._all_cat: pd.DataFrame | None = None
        self._all_data: pd.DataFrame | None = None
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
            self._load_all_data()
            self._create_combinations()
            self._initialize_switch()
            self._data_loaded = True
        except Exception as e:
            print(f"An error occurred while loading the data, make sure everything is loaded properly: {e}")

    def _initialize_switch(self):
        self.switch = {
            'layers': self._layers,
            'all_cont': self._all_cont,
            'all_cat': self._all_cat,
            'all_data': self._all_data,
            'metabolites': self._metabolites,
            'proteins_meta': self._proteins_meta,
            'proteins': self._proteins,
            'pheno_meta_label': self._pheno_meta_label,
            'pheno_meta': self._pheno_meta,
            'phenotypes': self._phenotypes,
            'var_label_map': self._var_label_map
            }

    def _load_all_data(self):
        self._phenotypes = _load_single_file(get_file_attr('phenotypes.path'), id_column=settings.PATIENT_ID_COLUMN)

        self._pheno_meta = _load_single_file(get_file_attr('phenotypes.meta'),
                                                  id_column=get_file_attr('phenotypes.label'),
                                                  column_list=[get_file_attr('phenotypes.type'),
                                                               get_file_attr('phenotypes.description')])

        assert isinstance(self._phenotypes, pd.DataFrame) == isinstance(self._pheno_meta, pd.DataFrame), \
            f"Phenotypes and phenotypes meta data should both be either None or a DataFrame.\nFound: " \
            f"{type(self._phenotypes)} and {type(self._pheno_meta)}"

        if isinstance(self._pheno_meta, pd.DataFrame):
            self._pheno_meta_label = self._pheno_meta.copy()
            self._pheno_meta_label["label"] = self._pheno_meta_label.index
            self._pheno_meta_label = self._pheno_meta_label[[get_file_attr('phenotypes.type'), "label"]]

        self._proteins = _load_single_file(get_file_attr('proteins.path'), id_column=settings.PATIENT_ID_COLUMN)

        self._proteins_meta = _load_single_file(get_file_attr('proteins.meta'),
                                                     id_column=get_file_attr('proteins.label'),
                                                     column_list=[get_file_attr('proteins.description'),])

        self._metabolites = _load_single_file(get_file_attr('metabolites.path'), id_column=settings.PATIENT_ID_COLUMN)

    @staticmethod
    def _load_label_map(file_path: str):
        full_map = defaultdict(dict)
        with open(file_path, 'r') as file:
            lines = file.readlines()
            for key, subkey, value in csv.reader(lines):
                full_map[key][subkey] = value
        return full_map

    def _create_combinations(self):
        self._all_data = join_dataframes([self._phenotypes, self._proteins, self._metabolites])

        self._all_cat, self._all_cont = separate_cat_cont(self._all_data, self._pheno_meta_label)
        # maximum number of categories here is 29 for variable: x0pe05d

        # Associate the layers with their respective variables
        self._layers = {'phenomics': self._phenotypes.columns if isinstance(self._phenotypes, pd.DataFrame) else [],
                        'proteomics': self._proteins.columns if isinstance(self._proteins, pd.DataFrame) else [],
                        'metabolomics': self._metabolites.columns if isinstance(self._metabolites, pd.DataFrame) else []}

        # If file exists open the file and load the JSON data
        # Get the mapping of values (e.g. 0:female, 1:male) for a nicer representation
        if os.path.isfile(get_file_attr('labels.path')):
            self._var_label_map = self._load_label_map(get_file_attr('labels.path'))

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

def _parse_list_env(env, name):
    """Parse a comma-separated env var into a list of stripped, non-empty strings."""
    raw = env(name, default="")
    return [item.strip() for item in raw.split(",") if item.strip()]


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


def _apply_type_column(meta, type_column, meta_path):
    """
    Rename `type_column` to 'type' if it is an existing column in `meta`.
    Otherwise, treat `type_column` as a literal type value (e.g. 'continuous') and
    assign it to every row, so a single fixed type can be used for an entire
    data source whose meta file has no type column.
    """
    if type_column in meta.columns:
        return meta.rename(columns={type_column: "type"})

    if type_column.lower() not in ALL_VALID_TYPES:
        logger.warning(
            f"{meta_path}: '{type_column}' is neither a column in this meta file nor one of "
            f"the recognized types {sorted(ALL_VALID_TYPES)}."
        )

    meta = meta.copy()
    meta["type"] = type_column
    return meta


def _normalize_meta_types(meta, meta_path):
    """
    Lowercase the 'type' column and map alternative spellings (TYPE_ALIASES, e.g.
    'boolean' -> 'binary', 'categorical' -> 'nominal', 'float'/'integer' -> 'continuous')
    to the canonical types modina expects. Rows whose type still isn't one of
    VALID_VARIABLE_TYPES are dropped, since modina cannot assign them to a test and
    the matching data column never needs to be read.
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


def _load_typed_data_source(data_path, meta_path, label_column, type_column, patient_id_column):
    """
    Load one data/meta pair, restricting the (potentially huge) data file to the
    columns modina can actually use. The meta file is read first since it's tiny, so
    the relevant columns and their dtypes are known before the data file is touched:
    variables with an unrecognized type and any per-column dtype inference are
    skipped entirely via `usecols`/`dtype` instead of being parsed and then dropped.

    Raises if `data_path` contains columns with no matching label in `meta_path`,
    since modina cannot assign those a type and would error out later anyway. Meta
    rows with no matching column in `data_path` (e.g. variables not simulated/
    collected) are dropped, logging how many.
    """
    meta_sep = _infer_separator(meta_path)
    meta = pd.read_csv(meta_path, sep=meta_sep, low_memory=False)
    meta = meta.rename(columns={label_column: "label"})
    meta = _apply_type_column(meta, type_column, meta_path)[["label", "type"]]
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


def combine_data(env):
    """
    Load and combine any number of data sources (e.g. phenotypes, proteins,
    metabolites, genomic variants), each with their own meta data file, label
    column and type column.

    Sources are configured via the comma-separated env vars DATA_PATHS,
    DATA_META_PATHS, DATA_LABEL_COLUMNS and DATA_TYPE_COLUMNS, which must all have
    the same number of entries (one per source) and at least one entry. If
    DATA_ROOT is set, it is prepended to any relative entry in DATA_PATHS and
    DATA_META_PATHS, so only file names need to be given there.

    Patients are combined via an inner join on the patient id index, so any patient
    missing from one of the data sources is dropped from the combined result. Such
    drops are logged. For every data/meta pair, the meta file's 'label' column is
    checked against the data file's column names and mismatches are logged.

    :return: tuple (combined_data, meta_file) ready for modina's compute_context_scores.
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

    combined_data = None
    meta_file = None

    for data_path, meta_path, label_column, type_column in zip(data_paths, meta_paths, label_columns, type_columns):
        extra_data, extra_meta = _load_typed_data_source(
            data_path, meta_path, label_column, type_column, patient_id_column,
        )

        if combined_data is None:
            combined_data = extra_data
            meta_file = extra_meta
            logger.info(
                f"Loaded base data from {data_path}: "
                f"{combined_data.shape[0]} patients, {combined_data.shape[1]} variables."
            )
            continue

        dropped_existing = combined_data.index.difference(extra_data.index)
        dropped_incoming = extra_data.index.difference(combined_data.index)
        if len(dropped_existing):
            logger.info(
                f"{data_path}: dropping {len(dropped_existing)} patient(s) not present "
                f"in this file: {_sample_ids(dropped_existing)}"
            )
        if len(dropped_incoming):
            logger.info(
                f"{data_path}: dropping {len(dropped_incoming)} patient(s) from this file "
                f"not present in previously loaded data: {_sample_ids(dropped_incoming)}"
            )

        combined_data = combined_data.join(extra_data, how="inner")
        meta_file = pd.concat([meta_file, extra_meta], ignore_index=True)
        logger.info(
            f"Combined with {data_path}: "
            f"{combined_data.shape[0]} patients, {combined_data.shape[1]} variables remaining."
        )

    return combined_data, meta_file