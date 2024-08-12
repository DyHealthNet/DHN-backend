import math
import numpy as np
import scipy as si
import pandas as pd
import itertools
import concurrent.futures
from joblib import Parallel, delayed
from functools import partial
import environ

env = environ.Env()
environ.Env.read_env()


# Parallel processing functions
def parallel_process(items, num_workers, function_call):  # currently unused
    with concurrent.futures.ProcessPoolExecutor(max_workers=num_workers) as executor:
        results = executor.map(function_call, items)
    return list(results)


def multiprocess(items, num_workers, function_call):
    results = Parallel(n_jobs=num_workers)(delayed(function_call)(i) for i in items)

    return list(results)


# Categorical-Categorical association scores
def cat_cat(pair, phenotypes_cat):
    label1, label2 = pair
    temp_cat1 = np.array(phenotypes_cat[label1].unique())
    temp_cat2 = np.array(phenotypes_cat[label2].unique())
    categ1 = len(temp_cat1[~pd.isna(temp_cat1)])
    categ2 = len(temp_cat2[~pd.isna(temp_cat2)])

    if (categ1 < 2) or (categ2 < 2):
        return {
            'label1': label1,
            'label2': label2,
            'pval': 1,
            'effsize': 0,
            'effsize_type': None,
            'test': None
        }

    else:
        contingency_table = pd.crosstab(phenotypes_cat[label1], phenotypes_cat[label2])
        pval = si.stats.chi2_contingency(contingency_table, correction=True)[1]
        effsize = si.stats.contingency.association(contingency_table, correction=True, method='cramer')

        return {
            'label1': label1,
            'label2': label2,
            'pval': pval,
            'effsize': effsize,
            'effsize_type': 'Cramer´s v',
            'test': 'Chi-squared test'
        }


# Continuous-Categorical association scores
def cat_cont(pair, phenotypes_cat, cont_data, test):
    cont, cat = pair
    temp_cat = np.array(phenotypes_cat.iloc[:, cat].unique())
    categ = len(temp_cat[~pd.isna(temp_cat)])
    if (categ < 2):
        return {
            'label1': cont_data.columns[cont],
            'label2': phenotypes_cat.columns[cat],
            'pval': 1,
            'effsize': 0,
            'effsize_type': None,
            'test': None
        }
    elif (categ == 2):
        temp = [*(cont_data.iloc[:, cont].groupby(phenotypes_cat.iloc[:, cat], dropna=True).agg(list))]
        if test == 'parametric':
            r = si.stats.ttest_ind(temp[0], temp[1], nan_policy='omit')
            test_performed = 't-test'
        else:
            r = si.stats.mannwhitneyu(temp[0], temp[1], nan_policy='omit')
            test_performed = 'Mann–Whitney U test'
        # calculate cohens d by substracting mean of group 1 by mean of group 2 and dividing by pooled standard deviation
        cohens_d = abs(
            (np.mean(temp[0]) - np.mean(temp[1])) / (math.sqrt((np.std(temp[1]) ** 2 + np.std(temp[0]) ** 2) / 2)))
        return {
            'label1': cont_data.columns[cont],
            'label2': phenotypes_cat.columns[cat],
            'pval': r.pvalue,
            'effsize': cohens_d,
            'effsize_type': "Cohen's d",
            'test': test_performed
        }
    else:
        if test == 'parametric':
            r = si.stats.f_oneway(
                *(cont_data.iloc[:, cont].groupby(phenotypes_cat.iloc[:, cat], dropna=True).agg(list)),
                nan_policy='omit')
            # calculate eta squared using f-statistic (formula from Richardson (2011, Educational Research Review))
            eta_squared = (r.statistic * (categ - 1)) / ((r.statistic * (categ - 1)) + (len(cont_data) - categ))
            test_performed = 'one-way ANOVA test'
        else:
            # calculate eta squared using H-statistic (formula from Tomczak, "The need to report effect size estimates revisited.
            # An overview of some recommended measures of effect size."(2014).
            r = si.stats.kruskal(*(cont_data.iloc[:, cont].groupby(phenotypes_cat.iloc[:, cat], dropna=True).agg(list)),
                                 nan_policy='omit')
            eta_squared = (r.statistic - categ + 1) / (len(cont_data) - categ)
            test_performed = 'Kruskal–Wallis test'
        return {
            'label1': cont_data.columns[cont],
            'label2': phenotypes_cat.columns[cat],
            'pval': r.pvalue,
            'effsize': eta_squared,
            'effsize_type': "eta squared",
            'test': test_performed
        }


