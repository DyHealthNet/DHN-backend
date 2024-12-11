import json
from functools import reduce

import numpy as np
import pandas as pd
from django.conf import settings
import logging
import napy as nanpy
import timeit

logger = logging.getLogger("network")

EXCLUDED_EFFECTS = {'chi2', 't', 'F', 'U', 'H'}


def df_to_numpy(df: pd.DataFrame):
    cols = df.columns
    df = df.fillna(settings.NAN_VALUE)
    df_np = df.to_numpy().astype(np.float64)
    return df_np, cols


def nanpy_formatting(assoc_out: dict[np.array], labels: list, test: str, file_name: str = None):
    start = timeit.default_timer()

    if not assoc_out:
        return None

    if len(labels) == 1:
        rows_idx, cols_idx = np.tril_indices(assoc_out['p_unadjusted'].shape[0], k=-1)
        # Pre-format labels and values
        label1 = np.array(labels[0])[rows_idx]
        label2 = np.array(labels[0])[cols_idx]
    else:
        rows_idx, cols_idx = np.indices(assoc_out['p_unadjusted'].shape)
        label1 = np.array(labels[0])[rows_idx.ravel()]
        label2 = np.array(labels[1])[cols_idx.ravel()]

    p_values_raw = {key: assoc_out[key][rows_idx, cols_idx].ravel() for key in assoc_out if key.startswith('p_')}
    effects_raw = {key: assoc_out[key][rows_idx, cols_idx].ravel() for key in assoc_out if not key.startswith('p_') and
                   key not in EXCLUDED_EFFECTS}

    p_columns = [f"{test}_{key}" for key in p_values_raw.keys()]
    e_columns = [f"{test}_e_{key}" for key in effects_raw.keys()]

    df = pd.DataFrame({
        'label1': label1,
        'label2': label2,
        **{p_columns[i]: p_values_raw[key] for i, key in enumerate(p_values_raw)},
        **{e_columns[i]: effects_raw[key] for i, key in enumerate(effects_raw)},
    })

    # remove all nan values with null
    # if df.isna().any().any():
    #     logger.debug("Removing %s NAs in dataframe", df.isnull().sum().sum())
    #     df = df.replace(np.nan, '')

    if settings.DROP_INSIGNIFICANT:
        logger.debug("Drop insignificant results")
        df = df[df[f"{test}_p_unadjusted"] < settings.ALPHA]

    if file_name:
        df.to_csv(file_name, sep=',', index=True, header=False, lineterminator='\n')

    logger.debug(f"Finished formatting of {test} with shape {df.shape} in {timeit.default_timer() - start:2f} seconds")
    return df


def combine_tests(cat_cat, cont_cont, cat_cont_b, cat_cont_m) -> pd.DataFrame:
    """
    Combine the non-parametric tests with the parametric tests, giving the non-parametric tests the suffix '_np'.
    If no non-parametric results are given, empty columns 'pval_np', 'effsize_np', 'test_np' are created.
    :param np_results: the non-parametric results
    :param p_results: the parametric results
    :return: results with both tests combined
    """
    merge_needed = False
    id_pairs = set()
    all_results = []
    start = timeit.default_timer()

    for results in [cat_cat, cont_cont, cat_cont_b, cat_cont_m]:
        for test in results:
            if test is None:
                continue
            all_results.append(test)
            test_pairs = set(zip(test['label1'], test['label2']))
            if id_pairs & test_pairs:
                merge_needed = True
            id_pairs.update(test_pairs)

    # Merge or concatenate results
    if merge_needed:
        logger.debug("Merging all results")
        out = reduce(lambda left, right: pd.merge(left, right, on=['label1', 'label2'], how='outer'), all_results)
    else:
        out = pd.concat(all_results, ignore_index=True)

    logger.debug(f"Finished combining of all results in {timeit.default_timer() - start:2f} seconds")

    return out


def nanpy_cat_cat(cat_phenotypes: pd.DataFrame):
    cat_phenotypes, cols = df_to_numpy(cat_phenotypes)
    output = nanpy.chi_squared(cat_phenotypes, axis=1, threads=settings.NUM_WORKERS, nan_value=settings.NAN_VALUE)
    return [nanpy_formatting(output, [cols], 'chi2')]


