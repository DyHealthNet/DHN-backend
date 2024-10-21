import json

import numpy as np
import pandas as pd
from django.conf import settings
import logging
import nanpy
import timeit

logger = logging.getLogger("django")


def df_to_numpy(df: pd.DataFrame):
    cols = df.columns
    df = df.fillna(settings.NAN_VALUE)
    return df.to_numpy(), cols


def nanpy_formatting(assoc_out: dict[np.array], labels: list, test: str, file_name: str = None):
    start = timeit.default_timer()

    if len(labels) == 1:
        logger.debug("Expected combinations: %s", len(labels[0]) * (len(labels[0]) - 1) / 2)
        rows_idx, cols_idx = np.tril_indices(assoc_out['p_unadjusted'].shape[0], k=-1)
        # Pre-format labels and values
        label1 = np.array(labels[0])[rows_idx]
        label2 = np.array(labels[0])[cols_idx]
    else:
        logger.debug("Expected combinations: %s", len(labels[0]) * len(labels[1]))
        rows_idx, cols_idx = np.indices(assoc_out['p_unadjusted'].shape)
        label1 = np.array(labels[0])[rows_idx.ravel()]
        label2 = np.array(labels[1])[cols_idx.ravel()]

    p_values_raw = {key: assoc_out[key][rows_idx, cols_idx].ravel() for key in assoc_out if key.startswith('p_')}
    effects_raw = {key: assoc_out[key][rows_idx, cols_idx].ravel() for key in assoc_out if not key.startswith('p_')}

    p_keys = list(p_values_raw.keys())
    e_keys = list(effects_raw.keys())

    # Pre-construct parts of the strings to avoid repeated operations in the loop
    p_template = '{' + ', '.join([f'"{k}": %f' for k in p_keys]) + '}'
    e_template = '{' + ', '.join([f'"{k}": %f' for k in e_keys]) + '}'

    p_values = [
        p_template % tuple(p_values_raw[k][i] for k in p_keys)
        for i in range(len(p_values_raw['p_unadjusted']))
    ]
    effects = [
        e_template % tuple(effects_raw[k][i] for k in e_keys)
        for i in range(len(p_values_raw['p_unadjusted']))
    ]

    df = pd.DataFrame({
        'label1': label1,
        'label2': label2,
        'pval': p_values,
        'effsize': effects,
        'test': test
    })
    logger.debug("Output shape of %s: %s", test, df.shape)

    if file_name:
        df.to_csv(file_name, sep=',', index=True, header=False, lineterminator='\n')

    logger.debug(f"Finished formatting of {test} in {timeit.default_timer() - start:2f} seconds")
    return df


def nanpy_cat_cat(cat_phenotypes: pd.DataFrame):
    cat_phenotypes, cols = df_to_numpy(cat_phenotypes)
    output = nanpy.chi_squared(cat_phenotypes, axis=1, threads=settings.NUM_WORKERS, nan_value=settings.NAN_VALUE)
    return nanpy_formatting(output, [cols], 'Chi-squared test')


def nanpy_cat_cont(cont_phenotypes: pd.DataFrame, cat_phenotypes: pd.DataFrame, test: str):
    # split cat_phenotypes into two dataframes, one with columns that contain only two unique values and one with more
    # than two unique values
    cat_phenotypes_two = cat_phenotypes.loc[:, cat_phenotypes.nunique() == 2]
    cat_phenotypes_more = cat_phenotypes.loc[:, cat_phenotypes.nunique() > 2]

    cont_phenotypes, cont_cols = df_to_numpy(cont_phenotypes)
    cat_phenotypes_two, cat_cols_two = df_to_numpy(cat_phenotypes_two)
    cat_phenotypes_more, cat_cols_more = df_to_numpy(cat_phenotypes_more)

    if test == 'parametric':
        logger.info("Doing parametric tests with shapes: %s and %s", cat_phenotypes_two.shape, cont_phenotypes.shape)
        two_cont_out = nanpy.ttest(cat_phenotypes_two, cont_phenotypes, axis=1,
                                   threads=settings.NUM_WORKERS, use_numba=True)
        logger.debug("Ttest done")
        more_cont_out = nanpy.anova(cat_phenotypes_more, cont_phenotypes, axis=1,
                                    threads=settings.NUM_WORKERS)
        tests = ("ttest", "anova")

    else:
        logger.debug("Doing non-parametric tests with shape: %s", cat_phenotypes_two.shape)
        two_cont_out = nanpy.mwu(cat_phenotypes_two, cont_phenotypes, axis=1,
                                   threads=settings.NUM_WORKERS)
        more_cont_out = nanpy.kruskal_wallis(cat_phenotypes_more, cont_phenotypes, axis=1,
                                             threads=settings.NUM_WORKERS)
        tests = ("mwu", "kruskal_wallis")

    return nanpy_formatting(two_cont_out, [cat_cols_two, cont_cols], tests[0], tests[1]), \
        nanpy_formatting(more_cont_out, [cat_cols_more, cont_cols], tests[0], tests[1])


