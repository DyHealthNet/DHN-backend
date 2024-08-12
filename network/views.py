import pandas as pd
import re
import numpy as np
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiTypes
from .models import *
from .models import Disorder, CohortProtein, CohortMetabolite, CohortPhenotype, Gene
from .models import (EffectsProteinProtein, EffectsProteinPhenotype,
                     EffectsProteinMetabolite, EffectsPhenotypePhenotype,
                     EffectsMetabolitePhenotype, EffectsMetaboliteMetabolite)
from django.views import generic
from rest_framework import generics
from django.http import HttpResponse, JsonResponse, HttpResponseBadRequest
from itertools import chain
#from orm_queries.network_queries import *
#from orm_queries.typeahead_query import *
from network.queries import *

import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import seaborn as sns

import environ
env = environ.Env()
environ.Env.read_env()

Nodes = {'Disorders':Disorder, 'Proteins':Protein, 'Metabolites':Metabolite, 'Phenotypes': Phenotype, 'Genes':Gene}
Edges = {'EffectsProteinProtein':EffectsProteinProtein,
         'EffectsProteinPhenotype':EffectsProteinPhenotype,
         'EffectsPhenotypePhenotype':EffectsPhenotypePhenotype,
         'EffectsMetabolitePhenotype':EffectsMetabolitePhenotype,
         'EffectsProteinMetabolite':EffectsProteinMetabolite,
         'EffectsMetaboliteMetabolite':EffectsMetaboliteMetabolite}
types = ["protein", "metabolite", "phenotype"] # "disorders", "genes"
phenotypes_filtered = pd.read_csv(
            env("PHENOTYPE_PATH"),
            sep=',', header=0)
phenotypes_meta_filtered = pd.read_csv(
            env("PHENOTYPE_META_PATH"),
            sep='\t', header=0, index_col=0, usecols=['label', 'type', 'description'])

# functions to get appropriate colors for plotting
def rgb_to_hex(rgb):
    return '#{:02x}{:02x}{:02x}'.format(int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))
def darken_rgb(rgb, factor=0.2):
    darkened_rgb = [max(0, min(1, c - factor)) for c in rgb]
    return tuple(darkened_rgb)

@extend_schema_view(
    get=extend_schema(
        summary="Returns the top network edges and corresponding nodes that are connected to a query node q",
        description="""Returns for a query node q the top l (limit, default = 10) network edges and corresponding nodes 
            for each type meaning protein, metabolite, phenotype (e.g. for limit 10 -> 30 edges). To efficiently query
            the correct tables the type of input node as a variable t is required. (Referring to function 
            orm_queries/network_query.)
            e.g. input: q="x0rd09",t="phenotype",limit = 10
            """,
        parameters=[
            OpenApiParameter(
                name='q',
                description='query id/ node id',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='t',
                description='query type/ node type',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='l',
                description='limit (concerning node retrieval)',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            )
        ],
    )
)
class GetNetworkView(generics.GenericAPIView):
    def get(self, request):
        # Get request vars
        query_id = request.GET.get("q")
        type = request.GET.get("t")
        limit = request.GET.get("l")
        if query_id is None or query_id == "":
            return HttpResponseBadRequest('Query id q must be declared and non empty.', status=405)
        if type is None or type not in types:
            return HttpResponseBadRequest('Query type t must be declared and either protein, metabolite and phenotype', status=405)
        if limit is None or limit == "":
            limit = 10
        else:
            try:
                limit = int(limit)
            except ValueError as e:
                return HttpResponseBadRequest(
                    f'Limit l must be a valid integerl, not {limit}', status=405)

        if limit > 20:
            return HttpResponseBadRequest(
                f'Limit l takes a maximal value of 15, not {limit}', status=405)
        # retrieve chris nodes & edges + external edges using orm_queries/network_queries function
        edges, nodes, externals = network_query(query_id, type, limit)
        # reformat Edges and Nodes and return as json
        Edges = {}
        for table, results in edges.items():
            Edges[table] = list(results)
        Nodes = {}
        for results in nodes:
            # Add reference id(s) (if present) to a nodes description dict using the node_reference_dict
            if results['source_table'] in Nodes:
                Nodes[results['source_table']].append(results)
            else:
                Nodes[results['source_table']] = [results]
        combined_query = {
            'Nodes': Nodes,
            'Edges': Edges,
            'External Edges': list(externals)
        }
        return JsonResponse(combined_query, safe=False, status=200)

