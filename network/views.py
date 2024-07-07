import pandas as pd
import re
import numpy as np
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiTypes
from .models import Node, Edge
from .models import Disorders, Proteins, Metabolites, Phenotypes, Genes
from .models import (EffectsProteinDisorder, EffectsProteinProtein, EffectsDisorderDisorder, EffectsProteinPhenotype,
                     EffectsPhenotypePhenotype, EffectsPhenotypeDisorder, EffectsMetabolitePhenotype,
                     EffectsProteinMetabolite, EffectsMetaboliteMetabolite, EffectsMetaboliteDisorder)
from .serializers import NodeSerializer, EdgeSerializer
from django.views import generic
from rest_framework import generics
from django.http import HttpResponse, JsonResponse, HttpResponseBadRequest
from itertools import chain
from .db_queries import *

import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import seaborn as sns


#Nodes = [Disorders, Proteins, Metabolites, Phenotypes, Genes]
Nodes = {'Disorders':Disorders, 'Proteins':Proteins, 'Metabolites':Metabolites, 'Phenotypes': Phenotypes, 'Genes':Genes}
#Edges = [EffectsProteinDisorder, EffectsProteinProtein, EffectsDisorderDisorder, EffectsProteinPhenotype,
 #                    EffectsPhenotypePhenotype, EffectsPhenotypeDisorder, EffectsMetabolitePhenotype,
  #                   EffectsProteinMetabolite, EffectsMetaboliteMetabolite, EffectsMetaboliteDisorder]
Edges = {'EffectsProteinDisorder':EffectsProteinDisorder, 'EffectsProteinProtein':EffectsProteinProtein,
         'EffectsDisorderDisorder':EffectsDisorderDisorder, 'EffectsProteinPhenotype':EffectsProteinPhenotype,
         'EffectsPhenotypePhenotype':EffectsPhenotypePhenotype, 'EffectsPhenotypeDisorder':EffectsPhenotypeDisorder,
         'EffectsMetabolitePhenotype':EffectsMetabolitePhenotype, 'EffectsProteinMetabolite':EffectsProteinMetabolite,
         'EffectsMetaboliteMetabolite':EffectsMetaboliteMetabolite, 'EffectsMetaboliteDisorder':EffectsMetaboliteDisorder}
phenotypes_filtered = pd.read_csv(
            '/nfs/scratch/DyHealthNet/chris_summary_data/fully_simulated/phenotypes_filtered.csv',
            sep=',', header=0, index_col=0)
phenotypes_meta_filtered = pd.read_csv(
            '/nfs/scratch/DyHealthNet/chris_summary_data/phenotypes/pheno_meta_filtered.tsv',
            sep='\t', header=0, index_col=0, usecols=['label', 'type', 'description'])

def rgb_to_hex(rgb):
    return '#{:02x}{:02x}{:02x}'.format(int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))
def darken_rgb(rgb, factor=0.2):
    darkened_rgb = [max(0, min(1, c - factor)) for c in rgb]
    return tuple(darkened_rgb)

class IndexView(generic.ListView):
    template_name = "network/index.html"
    context_object_name = "node_list"
    def get_queryset(self):
        """Return the last five added nodes."""
        return Node.objects.order_by("description_text")

class Detail_NodeView(generic.DetailView):
    model = Node
    template_name = "network/detail.html"

class Detail_EdgeView(generic.DetailView):
    model = Edge
    template_name = "network/detail_edge.html"

@extend_schema_view(
    get=extend_schema(summary="List all nodes", responses={200: NodeSerializer(many=True)}),
    post=extend_schema(summary="Create a new node", responses={201: NodeSerializer}),
)
class NodeListView(generics.ListCreateAPIView):
    queryset = Node.objects.all()
    serializer_class = NodeSerializer

@extend_schema_view(
    get=extend_schema(summary="Retrieve a node", responses={200: NodeSerializer}),
    put=extend_schema(summary="Update a node", responses={200: NodeSerializer}),
    delete=extend_schema(summary="Delete a node", responses={204: None}),
)
class NodeDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Node.objects.all()
    serializer_class = NodeSerializer

@extend_schema_view(
    get=extend_schema(summary="List all edges", responses={200: EdgeSerializer(many=True)}),
    post=extend_schema(summary="Create a new edge", responses={201: EdgeSerializer}),
)
class EdgeListView(generics.ListCreateAPIView):
    queryset = Edge.objects.all()
    serializer_class = EdgeSerializer

@extend_schema_view(
    get=extend_schema(summary="Retrieve an edge", responses={200: EdgeSerializer}),
    put=extend_schema(summary="Update an edge", responses={200: EdgeSerializer}),
    delete=extend_schema(summary="Delete an edge", responses={204: None}),
)
class EdgeDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Edge.objects.all()
    serializer_class = EdgeSerializer

