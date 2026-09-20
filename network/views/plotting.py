import timeit
from math import ceil

from django.core.cache import cache
from django.http import JsonResponse
from rest_framework import generics
from django.http import HttpResponseBadRequest
from django.conf import settings
from drf_spectacular.utils import extend_schema_view
from scipy.stats import gaussian_kde

from network.contexts.contexts import subset_patients, context_subset, context_compare_subset, \
    restrict_variables
from network.schemas.plotting_schemas import *
from network.utils.color_utils import *
from network.utils.db_utils import get_context
from network.utils.utils import *


@extend_schema_view(get=variable_catalog_schema)
class GetVariableCatalogView(generics.GenericAPIView):
    """Powers the data-overview page's variable metadata table (VariableCatalogTable.vue):
    one row per variable with its id, description, display name and missing-value count,
    plus the layer/subgroup info needed for the page's group tabs. See GetVariablesView
    (network/views/general.py) for the leaner identifier-list response plot/context
    selection dropdowns use."""
    data_manager = None

    def get(self, request):
        group_values, layers, layer_subgroups, has_context, context = build_group_values(self.data_manager, request)

        # build_group_values() only restricts which *variables* are in scope for a
        # context - list_group_variables()'s missing_count is computed over every
        # patient in the group, context or not. Get the context's actual patient subset
        # (same rule + missingness-check restriction every plot/GetTableView uses) so
        # missingCount reflects it too, rather than always reporting the whole cohort's
        # count regardless of which context is selected.
        context_data = None
        if has_context:
            all_data, = self.data_manager.get_df_copy(['all_data'])
            context_data = context_subset(request, all_data, layers, layer_subgroups)

        # Own cache entry (not shared with GetVariablesView's 'all_variables'/
        # 'variables_context_{id}') since the response shape differs; invalidated the
        # same way on context delete - see delete_context_tables().
        cache_key = f'variable_catalog_context_{context.context_id}' if has_context else 'variable_catalog'
        cache_timeout = 3600 * 24 * 30 if has_context else None
        if cache_key not in cache or settings.NO_CACHE:
            variables = []
            for group_name, values in group_values.items():
                for node_id, identifier, subgroup, description, display_name, missing_count, var_group in zip(
                    values.index, values['identifier'], values['subgroup'], values['description'],
                    values['display_name'], values['missing_count'], values['group']
                ):
                    if context_data is not None and node_id in context_data.columns:
                        missing_count = context_data[node_id].isna().sum()
                    variables.append({
                        'identifier': identifier,
                        'id': node_id,
                        'description': description if pd.notna(description) else None,
                        'displayName': display_name if pd.notna(display_name) else None,
                        'subgroup': subgroup if pd.notna(subgroup) else None,
                        'missingCount': int(missing_count),
                        'group': var_group,
                        'layer': group_name,
                    })

            available_layers = [
                group_name for group_name in layers
                if group_name in group_values and not group_values[group_name].empty
            ]
            if not available_layers:
                available_layers = ["All"]

            values_dict = {
                'variables': variables,
                'availableLayers': available_layers,
                'layerSubLayers': {
                    group_name: sorted(layer_subgroups[group_name].keys())
                    for group_name in group_values
                    if layer_subgroups.get(group_name)
                },
            }

            response = JsonResponse(values_dict, safe=True)
            if not settings.NO_CACHE:
                response = add_cache_header(response, not has_context)
                cache.set(cache_key, response, timeout=cache_timeout)
        else:
            logger.info(f"Cache hit: {cache_key}")
            return cache.get(cache_key)

        response = add_cache_header(response, not has_context)
        return response


