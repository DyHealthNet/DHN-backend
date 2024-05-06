from .models import Node, Edge
from django.http import HttpResponse, Http404
from django.template import loader
from django.shortcuts import render, get_object_or_404


def index(request):
    node_list = Node.objects.order_by("description_text")[:5]
    context = {"node_list": node_list}
    return render(request, "network/index.html", context)

def detail(request, node_id):
    node = get_object_or_404(Node, pk=node_id)
    return render(request, "network/detail.html", {"node": node})

def detail_edge(request, edge_id):
    edge = get_object_or_404(Edge, pk=edge_id)
    return render(request, "network/detail_edge.html", {"edge": edge})

# Unused for now/ #TODO:
def results(request, node_id):
    response = "You're looking at the results of node %s."
    return HttpResponse(response % node_id)

def adding_edge(request, node_id, node_id_2):
    return HttpResponse("You're adding an edge from node " % node_id % " to node " % node_id_2)


