"""
g:Profiler / Reactome / UniChem helpers for the Community Annotation batch job
(see network.tasks.run_community_annotation_task). These are server-side ports of the
identical client-side logic already used by the per-selection "Run Enrichment" buttons on
the network page (data-network.vue: selectedProteinAccessions, parseXrefs, normalizeHmdbId,
mapHmdbToChebi, runProteinEnrichment, runReactomeEnrichment) -- kept parameter-for-parameter
identical so results match what that existing feature already produces.
"""
import logging
import re

import requests

logger = logging.getLogger('network')

GPROFILER_URL = 'https://biit.cs.ut.ee/gprofiler/api/gost/profile/'
REACTOME_URL = 'https://reactome.org/AnalysisService/identifiers/projection'
UNICHEM_URL = 'https://www.ebi.ac.uk/unichem/api/v1/compounds'
EXTERNAL_API_TIMEOUT_SECONDS = 30

_ISOFORM_SUFFIX_RE = re.compile(r'-\d+$')
_HMDB_RE = re.compile(r'^hmdb0*(\d+)$', re.IGNORECASE)


def extract_protein_accessions(display_name):
    """
    UniProt accession(s) from a protein node's display_name -- semicolon-separated when a
    protein has multiple isoforms (e.g. "P01042;P01042-2"), isoform suffixes stripped since
    g:Profiler/Reactome expect base accessions. Port of selectedProteinAccessions
    (data-network.vue:865-877).
    """
    if not display_name:
        return []
    accessions = []
    for accession in display_name.split(';'):
        accession = _ISOFORM_SUFFIX_RE.sub('', accession.strip())
        if accession and accession not in accessions:
            accessions.append(accession)
    return accessions


def parse_xrefs(xrefs_string):
    """
    xrefs packs multiple cross-references into one string as "prefix.value" pairs joined by
    "|" (e.g. "hmdb.HMDB0001539|kegg.C00086"). Returns {prefix: [values...]}; a prefix can
    repeat, so each maps to a list. Port of parseXrefs (data-network.vue:1882-1894).
    """
    result = {}
    if not isinstance(xrefs_string, str) or not xrefs_string:
        return result
    for entry in xrefs_string.split(';'):
        if 'HMDB' in entry:
            result.setdefault('hmdb', []).append(entry)
        elif 'CHEBI:' in entry:
            prefix, _, value = entry.partition(':')
            prefix = prefix.lower
            result.setdefault(prefix, []).append(value) 
    return result


def normalize_hmdb_id(raw_id):
    """
    UniChem matches HMDB ids by exact string equality against "HMDB" + a zero-padded 7-digit
    accession. Port of normalizeHmdbId (data-network.vue:1901-1905).
    """
    match = _HMDB_RE.match(str(raw_id).strip())
    if not match:
        return None
    return f'HMDB{match.group(1).zfill(7)}'


def map_hmdb_to_chebi(hmdb_id):
    """
    Live HMDB -> ChEBI lookup via EBI's UniChem, for metabolites with no stored ChEBI xref.
    Source ids are fixed registry constants (18 = HMDB). A compound can map to more than one
    ChEBI id (e.g. stereoisomers) -- all are kept. Port of mapHmdbToChebi
    (data-network.vue:1912-1932).
    """
    normalized_id = normalize_hmdb_id(hmdb_id)
    if not normalized_id:
        return []
    try:
        response = requests.post(
            UNICHEM_URL,
            json={'type': 'sourceID', 'compound': normalized_id, 'sourceID': 18},
            timeout=EXTERNAL_API_TIMEOUT_SECONDS,
        )
        if not response.ok:
            return []
        compounds = response.json().get('compounds') or []
        if not compounds:
            return []
        return [
            source['compoundId'].upper().replace('CHEBI:', '')
            for source in compounds[0].get('sources', [])
            if source.get('shortName') == 'chebi'
        ]
    except (requests.RequestException, ValueError, KeyError, IndexError) as ex:
        logger.warning("Could not map %s to ChEBI via UniChem: %s", hmdb_id, ex)
        return []