@extend_schema_view(get=get_table_schema)
class GetTableView(generics.GenericAPIView):
    data_manager = None

    def get(self, request):
        all_data, layers, group_data, layer_subgroups = self.data_manager.get_df_copy(
            ['all_data', 'layers', 'group_data', 'layer_subgroups']
        )

        def layer_counts(context_variables=None, context_variable_layers=None, context_variable_sub_layers=None,
                         removed_variable_ids=None):
            # a group with zero presence in either context_variables or
            # context_variable_layers naturally gets a count of 0 below (no column of
            # its ever matches selected_ids), so there's no separate whole-layer gate
            # needed - variables/variablesLayers alone are a complete description.
            selected_ids = None
            if context_variables or context_variable_layers:
                selected_ids = set()
                if context_variables:
                    selected_ids.update(extract_var_id(v) for v in context_variables)
                selected_ids.update(
                    resolve_layer_selection(context_variable_layers, context_variable_sub_layers, layers, layer_subgroups)
                )
                if removed_variable_ids:
                    selected_ids -= set(removed_variable_ids)
            counts = {}
            for group_name in layers:
                idx = group_name.capitalize() if group_name.endswith('s') else group_name.capitalize() + 's'
                data = group_data.get(group_name)
                if data is None:
                    counts[idx] = 0
                elif selected_ids is not None:
                    counts[idx] = len([col for col in data.columns if col in selected_ids])
                else:
                    counts[idx] = len(data.columns)
            return counts

        # build result dict in right format
        if not request.GET.get("contextValue") or not request.user.is_authenticated:
            req_data_dict = {'Participants': len(all_data), 'preservePrivacy': settings.PRESERVE_PRIVACY,
                             **layer_counts()}
            response = JsonResponse(req_data_dict, safe=True)
            response = add_cache_header(response, True)
            return response

        # retrieve the context given the context value and user
        context = get_context(request.user, request.GET.get('contextValue'))

        if not context:
            # context not created yet (e.g. brand-new tab) or no longer exists;
            # fall back to the unfiltered counts rather than erroring
            req_data_dict = {'Participants': len(all_data), 'preservePrivacy': settings.PRESERVE_PRIVACY,
                             **layer_counts()}
            response = JsonResponse(req_data_dict, safe=True)
            response = add_cache_header(response, True)
            return response

        if f"participants_context_{context.context_id}" in cache:
            logger.debug("Cache hit for subset data")
            start = timeit.default_timer()
            participants = cache.get(f"participants_context_{context.context_id}")
            logger.debug(f"Retrieved participants from cache in {timeit.default_timer() - start} seconds")
        else:
            start = timeit.default_timer()
            subset = subset_patients(all_data, context.params)
            try:
                subset = restrict_variables(
                    subset, context.params.get('variables'), context.params.get('variablesLayers'),
                    context.params.get('variablesSubLayers'), context.params.get('missingnessVariables'),
                    context.params.get('missingnessLayers'), context.params.get('missingnessSubLayers'),
                    layers, layer_subgroups, context.params.get('removedVariables'),
                )
            except ValueError:
                # selected variables no longer resolve to any real column - fall back to
                # the rule-only subset rather than erroring on a display-only endpoint
                pass
            participants = subset.shape[0]
            logger.debug(f"Subsetted participants in {timeit.default_timer() - start} seconds")
        if settings.PRESERVE_PRIVACY:
            if participants < settings.CRITICAL_NUMBER:
                participants = 0
            else:
                participants = max(settings.CRITICAL_NUMBER, int(ceil(participants / 100) * 100))

        req_data_dict = {'Participants': participants, 'preservePrivacy': settings.PRESERVE_PRIVACY,
                         **layer_counts(context.params.get('variables'), context.params.get('variablesLayers'),
                                        context.params.get('variablesSubLayers'),
                                        context.params.get('removedVariables'))}
        return JsonResponse(req_data_dict, safe=True)


@extend_schema_view(get=get_data_schema)
class GetDataLinePlotView(generics.GenericAPIView):
    data_manager = None

    def get(self, request):
        all_data, var_label_map, layers, layer_subgroups = self.data_manager.get_df_copy(
            ['all_data', 'var_label_map', 'layers', 'layer_subgroups']
        )
        # Get request vars
        try:
            x, y, c = plot_variables(request)
        except ValueError as ex:
            return HttpResponseBadRequest(str(ex), status=405)

        # Get var_id from request vars (stored in brackets at the end of the requests var which is built
        # from description + (var_id) or (in case of metabolites) simply the request var)
        x_idx = extract_var_id(x)
        y_idx = extract_var_id(y)

        # Two-context comparison mode -- see GetDataBoxPlotView for the same pattern.
        if request.GET.get('contextValue1') and request.GET.get('contextValue2'):
            line_plot_df, _, _ = context_compare_subset(request, all_data, layers, layer_subgroups)
            if line_plot_df is None:
                return HttpResponseBadRequest('One or both contexts were not found for the current user.', status=404)
            c = '__context__'
        else:
            line_plot_df = context_subset(request, all_data, layers, layer_subgroups)

        if x_idx not in line_plot_df.columns or y_idx not in line_plot_df.columns:
            return HttpResponseBadRequest('Variable x and y must be a valid variable of the data', status=405)

        if pd.api.types.is_string_dtype(line_plot_df[y_idx]):
            return HttpResponseBadRequest(
                'y Variable is not numerical and can not be visualized in this plot.', status=405)

        df = pd.DataFrame(line_plot_df[[x_idx, y_idx]])
        send_warning = False

        # Continuous x variables are (near-)unique per participant, so grouping by the raw value
        # leaves every group under the privacy threshold and the whole plot comes back empty.
        # Bin them into a fixed number of equal-width bins (using the bin midpoint as the x value)
        # so groups can actually accumulate enough participants to pass the privacy filter.
        x_is_continuous = (pd.api.types.is_numeric_dtype(df[x_idx])
                            and not isinstance(df[x_idx].dtype, pd.CategoricalDtype))
        if x_is_continuous:
            LINE_PLOT_NUM_BINS = 20
            bins = pd.cut(df[x_idx], bins=LINE_PLOT_NUM_BINS)
            bin_midpoints = {interval: interval.mid for interval in bins.cat.categories}
            df[x_idx] = bins.map(bin_midpoints).astype(float)

        temp = []
        if c is not None and c != "":
            # Get var_id from request var (stored in brackets at the end of the request var which is built
            # from description + (var_id) (in case of phenotypes and proteins))
            c_idx = extract_var_id(c)
            # Check if c var is present in our data -> else throw HttpResponseBadRequest
            if c_idx not in line_plot_df.columns:
                return HttpResponseBadRequest('Variable c, if declared, must be a valid variable of the data',
                                              status=405)
            # Check if variables are equal because this will not return meaningful results and can throw an error later
            if c == x or c == y:
                return HttpResponseBadRequest(
                    'Variable x and y must be different from c', status=405)
            # Add var c column to subset df
            df[c_idx] = line_plot_df[c_idx]
            # Make group by x and c var, aggregate over y using mean (+sort by x var for sorted x-axis in plot)
            # privacy restriction: only return groups with 5 or more values =! NaN

            filtered_df = df
            if settings.PRESERVE_PRIVACY:
                filtered_df = df.groupby([x_idx, c_idx], observed=True).filter(
                    lambda x: x[y_idx].notna().sum() >= settings.CRITICAL_NUMBER)
                if len(filtered_df) < len(df):
                    send_warning = True

            # A group whose y-values are all NaN still gets a row here (grouping only
            # depends on x_idx/c_idx), with mean() == NaN; drop it rather than serialize
            # invalid JSON (dict-comment above explains we already skip x positions with
            # no aggregated value, so this keeps that guarantee even without the privacy filter).
            agg_df_mean = (filtered_df.groupby([x_idx, c_idx], observed=True)[y_idx].mean()
                           .reset_index().dropna(subset=[y_idx]).sort_values(x_idx, ascending=True))

            # Add for each color var its own dict containing its label, a color from the color palette and a dict that
            # associates the aggregated values with the corresponding x value (this way we do not have to create NaN
            # values for x positions with no aggregated value present)
            color = 0
            num_colors = agg_df_mean[c_idx].nunique()
            colormap_local = get_palette(request.GET.get('colors', 'tab10'), n_colors=num_colors)
            colormap_local = [rgb_to_hex(rgb) for rgb in colormap_local]
            for group_name, group_data in agg_df_mean.groupby(c_idx, observed=True):
                temp.append({
                    "label": var_label_mapping(c_idx, group_name, var_label_map),
                    "backgroundColor": colormap_local[color],
                    "borderColor": lighten_color(colormap_local[color]),
                    "data": [{'x': var_label_mapping(x_idx, x, var_label_map), 'y': y} for x, y in
                             zip(group_data[x_idx], group_data[y_idx])]
                })
                color += 1
        else:
            # Make group by x and, aggregate over y using mean (+sort by x var for sorted x-axis in plot)
            # privacy restriction: only return something when there are 5 or more values =! NaN
            # (opposite is very unlikely)
            filtered_df = df
            if settings.PRESERVE_PRIVACY:
                filtered_df = df.groupby(x_idx, observed=True).filter(
                    lambda x: x[y_idx].notna().sum() >= settings.CRITICAL_NUMBER)
                if len(filtered_df) < len(df):
                    send_warning = True

            agg_df_mean = (filtered_df.groupby(x_idx, observed=True)[y_idx].mean().reset_index()
                           .dropna(subset=[y_idx]).sort_values(x_idx, ascending=True))

            # Add dict for y-axis containing the y label, black as the color and the aggregated values
            temp.append({
                "label": "Whole Cohort",
                "backgroundColor": rgb_to_hex(get_palette(request.GET.get('colors', 'tab10'), n_colors=1)[0]),
                "data": agg_df_mean[y_idx].tolist()
            })
        # Store unique x_var values
        req_data_dict = {
            'labels': var_label_mapping(x_idx, agg_df_mean[x_idx].unique().tolist(), var_label_map),
            'datasets': temp
        }
        if send_warning:
            req_data_dict["warning"] = "Some groups have been removed to protect privacy."
        response = JsonResponse(req_data_dict, safe=True)
        response = add_cache_header(response, request.GET.get('default'))
        return response


