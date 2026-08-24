import os
import json
import shutil

from celery import shared_task
import time
import pandas as pd
from django.conf import settings

from network.models import Context, UserContextLink, Nodes
from network.contexts.contexts import insert_context, load_context_scores
from network.queries import query_node_annotation_details
from network.enrichment import (
    extract_protein_accessions, resolve_metabolite_chebi_ids,
    run_gprofiler_multi_query, run_reactome_analysis,
)
from network.views.gemini import _call_gemini, _build_multi_community_prompt_with_enrichment, GEMINI_BULK_TIMEOUT_SECONDS
from network.utils.utils import extract_var_id
from modina.context_net_inference import compute_context_scores
from modina.diff_net_construction import compute_diff_network
from modina.edge_filtering import filter as modina_filter, filter_differential
from modina.ranking import compute_ranking


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
        removed_raw_ids = list(scores.attrs.get('flagged_variables', []))
        dropped_edge_count = len(scores.attrs.get('scores_na', []))
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
        return {'success': False, 'removed_variables': [], 'dropped_edge_count': 0}

    if removed_raw_ids:
        current_vars = new_context.params.get('variables')
        if current_vars:
            new_context.params['variables'] = [
                v for v in current_vars if extract_var_id(v) not in removed_raw_ids
            ]
        else:
            new_context.params['variables'] = [
                c for c in context_df.columns if c not in removed_raw_ids
            ]
    # persisted alongside the other UI-facing fields in `params` so the removal log
    # survives a page reload (RetrieveContextsView serves `params` back as `content`)
    new_context.params['removedVariables'] = removed_raw_ids
    new_context.params['droppedEdgeCount'] = dropped_edge_count
    new_context.save(update_fields=['params'])

    user_context_link.context_status = "Finished"
    user_context_link.save()
    return {'success': success, 'removed_variables': removed_raw_ids, 'dropped_edge_count': dropped_edge_count}


def _df_records(df: pd.DataFrame) -> list:
    """
    Convert a DataFrame to JSON-safe records (NaN -> None, numpy scalars -> native Python).
    Celery's result backend and Django's JsonResponse can't serialize numpy int64/float64 or
    float NaN, both of which pandas produces freely (e.g. STC scores are NaN for nodes with no
    incident edges) -- round-tripping through pandas' own JSON encoder handles both cleanly.
    """
    return json.loads(df.to_json(orient='records'))


# Fixed for now: STC directly tests whether a variable differs between the two contexts, and
# diff-L-P (|delta -log10(p)|) is the plainest "how much does this edge's significance differ"
# edge metric. Both metrics need no user configuration. PageRank+ (personalized PageRank, seeded
# by the node metric and edge-weighted by the edge metric) is moDiNA's own recommended ranking
# algorithm -- see modina.ranking.compute_ranking.
MODINA_EDGE_METRIC = 'diff-L-P'
MODINA_NODE_METRIC = 'STC'
MODINA_RANKING_ALGORITHM = 'PageRank+'

_EDGE_STAT_RENAME = {
    'edge-min': 'edgeMin', 'edge-max': 'edgeMax', 'edge-median': 'edgeMedian',
    'edge-mean': 'edgeMean', 'edge-sd': 'edgeSd', 'edge-percentile-mean': 'edgePercentileMean',
}


