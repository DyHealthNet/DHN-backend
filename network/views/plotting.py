import pandas as pd
from django.http import JsonResponse
from rest_framework import generics
from django.http import HttpResponseBadRequest
from django.apps import apps
from network.models import CohortVariant
from drf_spectacular.utils import extend_schema_view
from network.schemas.plotting_schemas import *
from network.utils import *
from network.color_utils import *

import environ

env = environ.Env()
environ.Env.read_env()

config = apps.get_app_config('network')


@extend_schema_view(
    get=get_table_schema
)
class GetTableView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        # build result dict in right format
        req_data_dict = {'Participants': len(config.all_data), 'Phenotypes': len(config.PHENOTYPES.columns),
                         'Proteins': len(config.PROTEINS.columns) if config.PROTEINS is not None else 0,
                         'Metabolites': len(config.METABOLITES.columns) if config.METABOLITES is not None else 0,
                         'Genetic Variants': CohortVariant.objects.count()}
        # Get Phenotype mera file to count the different data types (currently not used in frontend table)
        df = pd.DataFrame(config.PHENO_META[env("PHENOTYPE_TYPE_COLUMN")][
                              [(i in config.PHENOTYPES.columns) for i in
                               config.PHENO_META.index]].copy()).value_counts()
        req_data_dict['Phenotype-Boolean'] = int(df['boolean']) if 'boolean' in df.index else 0
        req_data_dict['Phenotype-Categorical'] = int(df['categorical']) if 'categorical' in df.index else 0
        req_data_dict['Phenotype-Float'] = int(df['float']) if 'float' in df.index else 0
        req_data_dict['Phenotype-Integer'] = int(df['integer']) if 'integer' in df.index else 0
        req_data_dict['Phenotype-Time'] = int(df['time']) if 'time' in df.index else 0
        return JsonResponse(req_data_dict, safe=True)