@extend_schema_view(get=get_bar_count_schema)
class GetDataBarCountView(generics.GenericAPIView):
    data_manager = None

    def get(self, request):
        all_data, var_label_map, layers, layer_subgroups = self.data_manager.get_df_copy(
            ['all_data', 'var_label_map', 'layers', 'layer_subgroups']
        )

        send_warning = False

        # Get request vars
        x = request.GET.get("x")
        # Optional second categorical variable: every x tick then stands for one combination of x
        # and x2 (e.g. "female<br>underweight") instead of a single x category.
        x2 = request.GET.get("x2")
        c = request.GET.get("c")

        # build result dict in right format
        req_data_dict = {}
        # Check if x and y var are given -> else throw HttpResponseBadRequest
        if x is None or x == "":
            return HttpResponseBadRequest('Variable x must be declared.', status=405)
        # Get var_id from request var (stored in brackets at the end of the request var which is built
        # from description + (var_id) (in case of phenotypes and proteins))
        x_idx = extract_var_id(x)
        x2_idx = extract_var_id(x2) if x2 else None

        if request.GET.get('contextValue1') and request.GET.get('contextValue2'):
            bar_plot_df, _, _ = context_compare_subset(request, all_data, layers, layer_subgroups)
            if bar_plot_df is None:
                return HttpResponseBadRequest('One or both contexts were not found for the current user.', status=404)
            c = '__context__'
        else:
            bar_plot_df = context_subset(request, all_data, layers, layer_subgroups)

        if x_idx not in bar_plot_df.columns:
            return HttpResponseBadRequest('Variable x must be a valid variable of the data', status=405)
        if x2_idx is not None:
            if x2_idx not in bar_plot_df.columns:
                return HttpResponseBadRequest('Variable x2, if declared, must be a valid variable of the data',
                                              status=405)
            if x2_idx == x_idx:
                return HttpResponseBadRequest('Variable x and x2 must be different', status=405)
        x_cols = [x_idx] if x2_idx is None else [x_idx, x2_idx]

        def x_labels_for(df):
            # One tick label per row of a grouped count frame. Built from the raw category codes
            # (so the frame's own sort order -- x, then x2 -- is what orders the ticks, not the
            # alphabetical order of the label text) with a line break between the two labels.
            labels = [var_label_mapping(x_idx, v, var_label_map) for v in df[x_idx]]
            if x2_idx is None:
                return labels
            labels2 = [var_label_mapping(x2_idx, v, var_label_map) for v in df[x2_idx]]
            return [f"{a}<br>{b}" for a, b in zip(labels, labels2)]

        temp = []

        if c is not None and c != "":
            # Get var_id from request var (stored in brackets at the end of the requents var which is built
            # from description + (var_id) (in case of phenotypes and proteins))
            c_idx = extract_var_id(c)
            # Check if c var is present in our data -> else throw HttpResponseBadRequest
            if c_idx not in bar_plot_df.columns:
                return HttpResponseBadRequest(
                    'Variable c, if declared, must be a valid variable of the data', status=405)
            # Check if variables are equal because this will not return meaningful results and can throw an error later
            if c == x or c_idx in x_cols:
                return HttpResponseBadRequest('Variable x and c must be different', status=405)
            # Make df subset with x (and x2), c var and a count value for each group combination
            # TODO Group combinations where c_idx is NaN will not be returned and therefore not appear ->
            #  return 0 instead?
            df_count = bar_plot_df[[*x_cols, c_idx]].groupby([*x_cols, c_idx], observed=True).size().reset_index(name='counts')
            df_count['x_label'] = x_labels_for(df_count)

            if settings.PRESERVE_PRIVACY:
                below_threshold = df_count['counts'] < settings.CRITICAL_NUMBER
                if below_threshold.any():
                    send_warning = True
                df_count.loc[below_threshold, 'counts'] = 0

            # Add for each color var its own dict containing its label, a color from the color palette and a dict that
            # associates the count values with the corresponding x value
            color = 0
            num_colors = df_count[c_idx].nunique()
            colormap_local = get_palette(request.GET.get('colors', 'tab10'), n_colors=num_colors)
            colormap_local = [rgb_to_hex(rgb) for rgb in colormap_local]
            for group_name, group_data in df_count.groupby(c_idx, observed=True):
                temp.append({
                    "label": var_label_mapping(c_idx, group_name, var_label_map),
                    "backgroundColor": colormap_local[color],
                    "data": [{'x': x_label, 'y': y} for x_label, y in
                             zip(group_data['x_label'], group_data['counts'])]
                })
                color += 1
        # if no color var c is given only group by x var
        else:
            # Make df subset with x var and a count variable
            df_count = pd.DataFrame(bar_plot_df[x_cols]).groupby(x_cols).size().reset_index(name='counts')
            df_count['x_label'] = x_labels_for(df_count)
            if settings.PRESERVE_PRIVACY:
                below_threshold = df_count['counts'] < settings.CRITICAL_NUMBER
                if below_threshold.any():
                    send_warning = True
                df_count.loc[below_threshold, 'counts'] = 0

            # Add dict for y axis containing the y label, black as the color and the aggregated values
            temp.append({
                "label": "Whole Cohort",
                "backgroundColor": rgb_to_hex(get_palette(request.GET.get('colors', 'tab10'), n_colors=1)[0]),
                "data": df_count['counts'].tolist()
            })
        # Store unique x tick labels (in the frame's sort order)
        req_data_dict["labels"] = list(dict.fromkeys(df_count['x_label']))
        # Store the count data values
        req_data_dict["datasets"] = temp
        if send_warning:
            req_data_dict["warning"] = "Some data points have been removed to protect privacy."

        response = JsonResponse(req_data_dict, safe=True)
        response = add_cache_header(response, request.GET.get('default'))
        return response