@extend_schema_view(
    get=extend_schema(
        summary="Returns node id/name recommendations depending on the input request typed by the user",
        description="""Returns a dictionary of node id containing a display name, description, and source_table 
            (/node_type) (as dictionary) depending on the input request typed by the user which is sent via string s. 
            (Referring to function orm_queries/typeahead_query)
            """,
        parameters=[
            OpenApiParameter(
                name='s',
                description='typed query string',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            )
        ],
    )
)
class TypeaheadView(generics.GenericAPIView):
    def get(self, request):
        # Get request vars
        s = request.GET.get("s")
        if s is None or s == "":
            return HttpResponseBadRequest('Query string s must be declared and non empty.', status=405)
        # retrieve recommendations using the orm_queries/typeahead_query function
        res = typeahead_query(s)
        # reformat and return as json
        res_filtered = res.values('id', 'description', 'display_name','source_table')
        dict_from_queryset = {item['id']: {'display_name':item['display_name'], 'description':item['description'], 'source_table':item['source_table']} for item in res_filtered}
        return JsonResponse(dict_from_queryset, safe=True)

@extend_schema_view(
    get=extend_schema(
        summary="Returns all possible phenotype variables grouped by their type in JSON format",
        description='Returns all possible phenotype variables grouped by their type in JSON format. '
                    'e.g. {"nonbinaryCategorical":["Happiness on Scale 1 to 10 (happiness_scale_id)"],'
                    '"binaryCategorical":["Disease XY (diseaseXY_id)"], '
                    '"countinous":["BMI (BMI_id)","Height in cm (Height_id)"]}'
    )
)
class GetVariablesView(generics.GenericAPIView):
    def get(self, request):
        def makeGroup(cols):
            ctype = cols[0]
            cnumcat = cols[1]
            if ctype == 'integer' or ctype == 'float' or ctype == 'time':
                return 'continuous'
            elif cnumcat == 2:
                return 'binaryCategorical'
            else:
                return 'nonbinaryCategorical'
        # get subtable of meta data for the variables that are actually in the simulated phenotypes dataset
        phenotypes_meta_filtered_small = phenotypes_meta_filtered[
            [(i in phenotypes_filtered.columns) for i in phenotypes_meta_filtered.index]]
        # calculate the number of categories to differentiate the binary and nonbinary categorical type
        phenotypes_meta_filtered_small['num_cat'] = pd.Series(phenotypes_filtered.apply(np.unique, axis=0).apply(len))
        # annotate each variable with one of the types 'continuous', 'binaryCategorical' and 'nonbinaryCategorical'
        # based on the type variable in the data and the calculated number of categories
        phenotypes_meta_filtered_small['group'] = phenotypes_meta_filtered_small[['type', 'num_cat']].apply(makeGroup,
                                                                                                            axis=1)
        # create identifier annotation which combines the user friendly description with the chris id in brackets
        phenotypes_meta_filtered_small['identifier'] = (
                phenotypes_meta_filtered_small['description'] + ' (' + phenotypes_meta_filtered_small.index + ')')
        # create output dict and return it
        values_dict = phenotypes_meta_filtered_small.groupby('group').apply(lambda dd: list(dd.identifier)).to_dict()
        return JsonResponse(values_dict, safe=True)

