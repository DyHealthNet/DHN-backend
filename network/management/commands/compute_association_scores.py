from django.core.management.base import BaseCommand
import sys
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
        id_column = env("PATIENT_ID_COLUMN")
        # The following will likely raise an error for our data, since the phenotypes table does not have the 'Patient ID' column!
        # TODO: Add the Patient ID column to our toy dataset
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

        # phenotypes['Patient ID'] = metabolites['Patient ID']  Remove this later!

        if not isinstance(env("NUMBER_OF_WORKERS"), int):
            number_of_workers = 16
            print(f"{env('NUMBER_OF_WORKERS')} is not an integer. 16 workers will be used per default now.",
                  "You might want to adjust this next time according to your resources.")
        else:
            number_of_workers = env("NUMBER_OF_WORKERS")

        test_type = env("TEST_TYPE")

        results = utils.calculate_association_scores(phenotypes, phenotypes_meta, id_column, proteins, metabolites,
                                                     number_of_workers, test_type)
        results.to_csv(env("CALCULATED_EDGES_PATH"))
