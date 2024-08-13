from django.core.management.base import BaseCommand
import sys
import pandas as pd
import network.utils as utils
import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
env = environ.Env()
environ.Env.read_env()


class Command(BaseCommand):
    def handle(self, *args, **options):
        try:
            print("Starting association score testing.")
            self.compute_association_scores()
            print(
                f'Finished association score testing successfully. The results were saved in {env("CALCULATED_EDGES_PATH")}')
        except Exception as e:
            print(f"Association score testing failed: {e}")
            sys.exit(1)

    def compute_association_scores(self):
        phenotypes = pd.read_csv(env("PHENOTYPE_PATH"), header=0, index_col=None).copy()
        phenotypes_meta = pd.read_csv(env("PHENOTYPE_META_PATH"), header=0, sep="\t",
                                      index_col=None).copy()  # Remove sep="\t" later, only relevant for our own data tables!

        if env("METABOLITE_PATH") is not None:
            metabolites = pd.read_csv(env("METABOLITE_PATH"), header=0, index_col=None).copy()
        else:
            metabolites = None
            print("No metabolites file was provided.")
        if env("PROTEIN_PATH") is not None:
            proteins = pd.read_csv(env("PROTEIN_PATH"), header=0, index_col=None).copy()
        else:
            proteins = None
            print("No proteins file was provided.")

        phenotypes['Patient ID'] = metabolites['Patient ID'] # Remove later, only relevant for our own data tables!

        number_of_workers = env("NUMBER_OF_WORKERS")
        test_type = env("TEST_TYPE")
        id_column = env("PATIENT_ID_COLUMN")

        results = utils.calculate_association_scores(phenotypes, phenotypes_meta, id_column, proteins, metabolites,
                                                     number_of_workers, test_type)
        results.to_csv(env("CALCULATED_EDGES_PATH"))
