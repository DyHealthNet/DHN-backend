import pandas as pd
import re
import numpy as np
import matplotlib.colors as mcolors
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiTypes
from .models import Node, Edge, Disorders, Proteins, EffectsProteinDisorder
from .serializers import NodeSerializer, EdgeSerializer
from django.views import generic
from rest_framework import generics
from django.http import HttpResponse, JsonResponse, HttpResponseBadRequest
from itertools import chain

phenotypes_filtered = pd.read_csv(
            '/nfs/scratch/DyHealthNet/chris_summary_data/fully_simulated/phenotypes_filtered.csv',
            sep=',', header=0, index_col=0)
phenotypes_meta_filtered = pd.read_csv(
            '/nfs/scratch/DyHealthNet/chris_summary_data/phenotypes/pheno_meta_filtered.tsv',
            sep='\t', header=0, index_col=0, usecols=['label', 'type', 'description'])


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
        queryset_disorders = Disorders.objects.values('mondo_id',
            'description',
            'xrefs',
            'observation_source'
        )[5:15]
        queryset_protein = Proteins.objects.values('uniprot_id',
            'sequence',
            'gene_entrez_id',
            'description',
            'observation_source'
        )[5:15]
        queryset_edge = EffectsProteinDisorder.objects.values('uniprot',
                                                    'mondo',
                                                    'p_value',
                                                    'adjusted_p_value',
                                                    'effect_size',
                                                    'effect_size_type'
                                                   )[5:15]
        combined_query = {
            'Nodes':{
                'Disorder': list(queryset_disorders),
                'Proteins': list(queryset_protein)
            },
            'Edges':{
                'Disorder_Protein': list(queryset_edge)
            }
        }
        return JsonResponse(combined_query, safe=False, status=200)
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
        x = request.GET.get("x")
        y = request.GET.get("y")
        c = request.GET.get("c")

        req_data_dict = {}
        if x is None or x == "" or y is None and y == "":
            return HttpResponseBadRequest('Variable x and y must be declared.', status=405)
        x_idx = re.findall(r'\(.*?\)',x)[-1].replace('(','').replace(')','')
        y_idx = re.findall(r'\(.*?\)',y)[-1].replace('(','').replace(')','')
        if x_idx not in phenotypes_filtered.columns or y_idx not in phenotypes_filtered.columns:
            return HttpResponseBadRequest('Variable x and y must be a valid variable of the phenotype data', status=405)
        req_data_dict["labels"] = list(phenotypes_filtered[x_idx])
        temp = []
        if c is not None and c != "":
            c_idx = re.findall(r'\(.*?\)',c)[-1].replace('(','').replace(')','')
            if c_idx not in phenotypes_filtered.columns:
                return HttpResponseBadRequest('Variable c, if declared, must be a valid variable of the phenotype data', status=405)
            grouped_data = phenotypes_filtered[y_idx].groupby(phenotypes_filtered[c_idx], dropna=True).agg(list)
            color = 0
            color_pal = list(mcolors.TABLEAU_COLORS.keys()) #TODO change color palatte?
            for i in grouped_data.index:
                temp.append({
                    "label": i,
                    "backgroundColor": color_pal[color],
                    "data": grouped_data[i]
                })
                color += 1
        else:
            temp.append({
                "label": y,
                "backgroundColor": "black",   #TODO change default color?
                "data": list(phenotypes_filtered[y_idx])
            })
        req_data_dict["datasets"] = temp
        return JsonResponse(req_data_dict, safe=True)

# Unused for now/ #TODO:
def results(request, node_id):
    response = "You're looking at the results of node %s."
    return HttpResponse(response % node_id)
