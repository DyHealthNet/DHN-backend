import csv

from django.core.management.base import BaseCommand
import sys
import pandas as pd
import network.utils as utils
from network.score_calculation import calculate_association_scores
import environ
import traceback
import logging

# Build paths inside the project like this: BASE_DIR / 'subdir'.
env = environ.Env(
    NUMBER_OF_WORKERS=(int, 16)
)
environ.Env.read_env()

logger = logging.getLogger("network")


class Command(BaseCommand):
    def handle(self, *args, **options):
        try:
            logger.info("Starting association score testing.")
            self.compute_association_scores()
            logger.info(f'Finished association score testing successfully. '
                        f'The results were saved in {env("CALCULATED_EDGES_PATH")}')
        except Exception as e:
            # print stack trace
            traceback.print_exc()
            logger.error(f"Association score testing failed: {e}")
            sys.exit(1)

    def preprocess_data(self, phenotypes, phenotypes_meta, id_column, metabolites=None, proteins=None):
        # Data preprocessing
        allowed_types = ['boolean', 'categorical', 'float', 'integer']
        # Check if all types of phenotype variables are in the allowed list
        invalid_types = phenotypes_meta[~phenotypes_meta.type.str.lower().isin(allowed_types)]
        if not invalid_types.empty:
            logger.warning(f"Invalid variable types were found: {invalid_types.type.unique()}. "
                           f"These variables will be ignored.")

        # Extract categorical phenotypes
        phenotypes_cat = phenotypes.iloc[:, phenotypes.columns.isin(
            phenotypes_meta[phenotypes_meta.type.str.lower().isin(["categorical", "boolean"])].label)].copy()
        cat_data = phenotypes_cat.copy()

        # Extract continuous phenotypes
        phenotypes_cont = phenotypes.iloc[:, phenotypes.columns.isin(
            phenotypes_meta[phenotypes_meta.type.str.lower().isin(["integer", "float"])].label)].copy()
        phenotypes_cont = phenotypes_cont.reset_index()
        phenotypes_cont[id_column] = phenotypes.index

        # Merge metabolites and proteins to continuous phenotypes if provided
        cont_data = phenotypes_cont
        if metabolites is not None:
            logger.debug(f"Metabolite data: {metabolites.shape[0]} samples, {metabolites.shape[1]} variables.")
            cont_data = pd.merge(metabolites, cont_data, on=id_column)
        if proteins is not None:
            logger.debug(f"Protein data: {proteins.shape[0]} samples, {proteins.shape[1]} variables.")
            cont_data = pd.merge(proteins, cont_data, on=id_column)

        # make ID column the index
        cont_data.set_index(id_column, inplace=True)
        logger.debug(f"Total data: {phenotypes.shape[0]} samples, {phenotypes.shape[1]} variables.")
        return cat_data, cont_data


    @staticmethod
    def compute_association_scores():
        id_column = env("PATIENT_ID_COLUMN")

        phenotypes = utils.check_files_and_return(env("PHENOTYPE_PATH"), id_column=id_column)
        phenotypes_meta = utils.check_files_and_return(env("PHENOTYPE_META_PATH"))
        # rename the column PHENOTYPE_TYPE_COLUMN to "type" to work with the calculate_association_scores function
        phenotypes_meta = phenotypes_meta.rename(columns={env("PHENOTYPE_TYPE_COLUMN"): "type"})

        if env("METABOLITE_PATH") is not None:
            metabolites = utils.check_files_and_return(env("METABOLITE_PATH"), id_column=id_column)
        else:
            metabolites = None
            logger.warning("No metabolite file was provided.")

        if env("PROTEIN_PATH") is not None:
            proteins = utils.check_files_and_return(env("PROTEIN_PATH"), id_column=id_column)
        else:
            proteins = None
            logger.warning("No protein file was provided.")

        logger.debug(f"Using {env('NUMBER_OF_WORKERS')} workers for the calculation.")

        test_type = env("TEST_TYPE")

        cat_data, cont_data = Command().preprocess_data(phenotypes, phenotypes_meta, id_column, metabolites, proteins)

        results = calculate_association_scores(cat_data, cont_data, test_type)
        results.to_csv(env("CALCULATED_EDGES_PATH"), sep=',', index=True, lineterminator='\n')

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