def _shape_modina_result(edges_diff: pd.DataFrame, stc_ranking: pd.DataFrame,
                         pagerank_ranking: pd.DataFrame, name1: str, name2: str) -> dict:
    """
    Reshape the moDiNA pipeline's pandas outputs into the JSON contract differential-network.vue
    already expects (result.points / result.links / result.edgeRanking). `stc_ranking`
    (ranking_alg='nodeRank') is node-metric-indexed and covers every node with a node-metric
    value, including ones with no surviving edges -- compute_ranking already merges the node
    metric and the incident-edge statistics onto it, so it's used as the base for `points`
    (id-keyed, feeding both the graph and NodeRankPanel). `pagerank_ranking`
    (ranking_alg=MODINA_RANKING_ALGORITHM) only covers nodes present in edges_diff's graph, so its
    rank/score are left-merged onto the stc_ranking base as the primary displayed rank/score,
    while stc_ranking's own rank survives as 'nodeMetricRank' -- neither ranking silently drops a
    node the other one would have shown. The edge ranking is derived directly from edges_diff
    instead of a second compute_ranking(..., ranking_alg='edgeRank') call, since that branch
    discards label1/label2 (collapses them into a single 'edge' string) which result.links/
    EdgeRankPanel both need back.
    """
    edges_diff = edges_diff.copy()
    edges_diff['rank'] = edges_diff[MODINA_EDGE_METRIC].rank(method='min', ascending=False).astype(int)

    links_df = edges_diff.rename(columns={
        'label1': 'source', 'label2': 'target',
        MODINA_EDGE_METRIC: 'weight', f'{MODINA_EDGE_METRIC}_signed': 'signed',
        f'raw-P_{name1}': 'rawP1', f'raw-E_{name1}': 'rawE1',
        f'raw-P_{name2}': 'rawP2', f'raw-E_{name2}': 'rawE2',
    })[['source', 'target', 'weight', 'signed', 'rank', 'rawP1', 'rawE1', 'rawP2', 'rawE2']]

    edge_ranking_df = edges_diff.rename(columns={
        MODINA_EDGE_METRIC: 'score', f'{MODINA_EDGE_METRIC}_signed': 'signed',
    })[['label1', 'label2', 'rank', 'score', 'signed']].sort_values('rank').reset_index(drop=True)

    points_df = stc_ranking.rename(columns={
        'node': 'id', 'rank': 'nodeMetricRank', MODINA_NODE_METRIC: 'nodeMetricValue', **_EDGE_STAT_RENAME,
    }).drop(columns=['score'])  # 'score' here just duplicates 'nodeMetricValue' (nodeRank's score is the node metric itself)

    # PageRank+ only ranks nodes present in edges_diff's graph -- a node with zero surviving edges
    # (e.g. after filter_differential) has no PageRank+ rank/score, but still keeps its
    # nodeMetricRank/nodeMetricValue from the stc_ranking base above.
    pagerank_scores = pagerank_ranking.rename(columns={'node': 'id'})[['id', 'rank', 'score']]
    points_df = points_df.merge(pagerank_scores, on='id', how='left')
    # 'group' (the data layer a variable belongs to, e.g. phenotype/protein/metabolite, drives
    # point coloring on the frontend), 'display_name' (human-readable variable name) and
    # 'description' (a longer blurb) all come from the same place the main network page gets
    # them: a single direct lookup against the Postgres Nodes table (see network/queries.py's
    # _query_new_schema_nodes), keyed by the same node ids the per-context edge tables already
    # use -- not DataManager's file-based meta_df, which has no display_name at all and would
    # need its own (separately configured, and not guaranteed identical) id scheme besides.
    node_meta_df = pd.DataFrame(
        Nodes.objects.filter(node_id__in=points_df['id'].tolist())
        .values('node_id', 'display_name', 'description', 'node_group')
    )
    if not node_meta_df.empty:
        node_meta_df = node_meta_df.set_index('node_id')
        points_df['display_name'] = points_df['id'].map(node_meta_df['display_name'])
        points_df['description'] = points_df['id'].map(node_meta_df['description'])
        points_df['group'] = points_df['id'].map(node_meta_df['node_group'])
    else:
        points_df['display_name'] = None
        points_df['description'] = None
        points_df['group'] = None

    return {
        'points': _df_records(points_df),
        'links': _df_records(links_df),
        'edgeRanking': _df_records(edge_ranking_df),
        'nodeMetric': MODINA_NODE_METRIC,
        'edgeMetric': MODINA_EDGE_METRIC,
        'rankingAlgorithm': MODINA_RANKING_ALGORITHM,
    }


@shared_task(bind=True)
def create_comparison_wrapper(self, context1_data: str, context2_data: str, meta_file: str,
                              context1_id: str, context2_id: str, test_type: str, correction: str,
                              settings_params: dict, name1: str, name2: str, dir_path: str):
    context1_df = pd.read_pickle(context1_data)
    context2_df = pd.read_pickle(context2_data)
    meta_df = pd.read_pickle(meta_file)

    # Reuse each context's already-computed (and already corrected) association scores instead of
    # recomputing them -- consistent with what the network page already shows for these contexts,
    # and avoids redoing the expensive pairwise statistical testing a second time. Only STC (which
    # directly compares the two contexts' raw variable distributions, not their scores) and the
    # structural checks in compute_diff_network still need the raw per-patient data.
    scores1 = load_context_scores(context1_id, test_type)
    scores2 = load_context_scores(context2_id, test_type)

    filter_target = settings_params.get('filterTarget')
    filter_param = settings_params.get('filterParam') or 1
    filter_metric = settings_params.get('filterMetric')
    filter_rule = settings_params.get('filterRule')

    try:
        if filter_target == 'context-specific':
            scores1, scores2, context1_df, context2_df = modina_filter(
                context1=context1_df, context2=context2_df, scores1=scores1, scores2=scores2,
                filter_method='density', filter_param=filter_param,
                filter_metric=filter_metric, filter_rule=filter_rule,
            )

        edges_diff, nodes_diff, edge_node_stats = compute_diff_network(
            scores1=scores1,
            scores2=scores2,
            context1=context1_df,
            context2=context2_df,
            edge_metric=MODINA_EDGE_METRIC,
            node_metric=MODINA_NODE_METRIC,
            correction=correction,
            meta_file=meta_df,
            test_type=test_type,
            nan_value=settings.NAN_VALUE,
            num_workers=settings.NUM_WORKERS,
            name1=name1,
            name2=name2,
        )

        if filter_target == 'differential':
            edges_diff, edge_node_stats = filter_differential(
                edges_diff=edges_diff, edge_metric=MODINA_EDGE_METRIC,
                filter_method='density', filter_param=filter_param,
            )

        stc_ranking = compute_ranking(
            edges_diff=edges_diff, nodes_diff=nodes_diff, ranking_alg='nodeRank',
            meta_file=meta_df, edge_node_stats=edge_node_stats,
        )
        pagerank_ranking = compute_ranking(
            edges_diff=edges_diff, nodes_diff=nodes_diff, ranking_alg=MODINA_RANKING_ALGORITHM,
            meta_file=meta_df, edge_node_stats=edge_node_stats,
        )

        result = _shape_modina_result(edges_diff, stc_ranking, pagerank_ranking, name1, name2)
    finally:
        if os.path.exists(dir_path) and os.path.isdir(dir_path):
            shutil.rmtree(dir_path)

    return result


