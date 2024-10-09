import os
import pandas as pd
import numpy as np
from django.conf import settings
import logging

logger = logging.getLogger('django')


# Check file for correct format and return the dataset if needed
def check_files_and_return(path, id_column=None, column_list=None, return_dataset=True):
    # Check that provided pathways are leading to a csv or tsv file
    if path == "None" or path is None or path == "":
        return None

    ending = os.path.splitext(path)[1].lower()
    if ending not in ['.csv', '.tsv']:
        raise ValueError(f"Unsupported file format: {ending}. Only CSV and TSV files are supported.")
    # Set correct seperator according to ending
    sep = ',' if ending == '.csv' else '\t'

    logger.debug(f"Reading file {path}")
    dataset = pd.read_csv(path, header=0, sep=sep, index_col=None, low_memory=False).copy()

    # Check that id_column exists if provided
    if id_column:
        if id_column not in dataset.columns:
            raise KeyError(
                f"{path} does not have the correct ID column '{id_column}'. Please make sure that all files have the "
                f"same ID column.")
        else:
            dataset.set_index(id_column, inplace=True)  # set ID column
            # Check that columns in column_list exist if provided
            if column_list:
                for column in column_list:
                    if column not in dataset.columns:
                        raise KeyError(f"{path} is missing the column: '{column}'.")
                dataset = dataset[column_list]

    # Only return dataset if specified
    if return_dataset:
        return dataset

    else:
        return True


def list_node_variables(df, df2=None, type=None):
    if type == 'phenotype':
        return list_phenotype_variables(df, df2)
    elif type == 'protein':
        return list_protein_variables(df, df2)
    elif type == 'metabolite':
        return list_metabolite_variables(df)
    return None


def list_phenotype_variables(pheno_meta_filtered, phenotypes_filtered):
    def make_group(cols):
        ctype = cols['type']
        cnumcat = cols['num_cat']
        if ctype == 'integer' or ctype == 'float' or ctype == 'time':
            return 'continuous'
        elif cnumcat == 2:
            return 'binaryCategorical'
        return 'nonbinaryCategorical'

    # Get all variables with their type and a suitable identifier and put them in the same format
    # get Phenotype variables
    # get subtable of meta data for the variables that are actually in the simulated phenotypes dataset
    filtered_rows = pheno_meta_filtered[pheno_meta_filtered.index.isin(phenotypes_filtered.columns)]
    phenotypes_values = filtered_rows[[settings.PHENOTYPE_TYPE_COLUMN, settings.PHENOTYPE_DESCRIPTION_COLUMN]].copy()

    phenotypes_values.loc[:, 'num_cat'] = pd.Series(phenotypes_filtered.nunique())
    phenotypes_values.loc[:, 'group'] = phenotypes_values.loc[:, [settings.PHENOTYPE_TYPE_COLUMN, 'num_cat']].apply(
        make_group, axis=1)

    # if description is NaN only return the index
    phenotypes_values.loc[:, 'identifier'] = np.where(
        phenotypes_values[settings.PHENOTYPE_DESCRIPTION_COLUMN].isna(),
        phenotypes_values.index,
        phenotypes_values.apply(lambda row: f'{row[settings.PHENOTYPE_DESCRIPTION_COLUMN]} ({row.name})', axis=1)
    )

    phenotypes_values.drop(columns=[settings.PHENOTYPE_DESCRIPTION_COLUMN, 'num_cat', settings.PHENOTYPE_TYPE_COLUMN],
                           inplace=True)
    return phenotypes_values


def list_protein_variables(proteins_meta, proteins):
    protein_values = proteins_meta[proteins_meta.index.isin(proteins.columns)][
        [settings.PROTEIN_DESCRIPTION_COLUMN]].copy()

    # Create 'identifier' column based on conditions
    # (if description is NaN only return the index)
    protein_values['identifier'] = np.where(
        protein_values[settings.PROTEIN_DESCRIPTION_COLUMN].isna(),
        protein_values.index,
        protein_values.apply(lambda row: f'{row[settings.PROTEIN_DESCRIPTION_COLUMN]} / Protein ({row.name})',
                             axis=1)
    )

    protein_values.drop(columns=[settings.PROTEIN_DESCRIPTION_COLUMN], inplace=True)
    protein_values.loc[:, 'group'] = 'continuous'
    return protein_values


def list_metabolite_variables(metabolites):
    metabolite_values = pd.DataFrame(index=metabolites.columns,
                                     data={'identifier': metabolites.columns + ' / Metabolite'})
    metabolite_values.loc[:, 'group'] = 'continuous'
    return metabolite_values
