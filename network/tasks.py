import os
import shutil

from celery import shared_task
import time
import pandas as pd
import json

from network.contexts.contexts import insert_context
from network.score_calculation import calculate_association_scores


@shared_task
def create_context_wrapper(cat_data: json, cont_data: json, params: dict, context_name: str, **kwargs):
    cat_data = pd.read_pickle(cat_data)
    cont_data = pd.read_pickle(cont_data)
    scores = calculate_association_scores(cat_data, cont_data, params['tests'])

    # insert context to db
    succ = insert_context(scores, context_name, **kwargs)

    dir_path = os.path.join('/tmp', context_name)
    if os.path.exists(dir_path) and os.path.isdir(dir_path):
        # Remove all files and subdirectories in the specified directory
        shutil.rmtree(dir_path)

    return succ


@shared_task
def test_task():
    print("Executed async test task")
    time.sleep(10)