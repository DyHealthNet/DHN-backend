from django.core.management.base import BaseCommand
import sys
import network.utils as utils
from network.score_calculation import calculate_association_scores
import environ
import traceback

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
            # print stack trace
            traceback.print_exc()
            print(f"Association score testing failed: {e}")
            sys.exit(1)

    @staticmethod
    def compute_association_scores():
        id_column = env("PATIENT_ID_COLUMN")

        phenotypes = utils.check_files_and_return(env("PHENOTYPE_PATH"), id_column=id_column)
        phenotypes_meta = utils.check_files_and_return(env("PHENOTYPE_META_PATH"))

        if env("METABOLITE_PATH") is not None:
            metabolites = utils.check_files_and_return(env("METABOLITE_PATH"), id_column=id_column)
        else:
            metabolites = None
            print("No metabolite file was provided.")

        if env("PROTEIN_PATH") is not None:
            proteins = utils.check_files_and_return(env("PROTEIN_PATH"), id_column=id_column)
        else:
            proteins = None
            print("No protein file was provided.")

        try:
            number_of_workers = int(env("NUMBER_OF_WORKERS"))
        except ValueError:
            number_of_workers = 16
            print(f"{env('NUMBER_OF_WORKERS')} is not an integer. 16 workers will be used per default now.",
                  "You might want to adjust this next time according to your resources.")

        test_type = env("TEST_TYPE")
        multiple_testing = env("MULTIPLE_TESTING")

        results = calculate_association_scores(phenotypes, phenotypes_meta, id_column, proteins, metabolites,
                                               number_of_workers, test_type, multiple_testing)
        results.to_csv(env("CALCULATED_EDGES_PATH"))

        # Subset the data to participents that are present in all provided data tables
        # common_indices = set(phenotypes.index)
        # if proteins is not None:
        #     common_indices = common_indices.intersection(proteins.index)
        # if metabolites is not None:
        #     common_indices = common_indices.intersection(metabolites.index)
        # common_indices = list(common_indices)
        #
        # results = utils.calculate_association_scores(phenotypes, phenotypes_meta, id_column,
        #                                              proteins.loc[common_indices] if proteins is not None else None,
        #                                              metabolites.loc[common_indices] if metabolites is not None else None,
        #                                              number_of_workers, test_type, multiple_testing)
        # results.to_csv(env("CALCULATED_EDGES_PATH"))