def nanpy_cont_cont(cont_phenotypes: pd.DataFrame, test: str):
    cont_phenotypes, cont_cols = df_to_numpy(cont_phenotypes)
    if test == 'parametric':
        logger.debug("Doing Pearson correlation with shape: %s", cont_phenotypes.shape)
        cont_out = nanpy.pearsonr(cont_phenotypes, nan_value=settings.NAN_VALUE, threads=settings.NUM_WORKERS,
                                  axis=1, use_numba=True)
        test = "Pearson correlation"

    else:
        logger.debug("Doing Spearman correlation with shape: %s", cont_phenotypes.shape)
        cont_out = nanpy.spearmanr(cont_phenotypes, threads=settings.NUM_WORKERS, axis=1, use_numba=True)
        test = "Spearman's rank correlation"
    return nanpy_formatting(cont_out, [cont_cols], test)


def order_categories(data: pd.DataFrame):
    """
    Order categories in a dataframe such that they start at 0 and are consecutive integers.
    :param data: the dataframe to order
    :return: the ordered dataframe
    """
    data = data.copy()
    order_table = {col: {o: n for n, o in enumerate(sorted(data[col].unique()))} for col in data.columns}
    for col, mapping in order_table.items():
        data[col] = data[col].map(mapping).fillna(settings.NAN_VALUE).astype(int)
    return data


def calculate_association_scores(phenotypes, phenotypes_meta, id_column, proteins=None, metabolites=None,
                                 test='parametric', multiple_testing='bh'):
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
        cont_data = pd.merge(metabolites, cont_data, on=id_column)
    if proteins is not None:
        cont_data = pd.merge(proteins, cont_data, on=id_column)

    # make ID column the index
    cont_data.set_index(id_column, inplace=True)

    # subsample data for testing (only keep first 500 columns)
    # if settings.DEBUG:
    #     logger.debug("Subsampling data for testing")
    #     cont_data = cont_data.iloc[:, :500]
    #     cat_data = cat_data.iloc[:, :500]

    cont_data = cont_data.copy()
    cont_data = cont_data.select_dtypes(include=[np.number])

    cat_data = order_categories(cat_data)

    logger.debug(f"Continous data shape: {cont_data.shape}")
    logger.debug(f"Categorical data shape: {cat_data.shape}")

    start = timeit.default_timer()

    cat_cat_results = nanpy_cat_cat(cat_data)
    logger.info("Finished categorical-categorical score creation")

    # Continuous-Continuous association testing
    cont_cont_results = nanpy_cont_cont(cont_data, test)
    logger.info("Finished continuous-continuous score creation")

    # Continuous-Categorical association testing
    # cat_cont_two, cat_cont_more = nanpy_cat_cont(cont_data, cat_data, test)
    logger.info("Finished continuous-categorical score creation")

    # scores = pd.concat([cat_cat_results, cont_cont_results, cat_cont_two, cat_cont_more], ignore_index=True)
    scores = pd.concat([cat_cat_results, cont_cont_results], ignore_index=True)
    logger.debug("%s pairwise association scores were calculated in %s seconds", scores.shape[0],
                 int(timeit.default_timer() - start))

    return scores