def nanpy_cat_cont(cont_phenotypes: pd.DataFrame, cat_phenotypes: pd.DataFrame, tests: str):
    # split cat_phenotypes into two dataframes, one with columns that contain only two unique values and one with more
    # than two unique values
    cat_phenotypes_more = cat_phenotypes.loc[:, cat_phenotypes.nunique() > 2]

    cont_phenotypes, cont_cols = df_to_numpy(cont_phenotypes)
    cat_phenotypes_more, cat_cols_more = df_to_numpy(cat_phenotypes_more)
    # this is just to shut the IDE up
    more_cont_out_a, more_cont_out_k = None, None
    done_test_a, done_test_k = None, None

    if tests in ['parametric', 'anova']:
        more_cont_out_a = nanpy.anova(cat_phenotypes_more, cont_phenotypes, axis=1,
                                      threads=settings.NUM_WORKERS)
        done_test_a = "anova"

    if tests in ['non-parametric', 'kruskal-wallis']:
        more_cont_out_k = nanpy.kruskal_wallis(cat_phenotypes_more, cont_phenotypes, axis=1,
                                               threads=settings.NUM_WORKERS)
        done_test_k = "kruskal"

    return [nanpy_formatting(more_cont_out_a, [cat_cols_more, cont_cols], done_test_a),
            nanpy_formatting(more_cont_out_k, [cat_cols_more, cont_cols], done_test_k)]


def nanpy_binary_cat_cont(cont_phenotypes: pd.DataFrame, cat_phenotypes: pd.DataFrame, test: str):
    """
    Do binary categorical-continuous association testing of binary categorical variables with continuous variables.
    As the binary categorical variables can be seen as a special case of the categorical variables, this function
    allows for the same tests as the categorical-continuous association testing. In addition, it also allows for
    tests specific to binary categorical variables.
    :param cont_phenotypes: DataFrame with continuous variables
    :param cat_phenotypes: DataFrame with binary categorical variables
    :param test: the test to perform
    :return: DataFrame with the results of the association testing
    """
    cat_phenotypes_two = cat_phenotypes.loc[:, cat_phenotypes.nunique() == 2]
    cont_phenotypes, cont_cols = df_to_numpy(cont_phenotypes)
    cat_phenotypes_two, cat_cols_two = df_to_numpy(cat_phenotypes_two)

    two_cont_out_t, two_cont_out_a, two_cont_out_m, two_cont_out_k = None, None, None, None
    done_test_t, done_test_a, done_test_m, done_test_k = None, None, None, None

    if test in ['all', 't-test']:
        logger.info("Doing parametric tests with shapes: %s and %s", cat_phenotypes_two.shape, cont_phenotypes.shape)
        two_cont_out_t = nanpy.ttest(cat_phenotypes_two, cont_phenotypes, axis=1,
                                     threads=settings.NUM_WORKERS)
        done_test_t = "ttest"
    if test in ['anova', 'all']:
        logger.info("Doing ANOVA tests with shapes: %s and %s", cat_phenotypes_two.shape, cont_phenotypes.shape)
        two_cont_out_a = nanpy.anova(cat_phenotypes_two, cont_phenotypes, axis=1,
                                     threads=settings.NUM_WORKERS)
        done_test_a = "anova"

    if test in ['all', 'mann-whitney u']:
        logger.debug("Doing non-parametric tests with shape: %s", cat_phenotypes_two.shape)
        two_cont_out_m = nanpy.mwu(cat_phenotypes_two, cont_phenotypes, axis=1, threads=settings.NUM_WORKERS)
        done_test_m = "mwu"

    if test in ['kruskal-wallis', 'all']:
        logger.debug("Doing Kruskal-Wallis tests with shape: %s", cat_phenotypes_two.shape)
        two_cont_out_k = nanpy.kruskal_wallis(cat_phenotypes_two, cont_phenotypes, axis=1, threads=settings.NUM_WORKERS)
        done_test_k = "kruskal"

    return [nanpy_formatting(two_cont_out_t, [cat_cols_two, cont_cols], done_test_t),
            nanpy_formatting(two_cont_out_a, [cat_cols_two, cont_cols], done_test_a),
            nanpy_formatting(two_cont_out_m, [cat_cols_two, cont_cols], done_test_m),
            nanpy_formatting(two_cont_out_k, [cat_cols_two, cont_cols], done_test_k)]