# TODO assess if we want a limit for number of categories that color variable c has?
@extend_schema_view(
    get=extend_schema(
        summary="Returns averaged data for the given variables x and y grouped by c in JSON format",
        description="""Returns averaged data for the given variables x (e.g. time) and y (e.g. dosage) in JSON format.
            The optional parameter c (e.g. sex) allows for comparisons between different groups such as males and females.
            """,
        parameters=[
            OpenApiParameter(
                name='x',
                description='variable x',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='y',
                description='variable y',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='c',
                description='colour variable',
                required=False,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            )
        ],
    )
)
class GetDataView(generics.GenericAPIView):
    def get(self, request):
        # Get request vars
        x = request.GET.get("x")
        y = request.GET.get("y")
        c = request.GET.get("c")

        # build result dict in right format
        req_data_dict = {}
        # Variable that checks if any data can be shown based on privacy restriction (more than 5 patients/ values per group)
        show = False
        # Check if x and y var are given -> else throw HttpResponseBadRequest
        if x is None or x == "" or y is None and y == "":
            return HttpResponseBadRequest('Variable x and y must be declared.', status=405)
        # Get var_id from request vars (stored in brackets at the end of the requests var which is built
        # from description + (var_id))
        x_idx = re.findall(r'\(.*?\)',x)[-1].replace('(','').replace(')','')
        y_idx = re.findall(r'\(.*?\)',y)[-1].replace('(','').replace(')','')
        # Check if x and y var are present in our data -> else throw HttpResponseBadRequest
        if x_idx not in phenotypes_filtered.columns or y_idx not in phenotypes_filtered.columns:
            return HttpResponseBadRequest('Variable x and y must be a valid variable of the phenotype data', status=405)
        temp = []
        # Check if c var is given and if so split data by it
        if c is not None and c != "":
            # Get var_id from request var (stored in brackets at the end of the requents var which is built
            # from description + (var_id)
            c_idx = re.findall(r'\(.*?\)',c)[-1].replace('(','').replace(')','')
            # Check if c var is present in our data -> else throw HttpResponseBadRequest
            if c_idx not in phenotypes_filtered.columns:
                return HttpResponseBadRequest('Variable c, if declared, must be a valid variable of the phenotype data', status=405)
            # Make df subset with x, y and c var
            df = pd.DataFrame(phenotypes_filtered[[x_idx, y_idx, c_idx]])
            # Make group by x and c var, aggregate over y using mean (+sort by x var for sorted x-axis in plot)
            # privacy restriction: only return groups with 5 or more values =! NaN
            aggregated_df_mean = df.groupby([x_idx, c_idx]).filter(lambda x:
                x[y_idx].notna().sum() >= 5).groupby([x_idx, c_idx])[y_idx].mean().reset_index().sort_values(x_idx, ascending=True)
            # Add for each color var its own dict containing its label, a color from the color palette and a dict that
            # associates the aggregated values with the corresponding x value (this way we do not have to create NaN
            # values for x positions with no aggregated value present)
            color = 0
            colormap = sns.color_palette("tab10")
            # convert colors to hexcolors for compatibility with vue-chartjs plotting
            color_pal = [mcolors.to_hex(colormap[i]) for i in range(len(colormap))]
            for group_name, group_data in aggregated_df_mean.groupby(c_idx):
                temp.append({
                    "label": group_name,
                    "backgroundColor": color_pal[color],
                    "data": group_data.apply(lambda row: {'x': row[x_idx], 'y': row[y_idx]}, axis=1).tolist()
                })
                color += 1
        # if no color var c is given simply return all data in one group
        else:
            # Make df subset with x and y var
            df = pd.DataFrame(phenotypes_filtered[[x_idx, y_idx]])
            # Make group by x and, aggregate over y using mean (+sort by x var for sorted x-axis in plot)
            # privacy restriction: only return something when there are 5 or more values =! NaN (opposite is very unlikely) # TODO cover and test this corner case (show var?)
            aggregated_df_mean = df.groupby(x_idx).filter(lambda x:
                 x[y_idx].notna().sum() >= 5).groupby(x_idx)[y_idx].mean().reset_index().sort_values(x_idx, ascending=True)
            # Add dict for y axis containing the y label, black as the color and the aggregated values
            temp.append({
                "label": "Whole Population", #TODO rather empty label?
                "backgroundColor": "black",   #TODO change default color?
                "data": aggregated_df_mean[y_idx].tolist()
            })
        # Store unique x_var values
        req_data_dict["labels"] = aggregated_df_mean[x_idx].unique().tolist()
        # Store the y dict/ dicts (if color var was given)
        req_data_dict["datasets"] = temp
        return JsonResponse(req_data_dict, safe=True)