@extend_schema_view(get=get_pie_count_schema)
class GetDataPieCountView(generics.GenericAPIView):
    data_manager = None

    def get(self, request):
        all_data, var_label_map, layers, layer_subgroups = self.data_manager.get_df_copy(
            ['all_data', 'var_label_map', 'layers', 'layer_subgroups']
        )

        send_warning = False

        # Get request vars
        x = request.GET.get("x")

        # build result dict in right format
        req_data_dict = {}
        # Check if x and y var are given -> else throw HttpResponseBadRequest
        if x is None or x == "":
            return HttpResponseBadRequest('Variable x must be declared.', status=405)
        # Get var_id from request var (stored in brackets at the end of the request var which is built
        # from description + (var_id) (in case of phenotypes and proteins))
        x_idx = extract_var_id(x)

        pie_plot_df = context_subset(request, all_data, layers, layer_subgroups)

        if x_idx not in pie_plot_df.columns:
            return HttpResponseBadRequest('Variable x must be a valid variable of the data', status=405)
        temp = []

        # Make df subset with x var and a count variable
        df_count = pd.DataFrame(pie_plot_df[x_idx]).groupby(x_idx).size().reset_index(name='counts')
        if settings.PRESERVE_PRIVACY:
            below_threshold = df_count['counts'] < settings.CRITICAL_NUMBER
            if below_threshold.any():
                send_warning = True
            df_count.loc[below_threshold, 'counts'] = 0

        num_colors = len(df_count["counts"].tolist())
        colormap_local = get_palette(request.GET.get('colors', 'tab10'), n_colors=num_colors)
        colormap_local = [rgb_to_hex(rgb) for rgb in colormap_local]
        temp.append({
            "backgroundColor": colormap_local,
            "data": df_count['counts'].tolist()
        })
        # Store unique x tick labels (in the frame's sort order)
        req_data_dict["labels"] = list(dict.fromkeys(df_count['x_label']))
        # Store the count data values
        req_data_dict["datasets"] = temp
        if send_warning:
            req_data_dict["warning"] = "Some data points have been removed to protect privacy."

        response = JsonResponse(req_data_dict, safe=True)
        response = add_cache_header(response, request.GET.get('default'))
        return response



