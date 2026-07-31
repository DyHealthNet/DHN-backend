import json
import logging

import requests
from django.conf import settings
from django.http import JsonResponse, HttpResponseBadRequest
from rest_framework import generics

from network.queries import query_node_annotation_details

logger = logging.getLogger('network')

GEMINI_MODEL = 'gemini-3.5-flash'
GEMINI_ENDPOINT = f'https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent'
GEMINI_TIMEOUT_SECONDS = 30
# Bulk community-labeling prompts are much larger (many communities' worth of nodes in
# one request) and take Gemini noticeably longer to generate than a single-node prompt.
GEMINI_BULK_TIMEOUT_SECONDS = 90


class GeminiCallError(Exception):
    """Raised when a Gemini request fails or returns an unparseable response."""


def _require_gemini_configured():
    """Returns a 502 JsonResponse if GEMINI_API_KEY is missing, else None."""
    if not settings.GEMINI_API_KEY:
        logger.error("Gemini view called but GEMINI_API_KEY is not configured.")
        return JsonResponse(
            {"error": "Gemini labeling is not configured on this server (missing GEMINI_API_KEY)."},
            status=502,
        )
    return None


def _call_gemini(prompt, timeout=GEMINI_TIMEOUT_SECONDS):
    """
    POSTs prompt to Gemini and returns the parsed JSON response dict. Raises
    GeminiCallError on any request/parsing failure (network error, bad status,
    unexpected response shape, invalid JSON).
    """
    try:
        response = requests.post(
            GEMINI_ENDPOINT,
            params={"key": settings.GEMINI_API_KEY},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"response_mime_type": "application/json"},
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    except (requests.RequestException, KeyError, IndexError, ValueError) as ex:
        # Gemini's error body (esp. for 429s) names the specific quota that was hit
        # and its limit -- raise_for_status() discards it, so log it explicitly.
        error_body = ex.response.text if isinstance(ex, requests.HTTPError) and ex.response is not None else ""
        logger.error("Gemini request failed: %s | response body: %s", ex, error_body)
        raise GeminiCallError(str(ex)) from ex


def _format_node_line(node):
    line = (
        f"- {node.get('display_name') or node.get('node_id')} "
        f"(group: {node.get('node_group') or 'unknown'}, "
        f"subgroup: {node.get('node_subgroup') or 'none'}): "
        f"{node.get('description') or 'no description available'}"
    )
    xrefs = node.get('xrefs')
    if xrefs:
        line += f" [xrefs: {xrefs}]"
    return line


def _build_prompt(node_details):
    lines = [
        "You are helping annotate a community/cluster of nodes from a multi-omics heterogenous association network. "
        "Each node is a gene, phenotype, protein, or metabolite or similar omics variable while the edges upon which "
        "the clustering was performed represent associations between them. Given the nodes below, propose ONE short "
        "label (a single concise phrase, not a list) capturing the community's overall shared theme, and a "
        "one-sentence rationale. Synthesize a single overarching theme even if the nodes span several biological "
        "categories or subgroups -- do not enumerate multiple sub-themes or list the distinct subgroups separately "
        "in the label. If the nodes truly share no coherent theme at all, say so plainly in one short phrase (e.g. "
        "\"No clear shared theme\") rather than listing what the different subsets are about.",
        "",
        "Nodes:",
    ]
    lines.extend(_format_node_line(node) for node in node_details)
    lines.append("")
    lines.append('Respond with a JSON object of the form {"label": "...", "rationale": "..."}.')
    return "\n".join(lines)


