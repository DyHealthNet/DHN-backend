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


def nanpy_formating(r2: np.array, pvalues: np.array, labels: list, effsize_type: str, test: str, file_name: str = None):
    start = timeit.default_timer()
    rows_idx, cols_idx = np.tril_indices(r2.shape[0], k=-1)

    # Pre-format labels and values
    label1 = np.array(labels)[rows_idx]
    label2 = np.array(labels)[cols_idx]
    pval = [r'"{\"full\": %s}"' % val for val in pvalues[rows_idx, cols_idx]]
    effsize = [r'"{\"full\": %s}"' % val for val in r2[rows_idx, cols_idx]]

    df = pd.DataFrame({
        'label1': label1,
        'label2': label2,
        'pval': pval,
        'effsize': effsize,
        'effsize_type': effsize_type,
        'test': test
    })

    if file_name:
        df.to_csv(file_name, sep=',', index=True, header=False, quoting=3, lineterminator='\n')

    logger.debug(f"Finished formatting of {test} in {timeit.default_timer() - start:2f} seconds")
    return df


def nanpy_cat_cat(cat_phenotypes: pd.DataFrame):
    cat_phenotypes, cols = df_to_numpy(cat_phenotypes)
    effsize, pval = nanpy.chi_squared(cat_phenotypes, axis=1, threads=settings.NUM_WORKERS, return_type='cramers_v',
                                      nan_value=settings.NAN_VALUE)
    return nanpy_formating(effsize, pval, cols, 'Cramer\'s v', 'Chi-squared test')


def nanpy_cat_cont(cont_phenotypes: pd.DataFrame, cat_phenotypes: pd.DataFrame, test: str):
    # split cat_phenotypes into two dataframes, one with columns that contain only two unique values and one with more
    # than two unique values
    cat_phenotypes_two = cat_phenotypes.loc[:, cat_phenotypes.nunique() == 2]
    cat_phenotypes_more = cat_phenotypes.loc[:, cat_phenotypes.nunique() > 2]

    cont_phenotypes, cont_cols = df_to_numpy(cont_phenotypes)
    cat_phenotypes_two, cat_cols_two = df_to_numpy(cat_phenotypes_two)
    cat_phenotypes_more, cat_cols_more = df_to_numpy(cat_phenotypes_more)

    if test == 'parametric':
        logger.debug("Doing parametric tests with shape: %s", cat_phenotypes_two.shape)
        cohens_d, pval = nanpy.ttest(cat_phenotypes_two, cont_phenotypes, axis=1,
                                     threads=settings.NUM_WORKERS, return_type='cohens_d', check_data=True)
        np2, pval_np2 = nanpy.anova(cat_phenotypes_more, cont_phenotypes, axis=1,
                                    threads=settings.NUM_WORKERS, return_type='np2', check_data=True)
        tests = (("ttest", "cohens_d"), ("anova", "np2"))
    else:
        logger.debug("Doing non-parametric tests with shape: %s", cat_phenotypes_two.shape)
        cohens_d, pval = nanpy.mwu(cat_phenotypes_two, cont_phenotypes, axis=1,
                                   threads=settings.NUM_WORKERS, mode='asymptotic')
        np2, pval_np2 = nanpy.kruskal_wallis(cat_phenotypes_more, cont_phenotypes, axis=1,
                                             threads=settings.NUM_WORKERS, return_type='eta2')
        tests = (("mwu", "cohens_d"), ("kruskal_wallis", "eta2"))
    # TODO: check if the columns are in the correct order for this type of test
    return nanpy_formating(cohens_d, pval, cont_cols, tests[0][1], tests[0][0]), \
        nanpy_formating(np2, pval_np2, cont_cols, tests[1][1], tests[1][0])


def nanpy_cont_cont(cont_phenotypes: pd.DataFrame, test: str):
    cont_phenotypes, cont_cols = df_to_numpy(cont_phenotypes)
    if test == 'parametric':
        logger.debug("Doing Pearson correlation with shape: %s", cont_phenotypes.shape)
        r2, pval = nanpy.pearsonr(cont_phenotypes, nan_value=settings.NAN_VALUE, threads=settings.NUM_WORKERS,
                                  axis=1, use_numba=False)
        test = "Pearson correlation"
    else:
        logger.debug("Doing Spearman correlation with shape: %s", cont_phenotypes.shape)
        r2, pval = nanpy.spearmanr(cont_phenotypes, threads=settings.NUM_WORKERS, axis=1, use_numba=False)
        test = "Spearman's rank correlation"
    return nanpy_formating(r2, pval, cont_cols, 'correlation', test)


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


def calculate_association_scores(phenotypes, phenotypes_meta, id_column, proteins=None, metabolites=None, workers=16,
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
    if settings.DEBUG:
        logger.debug("Subsampling data for testing")
        cont_data = cont_data.iloc[:, :500]
        cat_data = cat_data.iloc[:, :500]

    cont_data = cont_data.copy()
    cont_data = cont_data.select_dtypes(include=[np.number])

    cat_data = order_categories(cat_data)

    logger.debug(f"Continous data shape: {cont_data.shape}")
    logger.debug(f"Categorical data shape: {cat_data.shape}")

    cat_cat_results = nanpy_cat_cat(cat_data)
    logger.info("Finished categorical-categorical score creation")

    # Continuous-Continuous association testing
    cont_cont_results = nanpy_cont_cont(cont_data, test)
    logger.info("Finished continuous-continuous score creation")

    # Continuous-Categorical association testing
    cat_cont_two, cat_cont_more = nanpy_cat_cont(cont_data, cat_data, test)
    logger.info("Finished continuous-categorical score creation")

    scores = pd.concat([cat_cat_results, cont_cont_results, cat_cont_two, cat_cont_more], ignore_index=True)

    return scores
