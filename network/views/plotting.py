import timeit

from django.core.cache import cache
from django.http import JsonResponse
from matplotlib.colors import Normalize
from rest_framework import generics
from django.http import HttpResponseBadRequest
from django.conf import settings
from drf_spectacular.utils import extend_schema_view
from scipy.stats import gaussian_kde

from network.contexts.contexts import subset_patients, context_subset
from network.models import CohortVariant
from network.schemas.plotting_schemas import *
from network.utils.color_utils import *
from network.utils.db_utils import get_context
from network.utils.utils import *


@extend_schema_view(get=get_table_schema)
class GetTableView(generics.GenericAPIView):
    data_manager = None

    def get(self, request):
        all_data, proteins, phenotypes, metabolites = self.data_manager.get_df_copy(['all_data', 'proteins',
                                                                                    'phenotypes', 'metabolites'])

        # build result dict in right format
        if not request.GET.get("contextValue") or not request.user.is_authenticated:
            req_data_dict = {'Participants': len(all_data),
                             'Phenotypes': len(phenotypes.columns) if phenotypes is not None else 0,
                             'Proteins': len(proteins.columns) if proteins is not None else 0,
                             'Metabolites': len(metabolites.columns) if metabolites is not None else 0,
                             'Genetic Variants': CohortVariant.objects.count()}
            response = JsonResponse(req_data_dict, safe=True)
            response = add_cache_header(response, True)
            return response

        # retrieve the context given the context value and user
        context = get_context(request.user, request.GET.get('contextValue'))

        if not context:
            return HttpResponseBadRequest('Context not found', status=405)

        if f"participants_context_{context.context_id}" in cache:
            logger.debug("Cache hit for subset data")
            start = timeit.default_timer()
            participants = cache.get(f"participants_context_{context.context_id}")
            logger.debug(f"Retrieved participants from cache in {timeit.default_timer() - start} seconds")
        else:
            start = timeit.default_timer()
            participants = subset_patients(all_data, context.params).shape[0]
            logger.debug(f"Subsetted participants in {timeit.default_timer() - start} seconds")
        if settings.PRESERVE_PRIVACY:
            if participants < settings.CRITICAL_NUMBER:
                participants = 0
            else:
                participants = max(settings.CRITICAL_NUMBER, int(round(participants / 100) * 100))

        phenotypes_num = len(phenotypes.columns) if 'phenomics' in context.params['layers'] else 0
        proteins_num = len(proteins.columns) if 'proteomics' in context.params['layers'] else 0
        metabolites_num = len(metabolites.columns) if 'metabolomics' in context.params['layers'] else 0
        variants_num = 0 if 'variants' in context.params['layers'] else 0

        req_data_dict = {'Participants': participants, 'Phenotypes': phenotypes_num, 'Proteins': proteins_num,
                         'Metabolites': metabolites_num, 'Genetic Variants': variants_num}
        return JsonResponse(req_data_dict, safe=True)


@extend_schema_view(get=get_data_schema)
class GetDataLinePlotView(generics.GenericAPIView):
    data_manager = None

    def get(self, request):
        all_data, var_label_map = self.data_manager.get_df_copy(['all_data', 'var_label_map'])
        # Get request vars
        try:
            x, y, c = plot_variables(request)
        except ValueError as ex:
            return HttpResponseBadRequest(str(ex), status=405)

        # Get var_id from request vars (stored in brackets at the end of the requests var which is built
        # from description + (var_id) or (in case of metabolites) simply the request var)
        x_idx = extract_var_id(x)
        y_idx = extract_var_id(y)

        line_plot_df = context_subset(request, all_data)

        if x_idx not in line_plot_df.columns or y_idx not in line_plot_df.columns:
            return HttpResponseBadRequest('Variable x and y must be a valid variable of the data', status=405)

        if pd.api.types.is_string_dtype(line_plot_df[y_idx]):
            return HttpResponseBadRequest(
                'y Variable is not numerical and can not be visualized in this plot.', status=405)

        df = pd.DataFrame(line_plot_df[[x_idx, y_idx]])
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

            agg_df_mean = df.groupby([x_idx, c_idx])

            if settings.PRESERVE_PRIVACY:
                agg_df_mean = agg_df_mean.filter(lambda x: x[y_idx].notna().sum() >= settings.CRITICAL_NUMBER)

            agg_df_mean = (agg_df_mean.groupby([x_idx, c_idx])[y_idx].mean()
                           .reset_index().sort_values(x_idx, ascending=True))

            # Add for each color var its own dict containing its label, a color from the color palette and a dict that
            # associates the aggregated values with the corresponding x value (this way we do not have to create NaN
            # values for x positions with no aggregated value present)
            color = 0
            num_colors = len(line_plot_df[c_idx].unique())
            colormap_local = get_palette(request.GET.get('colors', 'tab10'), n_colors=num_colors)
            colormap_local = [rgb_to_hex(rgb) for rgb in colormap_local]
            for group_name, group_data in agg_df_mean.groupby(c_idx):
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
            agg_df_mean = df.groupby(x_idx)
            if settings.PRESERVE_PRIVACY:
                agg_df_mean = agg_df_mean.filter(lambda x: x[y_idx].notna().sum() >= settings.CRITICAL_NUMBER)

            agg_df_mean = agg_df_mean.groupby(x_idx)[y_idx].mean().reset_index().sort_values(x_idx, ascending=True)

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
        response = JsonResponse(req_data_dict, safe=True)
        response = add_cache_header(response, request.GET.get('default'))
        return response


