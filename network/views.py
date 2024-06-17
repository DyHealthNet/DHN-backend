import pandas as pd

from .models import Node, Edge
from django.views import generic
from django.http import HttpResponse, JsonResponse

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

def getNetwork(request):
    """
        Returns all network edges whilst giving for each node (foreign key) its description
        e.g. [{"node1__description_text":"Pro (Metabolite)","node2__description_text":"PC aa C34:4 (Metabolite)",
        "score":"0.1104","effect_size":"-0.6072"},{"node1__description_text":"Pro (Metabolite)",
        "node2__description_text":"Pro (Metabolite)","score":"534.5000","effect_size":"684.0000"}]

    """
    if request.method == 'GET':
        queryset = Edge.objects.values('node1__description_text',
            'node2__description_text',
            'score',
            'effect_size'
        )
        return JsonResponse(queryset, safe=False, status=200)

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
        #indes_descr_dict = dict(zip(phenotypes_meta_filtered_small['description'], phenotypes_meta_filtered_small.index))
        values_dict = phenotypes_meta_filtered_small.groupby('type').apply(lambda dd: list(dd.index)).to_dict()
        return JsonResponse(values_dict, safe=True)


def plotData(request):
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