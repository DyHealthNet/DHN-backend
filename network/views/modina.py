import os
import math
import uuid
import logging

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, HttpResponseBadRequest
from celery.result import AsyncResult
from rest_framework import generics
from drf_spectacular.utils import extend_schema_view

from network.contexts.contexts import subset_patients, restrict_variables
from network.utils.db_utils import get_context
from network.tasks import create_comparison_wrapper
from network.schemas.modina_schemas import *

logger = logging.getLogger('network')

# Comparing more shared variables than this without first reducing each context's own scores (via
# a 'context-specific' filter, applied before compute_diff_network runs) builds a differential
# network from the full O(n^2) pairwise score tables -- for thousands of variables that's tens of
# millions of candidate edges, too large to compute and return in one request. 'differential'
# filtering doesn't help here: it only trims edges_diff *after* compute_diff_network has already
# built it. See CreateComparisonView.post's threshold check below.
MODINA_CONTEXT_SPECIFIC_FILTER_THRESHOLD = 1000

# Hard ceiling on the number of edges a 'context-specific' filter is allowed to keep per context.
# 'density' (the only filter_method moDiNA_filter is ever called with -- see tasks.py) is a
# *fraction of all possible pairs*, which scales quadratically with variable count: a fixed
# density like 0.01 keeps ~320k edges at 8000 variables but barely a dozen at 50, so no single
# density value is safe as a blanket default. This caps the actual resulting edge count instead,
# independently of how many variables are involved or what density the user (or a prefilled
# default) picked -- see _density_target_edges/_suggested_density and their use in
# CreateComparisonView.post below.
MODINA_MAX_FILTERED_EDGES = 300000


def _density_target_edges(filter_param: float, variable_count: int) -> int:
    """
    Mirrors moDiNA's edge_filtering._num_target_edges('density', ...) formula -- duplicated here
    (rather than imported) since it's a private helper of the moDiNA package, but it's a single
    stable formula. Predicts exactly how many edges per context edge_filtering.filter() is about
    to keep for a 'context-specific' filter, using the same n_nodes (context1.shape[1], i.e. the
    already-resolved variable_count) filter() itself uses -- so this is exact, not an estimate.
    """
    possible_edges = variable_count * (variable_count - 1) / 2
    return math.ceil(filter_param * possible_edges)


def _suggested_density(variable_count: int, target_edges: int = MODINA_MAX_FILTERED_EDGES) -> float:
    """The largest density that keeps _density_target_edges at or under target_edges."""
    possible_edges = variable_count * (variable_count - 1) / 2
    if possible_edges <= 0:
        return 1.0
    return round(min(1.0, target_edges / possible_edges), 6)


def _resolve_context_data(user, context_value, all_data, layers, meta_file, layer_subgroups):
    """
    Reconstruct a context's raw per-patient subset the same way CreateUserContext does at context
    creation time, driven entirely by the persisted Context.params (filter conditions, and the
    selected-variable/missingness restriction via variables/variablesLayers/variablesSubLayers --
    Context.params has no separate top-level layers/subLayers field) -- the raw subset itself
    isn't kept around after context creation, but is deterministic given Context.params and the
    (static, process-wide)
    DataManager data, so it can be re-derived here.

    Deliberately does NOT subtract params['removedVariables'] here (unlike the overview page):
    two contexts built on the very same variable selection can still end up with different
    removedVariables sets, since moDiNA flags a variable as unusable independently per context
    (no signal in that context's patients). Restricting to each context's own post-removal
    columns here would make the "do these two contexts share the same variables" check below
    reject that case, even though it's exactly what compute_diff_network's own reconciliation
    (modina.statistics_utils.reconcile_flagged_variables) is built to handle transparently once
    both sides start from the same raw column set. Keeping the original selection here means that
    check instead reflects genuine, user-driven variable/layer selection differences.
    """
    context = get_context(user, context_value)
    if context is None:
        return None, None, None

    params = context.params
    # row-filter by the defined rules first (subset_patients only ever touches the
    # specific columns rule conditions reference, which are always a subset of the
    # selected variables, so this can run directly on all_data)
    partial_data = subset_patients(all_data, params)
    partial_data = restrict_variables(
        partial_data, params.get('variables'), params.get('variablesLayers'), params.get('variablesSubLayers'),
        params.get('missingnessVariables'), params.get('missingnessLayers'), params.get('missingnessSubLayers'),
        layers, layer_subgroups,
    )
    context_meta = meta_file[meta_file['label'].isin(partial_data.columns)].reset_index(drop=True)
    partial_data = partial_data[context_meta['label'].tolist()]
    return context, partial_data, context_meta


