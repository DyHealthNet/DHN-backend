import logging

import requests
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, HttpResponseBadRequest
from rest_framework import generics

from network.models import Nodes

logger = logging.getLogger('network')


class ScoreClusteringView(LoginRequiredMixin, generics.GenericAPIView):
    """
    Scores a community-detection clustering's biological coherence via a self-hosted DIGEST API
    instance (see docker-compose.digest.yml, DIGEST_API_BASE_URL) -- DIGEST does its own async
    execution (its own celery worker), so this is a thin proxy: submit here, poll
    ScoreClusteringStatusView with the runId DIGEST hands back.

    Deliberately doesn't assume which node type maps to which DIGEST ID scheme -- the platform
    has no fixed identifier convention across node types (see network/models.py: Nodes.xrefs is a
    plain, deployment-configured string, not a typed/prefixed id). The caller must say explicitly
    which node_group to pull ('protein', 'metabolite', ...), which DIGEST ID scheme that group's
    xrefs actually are ('uniprot', 'mondo', ...), and which DIGEST category that scheme falls
    under ('gene' or 'disease') -- DIGEST itself rejects an unsupported tarId, so we don't
    duplicate its supported-ID list here.
    """
    login_url = settings.FRONTEND_HOME_URL

    def post(self, request, *args, **kwargs):
        params = request.data
        clustering = params.get('clustering')
        node_group = params.get('nodeGroup')
        tar_id = params.get('tarId')
        target_type = params.get('type')
        if not clustering or not node_group or not tar_id or not target_type:
            return JsonResponse(
                {'status': 'error', 'message': "'clustering' (node_id -> cluster label), 'nodeGroup', 'tarId' and "
                                                "'type' ('gene' or 'disease') are all required."},
                status=400)

        distance = params.get('distance', 'jaccard')
        if distance not in ('jaccard', 'overlap'):
            return JsonResponse({'status': 'error', 'message': "'distance' must be 'jaccard' or 'overlap'."},
                                status=400)
        runs = params.get('runs', 1000)
        replace = params.get('replace', 100)
        background_model = params.get('backgroundModel', 'complete')

        nodes = Nodes.objects.filter(node_id__in=clustering.keys(), node_group=node_group).values('node_id', 'xrefs')
        rows = []
        for node in nodes:
            xref_values = [x.strip() for x in (node['xrefs'] or '').split('|') if x.strip()]
            if not xref_values:
                continue
            # A node can carry more than one xref of the same scheme (e.g. multiple UniProt
            # accessions); DIGEST maps one id per row, so just take the first -- ambiguous
            # multi-mapping isn't something it supports either way.
            rows.append({'id': xref_values[0], 'cluster': clustering[node['node_id']]})

        if not rows:
            return JsonResponse(
                {'status': 'error',
                 'message': f"None of the {len(clustering)} input nodes are of node_group={node_group!r} with a "
                            f"usable xref. Nothing to score."},
                status=400)

        payload = {
            'target': rows,
            'target_id': tar_id,
            'type': target_type,
            'runs': runs,
            'replace': replace,
            'distance': distance,
            'background_model': background_model,
            'sigCont': False,
            # DIGEST echoes back whatever extra fields we send it in its `result` response's
            # `parameters` -- round-tripping our own coverage bookkeeping through DIGEST's task
            # storage this way means we don't need a DHN-side table keyed by DIGEST's run id.
            'dhnNodeGroup': node_group,
            'dhnInputNodeCount': len(clustering),
        }
        try:
            resp = requests.post(f'{settings.DIGEST_API_BASE_URL}/clustering', json=payload,
                                 timeout=settings.DIGEST_API_TIMEOUT_SECONDS)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"DIGEST API submit request failed: {e}")
            return JsonResponse({'status': 'error', 'message': 'DIGEST API request failed.'}, status=502)

        run_id = resp.json().get('task')
        logger.info(f"biodigest clustering score started via DIGEST API: {run_id}")
        return JsonResponse({'status': 'success', 'runId': run_id}, status=200)


class ScoreClusteringStatusView(LoginRequiredMixin, generics.GenericAPIView):
    login_url = settings.FRONTEND_HOME_URL

    @staticmethod
    def get(request):
        run_id = request.GET.get('runId')
        if not run_id:
            return HttpResponseBadRequest('No runId provided.', status=400)

        try:
            status_resp = requests.get(f'{settings.DIGEST_API_BASE_URL}/status', params={'task': run_id},
                                       timeout=settings.DIGEST_API_TIMEOUT_SECONDS)
            status_resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"DIGEST API status request failed: {e}")
            return JsonResponse({'status': 'error', 'message': 'DIGEST API request failed.'}, status=502)

        status_data = status_resp.json()
        if status_data.get('failed'):
            return JsonResponse({'status': 'FAILURE', 'result': status_data.get('status')}, status=200)
        if not status_data.get('done'):
            return JsonResponse({'status': 'PENDING', 'result': None}, status=200)

        try:
            result_resp = requests.get(f'{settings.DIGEST_API_BASE_URL}/result', params={'task': run_id},
                                       timeout=settings.DIGEST_API_TIMEOUT_SECONDS)
            result_resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"DIGEST API result request failed: {e}")
            return JsonResponse({'status': 'error', 'message': 'DIGEST API request failed.'}, status=502)

        result_data = result_resp.json()
        result = result_data.get('result', {})
        request_params = result_data.get('parameters', {})
        result['coverage'] = {
            'nodeGroup': request_params.get('dhnNodeGroup'),
            'tarId': request_params.get('target_id'),
            'inputNodeCount': request_params.get('dhnInputNodeCount'),
            'scoredNodeCount': len(request_params.get('target', [])),
        }
        return JsonResponse({'status': 'SUCCESS', 'result': result})