#@extend_schema_view(get=get_density_plot_schema)
class GetDataDensityPlotView(generics.GenericAPIView):
    data_manager = None

    def get(self, request):
        all_data, var_label_map, layers, layer_subgroups = self.data_manager.get_df_copy(
            ['all_data', 'var_label_map', 'layers', 'layer_subgroups']
        )

        send_warning = False
        send_data_warning = False

        # Get request vars
        x = request.GET.get("x")
        c = request.GET.get("c")
        bw_method = float(request.GET.get("bandwidth"))

        # Check if x is provided
        if x is None or x == "":
            return HttpResponseBadRequest('Variable x must be declared.', status=405)

        # Extract var_id from x (for phenotype or protein)
        x_idx = extract_var_id(x)

        # Two-context comparison mode: group by a synthetic '__context__' column instead of
        # (or filtering by) a single contextValue, reusing the exact same c-grouping
        # aggregation below rather than a separate code path (same pattern as GetDataBoxPlotView).
        if request.GET.get('contextValue1') and request.GET.get('contextValue2'):
            density_plot_df, _, _ = context_compare_subset(request, all_data, layers, layer_subgroups)
            if density_plot_df is None:
                return HttpResponseBadRequest('One or both contexts were not found for the current user.', status=404)
            c = '__context__'
        else:
            density_plot_df = context_subset(request, all_data, layers, layer_subgroups)

        # Check if there is in general enough data != nan to ensure privacy protection
        if settings.PRESERVE_PRIVACY:
            if len(density_plot_df[x_idx].dropna()) < settings.CRITICAL_NUMBER:
                return JsonResponse({
                    'labels': [],
                    'datasets': [{'label': 'No Data Available', 'data': [], 'borderColor': 'rgba(0,0,0,0)',
                                  'backgroundColor': 'rgba(0,0,0,0, 0.1)', 'fill': False, 'tension': 0.3}],
                    "warning" : "Not enough data available to ensure privacy protection."
                })

        if x_idx not in density_plot_df.columns:
            return HttpResponseBadRequest('Variable x must be a valid variable of the data', status=405)

        # np.min/np.max propagate NaN if any value is missing (unlike nanmin/nanmax), which
        # would make x_vals -- and the whole response -- all-NaN and unserializable as JSON.
        # gaussian_kde also hard-requires at least 2 points (raises ValueError below that) and
        # nonzero variance (raises LinAlgError for a degenerate/all-identical sample).
        valid_x = density_plot_df[x_idx].dropna()
        no_data_response = {
            'labels': [],
            'datasets': [{'label': 'No Data Available', 'data': [], 'borderColor': 'rgba(0,0,0,0)',
                          'backgroundColor': 'rgba(0,0,0,0, 0.1)', 'fill': False, 'tension': 0.3}],
        }
        if len(valid_x) < 2:
            return JsonResponse(no_data_response)
        min_val, max_val = valid_x.min(), valid_x.max()

        try:
            kde = gaussian_kde(valid_x, bw_method=0.1)
        except np.linalg.LinAlgError:
            return JsonResponse(no_data_response)

        x_vals = np.linspace(min_val, max_val, 100)
        y_vals = kde(x_vals)  # Get the density for these x values

        # Ensure y_vals is normalized to fit your chart (integral = 1 for proper normalization)
        y_vals /= np.sum(y_vals) * (x_vals[1] - x_vals[0])  # Normalize

        temp = []

        if c is not None and c != "":
            # Extract color variable
            c_idx = extract_var_id(c)

            if c_idx not in density_plot_df.columns:
                return HttpResponseBadRequest('Variable c must be a valid variable of the data', status=405)

            if c == x:
                return HttpResponseBadRequest('Variable x and c must be different', status=405)

            # Group by color variable
            grouped_data = density_plot_df.groupby(c_idx, observed=True)[x_idx]

            num_colors = len(list(grouped_data.groups.keys()))
            colormap_local = [tuple(map(lambda x: round(x * 255), color)) for color in
                              get_palette(request.GET.get('colors', 'tab10'), n_colors=num_colors)]

            for idx, (group_name, data) in enumerate(grouped_data):
                # Check per group if there is enough data != nan to ensure privacy protection
                # if not skip this group
                valid_data = data.dropna()
                if settings.PRESERVE_PRIVACY:
                    if len(valid_data) < settings.CRITICAL_NUMBER:
                        send_warning = True
                        continue
                # gaussian_kde hard-requires at least 2 points (raises ValueError for 0 or 1)
                # and nonzero variance (raises LinAlgError for an all-identical group) -- with
                # PRESERVE_PRIVACY off, or CRITICAL_NUMBER set below 2, nothing else catches
                # this, so skip the group instead of letting the view crash with a 500.
                if len(valid_data) < 2:
                    send_data_warning = True
                    continue
                try:
                    kde_group = gaussian_kde(valid_data, bw_method=bw_method)
                    y_vals_group = kde_group(x_vals)
                    y_vals_group /= np.sum(y_vals_group) * (x_vals[1] - x_vals[0])  # Normalize
                except np.linalg.LinAlgError:
                    send_data_warning = True
                    continue

                r, g, b = colormap_local[idx]
                temp.append({
                    "label": var_label_mapping(c_idx, group_name, var_label_map),
                    "borderColor": f"rgb({r},{g},{b})",
                    "backgroundColor": f"rgba({r},{g},{b}, 0.4)",
                    "data": y_vals_group.tolist(),
                    "fill": True,
                    "tension": 0.3,
                })
        else:
            # KDE for whole cohort (if no color variable is provided)
            r, g, b = [tuple(map(lambda x: round(x * 255), color)) for color in
                       get_palette(request.GET.get('colors', 'tab10'), n_colors=1)][0]
            temp.append({
                "label": "Whole Cohort",
                "borderColor": f"rgb({r},{g},{b})",
                "backgroundColor": f"rgba({r},{g},{b}, 0.4)",
                "data": y_vals.tolist(),
                "fill": True,
                "tension": 0.3,
            })

        # Prepare data for the response
        req_data = {
            'labels': np.round(x_vals, 2).tolist(),
            'datasets': temp,
        }
        warnings = []
        if send_warning:
            warnings.append("Some groups have been removed to protect privacy.")
        if send_data_warning:
            warnings.append("Some groups could not be displayed because they had too few or non-varying values.")
        if warnings:
            req_data["warning"] = " ".join(warnings)

        response = JsonResponse(req_data, safe=True)
        response = add_cache_header(response, request.GET.get('default'))
        return response


