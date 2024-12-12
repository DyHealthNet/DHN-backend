import os
import pandas as pd
import logging

logger = logging.getLogger('network')


def join_dataframes(dataframes: list):
    """
    Joins together all dataframes in the list with an inner join on the index
    :param dataframes: list of dataframes
    :return: joined dataframe
    """
    result = dataframes[0]
    for df in dataframes[1:]:
        result = pd.merge(result, df, left_index=True, right_index=True, how='inner')
    return result


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