# Continuous-Continuous association scores
def cont_cont(pair, cont_data, test):
    label1, label2 = pair
    indices = np.isfinite(cont_data[label1]) * np.isfinite(cont_data[label2])
    if test == 'parametric':
        cor = si.stats.pearsonr(cont_data.loc[indices, label1], cont_data.loc[indices, label2])
        test_performed = 'Pearson correlation'
    else:
        cor = si.stats.spearmanr(cont_data.loc[indices, label1], cont_data.loc[indices, label2])
        test_performed = 'Spearman´s rank correlation'

    return {
        'label1': label1,
        'label2': label2,
        'pval': cor.pvalue,
        'effsize': cor.statistic,
        'effsize_type': 'correlation',
        'test': test_performed
    }


def testing(pairs, function_call, num_workers):
    results = pd.DataFrame(multiprocess(pairs, num_workers=num_workers, function_call=function_call))
    results['adj_pval'] = si.stats.false_discovery_control(results['pval'], method='bh')
    return results


def calculate_association_scores(phenotypes, phenotypes_meta, id_column, proteins=None, metabolites=None, workers=16,
                                 test='parametric'):
    # Data preprocessing
    phenotypes_cat = phenotypes.iloc[:, phenotypes.columns.isin(
        phenotypes_meta[phenotypes_meta.type.isin(["categorical", "boolean"])].label)].copy()
    cat_data = phenotypes_cat.copy()
    phenotypes_cat[id_column] = phenotypes[id_column]
    phenotypes_cont = phenotypes.iloc[:, phenotypes.columns.isin(
        phenotypes_meta[phenotypes_meta.type.isin(["integer", "float"])].label)].copy()
    phenotypes_cont[id_column] = phenotypes[id_column]

    if metabolites is not None:
        if proteins is not None:
            cont_data = pd.merge(metabolites, proteins, on=id_column)
            cont_data = pd.merge(cont_data, phenotypes_cont, on=id_column)
        else:
            cont_data = pd.merge(metabolites, phenotypes_cont, on=id_column)
    elif proteins is not None:
        cont_data = pd.merge(proteins, phenotypes_cont, on=id_column)
    else:
        cont_data = phenotypes_cont

    cont_data = cont_data.copy().drop(id_column, axis=1)
    cont_data = cont_data.select_dtypes(include=[np.number])

    # Create partial functions with the necessary additional arguments
    cat_cat_partial = partial(cat_cat, phenotypes_cat=cat_data)
    cat_cont_partial = partial(cat_cont, phenotypes_cat=cat_data, cont_data=cont_data, test=test)
    cont_cont_partial = partial(cont_cont, cont_data=cont_data, test=test)

    # Categorical-Categorical association testing
    pairs = list(itertools.combinations(cat_data.columns, 2))
    cat_cat_results = testing(pairs=pairs, function_call=cat_cat_partial, num_workers=workers)

    # Continuous-Continuous association testing
    pairs = list(itertools.combinations(cont_data.columns, 2))
    cont_cont_results = testing(pairs=pairs, function_call=cont_cont_partial, num_workers=workers)

    # Continuous-Categorical association testing
    pairs = ((a, b) for a in range(len(cont_data.columns)) for b in range(len(cat_data.columns)))
    cat_cont_results = testing(pairs=pairs, function_call=cat_cont_partial, num_workers=workers)

    scores = pd.concat([cat_cat_results, cont_cont_results, cat_cont_results], ignore_index=True)

    return scores