@extend_schema_view(get=get_box_plot_schema)
class GetDataBoxPlotView(generics.GenericAPIView):
    data_manager = None

    def get(self, request):
        all_data, var_label_map, layers, layer_subgroups = self.data_manager.get_df_copy(
            ['all_data', 'var_label_map', 'layers', 'layer_subgroups']
        )

        # Fill NaN values with the NaN boxplot dictionary
        nan_boxplot = {'min': None, 'q1': None, 'median': None, 'mean': None, 'q3': None, 'max': None}

        try:
            x, y, c = plot_variables(request)
        except ValueError as ex:
            return HttpResponseBadRequest(str(ex), status=405)

        x_idx = extract_var_id(x)  # Extract var_id from request var
        y_idx = extract_var_id(y)

        # Two-context comparison mode: group by a synthetic '__context__' column instead of
        # (or filtering by) a single contextValue, reusing the exact same c-grouping
        # aggregation below rather than a separate code path.
        if request.GET.get('contextValue1') and request.GET.get('contextValue2'):
            box_plot_df, _, _ = context_compare_subset(request, all_data, layers, layer_subgroups)
            if box_plot_df is None:
                return HttpResponseBadRequest('One or both contexts were not found for the current user.', status=404)
            c = '__context__'
        else:
            box_plot_df = context_subset(request, all_data, layers, layer_subgroups)

        # Check if x and y var are present in our data -> else throw HttpResponseBadRequest
        if x_idx not in box_plot_df.columns or y_idx not in box_plot_df.columns:
            return HttpResponseBadRequest('Variable x and y must be a valid variable of the data',
                                          status=405)
        # Check if y var is a string (e.g. time variable) which would result in an error during aggregation
        # -> else throw HttpResponseBadRequest
        if pd.api.types.is_string_dtype(box_plot_df[y_idx]):
            return HttpResponseBadRequest(
                'y Variable is not numerical and can not be visualized in this plot.', status=405)

        # helper function to calculate boxplot stats or return nan boxplot when privacy restrictions are violated
        privacy_triggered = [False]

        def boxplot_stats(group):
            valid_count = group[y_idx].notna().sum()
            # No valid values: always return the None sentinel, since pandas stats on an
            # all-NaN slice are real NaN floats, which Django serializes as invalid JSON.
            if valid_count == 0:
                return nan_boxplot
            if settings.PRESERVE_PRIVACY and valid_count < settings.CRITICAL_NUMBER:
                privacy_triggered[0] = True
                return nan_boxplot
            return {
                'min': group[y_idx].min(),
                'q1': group[y_idx].quantile(0.25),
                'median': group[y_idx].median(),
                'mean': group[y_idx].mean(),
                'q3': group[y_idx].quantile(0.75),
                'max': group[y_idx].max(),
            }

        temp = []
        grouped = pd.DataFrame()
        # Make df subset with x and y var
        df = pd.DataFrame(box_plot_df[[x_idx, y_idx]])
        # Check if c var is given and if so split data by it
        if c is not None and c != "":
            c_idx = extract_var_id(c)
            # Check if c var is present in our data -> else throw HttpResponseBadRequest
            if c_idx not in box_plot_df.columns:
                return HttpResponseBadRequest(
                    'Variable c, if declared, must be a valid variable of the data', status=405)
            # Check if variables are equal because this will not return meaningful results and can throw an error later
            if c == x or c == y:
                return HttpResponseBadRequest(
                    'Variable x and y must be different from c', status=405)
            # Add var c column to subset df
            df[c_idx] = box_plot_df[c_idx]
            # Group and reformat data by calculating box plot statistics for each x_idx, c_idx group
            grouped = df.groupby([x_idx, c_idx], observed=True).apply(boxplot_stats).unstack()
            # x_idx, c_idx groups with no values are returned as NaNs and need to be converted to the nan_boxplot
            # representation
            grouped = grouped.map(lambda x: nan_boxplot if pd.isna(x) else x)
            # Add for each color var its own dict containing its label, a background and darker border color, some
            # styling parameters and the box plot statistics in a data dictionary.
            color = 0
            num_colors = len(grouped.columns)
            colormap_local = get_palette(request.GET.get('colors', 'tab10'), n_colors=num_colors)
            # check if more colors are needed than available, if yes enlarge palette to required size
            bordercolor_map_local = [rgb_to_hex(darken_rgb(rgb)) for rgb in colormap_local]
            colormap_local = [rgb_to_hex(rgb) for rgb in colormap_local]
            for group_name in grouped.columns:
                dataset = {
                    'label': var_label_mapping(c_idx, group_name, var_label_map),
                    'backgroundColor': colormap_local[color],
                    'borderColor': bordercolor_map_local[color],
                    'padding': 10,
                    'itemRadius': 0,
                    'borderWidth': 1,
                    # Get stats for each group. If group has less than 5 values (excluding Nan's) only nan stats are
                    # sent for privacy protection.
                    'data': grouped[group_name].tolist(),
                }
                temp.append(dataset)
                color += 1
        # if no color var c is given only group by x var
        else:
            # Group and reformat data by calculating box plot statistics for each x_idx group
            grouped = df.groupby(x_idx).apply(boxplot_stats)
            # Make a dict containing a background and darker border color, some styling parameters and
            # the box plot statistics in a data dictionary.
            col = get_palette(request.GET.get('colors', 'tab10'), n_colors=1)
            fill_col = rgb_to_hex(col[0])
            border_col = rgb_to_hex(darken_rgb(col[0]))
            temp_style = {
                "label": "Whole Cohort",
                "backgroundColor": fill_col,
                "borderColor": border_col,
                'padding': 10,
                'itemRadius': 0,
                'borderWidth': 1,
                'data': grouped.tolist(),
            }
            temp.append(temp_style)
        # Store unique x_var values
        req_data_dict = {
            'labels': var_label_mapping(x_idx, grouped.index.tolist(), var_label_map),
            'datasets': temp
        }
        if privacy_triggered[0]:
            req_data_dict["warning"] = "Some groups' statistics have been hidden to protect privacy."
        response = JsonResponse(req_data_dict, safe=True)
        response = add_cache_header(response, request.GET.get('default'))
        return response