@shared_task(bind=True)
def run_community_annotation_task(self, communities: dict, resolution: str):
    """
    For every community, runs g:Profiler + Reactome enrichment on its proteins/metabolites and
    feeds the results into a single bulk Gemini call (one request covering all communities) so
    each label/rationale is grounded in actual pathway evidence rather than node names alone.
    Backs the Community Annotation tab's "Run Community Annotation" button (via
    RunCommunityAnnotationView.delay(...)/CommunityAnnotationStatusView's AsyncResult polling).
    `communities`: {community_id: [node_id, ...]}. Progress is reported via self.update_state so
    CommunityAnnotationStatusView can show which stage/community is in flight -- this can take a
    few minutes (one g:Profiler call total, but one Reactome call per community).
    """
    all_node_ids = sorted({node_id for node_ids in communities.values() for node_id in node_ids})
    node_rows = query_node_annotation_details(all_node_ids)
    nodes_by_id = {row['node_id']: row for row in node_rows}

    communities_details = {}
    community_proteins = {}
    community_chebi_ids = {}
    for community_id, node_ids in communities.items():
        details = [nodes_by_id[node_id] for node_id in node_ids if node_id in nodes_by_id]
        if not details:
            continue
        communities_details[community_id] = details

        proteins = []
        for node in details:
            if node['node_group'] == 'protein':
                for accession in extract_protein_accessions(node['display_name']):
                    if accession not in proteins:
                        proteins.append(accession)
        community_proteins[community_id] = proteins

        chebi_ids = []
        for node in details:
            if node['node_group'] != 'metabolite':
                continue
            for chebi_id in resolve_metabolite_chebi_ids(node['node_id'], node['xrefs']):
                if chebi_id not in chebi_ids:
                    chebi_ids.append(chebi_id)
        community_chebi_ids[community_id] = chebi_ids

    total_communities = len(communities_details)
    self.update_state(state='PROGRESS', meta={'stage': 'gprofiler', 'completed': 0, 'total': total_communities})
    gprofiler_results = run_gprofiler_multi_query({
        community_id: proteins for community_id, proteins in community_proteins.items() if proteins
    })

    reactome_results = {}
    for i, community_id in enumerate(communities_details):
        identifiers = community_proteins.get(community_id, []) + community_chebi_ids.get(community_id, [])
        if identifiers:
            reactome_results[community_id] = run_reactome_analysis(identifiers)
        self.update_state(
            state='PROGRESS',
            meta={'stage': 'reactome', 'completed': i + 1, 'total': total_communities},
        )

    self.update_state(state='PROGRESS', meta={'stage': 'gemini', 'completed': 0, 'total': 1})
    prompt = _build_multi_community_prompt_with_enrichment(communities_details, gprofiler_results, reactome_results)
    label_data = _call_gemini(prompt, timeout=GEMINI_BULK_TIMEOUT_SECONDS)
    labels = label_data.get('communities', {})

    return {
        community_id: {
            'label': labels.get(community_id, {}).get('label', ''),
            'rationale': labels.get(community_id, {}).get('rationale', ''),
            'node_count': len(details),
            'gprofiler': gprofiler_results.get(community_id, []),
            'reactome': reactome_results.get(community_id, []),
        }
        for community_id, details in communities_details.items()
    }


@shared_task
def test_task():
    print("Executed async test task")
    time.sleep(10)