@extend_schema_view(get=get_bar_count_schema)
class GetDataBarCountView(generics.GenericAPIView):
    data_manager = None

    def get(self, request):
        all_data, var_label_map = self.data_manager.get_df_copy(['all_data', 'var_label_map'])

        send_warning = False

        # Get request vars
        x = request.GET.get("x")
        c = request.GET.get("c")

        # build result dict in right format
        req_data_dict = {}
        # Check if x and y var are given -> else throw HttpResponseBadRequest
        if x is None or x == "":
            return HttpResponseBadRequest('Variable x must be declared.', status=405)
        # Get var_id from request var (stored in brackets at the end of the request var which is built
        # from description + (var_id) (in case of phenotypes and proteins))
        x_idx = extract_var_id(x)

        bar_plot_df = context_subset(request, all_data)

        if x_idx not in bar_plot_df.columns:
            return HttpResponseBadRequest('Variable x must be a valid variable of the data', status=405)
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
            if c == x:
                return HttpResponseBadRequest('Variable x and c must be different', status=405)
            # Make df subset with x, c var and a count value for each pair of group
            # TODO Group combinations where c_idx is NaN will not be returned and therefore not appear ->
            #  return 0 instead?
            df_count = bar_plot_df[[x_idx, c_idx]].groupby([x_idx, c_idx]).size().reset_index(name='counts')

            if settings.PRESERVE_PRIVACY:
                df_count.loc[df_count['counts'] < settings.CRITICAL_NUMBER, 'counts'] = 0
                send_warning = True

            # Add for each color var its own dict containing its label, a color from the color palette and a dict that
            # associates the count values with the corresponding x value
            color = 0
            num_colors = len(bar_plot_df[c_idx].unique())
            colormap_local = get_palette(request.GET.get('colors', 'tab10'), n_colors=num_colors)
            colormap_local = [rgb_to_hex(rgb) for rgb in colormap_local]
            for group_name, group_data in df_count.groupby(c_idx):
                temp.append({
                    "label": var_label_mapping(c_idx, group_name, var_label_map),
                    "backgroundColor": colormap_local[color],
                    "data": [{'x': var_label_mapping(x_idx, x, var_label_map), 'y': y} for x, y in
                             zip(group_data[x_idx], group_data['counts'])]
                })
                color += 1
        # if no color var c is given only group by x var
        else:
            # Make df subset with x var and a count variable
            df_count = pd.DataFrame(bar_plot_df[x_idx]).groupby(x_idx).size().reset_index(name='counts')
            if settings.PRESERVE_PRIVACY:
                df_count.loc[df_count['counts'] < settings.CRITICAL_NUMBER, 'counts'] = 0
                send_warning = True

            # Add dict for y axis containing the y label, black as the color and the aggregated values
            temp.append({
                "label": "Whole Cohort",
                "backgroundColor": rgb_to_hex(get_palette(request.GET.get('colors', 'tab10'), n_colors=1)[0]),
                "data": df_count['counts'].tolist()
            })
        # Store unique x_var values
        req_data_dict["labels"] = var_label_mapping(x_idx, df_count[x_idx].unique().tolist(), var_label_map)
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
        all_data, var_label_map = self.data_manager.get_df_copy(['all_data', 'var_label_map'])

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

        pie_plot_df = context_subset(request, all_data)

        if x_idx not in pie_plot_df.columns:
            return HttpResponseBadRequest('Variable x must be a valid variable of the data', status=405)
        temp = []

        # Make df subset with x var and a count variable
        df_count = pd.DataFrame(pie_plot_df[x_idx]).groupby(x_idx).size().reset_index(name='counts')
        if settings.PRESERVE_PRIVACY:
            df_count.loc[df_count['counts'] < settings.CRITICAL_NUMBER, 'counts'] = 0
            send_warning = True

        num_colors = len(df_count["counts"].tolist())
        colormap_local = get_palette(request.GET.get('colors', 'tab10'), n_colors=num_colors)
        colormap_local = [rgb_to_hex(rgb) for rgb in colormap_local]
        temp.append({
            "backgroundColor": colormap_local,
            "data": df_count['counts'].tolist()
        })
        # Store unique x_var values
        req_data_dict["labels"] = var_label_mapping(x_idx, df_count[x_idx].unique().tolist(), var_label_map)
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
        all_data, var_label_map = self.data_manager.get_df_copy(['all_data', 'var_label_map'])

        send_warning = False

        # Get request vars
        x = request.GET.get("x")
        c = request.GET.get("c")
        bw_method = float(request.GET.get("bandwidth"))

        # Check if x is provided
        if x is None or x == "":
            return HttpResponseBadRequest('Variable x must be declared.', status=405)

        # Extract var_id from x (for phenotype or protein)
        x_idx = extract_var_id(x)

        density_plot_df = context_subset(request, all_data)

        # Check if there is in general enough data != nan to ensure privacy protection
        if settings.PRESERVE_PRIVACY:
            if len(density_plot_df[x_idx].dropna()) < settings.CRITICAL_NUMBER:
                return {
                    'labels': [],
                    'datasets': [{'label': 'No Data Available', 'data': [], 'borderColor': 'rgba(0,0,0,0)',
                                  'backgroundColor': 'rgba(0,0,0,0, 0.1)', 'fill': False, 'tension': 0.3}],
                    "warning" : "Not enough data available to ensure privacy protection."
                }

        if x_idx not in density_plot_df.columns:
            return HttpResponseBadRequest('Variable x must be a valid variable of the data', status=405)

        min_val, max_val = np.min(density_plot_df[x_idx]), np.max(density_plot_df[x_idx])

        kde = gaussian_kde(density_plot_df[x_idx].dropna(), bw_method=0.1)

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
            grouped_data = density_plot_df.groupby(c_idx)[x_idx]

            num_colors = len(density_plot_df[c_idx].unique())
            colormap_local = [tuple(map(lambda x: round(x * 255), color)) for color in
                              get_palette(request.GET.get('colors', 'tab10'), n_colors=num_colors)]

            for idx, (group_name, data) in enumerate(grouped_data):
                # Check per group if there is enough data != nan to ensure privacy protection
                # if not skip this group
                if settings.PRESERVE_PRIVACY:
                    if len(data.dropna()) < settings.CRITICAL_NUMBER:
                        send_warning = True
                        continue
                # KDE for each group
                kde_group = gaussian_kde(data.dropna(), bw_method=bw_method)
                y_vals_group = kde_group(x_vals)
                y_vals_group /= np.sum(y_vals_group) * (x_vals[1] - x_vals[0])  # Normalize

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
        if send_warning:
            req_data["warning"] = "Some groups have been removed to protect privacy."

        response = JsonResponse(req_data, safe=True)
        response = add_cache_header(response, request.GET.get('default'))
        return response