@extend_schema_view(
    get=get_data_schema
)
class GetDataView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        # Get request vars
        try:
            x, y, c = plot_variables(request)
        except ValueError as ex:
            return HttpResponseBadRequest(str(ex), status=405)

        # Get var_id from request vars (stored in brackets at the end of the requests var which is built
        # from description + (var_id) or (in case of metabolites) simply the request var)
        x_idx = extract_var_id(x)
        y_idx = extract_var_id(y)

        if x_idx not in config.all_data.columns or y_idx not in config.all_data.columns:
            return HttpResponseBadRequest('Variable x and y must be a valid variable of the data', status=405)

        if pd.api.types.is_string_dtype(config.all_data[y_idx]):
            return HttpResponseBadRequest(
                'y Variable is not numerical and can not be visualized in this plot.', status=405)

        df = pd.DataFrame(config.all_data[[x_idx, y_idx]])
        temp = []
        if c is not None and c != "":
            # Get var_id from request var (stored in brackets at the end of the request var which is built
            # from description + (var_id) (in case of phenotypes and proteins))
            c_idx = extract_var_id(c)
            # Check if c var is present in our data -> else throw HttpResponseBadRequest
            if c_idx not in config.all_data.columns:
                return HttpResponseBadRequest('Variable c, if declared, must be a valid variable of the data',
                                              status=405)
            # Check if variables are equal because this will not return meaningful results and can throw an error later
            if c == x or c == y:
                return HttpResponseBadRequest(
                    'Variable x and y must be different from c', status=405)
            # Add var c column to subset df
            df[c_idx] = config.all_data[c_idx]
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
            colormap_local = COLOR_PALETTE
            num_colors = len(config.all_data[c_idx].unique())
            # check if more colors are needed than available, if yes enlarge palette to required size
            if num_colors > len(colormap_local):
                colormap_local = enlarge_palette(COLOR_PALETTE, num_colors)
            colormap_local = [rgb_to_hex(rgb) for rgb in colormap_local]
            for group_name, group_data in aggregated_df_mean.groupby(c_idx):
                temp.append({
                    "label": var_label_mapping(c_idx, group_name, config.VAR_LABEL_MAP),
                    "backgroundColor": colormap_local[color],
                    "borderColor": lighten_color(colormap_local[color]),
                    "data": [{'x': var_label_mapping(x_idx, x, config.VAR_LABEL_MAP), 'y': y} for x, y in
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
            'labels': var_label_mapping(x_idx, aggregated_df_mean[x_idx].unique().tolist(), config.VAR_LABEL_MAP),
            'datasets': temp
        }
        return JsonResponse(req_data_dict, safe=True)


@extend_schema_view(
    get=get_bar_count_schema
)
class GetDataBarCountView(generics.GenericAPIView):
    @staticmethod
    def get(request):
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

        if x_idx not in config.all_data.columns:
            return HttpResponseBadRequest('Variable x must be a valid variable of the data', status=405)
        temp = []

        if c is not None and c != "":
            # Get var_id from request var (stored in brackets at the end of the requents var which is built
            # from description + (var_id) (in case of phenotypes and proteins))
            c_idx = extract_var_id(c)
            # Check if c var is present in our data -> else throw HttpResponseBadRequest
            if c_idx not in config.all_data.columns:
                return HttpResponseBadRequest(
                    'Variable c, if declared, must be a valid variable of the data', status=405)
            # Check if variables are equal because this will not return meaningful results and can throw an error later
            if c == x:
                return HttpResponseBadRequest('Variable x and c must be different', status=405)
            # Make df subset with x, c var and a count value for each pair of group
            # TODO Group combinations where c_idx is NaN will not be returned and therefore not appear ->
            #  return 0 instead?
            df_count = config.all_data[[x_idx, c_idx]].groupby([x_idx, c_idx]).size().reset_index(name='counts')
            # Add for each color var its own dict containing its label, a color from the color palette and a dict that
            # associates the count values with the corresponding x value
            color = 0
            colormap_local = COLOR_PALETTE
            num_colors = len(config.all_data[c_idx].unique())
            # check if more colors are needed than available, if yes enlarge palette to required size
            if num_colors > len(colormap_local):
                colormap_local = enlarge_palette(COLOR_PALETTE, num_colors)
            colormap_local = [rgb_to_hex(rgb) for rgb in colormap_local]
            for group_name, group_data in df_count.groupby(c_idx):
                temp.append({
                    "label": var_label_mapping(c_idx, group_name, config.VAR_LABEL_MAP),
                    "backgroundColor": colormap_local[color],
                    "data": [{'x': var_label_mapping(x_idx, x, config.VAR_LABEL_MAP), 'y': y} for x, y in
                             zip(group_data[x_idx], group_data['counts'])]
                })
                color += 1
        # if no color var c is given only group by x var
        else:
            # Make df subset with x var and a count variable
            df_count = pd.DataFrame(config.all_data[x_idx]).groupby(x_idx).size().reset_index(name='counts')
            # Add dict for y axis containing the y label, black as the color and the aggregated values
            temp.append({
                "label": "Whole Population",  # TODO rather empty label?
                "backgroundColor": "black",  # TODO change default color?
                "data": df_count['counts'].tolist()
            })
        # Store unique x_var values
        req_data_dict["labels"] = var_label_mapping(x_idx, df_count[x_idx].unique().tolist(), config.VAR_LABEL_MAP)
        # Store the count data values
        req_data_dict["datasets"] = temp
        return JsonResponse(req_data_dict, safe=True)


@extend_schema_view(
    get=get_box_plot_schema
)
class GetDataBoxPlotView(generics.GenericAPIView):
    @staticmethod
    def get(request):
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

        # Get var_id from request vars (stored in brackets at the end of the requests var which is built
        # from description + (var_id) or (in case of metabolites) simply the request var)
        x_idx = extract_var_id(x)
        y_idx = extract_var_id(y)
        # Check if x and y var are present in our data -> else throw HttpResponseBadRequest
        if x_idx not in config.all_data.columns or y_idx not in config.all_data.columns:
            return HttpResponseBadRequest('Variable x and y must be a valid variable of the data',
                                          status=405)
        # Check if y var is a string (e.g. time variable) which would result in an error during aggregation
        # -> else throw HttpResponseBadRequest
        if pd.api.types.is_string_dtype(config.all_data[y_idx]):
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
        df = pd.DataFrame(config.all_data[[x_idx, y_idx]])
        # Check if c var is given and if so split data by it
        if c is not None and c != "":
            c_idx = extract_var_id(c)
            # Check if c var is present in our data -> else throw HttpResponseBadRequest
            if c_idx not in config.all_data.columns:
                return HttpResponseBadRequest(
                    'Variable c, if declared, must be a valid variable of the data', status=405)
            # Check if variables are equal because this will not return meaningful results and can throw an error later
            if c == x or c == y:
                return HttpResponseBadRequest(
                    'Variable x and y must be different from c', status=405)
            # Add var c column to subset df
            df[c_idx] = config.all_data[c_idx]
            # Group and reformat data by calculating box plot statistics for each x_idx, c_idx group
            grouped = df.groupby([x_idx, c_idx]).apply(boxplot_stats).unstack()
            # x_idx, c_idx groups with no values are returned as NaNs and need to be converted to the nan_boxplot
            # representation
            grouped = grouped.applymap(lambda x: nan_boxplot if pd.isna(x) else x)
            # Add for each color var its own dict containing its label, a background and darker border color, some
            # styling parameters and the box plot statistics in a data dictionary.
            color = 0
            colormap_local = COLOR_PALETTE
            num_colors = len(config.all_data[c_idx].unique())
            # check if more colors are needed than available, if yes enlarge palette to required size
            if num_colors > len(colormap_local):
                colormap_local = enlarge_palette(COLOR_PALETTE, num_colors)
            bordercolor_map_local = [rgb_to_hex(darken_rgb(rgb)) for rgb in colormap_local]
            colormap_local = [rgb_to_hex(rgb) for rgb in colormap_local]
            for group_name in grouped.columns:
                dataset = {
                    'label': var_label_mapping(c_idx, group_name, config.VAR_LABEL_MAP),
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
            'labels': var_label_mapping(x_idx, grouped.index.tolist(), config.VAR_LABEL_MAP),
            'datasets': temp
        }
        return JsonResponse(req_data_dict, safe=True)


@extend_schema_view(
    get=heatmap_schema
)
class GetDataHeatmapView(generics.GenericAPIView):
    @staticmethod
    def get(request):
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
        # Check if x and y var are present in our data -> else throw HttpResponseBadRequest
        if x_idx not in config.all_data.columns or y_idx not in config.all_data.columns:
            return HttpResponseBadRequest('Variable x and y must be a valid variable of the data', status=405)
        # compute contingency table
        contingency_tab = pd.crosstab(config.all_data[x_idx], config.all_data[y_idx])
        # save in dictionary and return in json format
        req_data_dict = {}
        req_data_dict["xCategories"] = var_label_mapping(x_idx, contingency_tab.index.astype(str).tolist(), config.VAR_LABEL_MAP)
        req_data_dict["yCategories"] = var_label_mapping(y_idx, contingency_tab.columns.astype(str).tolist(), config.VAR_LABEL_MAP)
        contingency_tab_inverse = np.array(contingency_tab.values)
        req_data_dict["datasets"] = contingency_tab_inverse.T.tolist()
        return JsonResponse(req_data_dict, safe=True)