def nanpy_cont_cont(cont_phenotypes: pd.DataFrame, test: str):
    cont_phenotypes, cont_cols = df_to_numpy(cont_phenotypes)
    cont_out_p, cont_out_s = None, None
    test_p, test_s = None, None

    if test in ['pearson', 'all']:
        logger.debug("Doing Pearson correlation with shape: %s", cont_phenotypes.shape)
        cont_out_p = nanpy.pearsonr(cont_phenotypes, nan_value=settings.NAN_VALUE, threads=settings.NUM_WORKERS,
                                    axis=1)
        test_p = "pearson"

    if test in ['spearman', 'all']:
        logger.debug("Doing Spearman correlation with shape: %s", cont_phenotypes.shape)
        cont_out_s = nanpy.spearmanr(cont_phenotypes, threads=settings.NUM_WORKERS, axis=1)
        test_s = "spearman"
    return [nanpy_formatting(cont_out_p, [cont_cols], test_p),
            nanpy_formatting(cont_out_s, [cont_cols], test_s)]


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


def separate_cat_cont(all_data, phenotypes_meta) -> tuple[pd.DataFrame, pd.DataFrame] | tuple[None, None]:
    if isinstance(all_data, type(None)) or isinstance(phenotypes_meta, type(None)):
        return None, None
    logger.debug("Separating categorical and continuous phenotypes")
    cat_data = all_data.iloc[:, all_data.columns.isin(phenotypes_meta[phenotypes_meta.type.str.lower()
                                                      .isin(["categorical", "boolean"])].label)].copy()

    # Extract continuous phenotypes
    cont_data = all_data.iloc[:, ~all_data.columns.isin(phenotypes_meta[phenotypes_meta.type.str.lower()
                                                        .isin(["categorical", "boolean", "time"])].label)].copy()
    return cat_data, cont_data


def calculate_association_scores(cat_data, cont_data, tests: dict[str, dict] | str) -> pd.DataFrame:
    # subsample data for testing (only keep first 500 columns)
    # if settings.DEBUG:
    #     logger.debug("Subsampling data for testing")
    #     cont_data = cont_data.iloc[:, :500]
    #     cat_data = cat_data.iloc[:, :500]

    if isinstance(tests, str):
        tests = {'contCont': tests,
                 'catCat': tests,
                 'catContB': tests,
                 'catContM': tests}
    else:
        tests = {k: v.get('value') for k, v in tests.items()}

    cont_data = cont_data.copy()
    cont_data = cont_data.select_dtypes(include=[np.number])

    cat_data = order_categories(cat_data)

    logger.debug(f"Continuous data shape: {cont_data.shape}")
    logger.debug(f"Categorical data shape: {cat_data.shape}")

    logger.debug(f"Doing tests: {tests}")
    tests = {k: v.lower() for k, v in tests.items()}

    start = timeit.default_timer()

    cat_cat_results = nanpy_cat_cat(cat_data)
    logger.info("Finished categorical-categorical score creation")

    cont_cont_results = nanpy_cont_cont(cont_data, tests.get('contCont'))
    logger.info("Finished continuous-continuous score creation")

    # Continuous-Categorical association testing
    cat_cont_more = nanpy_cat_cont(cont_data, cat_data, tests.get('catContM'))
    cat_cont_two = nanpy_binary_cat_cont(cont_data, cat_data, tests.get('catContB'))
    logger.info("Finished continuous-categorical score creation")

    scores = combine_tests(cat_cat_results, cont_cont_results, cat_cont_two, cat_cont_more)
    logger.debug("%s pairwise association scores were calculated in %s seconds", scores.shape[0],
                 int(timeit.default_timer() - start))
    return scores
