import os
from math import floor, ceil

import pandas as pd
from celery.result import AsyncResult
from django.core.cache import cache
from django.http import JsonResponse, HttpResponseBadRequest
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin

from rest_framework import generics

from network.utils.color_utils import define_context_color
from network.contexts.contexts import subset_patients, create_context_id, delete_context_tables
from network.models import UserContextLink, Context
from network.tasks import create_context_wrapper
from network.schemas.context_schemas import *
from network.utils.data_manager import DataManager

from drf_spectacular.utils import extend_schema_view
import logging

from network.utils.utils import var_label_mapping

logger = logging.getLogger('network')


@extend_schema_view(post=create_context_schema)
class CreateUserContext(LoginRequiredMixin, generics.GenericAPIView):
    login_url = settings.FRONTEND_HOME_URL
    data_manager: DataManager = None

    def post(self, request, *args, **kwargs):
        all_data, layers, meta_file = self.data_manager.get_df_copy(['all_data', 'layers', 'meta_file'])

        params = request.data
        if not params:
            return HttpResponseBadRequest('No parameters provided.', status=405)

        if params.get('testType') not in ('parametric', 'nonparametric'):
            return HttpResponseBadRequest(
                "Parameter 'testType' must be 'parametric' or 'nonparametric'.", status=405)

        if params.get('correction') not in ('bh', 'by'):
            return HttpResponseBadRequest(
                "Parameter 'correction' must be 'bh' or 'by'.", status=405)

        logger.debug(f"The user {request.user.username} has the id {request.user.id}")

        user_context_query = UserContextLink.objects.filter(user=request.user)
        for us_ctxt in user_context_query:
            status = us_ctxt.context_status
            logger.debug(f"Context {us_ctxt.context_id} has status {status}")
            if status == 'Pending':
                logger.debug(f"Another context task is pending. User cannot start a second context creation "
                             f"until finished")
                return JsonResponse({'status': 'error',
                                     'message': 'You can only start one context creation at a time.'}, status=429)

        user_objects_count = UserContextLink.objects.filter(user=request.user).count()
        if user_objects_count >= settings.MAX_CONTEXT_PER_USER:
            return JsonResponse({'status': 'error',
                                 'message': f'You can only create up to {settings.MAX_CONTEXT_PER_USER} objects.'},
                                status=429)

        logger.info(f"The user {request.user.username} can create another context.")

        # remove layers not requested
        context_data = all_data
        for layer in list(set(layers.keys()) - set(params['layers'])):
            logger.debug(f"Removing layer {layer} as it is not wanted in the context")
            context_data = context_data.drop(layers[layer], axis=1)

        params['colors'] = define_context_color(value=params.get('contextValue', 1) - 1)

        try:
            partial_data = subset_patients(context_data, params)
        except ValueError as ex:
            return HttpResponseBadRequest(str(ex), status=405)

        context_id = create_context_id()
        logger.info(f"Creating context with id {context_id}, {partial_data.shape[1]} variables, "
                    f"{partial_data.shape[0]} patients")

        try:
            cache.set(f'participants_context_{context_id}', partial_data.shape[0], timeout=3600 * 24 * 30)
        except Exception as ex:
            logger.error(f"Could not save subset data to cache: {ex}, too large?")

        # filter meta_file to variables present in partial_data and align partial_data to meta
        context_meta = meta_file[meta_file['label'].isin(partial_data.columns)].reset_index(drop=True)
        partial_data = partial_data[context_meta['label'].tolist()]

        folder_name = f"dyhealthnet-{context_id}"
        if not os.path.exists(f"/tmp/{folder_name}"):
            os.mkdir(f"/tmp/{folder_name}")

        context_file = f"/tmp/{folder_name}/context_data.pkl"
        partial_data.to_pickle(context_file)

        meta_file_path = f"/tmp/{folder_name}/meta_file.pkl"
        context_meta.to_pickle(meta_file_path)

        task = create_context_wrapper.delay(
            context_data=context_file,
            meta_file=meta_file_path,
            params=params,
            context_name=context_id,
            user_id=request.user.id,
        )

        logger.info(f"Context creation for {context_id} successfully started: {task}")
        return JsonResponse({'status': 'success', 'message': 'Context creation started'}, status=200)


@extend_schema_view(get=context_status_schema)
class ContextStatusView(LoginRequiredMixin, generics.GenericAPIView):
    login_url = settings.FRONTEND_HOME_URL

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
    data_manager: DataManager = None

    def post(self, request, *args, **kwargs):
        all_data, layers = self.data_manager.get_df_copy(['all_data', 'layers'])
        params = request.data
        if not params:
            return HttpResponseBadRequest('No subset parameters provided.', status=405)
        try:
            context_data = all_data
            for layer in list(set(layers.keys()) - set(params['layers'])):
                logger.debug(f"Removing layer {layer} as it is not wanted in the context")
                context_data = context_data.drop(layers[layer], axis=1)
            out_df = subset_patients(context_data, params)
        except ValueError as ex:
            return HttpResponseBadRequest(str(ex), status=405)

        remaining_users = out_df.shape[0]
        # for settings that want to preserve privacy, we only return the number of remaining users in the subset
        if settings.PRESERVE_PRIVACY:
            if remaining_users < settings.CRITICAL_NUMBER:
                remaining_users = 0
            else:
                remaining_users = max(settings.CRITICAL_NUMBER, int(round(remaining_users / 100) * 100))

        logger.info(f"Remaining users after subsetting: {remaining_users}")
        return JsonResponse({'result': remaining_users})


@extend_schema_view(delete=delete_context_schema)
class DeleteUserContext(generics.GenericAPIView):
    login_url = settings.FRONTEND_HOME_URL

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
                                status=401)

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
# Does this need OPENAPI specification if not accessible via API call? No.
class DeleteContext(generics.GenericAPIView):
    login_url = settings.FRONTEND_HOME_URL

    @staticmethod
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
    data_manager: DataManager = None

    def get(self, request):
        all_cat, all_cont, var_label_map = self.data_manager.get_df_copy(['all_cat', 'all_cont', 'var_label_map'])
        variable = request.GET.get("variableId")
        if variable is None:
            return HttpResponseBadRequest('No variableId provided.', status=400)

        # Get the variable information
        if variable in all_cat.columns:
            var_info = [int(x) for x in all_cat[variable].unique() if not pd.isna(x)]
            var_info = [{'label': var_label_mapping(variable, x, var_label_map), 'value': x} for x in var_info]
            bins = all_cat[variable].value_counts().sort_index()
            bin_labels = [str(x) for x in list(bins.index)]

        elif variable in all_cont.columns:
            var_info = all_cont[variable].min(), all_cont[variable].max()
            var_info = [floor(var_info[0]), ceil(var_info[1])]
            bins = pd.cut(all_cont[variable], bins=20).value_counts().sort_index()
            first = [str(bins.index[0]).split(",")[0].strip("(")]
            last = [str(bins.index[len(bins.index) - 1]).split(",")[1].strip("]")]
            if settings.PRESERVE_PRIVACY:
                first = [str(int(round(float(first[0]))))]
                last = [str(int(round(float(last[0]))))]
            # we're cheating here a little to make it better visible in the frontend
            bin_labels = first + [""] * (len(bins.index) - 3) + last + [""]
        else:
            return HttpResponseBadRequest('Variable not found.', status=404)

        return JsonResponse({'result': var_info,
                             'distribution': {'values': [int(x) for x in bins.values],
                                              'labels': bin_labels},
                             'type': 'bar' if variable in all_cat.columns else 'trend'})


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
