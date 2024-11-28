import os
import shutil

from celery import shared_task
import time
import pandas as pd
import json

from network.models import Context
from network.contexts.contexts import insert_context
from network.score_calculation import calculate_association_scores

from django.contrib.auth.models import User
from network.models import UserContextLink

@shared_task
def create_context_wrapper(cat_data: json, cont_data: json, params: dict, context_name: str, user_id: int,**kwargs):
    cat_data = pd.read_pickle(cat_data)
    cont_data = pd.read_pickle(cont_data)
    scores = calculate_association_scores(cat_data, cont_data, params['tests'])

    # insert context to db
    success = insert_context(scores, context_name, **kwargs)

    # remove temp files created by my lack of RAM
    path_name = f"dyhealthnet-{context_name}"
    dir_path = os.path.join('/tmp', path_name)
    if os.path.exists(dir_path) and os.path.isdir(dir_path):
        shutil.rmtree(dir_path)

    if success:
        # extract relevant info from params and add it to db
        new_context = Context(context_id=context_name,
                              cat_cat_test=params['tests']['catCat'].lower(),
                              cont_cont_test=params['tests']['contCont'].lower(),
                              cat_cont_b_test=params['tests']['catContB'].lower(),
                              cat_cont_m_test=params['tests']['catContM'].lower(),
                              last_accessed=None,
                              params=params)
        new_context.save()
        user = User.objects.get(id=user_id)
        UserContextLink.objects.create(user_id=user, context_id=context_name, context_value=params['contextValue'])

    return success


@shared_task
def test_task():
    print("Executed async test task")
    time.sleep(10)