def resolve_metabolite_chebi_ids(node_id, xrefs_string):
    """
    ChEBI ids for a metabolite node, for Reactome's Analysis Service (it doesn't recognize HMDB
    directly). Two-tier, mirroring selectedMetaboliteChebiIds/selectedMetabolitesWithoutChebi/
    runReactomeEnrichment (data-network.vue:884-900, 1942-1969): a directly-stored ChEBI xref is
    used as-is; otherwise every HMDB-shaped candidate is tried against UniChem and every match is
    unioned (not just the first hit -- a compound can map to more than one ChEBI id, e.g.
    stereoisomers). Candidates are widened beyond parse_xrefs' "hmdb." prefix convention because
    this project's xrefs data isn't consistently prefixed -- e.g. a bare "HMDB0001539" with no
    "hmdb." prefix at all is common -- so raw pipe/semicolon-delimited segments and the node's own
    id are tried too; normalize_hmdb_id() rejects non-matches for free, so extra candidates cost
    nothing but an early return, not a wasted call.
    """
    parsed = parse_xrefs(xrefs_string)
    direct_chebi = parsed.get('chebi')
    if direct_chebi:
        return list(dict.fromkeys(direct_chebi))
    else:
        return []

    raw_segments = re.split(r'[|;]', xrefs_string) if isinstance(xrefs_string, str) else []
    candidates = list(dict.fromkeys(
        parsed.get('HMDB', []) + [segment.strip() for segment in raw_segments if segment.strip()] + [node_id]
    ))
    chebi_ids = []
    for candidate in candidates:
        for chebi_id in map_hmdb_to_chebi(candidate):
            if chebi_id not in chebi_ids:
                chebi_ids.append(chebi_id)
    return chebi_ids


def run_gprofiler_multi_query(community_gene_lists):
    """
    community_gene_lists: {community_id: [uniprot_accession, ...]}, communities with an empty
    list already filtered out by the caller. One g:Profiler multi-query POST (its `query` field
    accepts a dict of named gene lists, scored together in a single request) rather than one
    call per community -- same sources/thresholds as the existing per-selection Protein
    Enrichment feature (runProteinEnrichment, data-network.vue:1846-1877). Returns
    {community_id: [top 20 terms sorted by p_value asc]}; on total failure, returns {} for
    every requested community rather than raising, so one bad request doesn't abort the whole
    community-annotation run.
    """
    if not community_gene_lists:
        return {}
    try:
        response = requests.post(
            GPROFILER_URL,
            json={
                'organism': 'hsapiens',
                'query': community_gene_lists,
                'sources': ['GO:BP', 'GO:CC', 'GO:MF', 'KEGG', 'REAC', 'WP'],
                'user_threshold': 0.05,
                'significance_threshold_method': 'g_SCS',
                'no_evidences': True,
            },
            timeout=EXTERNAL_API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        results = response.json().get('result') or []
    except (requests.RequestException, ValueError) as ex:
        logger.error("g:Profiler multi-query request failed: %s", ex)
        return {}

    by_community = {community_id: [] for community_id in community_gene_lists}
    for row in results:
        by_community.setdefault(row.get('query'), []).append(row)
    return {
        community_id: sorted(terms, key=lambda term: term['p_value'])[:20]
        for community_id, terms in by_community.items()
    }


def run_reactome_analysis(identifiers):
    """
    One community's identifiers (UniProt accessions + ChEBI ids) against Reactome's Analysis
    Service -- it only accepts one combined identifier list per request, so (unlike
    g:Profiler) this is called once per community by the caller. Same endpoint/params as the
    existing per-selection Reactome Enrichment feature (runReactomeEnrichment,
    data-network.vue:1936-1991). Returns the top 20 pathways sorted by entities.pValue asc, or
    [] on failure/no identifiers.
    """
    if not identifiers:
        return []
    try:
        response = requests.post(
            REACTOME_URL,
            data='\n'.join(identifiers),
            headers={'Content-Type': 'text/plain'},
            timeout=EXTERNAL_API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        pathways = response.json().get('pathways') or []
    except (requests.RequestException, ValueError, KeyError) as ex:
        logger.error("Reactome analysis request failed: %s", ex)
        return []
    return sorted(pathways, key=lambda pathway: pathway['entities']['pValue'])[:20]