def _build_multi_community_prompt(communities_details):
    """communities_details: {community_id: [node_detail_dict, ...]}."""
    lines = [
        "You are helping annotate the communities/clusters produced by running community detection on a "
        "multi-omics heterogenous association network. Each node is a gene, phenotype, "
        "protein, metabolite, or similar omics variable; edges represent associations between them. Below are "
        "ALL communities from this resolution at once. For EACH community, propose ONE short label (a single "
        "concise phrase, not a list) and a one-sentence rationale. Synthesize a single overarching theme per "
        "community even when it spans several biological categories or subgroups -- do not enumerate multiple "
        "sub-themes or list the distinct subgroups separately within one community's label. If a community truly "
        "has no coherent theme at all, say so plainly in one short phrase. Since you can see every community together, also make "
        "the labels mutually distinctive across communities -- avoid giving two different communities the same or "
        "a near-identical label unless their node sets are genuinely indistinguishable.",
        "",
    ]
    for community_id, node_details in communities_details.items():
        lines.append(f"Community {community_id} ({len(node_details)} nodes):")
        lines.extend(_format_node_line(node) for node in node_details)
        lines.append("")
    community_ids = ", ".join(f'"{cid}"' for cid in communities_details.keys())
    lines.append(
        "Respond with a JSON object of the form "
        '{"communities": {"<community_id>": {"label": "...", "rationale": "..."}, ...}}, '
        f"using exactly these community id keys: {community_ids}."
    )
    return "\n".join(lines)


class GetGeminiLabelView(generics.GenericAPIView):
    @staticmethod
    def post(request):
        # Use DRF's already-parsed request.data rather than request.body: on a DRF
        # Request object the underlying stream may already be consumed by the time the
        # view runs, which makes .body raise RawPostDataException.
        node_ids = request.data.get('node_ids')
        if not isinstance(node_ids, list) or not node_ids:
            return HttpResponseBadRequest("node_ids must be a non-empty list of node IDs.")

        not_configured = _require_gemini_configured()
        if not_configured is not None:
            return not_configured

        node_details = query_node_annotation_details(node_ids)
        if not node_details:
            return HttpResponseBadRequest("None of the provided node_ids were found.")

        prompt = _build_prompt(node_details)
        logger.info("Requesting Gemini label for %d node(s)", len(node_details))

        try:
            label_data = _call_gemini(prompt)
        except GeminiCallError:
            return JsonResponse({"error": "Could not get a label from Gemini. Please try again."}, status=502)

        return JsonResponse({
            "label": label_data.get("label", ""),
            "rationale": label_data.get("rationale", ""),
        })


class GetGeminiClusterLabelsView(generics.GenericAPIView):
    @staticmethod
    def post(request):
        communities = request.data.get('communities')
        if not isinstance(communities, dict) or not communities:
            return HttpResponseBadRequest(
                "communities must be a non-empty object of community_id -> [node_id, ...]."
            )

        all_node_ids = sorted({
            node_id
            for node_ids in communities.values()
            if isinstance(node_ids, list)
            for node_id in node_ids
        })
        if not all_node_ids:
            return HttpResponseBadRequest("communities must contain at least one node ID.")

        not_configured = _require_gemini_configured()
        if not_configured is not None:
            return not_configured

        node_rows = query_node_annotation_details(all_node_ids)
        by_id = {row['node_id']: row for row in node_rows}

        communities_details = {}
        for community_id, node_ids in communities.items():
            if not isinstance(node_ids, list):
                continue
            details = [by_id[node_id] for node_id in node_ids if node_id in by_id]
            if details:
                communities_details[community_id] = details
            else:
                logger.warning("Community %s had no matching nodes in the database; skipping.", community_id)

        if not communities_details:
            return HttpResponseBadRequest("None of the provided node_ids were found.")

        prompt = _build_multi_community_prompt(communities_details)
        logger.info(
            "Requesting Gemini cluster labels for %d communities (%d nodes total)",
            len(communities_details), len(all_node_ids),
        )

        try:
            label_data = _call_gemini(prompt, timeout=GEMINI_BULK_TIMEOUT_SECONDS)
        except GeminiCallError:
            return JsonResponse(
                {"error": "Could not get community labels from Gemini. Please try again."}, status=502
            )

        return JsonResponse({"communities": label_data.get("communities", {})})
