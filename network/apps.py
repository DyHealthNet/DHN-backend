import json
import sys
import timeit

from django.apps import AppConfig

from network.score_calculation import separate_cat_cont
from network.utils.startup_utils import *
import environ

env = environ.Env()
environ.Env.read_env()


class NetworksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "network"

    def __init__(self, app_name, app_module):
        super().__init__(app_name, app_module)
        self.VAR_LABEL_MAP = None
        self.LAYERS = None
        self.ALL_CONT = None
        self.ALL_CAT = None
        self.all_data = None
        self.METABOLITES = None
        self.PROTEINS_META = None
        self.PROTEINS = None
        self.PHENO_META_LABEL = None
        self.PHENO_META = None
        self.PHENOTYPES = None

    def ready(self):
        # To avoid loading the files twice during server start
        if os.environ.get("RUN_MAIN") != "true":
            return  # Skip loading during autoreload

        if len(sys.argv) > 1 and sys.argv[1] != 'runserver':
            pass
        else:
            start = timeit.default_timer()
            self.PHENOTYPES = check_files_and_return(env("PHENOTYPE_PATH"),
                                                     id_column=env("PATIENT_ID_COLUMN"),
                                                     return_dataset=True)
            self.PHENO_META = check_files_and_return(env("PHENOTYPE_META_PATH"),
                                                     id_column=env("PHENOTYPE_LABEL_COLUMN"),
                                                     column_list=[env("PHENOTYPE_TYPE_COLUMN"),
                                                                  env("PHENOTYPE_DESCRIPTION_COLUMN")])
            # ugly but it works
            self.PHENO_META_LABEL = check_files_and_return(env("PHENOTYPE_META_PATH"),
                                                           id_column=env("PHENOTYPE_LABEL_COLUMN"),
                                                           column_list=["type"], )
            self.PHENO_META_LABEL["label"] = self.PHENO_META_LABEL.index

            self.PROTEINS = check_files_and_return(env("PROTEIN_PATH"),
                                                   id_column=env("PATIENT_ID_COLUMN"),
                                                   return_dataset=True)

            self.PROTEINS_META = check_files_and_return(env("PROTEIN_META_PATH"),
                                                        id_column=env("PROTEIN_LABEL_COLUMN"),
                                                        column_list=[env("PROTEIN_DESCRIPTION_COLUMN")],
                                                        return_dataset=True)

            self.METABOLITES = check_files_and_return(env("METABOLITE_PATH"),
                                                      id_column=env("PATIENT_ID_COLUMN"),
                                                      return_dataset=True)

            self.all_data = join_dataframes([self.PHENOTYPES, self.PROTEINS, self.METABOLITES])

            logger.info("Startup time: " + str(timeit.default_timer() - start))

            self.ALL_CAT, self.ALL_CONT = separate_cat_cont(self.all_data, self.PHENO_META_LABEL)
            # maximum number of categories here is 29 for variable: x0pe05d

            # Associate the layers with their respective variables
            self.LAYERS = {'phenomics': self.PHENOTYPES.columns,
                           'proteomics': self.PROTEINS.columns,
                           'metabolomics': self.METABOLITES.columns}

            # If file exists open the file and load the JSON data
            # Get the mapping of values (e.g. 0:female, 1:male) for a nicer representation
            self.VAR_LABEL_MAP = None
            if os.path.isfile(env("VAR_LABEL_MAPPING")):
                # logger.debug("Loading variable label mapping from file")
                with open(env("VAR_LABEL_MAPPING"), 'r') as file:
                    self.VAR_LABEL_MAP = json.load(file)
