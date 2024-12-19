import pandas as pd
from django.http import JsonResponse
from rest_framework import generics
from django.http import HttpResponseBadRequest
from django.apps import apps

from drf_spectacular.utils import extend_schema_view

from network.contexts.contexts import subset_patients, context_subset
from network.models import CohortVariant
from network.schemas.plotting_schemas import *
from network.utils.color_utils import *
from network.utils.db_utils import get_context
from network.utils.utils import *

import environ

env = environ.Env()
environ.Env.read_env()


@extend_schema_view(
    get=get_table_schema
)
class GetTableView(generics.GenericAPIView):
    data_manager = None

    def get(self, request):
        all_data, proteins, phenotypes, metabolites = self.data_manager.get_df_copy(['all_data', 'proteins',
                                                                                    'phenotypes', 'metabolites'])

        # build result dict in right format
        if not request.GET.get("contextValue") or not request.user.is_authenticated:
            req_data_dict = {'Participants': len(all_data), 'Phenotypes': len(phenotypes.columns),
                             'Proteins': len(proteins.columns) if proteins is not None else 0,
                             'Metabolites': len(metabolites.columns) if metabolites is not None else 0,
                             'Genetic Variants': CohortVariant.objects.count()}
            return JsonResponse(req_data_dict, safe=True)

        # retrieve the context given the context value and user
        context = get_context(request.user, request.GET.get('contextValue'))

        if not context:
            return HttpResponseBadRequest('Context not found', status=405)

        participants = subset_patients(all_data, context.params).shape[0]
        if settings.PRESERVE_PRIVACY:
            participants = int(round(participants / 100) * 100)

        phenotypes, proteins, metabolites, variants = 0, 0, 0, 0
        for layer in context.params['layers']:
            phenotypes = len(phenotypes.columns) if 'phenomics' in layer else phenotypes
            proteins = len(proteins.columns) if 'proteomics' in layer else proteins
            metabolites = len(metabolites.columns) if 'metabolomics' in layer else metabolites
            variants = 0 if 'variants' in layer else variants
        req_data_dict = {'Participants': participants, 'Phenotypes': phenotypes, 'Proteins': proteins,
                         'Metabolites': metabolites, 'Genetic Variants': variants}
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
            aggregated_df_mean = (df.groupby([x_idx, c_idx]).filter(lambda x:
                                                                    x[y_idx].notna().sum() >= 5).groupby(
                [x_idx, c_idx])[y_idx].mean().reset_index().
                                  sort_values(x_idx, ascending=True))
            # Add for each color var its own dict containing its label, a color from the color palette and a dict that
            # associates the aggregated values with the corresponding x value (this way we do not have to create NaN
            # values for x positions with no aggregated value present)
            color = 0
            colormap_local = COLOR_PALETTES.get(request.GET.get('colors', 'tab10'))
            num_colors = len(line_plot_df[c_idx].unique())
            # check if more colors are needed than available, if yes enlarge palette to required size
            if num_colors > len(colormap_local):
                colormap_local = enlarge_palette(colormap_local, num_colors)
            colormap_local = [rgb_to_hex(rgb) for rgb in colormap_local]
            for group_name, group_data in aggregated_df_mean.groupby(c_idx):
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
            aggregated_df_mean = df.groupby(x_idx).filter(lambda x:
                                                          x[y_idx].notna().sum() >= 5).groupby(x_idx)[
                y_idx].mean().reset_index().sort_values(x_idx, ascending=True)
            # Add dict for y-axis containing the y label, black as the color and the aggregated values
            temp.append({
                "label": "Whole Population",
                "backgroundColor": "black",
                "data": aggregated_df_mean[y_idx].tolist()
            })
        # Store unique x_var values
        req_data_dict = {
            'labels': var_label_mapping(x_idx, aggregated_df_mean[x_idx].unique().tolist(), var_label_map),
            'datasets': temp
        }
        return JsonResponse(req_data_dict, safe=True)


@extend_schema_view(
    get=get_bar_count_schema
)
class GetDataBarCountView(generics.GenericAPIView):
    data_manager = None

    def get(self, request):
        all_data, var_label_map = self.data_manager.get_df_copy(['all_data', 'var_label_map'])

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
            # Add for each color var its own dict containing its label, a color from the color palette and a dict that
            # associates the count values with the corresponding x value
            color = 0
            colormap_local = COLOR_PALETTES.get(request.GET.get('colors', 'tab10'))
            num_colors = len(bar_plot_df[c_idx].unique())
            # check if more colors are needed than available, if yes enlarge palette to required size
            if num_colors > len(colormap_local):
                colormap_local = enlarge_palette(colormap_local, num_colors)
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
            # Add dict for y axis containing the y label, black as the color and the aggregated values
            temp.append({
                "label": "Whole Population",  # TODO rather empty label?
                "backgroundColor": "black",  # TODO change default color?
                "data": df_count['counts'].tolist()
            })
        # Store unique x_var values
        req_data_dict["labels"] = var_label_mapping(x_idx, df_count[x_idx].unique().tolist(), var_label_map)
        # Store the count data values
        req_data_dict["datasets"] = temp
        return JsonResponse(req_data_dict, safe=True)


@extend_schema_view(
    get=get_box_plot_schema
)
class GetDataBoxPlotView(generics.GenericAPIView):
    data_manager = None

    def get(self, request):
        all_data, var_label_map = self.data_manager.get_df_copy(['all_data', 'var_label_map'])

        # Fill NaN values with the NaN boxplot dictionary
        nan_boxplot = {
            'min': -100,
            'q1': -100,
            'median': -100,
            'mean': -100,
            'q3': -100,
            'max': -100
        }

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
            if group[y_idx].notna().sum() >= 5:
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
            colormap_local = COLOR_PALETTES.get(request.GET.get('colors', 'tab10'))
            num_colors = len(box_plot_df[c_idx].unique())
            # check if more colors are needed than available, if yes enlarge palette to required size
            if num_colors > len(colormap_local):
                colormap_local = enlarge_palette(colormap_local, num_colors)
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
            temp_style = {
                "label": "Whole Population",
                "backgroundColor": "black",
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
        return JsonResponse(req_data_dict, safe=True)


@extend_schema_view(
    get=heatmap_schema
)
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

        # get colors for heatmap, 3 colors: low, medium, high
        palette = COLOR_PALETTES.get(request.GET.get('colors', 'viridis'))
        colors = [rgb_to_hex(rgb) for rgb in palette]
        colors = [colors[0], colors[int(len(colors)/2)], colors[-1]]

        # save in dictionary and return in json format
        req_data_dict = {}
        req_data_dict["xCategories"] = var_label_mapping(x_idx, contingency_tab.index.astype(str).tolist(), var_label_map)
        req_data_dict["yCategories"] = var_label_mapping(y_idx, contingency_tab.columns.astype(str).tolist(), var_label_map)
        contingency_tab_inverse = np.array(contingency_tab.values)
        req_data_dict["datasets"] = contingency_tab_inverse.T.tolist()
        req_data_dict["colors"] = colors
        return JsonResponse(req_data_dict, safe=True)
