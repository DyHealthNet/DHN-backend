import pickle
import timeit
import json

import numpy as np
import pandas as pd

from network.score_calculation import separate_cat_cont
from network.utils.startup_utils import *
from django.conf import settings
from django.core.cache import cache
import environ

env = environ.Env()
environ.Env.read_env()


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
        self._load_all_data()
        self._create_combinations()

    def _load_all_data(self):
        self._phenotypes = _load_single_file(env("PHENOTYPE_PATH"), id_column=env("PATIENT_ID_COLUMN"))

        self._pheno_meta = _load_single_file(env("PHENOTYPE_META_PATH"),
                                                  id_column=env("PHENOTYPE_LABEL_COLUMN"),
                                                  column_list=[env("PHENOTYPE_TYPE_COLUMN"),
                                                               env("PHENOTYPE_DESCRIPTION_COLUMN")])

        self._pheno_meta_label = _load_single_file(env("PHENOTYPE_META_PATH"),
                                                        id_column=env("PHENOTYPE_LABEL_COLUMN"),
                                                        column_list=["type"],)
        self._pheno_meta_label["label"] = self._pheno_meta_label.index

        self._proteins = _load_single_file(env("PROTEIN_PATH"), id_column=env("PATIENT_ID_COLUMN"))

        self._proteins_meta = _load_single_file(env("PROTEIN_META_PATH"),
                                                     id_column=env("PROTEIN_LABEL_COLUMN"),
                                                     column_list=[env("PROTEIN_DESCRIPTION_COLUMN")])

        self._metabolites = _load_single_file(env("METABOLITE_PATH"), id_column=env("PATIENT_ID_COLUMN"))

    def _create_combinations(self):
        self._all_data = join_dataframes([self._phenotypes, self._proteins, self._metabolites])

        self._all_cat, self._all_cont = separate_cat_cont(self._all_data, self._pheno_meta_label)
        # maximum number of categories here is 29 for variable: x0pe05d

        # Associate the layers with their respective variables
        self._layers = {'phenomics': self._phenotypes.columns,
                        'proteomics': self._proteins.columns,
                        'metabolomics': self._metabolites.columns}

        # If file exists open the file and load the JSON data
        # Get the mapping of values (e.g. 0:female, 1:male) for a nicer representation
        self._var_label_map = None
        if os.path.isfile(env("VAR_LABEL_MAPPING")):
            # logger.debug("Loading variable label mapping from file")
            with open(env("VAR_LABEL_MAPPING"), 'r') as file:
                self._var_label_map = json.load(file)

    def get_df_copy(self, df: str | list) -> pd.DataFrame | dict | None:
        """
        Returns a copy of the requested dataframe(s) ensuring thread safety.
        All data should be retrieved through here and never directly accessed.
        :param df:
        :return:
        """
        switch = {
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

        if isinstance(df, str):
            dataframe = switch.get(df, None)
            return dataframe.copy() if not isinstance(dataframe, type(None)) else None
        elif isinstance(df, list):
            return [switch[key].copy() if not isinstance(switch.get(key), type(None)) else None for key in df]
        else:
            raise ValueError("The input should be a string or a list of strings.")