@extend_schema_view(
    get=extend_schema(
        summary="Returns all network edges whilst giving for each node (foreign key) its description",
        description="""Returns all network edges whilst giving for each node (foreign key) its description
            e.g. [{"node1__description_text":"Pro (Metabolite)","node2__description_text":"PC aa C34:4 (Metabolite)",
            "score":"0.1104","effect_size":"-0.6072"},{"node1__description_text":"Pro (Metabolite)",
            "node2__description_text":"Pro (Metabolite)","score":"534.5000","effect_size":"684.0000"}]
            """
    )
)
class GetNetworkView(generics.GenericAPIView):
    def get(self, request):
        # queryset_disorders = Disorders.objects.values('mondo_id',
        #     'description',
        #     'xrefs',
        #     'observation_source'
        # )[5:15]
        # queryset_protein = Proteins.objects.values('uniprot_id',
        #     'sequence',
        #     'gene_entrez_id',
        #     'description',
        #     'observation_source'
        # )[5:15]
        # queryset_edge = EffectsProteinDisorder.objects.values('uniprot',
        #                                             'mondo',
        #                                             'p_value',
        #                                             'adjusted_p_value',
        #                                             'effect_size',
        #                                             'effect_size_type'
        #                                            )[5:15]
        # combined_query = {
        #     'Nodes':{
        #         'Disorder': list(queryset_disorders),
        #         'Proteins': list(queryset_protein)
        #     },
        #     'Edges':{
        #         'Disorder_Protein': list(queryset_edge)
        #     }
        # }
        query = {}
        node_dict = {}
        edge_dict = {}
        for node_name, node_info in Nodes.items():
            node_dict[node_name] = list(node_info.objects.values()[1:3])
        query['Nodes'] = node_dict
        for edge_name, edge_info in Edges.items():
            edge_dict[edge_name] = list(edge_info.objects.values()[1:3])
        query['Edges'] = edge_dict
        #print("query: ")
        #print(query)
        return JsonResponse(query, safe=False, status=200)
    # if request.method == 'GET':
    #     queryset = Edge.objects.values('node1__description_text',
    #         'node2__description_text',
    #         'score',
    #         'effect_size'
    #     )
    #     return JsonResponse(list(queryset), safe=False, status=200)

