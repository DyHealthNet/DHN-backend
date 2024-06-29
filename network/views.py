import pandas as pd
import re
import numpy as np
import matplotlib.colors as mcolors


from .models import Node, Edge, Disorders, Proteins, EffectsProteinDisorder
from django.views import generic
from django.http import HttpResponse, JsonResponse, HttpResponseBadRequest

#from itertools import chain

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

def getVariables(request):
    """
        Returns all possible phenotype variables grouped by their type in JSON format
        e.g. {"discrete":["age_id"], "countinous":["BMI_id","Height_id"]}
    """
    if request.method == 'GET':
        def makeGroup(cols):
            ctype = cols[0]
            cnumcat = cols[1]
            if ctype == 'integer' or ctype == 'float' or ctype == 'time':
                return 'continuous'
            elif cnumcat == 2:
                return 'binaryCategorical'
            else:
                return 'nonbinaryCategorical'
        # get sub-table of meta data for the variables that are actually in the simulated phenotypes dataset
        phenotypes_meta_filtered_small = phenotypes_meta_filtered[
            [(i in phenotypes_filtered.columns) for i in phenotypes_meta_filtered.index]]
        phenotypes_meta_filtered_small['num_cat'] = pd.Series(phenotypes_filtered.apply(np.unique, axis=0).apply(len))
        phenotypes_meta_filtered_small['group'] = phenotypes_meta_filtered_small[['type', 'num_cat']].apply(makeGroup,
                                                                                                            axis=1)
        phenotypes_meta_filtered_small['identifier'] = phenotypes_meta_filtered_small[
                                                           'description'] + ' (' + phenotypes_meta_filtered_small.index + ')'
        values_dict = phenotypes_meta_filtered_small.groupby('group').apply(lambda dd: list(dd.identifier)).to_dict()
        return JsonResponse(values_dict, safe=True)


def plotData(request):
    """
        Returns the data out of the given variables x, y and c in JSON format
        e.g. {"x_var":[25, 48, 21], "y_var":[0,1,0], "col_var": ["male", "female", "female]}
    """
    if request.method == 'GET':
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

def adding_edge(request, node_id, node_id_2):
    return HttpResponse("You're adding an edge from node " % node_id % " to node " % node_id_2)