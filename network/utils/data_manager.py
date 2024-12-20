import json
from network.score_calculation import separate_cat_cont
from network.utils.startup_utils import *
from django.conf import settings


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

        self._load_all_data()
        self._create_combinations()
        self._initialize_switch()
        self._data_loaded = True

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

        self._pheno_meta_label = _load_single_file(get_file_attr('phenotypes.meta'),
                                                        id_column=get_file_attr('phenotypes.label'),
                                                        column_list=[get_file_attr('phenotypes.type')],)
        self._pheno_meta_label["label"] = self._pheno_meta_label.index

        self._proteins = _load_single_file(get_file_attr('proteins.path'), id_column=settings.PATIENT_ID_COLUMN)

        self._proteins_meta = _load_single_file(get_file_attr('proteins.meta'),
                                                     id_column=get_file_attr('proteins.label'),
                                                     column_list=[get_file_attr('proteins.description'),])

        self._metabolites = _load_single_file(get_file_attr('metabolites.path'), id_column=settings.PATIENT_ID_COLUMN)

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
        if os.path.isfile(get_file_attr('labels.path')):
            with open(get_file_attr('labels.path'), 'r') as file:
                self._var_label_map = json.load(file)

    def get_valid_keys(self) -> list[str]:
        """
        Returns the keys for the available dataframes.
        :return: A list of keys for the available dataframes.
        """
        return list(self.switch.keys())

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
