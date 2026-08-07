import os
import uuid
import logging

import pandas as pd
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, HttpResponseBadRequest
from celery.result import AsyncResult
from rest_framework import generics

from network.models import Nodes
from network.tasks import score_clustering_wrapper

logger = logging.getLogger('network')


class ScoreClusteringView(LoginRequiredMixin, generics.GenericAPIView):
    """
    Scores a community-detection clustering's biological coherence with biodigest.

    Deliberately doesn't assume which node type maps to which biodigest ID scheme -- the platform
    has no fixed identifier convention across node types (see network/models.py: Nodes.xrefs is a
    plain, deployment-configured string, not a typed/prefixed id). The caller must say explicitly
    which node_group to pull ('protein', 'metabolite', ...) and which biodigest ID scheme that
    group's xrefs actually are ('uniprot', 'mondo', ...) -- biodigest itself rejects an
    unsupported tarId, so we don't duplicate its supported-ID list here.
    """
    login_url = settings.FRONTEND_HOME_URL

    def post(self, request, *args, **kwargs):
        params = request.data
        clustering = params.get('clustering')
        node_group = params.get('nodeGroup')
        tar_id = params.get('tarId')
        if not clustering or not node_group or not tar_id:
            return JsonResponse(
                {'status': 'error', 'message': "'clustering' (node_id -> cluster label), 'nodeGroup' and "
                                                "'tarId' are all required."},
                status=400)

        distance = params.get('distance', 'jaccard')
        if distance not in ('jaccard', 'overlap'):
            return JsonResponse({'status': 'error', 'message': "'distance' must be 'jaccard' or 'overlap'."},
                                status=400)
        runs = params.get('runs', 1000)

        nodes = Nodes.objects.filter(node_id__in=clustering.keys(), node_group=node_group).values('node_id', 'xrefs')
        rows = []
        for node in nodes:
            xref_values = [x.strip() for x in (node['xrefs'] or '').split('|') if x.strip()]
            if not xref_values:
                continue
            # A node can carry more than one xref of the same scheme (e.g. multiple UniProt
            # accessions); biodigest maps one id per row, so just take the first -- ambiguous
            # multi-mapping isn't something it supports either way.
            rows.append({'id': xref_values[0], 'cluster': clustering[node['node_id']]})

        if not rows:
            return JsonResponse(
                {'status': 'error',
                 'message': f"None of the {len(clustering)} input nodes are of node_group={node_group!r} with a "
                            f"usable xref. Nothing to score."},
                status=400)

        run_id = str(uuid.uuid4())
        dir_path = os.path.join('/tmp', f'dyhealthnet-biodigest-{run_id}')
        os.mkdir(dir_path)
        clustering_file = os.path.join(dir_path, 'clustering.pkl')
        pd.DataFrame(rows, columns=['id', 'cluster']).to_pickle(clustering_file)

        task = score_clustering_wrapper.delay(
            clustering_data=clustering_file, dir_path=dir_path, node_group=node_group, tar_id=tar_id,
            input_node_count=len(clustering), distance=distance, runs=runs,
        )
        logger.info(f"biodigest clustering score started: {task.id}")
        return JsonResponse({'status': 'success', 'runId': task.id}, status=200)


class ScoreClusteringStatusView(LoginRequiredMixin, generics.GenericAPIView):
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