@extend_schema_view(get=get_box_plot_schema)
class GetDataBoxPlotView(generics.GenericAPIView):
    data_manager = None

    def get(self, request):
        all_data, var_label_map = self.data_manager.get_df_copy(['all_data', 'var_label_map'])

        # Fill NaN values with the NaN boxplot dictionary
        nan_boxplot = {'min': None, 'q1': None, 'median': None, 'mean': None, 'q3': None, 'max': None}

        try:
            x, y, c = plot_variables(request)
        except ValueError as ex:
            return HttpResponseBadRequest(str(ex), status=405)

        x_idx = extract_var_id(x)  # Extract var_id from request var
        y_idx = extract_var_id(y)

        box_plot_df = context_subset(request, all_data)

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
        def boxplot_stats(group):
            if (settings.PRESERVE_PRIVACY and group[y_idx].notna().sum() >= settings.CRITICAL_NUMBER or
                    not settings.PRESERVE_PRIVACY):
                return {
                    'min': group[y_idx].min(),
                    'q1': group[y_idx].quantile(0.25),
                    'median': group[y_idx].median(),
                    'mean': group[y_idx].mean(),
                    'q3': group[y_idx].quantile(0.75),
                    'max': group[y_idx].max(),
                }
            else:
                return nan_boxplot

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
            grouped = df.groupby([x_idx, c_idx]).apply(boxplot_stats).unstack()
            # x_idx, c_idx groups with no values are returned as NaNs and need to be converted to the nan_boxplot
            # representation
            grouped = grouped.map(lambda x: nan_boxplot if pd.isna(x) else x)
            # Add for each color var its own dict containing its label, a background and darker border color, some
            # styling parameters and the box plot statistics in a data dictionary.
            color = 0
            num_colors = len(box_plot_df[c_idx].unique())
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
        response = JsonResponse(req_data_dict, safe=True)
        response = add_cache_header(response, request.GET.get('default'))
        return response


