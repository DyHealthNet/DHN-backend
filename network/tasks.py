import os
import shutil

from celery import shared_task, current_task
import time
import pandas as pd
import json

from django.http import HttpResponseServerError

from network.models import Context
from network.contexts.contexts import insert_context
from network.score_calculation import calculate_association_scores

from network.models import UserContextLink
#from network.views import DeleteContext

@shared_task(bind=True)
def create_context_wrapper(self, cat_data: json, cont_data: json, params: dict, context_name: str, user_id: int, **kwargs):
    # extract relevant info from params and add it to db
    new_context = Context(context_id=context_name,
                          cat_cat_test=params['tests']['catCat']['value'],
                          cont_cont_test=params['tests']['contCont']['value'],
                          cat_cont_b_test=params['tests']['catContB']['value'],
                          cat_cont_m_test=params['tests']['catContM']['value'],
                          last_accessed=None,
                          params=params)

    new_context.save()
    if UserContextLink.objects.filter(user_id=user_id, context_value=params['contextValue']).exists():
        UserContextLink.objects.filter(user_id=user_id, context_value=params['contextValue']).delete()
    user_context_link = UserContextLink.objects.create(user_id=user_id, context_id=context_name,
                                   context_value=params['contextValue'], context_task_id=self.request.id)

    cat_data = pd.read_pickle(cat_data)
    cont_data = pd.read_pickle(cont_data)
    try:
        scores = calculate_association_scores(cat_data, cont_data, params['tests'])
        # insert context to db
        success = insert_context(scores, context_name, **kwargs)
    except Exception as e:
        print(e)
        success = False

    # remove temp files created by my lack of RAM
    path_name = f"dyhealthnet-{context_name}"
    dir_path = os.path.join('/tmp', path_name)
    if os.path.exists(dir_path) and os.path.isdir(dir_path):
        shutil.rmtree(dir_path)

    if not success:
        UserContextLink.objects.filter(user_id=user_id, context_id=context_name, context_value=params['contextValue']).delete()
        Context.objects.filter(context_id=context_name).delete()
        # DeleteContext.delete(context_id=context_name) not needed if insertion is atomic / all or nothing
        return False

    user_context_link.context_status = "Finished"
    user_context_link.save()

    return success


@shared_task
def test_task():
    print("Executed async test task")
    time.sleep(10)