@extend_schema_view(
    get=extend_schema(
        summary="Returns boxplot data for the given variables x and y grouped by c in JSON format",
        description="""Returns boxplot data for the given variables x (e.g. time) and y (e.g. dosage) in JSON format.
            The optional parameter c (e.g. sex) allows for comparisons between different groups such as males and females.
            """,
        parameters=[
            OpenApiParameter(
                name='x',
                description='variable x',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='y',
                description='variable y',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='c',
                description='colour variable',
                required=False,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            )
        ],
    )
)
class GetDataBoxPlotView(generics.GenericAPIView):
    def get(self, request):
        # Get request vars
        x = request.GET.get("x")
        y = request.GET.get("y")
        c = request.GET.get("c")

        # build result dict in right format
        req_data_dict = {}
        # Check if x and y var are given -> else throw HttpResponseBadRequest
        if x is None or x == "" or y is None and y == "":
            return HttpResponseBadRequest('Variable x and y must be declared.', status=405)
        # Get var_id from request vars (stored in brackets at the end of the requents var which is built
        # from description + (var_id)
        x_idx = re.findall(r'\(.*?\)', x)[-1].replace('(', '').replace(')', '')
        y_idx = re.findall(r'\(.*?\)', y)[-1].replace('(', '').replace(')', '')
        # Check if x and y var are present in our data -> else throw HttpResponseBadRequest
        if x_idx not in phenotypes_filtered.columns or y_idx not in phenotypes_filtered.columns:
            return HttpResponseBadRequest('Variable x and y must be a valid variable of the phenotype data',
                                          status=405)
        temp = []
        # Check if c var is given and if so split data by it
        if c is not None and c != "":
            # Get var_id from request var (stored in brackets at the end of the requents var which is built
            # from description + (var_id)
            c_idx = re.findall(r'\(.*?\)', c)[-1].replace('(', '').replace(')', '')
            # Check if c var is present in our data -> else throw HttpResponseBadRequest
            if c_idx not in phenotypes_filtered.columns:
                return HttpResponseBadRequest(
                    'Variable c, if declared, must be a valid variable of the phenotype data', status=405)
            # Make df subset with x, y and c var
            df = pd.DataFrame(phenotypes_filtered[[x_idx, y_idx, c_idx]]).sort_values(x_idx,ascending=True).reset_index()
            # Add for each color var its own dict containing its label, a background and darker border color, some
            # styling parameters and the box plot statistics in a data dictionary.
            color = 0
            colormap = sns.color_palette("tab10")
            # convert colors to hexcolors for compatibility with vue-chartjs plotting
            color_pal = [mcolors.to_hex(colormap[i]) for i in range(len(colormap))]
            bordercolor_pal = [mcolors.to_hex(darken_rgb(colormap[i])) for i in range(len(colormap))]
            for group_name, group_data in df.groupby(c_idx):
                dataset = {
                    'label': group_name,
                    'backgroundColor': color_pal[color],
                    'borderColor': bordercolor_pal[color],
                    'padding': 10,
                    'itemRadius': 0,
                    'borderWidth': 1,
                    # Get stats for each group. If group has less than 5 values (excluding Nan's) only nan stats are
                    # sent for privacy protection.
                    'data': ((group_data.groupby(x_idx).apply(lambda col: {
                            'min': col[y_idx].min(),
                            'q1': col[y_idx].quantile(0.25),
                            'median': col[y_idx].median(),
                            'q3': col[y_idx].quantile(0.75),
                            'max': col[y_idx].max(),
                        }
                        if col[y_idx].notna().sum() >= 5 else {
                            'min': np.nan, 'q1': np.nan, 'median': np.nan,
                            'q3': np.nan, 'max': np.nan}
                        ).tolist()
                    # corner case when all data is empty
                    if not group_data.empty else (
                        {'min': np.nan, 'q1': np.nan, 'median': np.nan,
                         'q3': np.nan, 'max': np.nan}.tolist())
                             )),
                }
                temp.append(dataset)
                color += 1
        # if no color var c is given simply return all data in one group
        else:
            # Make df subset with x and y var
            df = pd.DataFrame(phenotypes_filtered[[x_idx, y_idx]]).sort_values(x_idx,ascending=True)
            # Make a dict containing a background and darker border color, some styling parameters and
            # the box plot statistics in a data dictionary.
            temp_style = {
                "label": "Whole Population",  # TODO rather empty label?
                "backgroundColor": "black",  # TODO change default color?
                'padding': 10,
                'itemRadius': 0,
                'borderWidth': 1,
            }
            # privacy restriction: return values when there are 5 or more values =! NaN
            if df[y_idx].notna().sum() >= 5:
                temp_style['data'] = {
                        'min': float(np.min(df[y_idx])),
                        'q1': float(np.percentile(df[y_idx], 25)),
                        'median': float(np.median(df[y_idx])),
                        'q3': float(np.percentile(df[y_idx], 75)),
                        'max': float(np.min(df[y_idx])),
                    }
            # otherwise only NaNs (very unlikely) # TODO cover and test this corner case (show var?)
            else:
                temp_style['data'] = {
                    'min': np.nan,
                    'q1': np.nan,
                    'median': np.nan,
                    'q3': np.nan,
                    'max': np.nan,
                }
            temp.append(temp_style)
        # Store unique x_var values
        req_data_dict["labels"] = df[x_idx].unique().tolist()
        # Store the y dict/ dicts (if color var was given)
        req_data_dict["datasets"] = temp
        return JsonResponse(req_data_dict, safe=True)

# Unused for now/ #TODO:
def results(request, node_id):
    response = "You're looking at the results of node %s."
    return HttpResponse(response % node_id)