@extend_schema_view(get=heatmap_schema)
class GetDataHeatmapView(generics.GenericAPIView):
    data_manager = None

    def get(self, request):
        all_data, var_label_map, layers, layer_subgroups = self.data_manager.get_df_copy(
            ['all_data', 'var_label_map', 'layers', 'layer_subgroups']
        )
        # Get request vars
        x = request.GET.get("x")
        y = request.GET.get("y")
        # Check if x and y var are given -> else throw HttpResponseBadRequest
        if x is None or x == "" or y is None or y == "":
            return HttpResponseBadRequest('Variable x and y must be declared.', status=405)
        # Check if variables are equal because this will not return meaningful results and can throw an error later
        # -> not necessary here since it works but for consistency can be included
        # if x == y:
        #    return HttpResponseBadRequest(
        #        'Variable x and y must be different', status=405)
        x_idx = extract_var_id(x)
        y_idx = extract_var_id(y)

        send_warning = False

        heatmap_df = context_subset(request, all_data, layers, layer_subgroups)
        # Check if x and y var are present in our data -> else throw HttpResponseBadRequest
        if x_idx not in heatmap_df.columns or y_idx not in heatmap_df.columns:
            return HttpResponseBadRequest('Variable x and y must be a valid variable of the data', status=405)
        contingency_tab = pd.crosstab(heatmap_df[x_idx], heatmap_df[y_idx])

        # Zero out cells representing fewer participants than the privacy threshold, same
        # pattern as GetDataBarCountView/GetDataPieCountView.
        if settings.PRESERVE_PRIVACY and (contingency_tab.values < settings.CRITICAL_NUMBER).any():
            send_warning = True
            contingency_tab = contingency_tab.where(contingency_tab >= settings.CRITICAL_NUMBER, 0)

        x_categories = var_label_mapping(x_idx, [str(v) for v in contingency_tab.index], var_label_map)
        y_categories = var_label_mapping(y_idx, [str(v) for v in contingency_tab.columns], var_label_map)

        # 'v'/'c' (a rank string and a pre-baked palette color) used to also be sent per cell,
        # but the frontend (OverviewHeatmap.vue) only ever reads 'r' -- it computes its own
        # colors from the z grid via Plotly's colorscale -- so those were always dead weight.
        values = [
            {'x': x_categories[i], 'y': y_categories[j], 'r': float(contingency_tab.iloc[i, j])}
            for i in range(len(contingency_tab.index))
            for j in range(len(contingency_tab.columns))
        ]

        req_data_dict = {
            'xCategories': x_categories,
            'yCategories': y_categories,
            'values': values,
        }
        if send_warning:
            req_data_dict["warning"] = "Some cells have been removed to protect privacy."

        response = JsonResponse(req_data_dict, safe=True)
        response = add_cache_header(response, request.GET.get('default'))
        return response

