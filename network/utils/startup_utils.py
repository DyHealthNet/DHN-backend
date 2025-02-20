import os
import pandas as pd
import logging
from django.conf import settings
import numpy as np

logger = logging.getLogger('network')


def join_dataframes(dataframes: list):
    """
    Joins together all dataframes in the list with an inner join on the index
    :param dataframes: list of dataframes
    :return: joined dataframe
    """
    filled_dfs = [df for df in dataframes if df is not None]
    if not filled_dfs:
        raise ValueError("No dataframes to join")

    result = filled_dfs[0]

    for df in filled_dfs[1:]:
        result = pd.merge(result, df, left_index=True, right_index=True, how='outer')
    logger.debug(f"Joined dataframes has shape: {result.shape}")
    return result


def check_files_and_return(path, id_column=None, column_list=None, return_dataset=True):
    # Check that provided pathways are leading to a csv or tsv file
    if path == "None" or path is None or path == "" or not os.path.exists(path):
        return None

    file_name, ending = os.path.splitext(path)
    ending = ending.lower()
    if ending not in ['.csv', '.tsv']:
        raise ValueError(f"Unsupported file format: {ending}. Only CSV and TSV files are supported.")

    parquet_file = f"{file_name}.parquet"

    if not os.path.exists(parquet_file):
        logger.info("Creating parquet file")
        # Set correct seperator according to ending
        sep = ',' if ending == '.csv' else '\t'
        df = pd.read_csv(path, sep=sep, index_col=None, low_memory=False)
        df.to_parquet(parquet_file)

    logger.debug(f"Reading file {parquet_file}")
    dataset = pd.read_parquet(parquet_file)

    # NA_value to real nan
    dataset.replace(settings.NAN_VALUE, np.nan, inplace=True)

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


def get_file_attr(path, default=None):
    """
    Helper function to make traversing through INPUT_FILES setting easier
    :param path: dot-separated path to the desired attribute
    :param default: default value to return if the attribute is not found
    :return: attribute at the given path or the default value
    """
    current = settings.INPUT_FILES
    for key in path.split('.'):
        current = current.get(key, default)
        if current is default:
            break
    return current
