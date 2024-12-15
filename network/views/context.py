import os
from math import floor, ceil

import pandas as pd
from celery.result import AsyncResult
from django.http import JsonResponse, HttpResponseBadRequest
from django.conf import settings
from django.apps import apps
from django.contrib.auth.mixins import LoginRequiredMixin

from rest_framework import generics

from network.utils.color_utils import define_context_color
from network.contexts.contexts import subset_patients, create_context_id, delete_context_tables
from network.models import UserContextLink, Context
from network.score_calculation import separate_cat_cont
from network.tasks import create_context_wrapper
from network.schemas.context_schemas import *

from drf_spectacular.utils import extend_schema_view
import logging
import environ

from network.utils.utils import var_label_mapping

env = environ.Env()
environ.Env.read_env()
logger = logging.getLogger('network')

config = apps.get_app_config('network')


@extend_schema_view(post=create_context_schema)
class CreateUserContext(LoginRequiredMixin, generics.GenericAPIView):
    login_url = env("FRONTEND_HOME_URL")

    # redirect_field_name = None
    # permission_denied_message = "You are not allowed here."
    def post(self, request, *args, **kwargs):
        params = request.data
        if not params:
            return HttpResponseBadRequest('No parameters provided.', status=405)

        logger.debug(f"The user {request.user.username} has the id {request.user.id}")

        user_context_query = UserContextLink.objects.filter(user=request.user)
        # Check that no other context is pending/calculating for that user
        for us_ctxt in user_context_query:
            status = us_ctxt.context_status
            logger.debug(f"Context {us_ctxt.context_id} has status {status}")
            if status == 'Pending':
                logger.debug(f"Another context task is pending. User cannot start a second context creation "
                             f"until finished")
                return JsonResponse({'status': 'error',
                                     'message': 'You can only start one context creation at a time.'}, status=429)

        # Probably not needed in the end as user can only have 5 Context tabs, but they might just call the API so we
        # should check here as well
        user_objects_count = UserContextLink.objects.filter(user=request.user).count()
        if user_objects_count >= settings.MAX_CONTEXT_PER_USER:
            return JsonResponse({'status': 'error',
                                 'message': f'You can only create up to {settings.MAX_CONTEXT_PER_USER} objects.'},
                                status=429)

        logger.info(f"The user {request.user.username} can create another context.")

        # nullth step: remove all layers that are not wanted as per params['layers']
        context_data = config.all_data.copy()
        for layer in list(set(config.LAYERS.keys()) - set(params['layers'])):
            logger.debug(f"Removing layer {layer} as it is not wanted in the context")
            context_data = context_data.drop(config.LAYERS[layer], axis=1)

        # first step: set a color for the context
        params['colors'] = define_context_color(value=params.get('contextValue', 1) - 1)

        # second step: subset the data
        try:
            partial_data = subset_patients(context_data, params)
        except ValueError as ex:
            return HttpResponseBadRequest(str(ex), status=405)

        # third step: get the context-name
        context_id = create_context_id()
        logger.info(f"Creating context with id {context_id}, has {partial_data.shape[1]} columns")

        # fourth step: separate the data into categorical and continuous data
        cat_data, cont_data = separate_cat_cont(partial_data, config.PHENO_META_LABEL)
        logger.info(f"Calculating association scores for context {context_id} with shapes {cat_data.shape} and "
                    f"{cont_data.shape}")

        # fifth step: save data to file in order to be able to load it in the celery task
        folder_name = f"dyhealthnet-{context_id}"
        if not os.path.exists(f"/tmp/{folder_name}"):
            os.mkdir(f"/tmp/{folder_name}")
        cont_file_name = f"/tmp/{folder_name}/cont.pkl"
        cont_data.to_pickle(cont_file_name)
        cat_file_name = f"/tmp/{folder_name}/cat.pkl"
        cat_data.to_pickle(cat_file_name)

        # seventh step: start the celery task
        task = create_context_wrapper.delay(cat_data=cat_file_name, cont_data=cont_file_name, params=params,
                                            context_name=context_id, user_id=request.user.id,
                                            protein_set=list(config.PROTEINS.columns),
                                            phenotype_set=list(config.PHENOTYPES.columns),
                                            metabolite_set=list(config.METABOLITES.columns), variant_set=[])

        logger.info(f"Context creation for {context_id} successfully started: {task}")
        return JsonResponse({'status': 'success', 'message': 'Context creation started'}, status=200)


@extend_schema_view(get=context_status_schema)
class ContextStatusView(LoginRequiredMixin, generics.GenericAPIView):
    login_url = env("FRONTEND_HOME_URL")

    @staticmethod
    def get(request):
        try:
            user_context = UserContextLink.objects.get(user_id=request.user.id,
                                                       context_value=request.GET.get("context_value"))
        except UserContextLink.DoesNotExist:
            return JsonResponse({'status': 'null', 'result': 'No Context for that User and that Tab created'},
                                status=200)
        task_id = user_context.context_task_id
        task = AsyncResult(task_id)
        if task.status == 'FAILURE':
            return JsonResponse({'status': task.status, 'result': 'Something went wrong!'}, status=200)
        return JsonResponse({'status': task.status, 'result': task.result})


@extend_schema_view(post=filter_context_schema)
class FilterUserContext(LoginRequiredMixin, generics.GenericAPIView):
    # login_url = env("FRONTEND_HOME_URL")

    def post(self, request, *args, **kwargs):
        params = request.data
        if not params:
            return HttpResponseBadRequest('No subset parameters provided.', status=405)
        try:
            context_data = config.all_data.copy()
            for layer in list(set(config.LAYERS.keys()) - set(params['layers'])):
                logger.debug(f"Removing layer {layer} as it is not wanted in the context")
                context_data = context_data.drop(config.LAYERS[layer], axis=1)
            out_df = subset_patients(context_data, params)
        except ValueError as ex:
            return HttpResponseBadRequest(str(ex), status=405)

        remaining_users = out_df.shape[0]
        # for settings that want to preserve privacy, we only return the number of remaining users in the subset
        if settings.PRESERVE_PRIVACY:
            remaining_users = int(round(remaining_users / 100) * 100)

        logger.info(f"Remaining users after subsetting: {remaining_users}")
        return JsonResponse({'result': remaining_users})


