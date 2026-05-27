import csv

from django.core.management.base import BaseCommand
import sys
import pandas as pd
import network.utils.startup_utils as utils
from network.score_calculation import calculate_association_scores
from django.apps import apps
from modina.context_net_inference import calculate_association_scores as modina_calculate_association_scores
import environ
from django.conf import settings
import traceback
import logging
import timeit
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
env = environ.Env(
    NUMBER_OF_WORKERS=(int, 16)
)
environ.Env.read_env()

logger = logging.getLogger("network")
config = apps.get_app_config('network')


def human_readable_size(num, suffix='B'):
    for unit in ['','K','M','G','T','P']:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}P{suffix}"


class Command(BaseCommand):
    def handle(self, *args, **options):
        try:
            logger.info("Starting association score testing.")
            #self.check_score_files()
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
        cat_columns = phenotypes_meta[phenotypes_meta.type.str.lower().isin(["categorical", "boolean"])]["label"].tolist()
        cat_data = phenotypes.loc[:, phenotypes.columns.isin(cat_columns)].copy()

        # Extract continuous phenotypes
        cont_columns = phenotypes_meta[phenotypes_meta.type.str.lower().isin(["integer", "float"])]["label"].tolist()
        cont_data = phenotypes.loc[:, phenotypes.columns.isin(cont_columns)].copy()

        cat_data.reset_index(inplace=True)
        cont_data.reset_index(inplace=True)

        # Merge metabolites and proteins to continuous phenotypes if provided
        if metabolites is not None:
            logger.debug(f"Metabolite data: {metabolites.shape[0]} samples, {metabolites.shape[1]} variables.")
            cont_data = pd.merge(metabolites, cont_data, on=id_column, how='outer')
        if proteins is not None:
            logger.debug(f"Protein data: {proteins.shape[0]} samples, {proteins.shape[1]} variables.")
            cont_data = pd.merge(proteins, cont_data, on=id_column, how='outer')

        # Check if all samples of cat_data are in cont_data and vice versa
        all_sample_ids = pd.DataFrame({id_column: pd.concat([cont_data[id_column], cat_data[id_column]]).unique()})
        cont_data = pd.merge(cont_data, all_sample_ids, on=id_column, how='outer')
        cat_data = pd.merge(cat_data, all_sample_ids, on=id_column, how='outer')

        cat_data.set_index(id_column, inplace=True)
        cont_data.set_index(id_column, inplace=True)

        return cat_data, cont_data


    @staticmethod
    def compute_association_scores():
        data_manager = config.DATA_MANAGER
        cat_data, cont_data = data_manager.get_df_copy(['all_cat', 'all_cont'])

        logger.debug(f"Using {env('NUMBER_OF_WORKERS')} workers for the calculation.")

        test_type = env("TEST_TYPE")

        start_dyhealthnet = timeit.default_timer()
        logger.info("DataManager returned DyHealthNet cat_data shape: %s, cont_data shape: %s",
                    cat_data.shape, cont_data.shape)
        results = calculate_association_scores(cat_data, cont_data, test_type)
        logger.info("DyHealthNet association calculation finished in %.2f seconds",
                    timeit.default_timer() - start_dyhealthnet)
        dy_path = f"{env('CALCULATED_EDGES_PATH')}_dyhealthnet_calculation"
        logger.info("Dyhealthnet Scores df shape: %s", results.shape)
        results.to_csv(dy_path, sep=',', index=True, lineterminator='\n')
        try:
            dy_size = os.path.getsize(dy_path)
            logger.info("DyHealthNet result written to %s (size: %s)", dy_path, human_readable_size(dy_size))
        except Exception:
            logger.warning("Could not determine size for DyHealthNet result file: %s", dy_path)

        ord_data, nom_data, modina_cont_data, bi_data = data_manager.get_df_copy(
            ['all_ordinal', 'all_nominal', 'all_continuous', 'all_binary']
        )
        modina_cont_data = modina_cont_data.select_dtypes(include='number').copy() if modina_cont_data is not None else None
        dropped_modina_cols = []
        if cont_data is not None and modina_cont_data is not None:
            dropped_modina_cols = [col for col in cont_data.columns if col not in modina_cont_data.columns]
        logger.info(
            "Modina continuous data shape after numeric filter: %s; dropped %s columns: %s",
            modina_cont_data.shape if modina_cont_data is not None else None,
            len(dropped_modina_cols),
            dropped_modina_cols,
        )
        logger.info(
            "Modina input shapes ord: %s, nom: %s, cont: %s, binary: %s",
            ord_data.shape if ord_data is not None else None,
            nom_data.shape if nom_data is not None else None,
            modina_cont_data.shape if modina_cont_data is not None else None,
            bi_data.shape if bi_data is not None else None,
        )
        if test_type == "all":
            start_parametric = timeit.default_timer()
            results_par = modina_calculate_association_scores(ord_data, nom_data, modina_cont_data, bi_data, test_type='parametric', num_workers=settings.NUM_WORKERS)
            logger.info("Modina parametric calculation finished in %.2f seconds",
                        timeit.default_timer() - start_parametric)

            start_nonparametric = timeit.default_timer()
            results_nonpar = modina_calculate_association_scores(ord_data, nom_data, modina_cont_data, bi_data, test_type='nonparametric', num_workers=settings.NUM_WORKERS)
            logger.info("Modina nonparametric calculation finished in %.2f seconds",
                        timeit.default_timer() - start_nonparametric)

            start_modina = timeit.default_timer()
            results = pd.concat([results_par, results_nonpar], axis=0, ignore_index=True)
            logger.info("Modina result concatenation finished in %.2f seconds",
                        timeit.default_timer() - start_modina)
            logger.info("Modina total calculation finished in %.2f seconds",
               timeit.default_timer() - start_parametric)
        else:
            start_modina = timeit.default_timer()
            results = modina_calculate_association_scores(ord_data, nom_data, modina_cont_data, bi_data, test_type=test_type, num_workers=settings.NUM_WORKERS)
            logger.info("Modina calculation finished in %.2f seconds",
                        timeit.default_timer() - start_modina)

        modina_path = f"{env('CALCULATED_EDGES_PATH')}_modina_calculation"
        logger.info("Modina Scores df shape: %s", results.shape)
        results.to_csv(modina_path, sep=',', index=True, lineterminator='\n')
        try:
            modina_size = os.path.getsize(modina_path)
            logger.info("Modina result written to %s (size: %s)", modina_path, human_readable_size(modina_size))
        except Exception:
            logger.warning("Could not determine size for Modina result file: %s", modina_path)

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
