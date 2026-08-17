import logging

from celery.result import AsyncResult
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseBadRequest, JsonResponse
from rest_framework import generics

from network.tasks import run_community_annotation_task
from network.views.gemini import _require_gemini_configured

logger = logging.getLogger('network')


class RunCommunityAnnotationView(LoginRequiredMixin, generics.GenericAPIView):
    """
    Kicks off the Community Annotation batch job (g:Profiler + Reactome + Gemini for every
    community) as a background Celery task -- this can take several minutes, so it's dispatched
    rather than run inline. See CommunityAnnotationStatusView for polling and
    network.tasks.run_community_annotation_task for the actual work.
    """
    login_url = settings.FRONTEND_HOME_URL

    def post(self, request, *args, **kwargs):
        communities = request.data.get('communities')
        if not isinstance(communities, dict) or not communities:
            return HttpResponseBadRequest(
                "communities must be a non-empty object of community_id -> [node_id, ...]."
            )
        resolution = request.data.get('resolution')

        has_node_ids = any(isinstance(node_ids, list) and node_ids for node_ids in communities.values())
        if not has_node_ids:
            return HttpResponseBadRequest("communities must contain at least one node ID.")

        # Fail fast on a missing API key rather than spending minutes on g:Profiler/Reactome
        # calls only to be unable to produce labels at the end.
        not_configured = _require_gemini_configured()
        if not_configured is not None:
            return not_configured

        task = run_community_annotation_task.delay(communities, resolution)
        logger.info(
            "Community annotation run started: %s (%d communities)", task.id, len(communities),
        )
        return JsonResponse({'status': 'success', 'runId': task.id}, status=200)


class CommunityAnnotationStatusView(LoginRequiredMixin, generics.GenericAPIView):
    login_url = settings.FRONTEND_HOME_URL

    @staticmethod
    def get(request):
        run_id = request.GET.get('runId')
        if not run_id:
            return HttpResponseBadRequest('No runId provided.', status=400)

        task = AsyncResult(run_id)
        if task.status == 'FAILURE':
            # task.traceback is the formatted traceback string Celery stores separately from
            # the exception itself -- str(task.result) alone only gives the exception's message
            # (e.g. "cannot access local variable 'x'..."), not where it happened.
            logger.error("Community annotation run %s failed:\n%s", run_id, task.traceback)
            return JsonResponse(
                {'status': task.status, 'result': str(task.result), 'traceback': task.traceback}, status=200
            )
        return JsonResponse({'status': task.status, 'result': task.result})