@extend_schema_view(post=create_comparison_schema)
class CreateComparisonView(LoginRequiredMixin, generics.GenericAPIView):
    login_url = settings.FRONTEND_HOME_URL
    data_manager = None

    def post(self, request, *args, **kwargs):
        all_data, layers, meta_file, layer_subgroups = self.data_manager.get_df_copy(
            ['all_data', 'layers', 'meta_file', 'layer_subgroups']
        )

        params = request.data
        if not params:
            return JsonResponse({'status': 'error', 'message': 'No parameters provided.'}, status=405)

        context1_value = params.get('context1')
        context2_value = params.get('context2')
        if context1_value is None or context2_value is None:
            return JsonResponse(
                {'status': 'error', 'message': "Both 'context1' and 'context2' must be provided."}, status=400)

        filter_target = params.get('filterTarget')
        if filter_target not in (None, 'context-specific', 'differential'):
            return JsonResponse({'status': 'error',
                                 'message': "Parameter 'filterTarget' must be 'context-specific', 'differential' "
                                            "or null."},
                                status=405)

        filter_metric = params.get('filterMetric')
        filter_rule = params.get('filterRule')
        filter_param = params.get('filterParam') or 1
        if filter_target == 'context-specific':
            if filter_metric not in ('raw-P', 'rescaled-E'):
                return JsonResponse({'status': 'error',
                                     'message': "Parameter 'filterMetric' must be 'raw-P' or 'rescaled-E' when "
                                                "'filterTarget' is 'context-specific'."},
                                    status=405)
            if filter_rule not in ('union', 'zero'):
                return JsonResponse({'status': 'error',
                                     'message': "Parameter 'filterRule' must be 'union' or 'zero' when "
                                                "'filterTarget' is 'context-specific'."},
                                    status=405)

        try:
            context1, data1, meta1 = _resolve_context_data(
                request.user, context1_value, all_data, layers, meta_file, layer_subgroups)
            context2, data2, meta2 = _resolve_context_data(
                request.user, context2_value, all_data, layers, meta_file, layer_subgroups)
        except ValueError as ex:
            return JsonResponse({'status': 'error', 'message': str(ex)}, status=405)

        if context1 is None or context2 is None:
            return JsonResponse(
                {'status': 'error', 'message': 'One or both contexts were not found for the current user.'},
                status=404)

        if len(data1.index.intersection(data2.index)) > 0:
            return JsonResponse({'status': 'error',
                                 'message': 'These contexts have overlapping patients, which would introduce '
                                            'statistical bias into the differential context analysis. Please '
                                            'choose two contexts with disjoint patient sets.'},
                                status=400)

        # data1/data2 reflect each context's original variable selection (see
        # _resolve_context_data), not what's left after moDiNA's own per-context removal -- so
        # this only rejects a genuine, user-driven selection mismatch. Variables that moDiNA
        # flagged as unusable in only one of the two contexts are still allowed through here; they
        # get reconciled out transparently inside compute_diff_network and reported to the caller
        # instead (see create_comparison_wrapper's excludedVariables).
        if not data1.columns.equals(data2.columns):
            return JsonResponse({'status': 'error',
                                 'message': 'The two contexts do not share the same set of variables. Please '
                                            'choose two contexts built on the same data layers.'},
                                status=400)

        variable_count = len(data1.columns)
        if variable_count > MODINA_CONTEXT_SPECIFIC_FILTER_THRESHOLD and filter_target != 'context-specific':
            suggested_density = _suggested_density(variable_count)
            return JsonResponse({
                'status': 'error',
                'requiresContextSpecificFilter': True,
                'variableCount': variable_count,
                'thresholdVariableCount': MODINA_CONTEXT_SPECIFIC_FILTER_THRESHOLD,
                'suggestedFilterParam': suggested_density,
                'message': (
                    f"These contexts share {variable_count} variables. Comparing more than "
                    f"{MODINA_CONTEXT_SPECIFIC_FILTER_THRESHOLD} variables without filtering first builds a "
                    "differential network from the full pairwise score tables, which is too large to compute "
                    "and return. Please choose the 'context-specific' filter (reduces each context's own "
                    "variables before the differential network is built) rather than 'differential' filtering, "
                    f"which only trims the result afterward and would not avoid this. A density around "
                    f"{suggested_density} would keep roughly {MODINA_MAX_FILTERED_EDGES} edges per context."
                ),
            }, status=400)

        # A 'context-specific' filter's actual resulting edge count is exact and known here (see
        # _density_target_edges) -- guard it regardless of whether it was just forced above or
        # chosen directly, and regardless of variable_count, since 'density' at a fixed value
        # scales quadratically: e.g. the default density of 1 (no filtering) already exceeds
        # MODINA_MAX_FILTERED_EDGES for as few as ~200 shared variables.
        if filter_target == 'context-specific':
            target_edges = _density_target_edges(filter_param, variable_count)
            if target_edges > MODINA_MAX_FILTERED_EDGES:
                suggested_density = _suggested_density(variable_count)
                return JsonResponse({
                    'status': 'error',
                    'filterParamTooHigh': True,
                    'variableCount': variable_count,
                    'targetEdgeCount': target_edges,
                    'maxFilteredEdges': MODINA_MAX_FILTERED_EDGES,
                    'suggestedFilterParam': suggested_density,
                    'message': (
                        f"With {variable_count} variables per context, a density of {filter_param} would keep "
                        f"up to {target_edges} edges per context -- more than the {MODINA_MAX_FILTERED_EDGES}-edge "
                        f"limit for this comparison. Please lower the Density setting (e.g. to {suggested_density}) "
                        "and try again."
                    ),
                }, status=400)

        # testType/correction are properties of each context's already-computed association
        # scores (fixed at context-creation time), not something to re-pick here -- we reuse the
        # stored edges_{test_type}_{context_id} tables rather than recomputing scores, so the two
        # contexts must already agree on both. (Future: offer to (re)compute a missing/mismatched
        # one instead of just rejecting.)
        test_type1, test_type2 = context1.params.get('testType'), context2.params.get('testType')
        correction1, correction2 = context1.params.get('correction'), context2.params.get('correction')
        if not test_type1 or not test_type2 or not correction1 or not correction2:
            return JsonResponse({'status': 'error',
                                 'message': "Both contexts must have already-computed association scores (a "
                                            "recorded 'testType' and 'correction') before they can be compared."},
                                status=400)
        if test_type1 != test_type2 or correction1 != correction2:
            return JsonResponse({'status': 'error',
                                 'message': 'The two contexts were built with different test types or correction '
                                            'methods, so their association scores are not directly comparable. '
                                            'Please choose two contexts that used the same test type and '
                                            'correction method.'},
                                status=400)

        run_id = str(uuid.uuid4())
        dir_path = os.path.join('/tmp', f'dyhealthnet-modina-{run_id}')
        os.mkdir(dir_path)

        context1_file = os.path.join(dir_path, 'context1.pkl')
        context2_file = os.path.join(dir_path, 'context2.pkl')
        meta_file_path = os.path.join(dir_path, 'meta_file.pkl')
        data1.to_pickle(context1_file)
        data2.to_pickle(context2_file)
        meta1.to_pickle(meta_file_path)

        settings_params = {
            'filterTarget': filter_target,
            'filterMetric': filter_metric,
            'filterRule': filter_rule,
            'filterParam': filter_param,
        }

        task = create_comparison_wrapper.delay(
            context1_data=context1_file,
            context2_data=context2_file,
            meta_file=meta_file_path,
            context1_id=context1.context_id,
            context2_id=context2.context_id,
            test_type=test_type1,
            correction=correction1,
            settings_params=settings_params,
            name1=context1.params.get('contextName', 'context1'),
            name2=context2.params.get('contextName', 'context2'),
            dir_path=dir_path,
        )

        logger.info(f"Differential network comparison started: {task.id}")
        return JsonResponse({'status': 'success', 'runId': task.id}, status=200)


@extend_schema_view(get=comparison_status_schema)
class ComparisonStatusView(LoginRequiredMixin, generics.GenericAPIView):
    login_url = settings.FRONTEND_HOME_URL

    @staticmethod
    def get(request):
        run_id = request.GET.get('runId')
        if not run_id:
            return HttpResponseBadRequest('No runId provided.', status=400)

        task = AsyncResult(run_id)
        if task.status == 'FAILURE':
            return JsonResponse({'status': task.status, 'result': str(task.result)}, status=200)
        return JsonResponse({'status': task.status, 'result': task.result})
