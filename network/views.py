import pandas as pd
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import ListView
from drf_spectacular.utils import extend_schema

from .models import Node, Edge
from django.db.models import F
from django.http import HttpResponseRedirect, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views import generic

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.parsers import JSONParser
from django.contrib.auth.models import User, Group
from rest_framework import viewsets
from rest_framework import permissions
#from network.serializers import UserSerializer, GroupSerializer

# class UserViewSet(viewsets.ModelViewSet):
#     """
#     API endpoint that allows users to be viewed or edited.
#     """
#     queryset = User.objects.all().order_by('-date_joined')
#     serializer_class = UserSerializer
#     permission_classes = [permissions.IsAuthenticated]
# class GroupViewSet(viewsets.ModelViewSet):
#     """
#     API endpoint that allows groups to be viewed or edited.
#     """
#     queryset = Group.objects.all()
#     serializer_class = GroupSerializer
#     permission_classes = [permissions.IsAuthenticated]

class IndexView(generic.ListView):
    template_name = "network/index.html"
    context_object_name = "node_list"
    def get_queryset(self):
        """Return the last five published questions."""
        return Node.objects.order_by("description_text")

class DetailView(generic.DetailView):
    model = Node
    template_name = "network/detail.html"

class Detail_EdgeView(generic.DetailView):
    model = Edge
    template_name = "network/detail_edge.html"


def getVariables(request):
    """
        Returns all possible phenotype variables grouped by their type in JSON format
        e.g. {"discrete":["age_id"], "countinous":["BMI_id","Height_id"]}
    """
    if request.method == 'GET':
        phenotypes_filtered = pd.read_csv(
            '/Users/basti/Documents/Uni/Bioinformatik/Master/2.Semester/MasterPraktikum/Server_data/chris_summary_data/fully_simulated/phenotypes_filtered.csv',
            sep=',', header=0, index_col=0)
        phenotypes_meta_filtered = pd.read_csv(
            '/Users/basti/Documents/Uni/Bioinformatik/Master/2.Semester/MasterPraktikum/Server_data/chris_summary_data/phenotypes/pheno_meta_filtered.tsv',
            sep='\t', header=0, index_col=0)
        # get subtable of meta data for the variables that are actually in the simulated phenotypes dataset
        phenotypes_meta_filtered_small = phenotypes_meta_filtered[
            [(i in phenotypes_filtered.columns) for i in phenotypes_meta_filtered.index]]
        indes_descr_dict = dict(zip(phenotypes_meta_filtered_small['description'], phenotypes_meta_filtered_small.index))
        #serializer = GetVariablesSerializer(snippets, many=True)
        values_dict = phenotypes_meta_filtered_small.groupby('type').apply(lambda dd: list(dd.index)).to_dict()
        return JsonResponse(values_dict, safe=True)
    #response = "You're looking at the results of node %s."
    #return HttpResponse(response % node_id)

def getData(request):
    """
        Returns the data out of the given variables x, y and c in JSON format
        e.g. {"x_var":[25, 48, 21], "y_var":[0,1,0], "col_var": ["male", "female", "female]}
    """
    if request.method == 'GET':
        x = str(request.GET.get("x"))
        y = str(request.GET.get("y"))
        c = str(request.GET.get("c"))
        phenotypes_filtered = pd.read_csv(
            '/Users/basti/Documents/Uni/Bioinformatik/Master/2.Semester/MasterPraktikum/Server_data/chris_summary_data/fully_simulated/phenotypes_filtered.csv',
            sep=',', header=0, index_col=0)
        index = [x, y]
        if c != None:
            index = [x, y, c]
        print(index)
        req_data_dict = phenotypes_filtered[index].to_dict(orient='list')
        return JsonResponse(req_data_dict, safe=True)

# Unused for now/ #TODO:
def results(request, node_id):
    response = "You're looking at the results of node %s."
    return HttpResponse(response % node_id)

def adding_edge(request, node_id, node_id_2):
    return HttpResponse("You're adding an edge from node " % node_id % " to node " % node_id_2)