@extend_schema_view(
    get=extend_schema(
        summary="Returns all possible phenotype variables grouped by their type in JSON format",
        description='Returns all possible phenotype variables grouped by their type in JSON format. e.g. {"discrete":["age_id"], "countinous":["BMI_id","Height_id"]}'
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
        phenotypes_meta_filtered_small['num_cat'] = pd.Series(phenotypes_filtered.apply(np.unique, axis=0).apply(len))
        phenotypes_meta_filtered_small['group'] = phenotypes_meta_filtered_small[['type', 'num_cat']].apply(makeGroup,                                                                                      axis=1)
        phenotypes_meta_filtered_small['identifier'] = phenotypes_meta_filtered_small[
                                                           'description'] + ' (' + phenotypes_meta_filtered_small.index + ')'
        values_dict = phenotypes_meta_filtered_small.groupby('group').apply(lambda dd: list(dd.identifier)).to_dict()
        return JsonResponse(values_dict, safe=True)

@extend_schema_view(
    get=extend_schema(
        summary="Returns the data out of the given variables x (e.g. time), y (dosage) and c(drug) in JSON format",
        description="""Returns the data for the given variables x, y, and c in JSON format. 
            e.g. {"labels": ["18:00","18:30","19:00","19:30","20:00","20:30","21:00"], 
            # x var values "datasets": [{
                "label": "Ibuprofen",
                    "backgroundColor": "pink",
                    "data": [0, 20,40, 65, 70, 75, 80]},{      # y var values of c var group "Iboprofen"
                "label": "Aspirin",
                    "backgroundColor": "blue",
                    "data": [0, 10,20, 30, 40, 45, 50]}]}      # y var values of c var group "Aspirin"
            """,
        parameters=[
            OpenApiParameter(
                name='x',
                description='X parameter',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='y',
                description='Y parameter',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='c',
                description='C parameter',
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
        aggregated_df_mean = pd.DataFrame()
        # Check if x and y var are given -> else throw HttpResponseBadRequest
        if x is None or x == "" or y is None and y == "":
            return HttpResponseBadRequest('Variable x and y must be declared.', status=405)
        # Get var_id from request vars (stored in brackets at the end of the requents var which is built
        # from description + (var_id)
        x_idx = re.findall(r'\(.*?\)',x)[-1].replace('(','').replace(')','')
        y_idx = re.findall(r'\(.*?\)',y)[-1].replace('(','').replace(')','')
        # Check if x and y var are present in our data -> else throw HttpResponseBadRequest
        if x_idx not in phenotypes_filtered.columns or y_idx not in phenotypes_filtered.columns:
            return HttpResponseBadRequest('Variable x and y must be a valid variable of the phenotype data', status=405)
        temp = []
        # Check if c var is given
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
            aggregated_df_mean = df.groupby([x_idx, c_idx])[y_idx].mean().reset_index().sort_values(x_idx, ascending=True)
            # Add for each color var it's own dict containing it's label, a color from the color palette and a dict that
            # associates the aggregated values with the corresponding x value (this way we do not have to create NaN
            # values for x possitions with no aggregated value present)
            color = 0
            #color_pal = ["blue","orange","green","pink","grey"] #list(mcolors.TABLEAU_COLORS.keys()) #TODO change color palatte?
            colormap = sns.color_palette("tab10")
            color_pal = [mcolors.to_hex(colormap[i]) for i in range(len(colormap))]
            for group_name, group_data in aggregated_df_mean.groupby(c_idx):
                temp.append({
                    "label": group_name,
                    "backgroundColor": color_pal[color],
                    "data": group_data.apply(lambda row: {'x': row[x_idx], 'y': row[y_idx]}, axis=1).tolist()
                })
                color += 1
        else:
            # Make df subset with x and y var
            df = pd.DataFrame(phenotypes_filtered[[x_idx, y_idx]])
            # Make group by x and, aggregate over y using mean (+sort by x var for sorted x-axis in plot)
            aggregated_df_mean = df.groupby(x_idx)[y_idx].mean().reset_index().sort_values(x_idx, ascending=True)
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

class GetDataBoxPlotView(generics.GenericAPIView):
    def get(self, request):
        # Get request vars
        x = request.GET.get("x")
        y = request.GET.get("y")
        c = request.GET.get("c")

        # build result dict in right format
        req_data_dict = {}
        df = pd.DataFrame()
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
        # Check if c var is given
        if c is not None and c != "":
            # Get var_id from request var (stored in brackets at the end of the requents var which is built
            # from description + (var_id)
            c_idx = re.findall(r'\(.*?\)', c)[-1].replace('(', '').replace(')', '')
            # Check if c var is present in our data -> else throw HttpResponseBadRequest
            if c_idx not in phenotypes_filtered.columns:
                return HttpResponseBadRequest(
                    'Variable c, if declared, must be a valid variable of the phenotype data', status=405)
            # Make df subset with x, y and c var
            df = pd.DataFrame(phenotypes_filtered[[x_idx, y_idx, c_idx]]).sort_values(x_idx,ascending=True)
            # Make group by x and c var, aggregate over y using mean (+sort by x var for sorted x-axis in plot)
            #aggregated_df_mean = df.groupby([x_idx, c_idx])[y_idx].mean().reset_index().sort_values(x_idx,
            #                                                                                        ascending=True)
            # Add for each color var it's own dict containing it's label, a color from the color palette and a dict that
            # associates the aggregated values with the corresponding x value (this way we do not have to create NaN
            # values for x possitions with no aggregated value present)
            color = 0
            # color_pal = ["blue", "orange", "green", "pink","grey"]  # list(mcolors.TABLEAU_COLORS.keys()) #TODO change color palatte?
            # color_pal = sns.color_palette("tab10")
            colormap = sns.color_palette("tab10")
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
                    'data': ((group_data.groupby(x_idx).apply(lambda col: {
                        'min': col[y_idx].min(),
                        'q1': col[y_idx].quantile(0.25),
                        'median': col[y_idx].median(),
                        'q3': col[y_idx].quantile(0.75),
                        'max': col[y_idx].max(),
                    }).tolist()) if not group_data.empty else (
                        {'min': np.nan, 'q1': np.nan, 'median': np.nan,
                         'q3': np.nan, 'max': np.nan}.tolist())
                             ),
                }
                temp.append(dataset)
                color += 1
        else:
            # Make df subset with x and y var
            df = pd.DataFrame(phenotypes_filtered[[x_idx, y_idx]]).sort_values(x_idx,ascending=True)
            # Make group by x and, aggregate over y using mean (+sort by x var for sorted x-axis in plot)
            #aggregated_df_mean = df.groupby(x_idx)[y_idx].mean().reset_index().sort_values(x_idx, ascending=True)
            # Add dict for y axis containing the y label, black as the color and the aggregated values
            temp.append({
                "label": "Whole Population",  # TODO rather empty label?
                "backgroundColor": "black",  # TODO change default color?
                'padding': 10,
                'itemRadius': 0,
                'borderWidth': 1,
                'data': {
                    'min': np.min(df[y_idx]),
                    'q1': np.percentile(df[y_idx], 25),
                    'median': np.median(df[y_idx]),
                    'q3': np.percentile(df[y_idx], 75),
                    'max': np.min(df[y_idx]),
                }.tolist(),
            })
        # Store unique x_var values
        req_data_dict["labels"] = df[x_idx].unique().tolist()
        # Store the y dict/ dicts (if color var was given)
        req_data_dict["datasets"] = temp
        return JsonResponse(req_data_dict, safe=True)

# Unused for now/ #TODO:
def results(request, node_id):
    response = "You're looking at the results of node %s."
    return HttpResponse(response % node_id)