@extend_schema_view(delete=delete_context_schema)
class DeleteUserContext(generics.GenericAPIView):
    login_url = env("FRONTEND_HOME_URL")

    def delete(self, request, *args, **kwargs):
        try:
            data = request.data
        except AttributeError:
            return HttpResponseBadRequest('No data provided.', status=400)

        context_value = data.get('contextValue')
        if context_value is None:
            return HttpResponseBadRequest('No contextValue provided.', status=400)

        if not request.user.is_authenticated:
            return JsonResponse({'status': 'error', 'message': 'Permission denied. User not authenticated'},
                                status=400)  # 401?

        logger.debug(f"Delete UserContextLink and associates for user {request.user.id} "
                     f"and Context with value {context_value}")
        try:
            user_context = UserContextLink.objects.get(user_id=request.user.id, context_value=context_value)
        except UserContextLink.DoesNotExist:
            return HttpResponseBadRequest('Context not found.', status=404)

        # we explicitly never leak the context id to the frontend
        context_id = user_context.context_id

        # remove the context from the context table also
        Context.objects.get(context_id=int(context_id)).delete()
        delete_context_tables(context_id)

        user_context.delete()
        return JsonResponse({'status': 'success', 'message': 'Context deleted successfully'}, status=200)


# In case you have accidentally deleted the UserContextLink but not the Context(s), not frontend accessible
# Does this need OPENAPI specification if not accessible via API call?
class DeleteContext(generics.GenericAPIView):
    login_url = env("FRONTEND_HOME_URL")

    def delete(context_id):
        if context_id is None:
            return HttpResponseBadRequest('No data provided.', status=400)

        # remove the context from the context table also
        try:
            Context.objects.get(context_id=int(context_id)).delete()
        except UserContextLink.DoesNotExist:
            return HttpResponseBadRequest('Context not found.', status=404)
        delete_context_tables(context_id)

        return JsonResponse({'status': 'success', 'message': 'Context deleted successfully'}, status=200)


@extend_schema_view(get=variable_info_schema)
class VariableInfoView(generics.GenericAPIView):
    def get(self, request):
        variable = request.GET.get("variableId")
        if variable is None:
            return HttpResponseBadRequest('No variableId provided.', status=400)

        # Get the variable information
        if variable in config.ALL_CAT.columns:
            var_info = [int(x) for x in config.ALL_CAT[variable].unique() if not pd.isna(x)]
            var_info = [{'label': var_label_mapping(variable, x, config.VAR_LABEL_MAP), 'value': x} for x in var_info]
            bins = config.ALL_CAT[variable].value_counts().sort_index()

        elif variable in config.ALL_CONT.columns:
            var_info = config.ALL_CONT[variable].min(), config.ALL_CONT[variable].max()
            var_info = [floor(var_info[0]), ceil(var_info[1])]
            bins = pd.cut(config.ALL_CONT[variable], bins=20).value_counts().sort_index()
        else:
            return HttpResponseBadRequest('Variable not found.', status=404)

        return JsonResponse({'result': var_info,
                             'distribution': {'values': [int(x) for x in bins.values],
                                              'labels': [str(x) for x in list(bins.index)]},
                             'type': 'bar' if variable in config.ALL_CAT.columns else 'trend'})


@extend_schema_view(get=retrieve_context_schema)
class RetrieveContextsView(generics.GenericAPIView):
    def get(self, request):
        empty_context_field = {'contextName': '', 'contextValue': 0, 'colors': {}, 'content': None}
        default_colors = {'color': '#000000', 'lightVariant': '#000000', 'darkVariant': '#000000'}
        context_ids = []
        user = request.user.id
        # context id, value pairs
        for context_pair in UserContextLink.objects.filter(user_id=user).values_list('context_id', 'context_value'):
            context_ids.append(context_pair)
        result = []

        for i in range(1, settings.MAX_CONTEXT_PER_USER + 1):
            # check if value exists in context_ids, if not, add empty context field
            if i not in [x[1] for x in context_ids]:
                empty_field = empty_context_field.copy()
                empty_field['contextName'] = f'Context {i}'
                empty_field['contextValue'] = i
                empty_field['colors'] = default_colors
                empty_field['status'] = "Waiting"
                result.append(empty_field)
                continue
            # get the context with the corresponding id
            context = Context.objects.get(context_id=[x[0] for x in context_ids if x[1] == i][0])
            user_context = UserContextLink.objects.get(user_id=request.user.id,
                                                       context_id=context.context_id)
            task_status = user_context.context_status
            if task_status != "Finished":
                task_status = AsyncResult(user_context.context_task_id).status
                if task_status:
                    task_status = str(task_status).capitalize()
                    logger.debug(f"context {context.params['contextName']} status {task_status}")
                else:
                    task_status = 'Waiting'
            result.append({'contextName': context.params['contextName'],
                           'contextValue': i,
                           'colors': context.params.get('colors', default_colors),
                           'content': context.params, 'status': task_status})

        # check if there is a fields parameter in the request and if so, only return the requested fields
        fields = request.GET.get('fields')
        if fields:
            logger.debug(f"Requested fields: {fields}")
            result = [{key: value for key, value in context.items() if key in fields.split(',')} for context in result]

        return JsonResponse({'result': result}, status=200)