@extend_schema_view(get=heatmap_schema)
class GetDataHeatmapView(generics.GenericAPIView):
    data_manager = None

    def get(self, request):
        all_data, var_label_map = self.data_manager.get_df_copy(['all_data', 'var_label_map'])
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

        heatmap_df = context_subset(request, all_data)

        # Check if x and y var are present in our data -> else throw HttpResponseBadRequest
        if x_idx not in heatmap_df.columns or y_idx not in heatmap_df.columns:
            return HttpResponseBadRequest('Variable x and y must be a valid variable of the data', status=405)
        # compute contingency table
        contingency_tab = pd.crosstab(heatmap_df[x_idx], heatmap_df[y_idx])
        contingency_tab_inverse = np.array(contingency_tab.values).T
        min_val, max_val = contingency_tab_inverse.min(), contingency_tab_inverse.max()
        x_categories = var_label_mapping(x_idx, contingency_tab.index.astype(str).tolist(), var_label_map)
        y_categories = var_label_mapping(y_idx, contingency_tab.columns.astype(str).tolist(), var_label_map)

        # get colors for heatmap, 3 colors: low, medium, high
        palette = get_palette(request.GET.get('colors', 'viridis'), as_cmap=True)
        norm_col = Normalize(vmin=min_val, vmax=max_val)

        values = []
        for i in range(len(contingency_tab.index)):
            for j in range(len(contingency_tab.columns)):
                x_value = x_categories[i]
                y_value = y_categories[j]
                value = contingency_tab_inverse[j][i]
                color = rgb_to_hex(palette(norm_col(value)))
                values.append({'x': x_value, 'y': y_value, 'v': f'{i+1}{j+1}', 'r': float(value), 'c': color})

        # save in dictionary and return in json format
        req_data_dict = {}
        req_data_dict["xCategories"] = x_categories
        req_data_dict["yCategories"] = y_categories
        req_data_dict["values"] = values

        response = JsonResponse(req_data_dict, safe=True)
        response = add_cache_header(response, request.GET.get('default'))
        return response

#@extend_schema_view(get=get_density_plot_schema)
class GetDataDensityHistogramPlotView(generics.GenericAPIView):
    data_manager = None

    def get(self, request):
        all_data, var_label_map = self.data_manager.get_df_copy(['all_data', 'var_label_map'])

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

        density_plot_df = context_subset(request, all_data)

        # Check if there is in general enough data != nan to ensure privacy protection
        if settings.PRESERVE_PRIVACY:
            if len(density_plot_df[x_idx].dropna()) < settings.CRITICAL_NUMBER:
                return {
                    'labels': [],
                    'datasets': [{'label': 'No Data Available', 'data': [], 'borderColor': 'rgba(0,0,0,0)',
                                  'backgroundColor': 'rgba(0,0,0,0, 0.1)', 'fill': False, 'tension': 0.3}],
                    "warning" : "Not enough data available to ensure privacy protection."
                }

        if x_idx not in density_plot_df.columns:
            return HttpResponseBadRequest('Variable x must be a valid variable of the data', status=405)

        min_val, max_val = np.min(density_plot_df[x_idx]), np.max(density_plot_df[x_idx])
        bin_width = (max_val - min_val) / num_bins

        # Create histogram bins and bin centers for the entire data
        bins = np.linspace(min_val, max_val, num_bins + 1)
        bin_centers = (bins[:-1] + bins[1:]) / 2  # Compute the bin centers

        def compute_density(data):

            # Count the number of values in each bin
            hist, _ = np.histogram(data, bins=bins)

            # Normalize the histogram to get the density (integral of density should be 1)
            total = len(data)
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
            grouped_data = density_plot_df.groupby(c_idx)[x_idx]

            num_colors = len(density_plot_df[c_idx].unique())
            colormap_local = [tuple(map(lambda x: round(x * 255), color)) for color
                            in get_palette(request.GET.get('colors', 'tab10'), n_colors=num_colors)]
            print(f"colormap_local: {colormap_local}")

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
