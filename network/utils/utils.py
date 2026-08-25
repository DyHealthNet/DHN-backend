import pandas as pd
import numpy as np
import logging
import re

from django.conf import settings

logger = logging.getLogger('network')


def list_group_variables(meta, data):
    """
    Build the statistical-type grouping and display identifier for every variable in one
    data group (phenotype/protein/metabolite/... - any group produced by DataManager).
    :param meta: metadata DataFrame for this group, indexed by label, with 'type',
                 'description' and 'subgroup' columns (description/subgroup may be
                 all-NaN if not configured for this group).
    :param data: data DataFrame for this group (columns = variable labels).
    :return: DataFrame indexed by label with columns 'group' (continuous/binaryCategorical/
             nonbinaryCategorical), 'identifier' (display string) and 'subgroup' (may be NaN).
    """
    def make_group(cols):
        ctype = cols['type']
        cnumcat = cols['num_cat']
        if ctype == 'continuous':
            return 'continuous'
        elif cnumcat == 2:
            return 'binaryCategorical'
        return 'nonbinaryCategorical'

    type_col = 'type'
    desc_col = 'description'
    subgroup_col = 'subgroup'

    # get subtable of meta data for the variables that are actually in the data
    filtered_rows = meta[meta.index.isin(data.columns)]
    values = filtered_rows[[type_col, desc_col, subgroup_col]].copy()

    values.loc[:, 'num_cat'] = pd.Series(data.nunique())
    values.loc[:, 'group'] = values.loc[:, [type_col, 'num_cat']].apply(make_group, axis=1)

    # if description is NaN only return the index
    values.loc[:, 'identifier'] = np.where(
        values[desc_col].isna(),
        values.index,
        values.apply(lambda row: f'{row[desc_col]} ({row.name})', axis=1)
    )

    values.drop(columns=[desc_col, 'num_cat', type_col], inplace=True)
    return values


def resolve_layer_selection(layer_names, sub_layers_map, layers, layer_subgroups):
    """
    Resolve a compact (sub)layer selection -- a list of layer names plus an optional
    lowercase-keyed map of layer -> selected subgroup names -- into the union of raw
    column ids it refers to, via the `layers`/`layer_subgroups` dicts DataManager
    provides (group name -> pd.Index of all its labels; group name ->
    {subgroup: pd.Index of labels}).

    A layer name present in `layer_names` without its own entry in `sub_layers_map` means
    literally every subgroup that layer has -- the whole layer, full stop. There is no
    outer restriction to fall back on: the frontend only ever compacts a (sub)layer
    reference when EVERY variable it refers to, globally, is actually selected (see
    ContextSetup.vue's layerCoverage()/variablesAvailableIn*), so `variablesLayers`/
    `missingnessLayers` are unambiguous on their own -- Context.params has no separate
    top-level `layers`/`subLayers` selection field to fall back on or consult here.

    Used to expand a context's compact variable selection (variablesLayers/
    variablesSubLayers) and its compact missingness-check selection (missingnessLayers/
    missingnessSubLayers) the same way, in restrict_variables() and layer_counts().
    :return: set of raw column ids.
    """
    if not layer_names or layers is None:
        return set()
    sub_layers_map = sub_layers_map or {}
    result = set()
    for layer in layer_names:
        layer_key = layer.lower()
        subgroups = (layer_subgroups or {}).get(layer_key)
        wanted_subgroups = sub_layers_map.get(layer_key)
        if subgroups and wanted_subgroups:
            for subgroup in wanted_subgroups:
                labels = subgroups.get(subgroup)
                if labels is not None:
                    result.update(labels)
        else:
            labels = layers.get(layer_key)
            if labels is not None:
                result.update(labels)
    return result


# Function to extract the variable Id from the user-friendly input
# (id is either in brackets at the end or simply the input)
def extract_var_id(var):
    # This is necessary because '/ Metabolite' & '/ Protein' is artificially added to the identifiers of
    # metabolites or proteins to be more user-friendly and for an easier search
    var = var.replace(' / Metabolite', '')
    # var = var.replace(' / Protein', '') # -> not needed because id gets extracted from brackets at the end anyways
    return re.sub(r'^.*\(|\)$', '', var) if re.search(r'\(.*?\)', var) else var


# Strip xref string of db -> Not used currently
def strip_db_name(nodes_refs):
    def strip_string(s):
        return s.split('.', 1)[-1] if '.' in s else s

    if not nodes_refs:
        return ""
    # Split the input string by "|", process each part, and join them back together
    parts = nodes_refs.split('|')
    stripped_parts = [strip_string(part) for part in parts]
    return '|'.join(stripped_parts)


# Function to convert the numerical values of (most) phenotypical variables into more representative labels
# (e.g. 0:female, 1:male)
def var_label_mapping(var_id, label, var_label_map_dict):
    # When no var label mapping provided return original labels
    if var_label_map_dict is None:
        return label
    if var_id not in var_label_map_dict:
        return label
    curr_var_label_dict = var_label_map_dict[var_id]
    # convert list of labels or one label using the var label mapping dictionary
    # -> when the label is not contained in the dict (e.g. for proteins, metabolites and some phenotypes)
    # the original label is returned
    if isinstance(label, list):
        return [curr_var_label_dict.get(str(int(float(la))), str(int(float(la)))) for la in label]
    else:
        return curr_var_label_dict.get(str(int(float(label))), str(int(float(label))))


def plot_variables(request):
    x = request.GET.get("x")
    y = request.GET.get("y")
    c = request.GET.get("c")

    if x is None or x == "" or y is None or y == "":
        raise ValueError('Variable x and y must be declared.')
    # equal variables will not return meaningful results and can throw an error later
    if x == y:
        raise ValueError('Variable x and y must be different')
    return x, y, c


def add_cache_header(response, is_default):
    """
    Adds a cache header to the response object if caching is enabled and the response is the default one.
    is_default can be used to disable caching for specific responses.
    :param response: Response object
    :param is_default: Boolean value indicating if the response is the default one
    :return: Response object with cache header
    """
    if not settings.NO_CACHE and is_default:
        keep_alive = 3600 * 24 * 7
        response['Cache-Control'] = f'max-age={keep_alive}, public'
    else:
        logger.debug(f"No cache header, found: {settings.NO_CACHE} and {is_default}")
    return response
