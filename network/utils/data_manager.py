from network.score_calculation import separate_cat_cont, separate_types
from network.utils.startup_utils import *
from django.conf import settings
import csv
from collections import defaultdict
import os
import logging
import pandas as pd

logger = logging.getLogger("network")


def human_readable_size(num, suffix='B'):
    for unit in ['','K','M','G','T','P']:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}P{suffix}"


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
            'var_label_map': self._var_label_map,
            'all_ordinal': getattr(self, '_all_ordinal', pd.DataFrame()),
            'all_nominal': getattr(self, '_all_nominal', pd.DataFrame()),
            'all_binary': getattr(self, '_all_binary', pd.DataFrame()),
            'all_continuous': getattr(self, '_all_continuous', pd.DataFrame())
        }

    def _load_all_data(self):
        phen_path = get_file_attr('phenotypes.path')
        self._phenotypes = _load_single_file(phen_path, id_column=settings.PATIENT_ID_COLUMN)
        try:
            if phen_path and os.path.exists(phen_path):
                phen_size = os.path.getsize(phen_path)
                logger.info("Phenotypes loaded from %s (size: %s), shape: %s", phen_path, human_readable_size(phen_size), getattr(self._phenotypes, 'shape', None))
            else:
                logger.info("Phenotypes loaded (no file path available). shape: %s", getattr(self._phenotypes, 'shape', None))
        except Exception:
            logger.warning("Could not determine phenotype file size for path: %s", phen_path)

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

        prot_path = get_file_attr('proteins.path')
        self._proteins = _load_single_file(prot_path, id_column=settings.PATIENT_ID_COLUMN)
        try:
            if prot_path and os.path.exists(prot_path):
                prot_size = os.path.getsize(prot_path)
                logger.info("Proteins loaded from %s (size: %s), shape: %s", prot_path, human_readable_size(prot_size), getattr(self._proteins, 'shape', None))
            else:
                logger.info("Proteins loaded (no file path available). shape: %s", getattr(self._proteins, 'shape', None))
        except Exception:
            logger.warning("Could not determine protein file size for path: %s", prot_path)

        self._proteins_meta = _load_single_file(get_file_attr('proteins.meta'),
                                                     id_column=get_file_attr('proteins.label'),
                                                     column_list=[get_file_attr('proteins.description'),])

        metab_path = get_file_attr('metabolites.path')
        self._metabolites = _load_single_file(metab_path, id_column=settings.PATIENT_ID_COLUMN)
        try:
            if metab_path and os.path.exists(metab_path):
                metab_size = os.path.getsize(metab_path)
                logger.info("Metabolites loaded from %s (size: %s), shape: %s", metab_path, human_readable_size(metab_size), getattr(self._metabolites, 'shape', None))
            else:
                logger.info("Metabolites loaded (no file path available). shape: %s", getattr(self._metabolites, 'shape', None))
        except Exception:
            logger.warning("Could not determine metabolite file size for path: %s", metab_path)

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

        # basic categorical / continuous split (kept for compatibility)
        self._all_cat, all_cont = separate_cat_cont(self._phenotypes, self._pheno_meta_label)
        self._all_cont = join_dataframes([all_cont, self._proteins, self._metabolites])

        # detailed type split (ordinal, nominal, continuous, binary)
        ord_df, nom_df, cont_df2, bi_df = separate_types(self._phenotypes, self._pheno_meta_label)
        self._all_continuous = join_dataframes([cont_df2, self._proteins, self._metabolites])

        # Push nominal columns with only two categories into binary
        if isinstance(nom_df, pd.DataFrame) and not nom_df.empty:
            two_cat = nom_df.nunique() == 2
            if two_cat.any():
                cols_two = list(two_cat[two_cat].index)
                # move columns into binary df
                if isinstance(bi_df, pd.DataFrame):
                    bi_df = pd.concat([bi_df, nom_df[cols_two]], axis=1)
                else:
                    bi_df = nom_df[cols_two].copy()
                nom_df = nom_df.drop(columns=cols_two)

        # convert low-cardinality columns to categorical dtype to save memory and speed groupby
        for df in (ord_df, nom_df, bi_df):
            if isinstance(df, pd.DataFrame) and not df.empty:
                for c in df.columns:
                    try:
                        if df[c].nunique() < 200:
                            df[c] = df[c].astype('category')
                    except Exception:
                        continue

        # save dfs in data manager
        self._all_ordinal = ord_df
        self._all_nominal = nom_df
        self._all_binary = bi_df
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