#@extend_schema_view(get=get_density_plot_schema)
class GetDataDensityHistogramPlotView(generics.GenericAPIView):
    data_manager = None

    def get(self, request):
        all_data, var_label_map, layers, layer_subgroups = self.data_manager.get_df_copy(
            ['all_data', 'var_label_map', 'layers', 'layer_subgroups']
        )

        send_warning = False

        # Get request vars
        x = request.GET.get("x")
        c = request.GET.get("c")
        try:
            num_bins = int(request.GET.get("bins", 50))  # Default to 50 if 'bins' is not provided
        except ValueError:
            num_bins = 50  # If the conversion fails, fallback to 50

        # Check if x and y var are given -> else throw HttpResponseBadRequest
        if x is None or x == "":
            return HttpResponseBadRequest('Variable x must be declared.', status=405)
        # Get var_id from request var (stored in brackets at the end of the request var which is built
        # from description + (var_id) (in case of phenotypes and proteins))
        x_idx = extract_var_id(x)

        density_plot_df = context_subset(request, all_data, layers, layer_subgroups)

        # Check if there is in general enough data != nan to ensure privacy protection
        if settings.PRESERVE_PRIVACY:
            if len(density_plot_df[x_idx].dropna()) < settings.CRITICAL_NUMBER:
                return JsonResponse({
                    'labels': [],
                    'datasets': [{'label': 'No Data Available', 'data': [], 'borderColor': 'rgba(0,0,0,0)',
                                  'backgroundColor': 'rgba(0,0,0,0, 0.1)', 'fill': False, 'tension': 0.3}],
                    "warning" : "Not enough data available to ensure privacy protection."
                })

        if x_idx not in density_plot_df.columns:
            return HttpResponseBadRequest('Variable x must be a valid variable of the data', status=405)

        # np.min/np.max propagate NaN if any value is missing (unlike nanmin/nanmax), which
        # would make the bins -- and the whole response -- all-NaN and unserializable as JSON.
        valid_x = density_plot_df[x_idx].dropna()
        if len(valid_x) == 0:
            return JsonResponse({
                'labels': [],
                'datasets': [{'label': 'No Data Available', 'data': [], 'borderColor': 'rgba(0,0,0,0)',
                              'backgroundColor': 'rgba(0,0,0,0, 0.1)', 'fill': False, 'tension': 0.3}],
            })
        min_val, max_val = valid_x.min(), valid_x.max()
        bin_width = (max_val - min_val) / num_bins

        # Create histogram bins and bin centers for the entire data
        bins = np.linspace(min_val, max_val, num_bins + 1)
        bin_centers = (bins[:-1] + bins[1:]) / 2  # Compute the bin centers

        def compute_density(data):
            # Drop NaNs so they neither skew the histogram counts nor deflate the total,
            # and so an all-NaN group produces zeros instead of a 0/0 NaN density.
            data = data.dropna()
            total = len(data)
            if total == 0:
                return [0.0] * num_bins

            # Count the number of values in each bin
            hist, _ = np.histogram(data, bins=bins)

            # Normalize the histogram to get the density (integral of density should be 1)
            density = hist / (total * bin_width)

            return density.tolist()

        temp = []

        if c is not None and c != "":
            # Get var_id from request var (stored in brackets at the end of the requents var which is built
            # from description + (var_id) (in case of phenotypes and proteins))
            c_idx = extract_var_id(c)
            # Check if c var is present in our data -> else throw HttpResponseBadRequest
            if c_idx not in density_plot_df.columns:
                return HttpResponseBadRequest(
                    'Variable c, if declared, must be a valid variable of the data', status=405)
            # Check if variables are equal because this will not return meaningful results and can throw an error later
            if c == x:
                return HttpResponseBadRequest('Variable x and c must be different', status=405)

            # Group by the color variable and calculate density for each group
            grouped_data = density_plot_df.groupby(c_idx, observed=True)[x_idx]

            num_colors = len(list(grouped_data.groups.keys()))
            colormap_local = [tuple(map(lambda x: round(x * 255), color)) for color
                            in get_palette(request.GET.get('colors', 'tab10'), n_colors=num_colors)]

            for idx, (group_name, data) in enumerate(grouped_data):
                # Check per group if there is enough data != nan to ensure privacy protection
                # if not skip this group
                if settings.PRESERVE_PRIVACY:
                    if len(data.dropna()) < settings.CRITICAL_NUMBER:
                        send_warning = True
                        continue
                r, g, b = colormap_local[idx]
                logger.debug(f"compute_density(data): {compute_density(data)}")
                temp.append({"label": var_label_mapping(c_idx, group_name, var_label_map),
                                "borderColor": f"rgb({r},{g},{b})",
                                "backgroundColor": f"rgba({r},{g},{b}, 0.4)",
                                "data": compute_density(data),
                                "fill": True,
                                "tension": 0.3,}),

        # if no color var c is given only group by x var
        else:
            # Add dict for y axis containing the y label, black as the color and the aggregated values
            r,g,b = [tuple(map(lambda x: round(x * 255), color)) for color
                            in get_palette(request.GET.get('colors', 'tab10'), n_colors=1)][0]
            temp.append({
                "label": "Whole Cohort",
                "borderColor": f"rgba({r},{g},{b})",
                "backgroundColor": f"rgba({r},{g},{b}, 0.4)",
                "data": compute_density(density_plot_df[x_idx]),
                "fill": True,
                "tension": 0.3,
            })
        # Store unique x_var values
        req_data = {
            'labels': np.round(bin_centers,2).tolist(),
            'datasets': temp,
        }
        if send_warning:
            req_data["warning"] = "Some groups have been removed to protect privacy."

        response = JsonResponse(req_data, safe=True)
        response = add_cache_header(response, request.GET.get('default'))
        return response
