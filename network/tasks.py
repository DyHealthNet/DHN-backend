import os
import shutil

from celery import shared_task
import time
import pandas as pd
from django.conf import settings

from network.models import Context, UserContextLink
from network.contexts.contexts import insert_context
from modina.context_net_inference import compute_context_scores


@shared_task(bind=True)
def create_context_wrapper(self, context_data: str, meta_file: str, params: dict,
                           context_name: str, user_id: int):
    new_context = Context(context_id=context_name,
                          last_accessed=None,
                          params=params)
    new_context.save()

    if UserContextLink.objects.filter(user_id=user_id, context_value=params['contextValue']).exists():
        UserContextLink.objects.filter(user_id=user_id, context_value=params['contextValue']).delete()
    user_context_link = UserContextLink.objects.create(
        user_id=user_id, context_id=context_name,
        context_value=params['contextValue'], context_task_id=self.request.id)

    context_df = pd.read_pickle(context_data)
    meta_df = pd.read_pickle(meta_file)

    test_type = params.get('testType')
    correction = params.get('correction')

    try:
        if test_type not in ('parametric', 'nonparametric'):
            raise ValueError(f"Parameter 'testType' must be 'parametric' or 'nonparametric', got {test_type!r}.")
        if correction not in ('bh', 'by'):
            raise ValueError(f"Parameter 'correction' must be 'bh' or 'by', got {correction!r}.")
        scores = compute_context_scores(
            context_data=context_df,
            meta_file=meta_df,
            test_type=test_type,
            correction=correction,
            num_workers=settings.NUM_WORKERS,
            nan_value=settings.NAN_VALUE,
        )
        success = insert_context(scores, context_name, test_type)
    except Exception as e:
        print(e)
        success = False

    path_name = f"dyhealthnet-{context_name}"
    dir_path = os.path.join('/tmp', path_name)
    if os.path.exists(dir_path) and os.path.isdir(dir_path):
        shutil.rmtree(dir_path)

    if not success:
        UserContextLink.objects.filter(
            user_id=user_id, context_id=context_name,
            context_value=params['contextValue']).delete()
        Context.objects.filter(context_id=context_name).delete()
        return False

    user_context_link.context_status = "Finished"
    user_context_link.save()
    return success


@shared_task
def test_task():
    print("Executed async test task")
    time.sleep(10)
