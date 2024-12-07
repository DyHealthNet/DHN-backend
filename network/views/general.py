import pandas as pd
from django.http import JsonResponse
from django.apps import apps
from rest_framework import generics
from drf_spectacular.utils import extend_schema_view
from network.schemas.general_schemas import *

from network.utils import *

config = apps.get_app_config('network')


@extend_schema_view(
    get=variables_schema
)
class GetVariablesView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        phenotypes_values = list_node_variables(config.PHENO_META, config.PHENOTYPES, type="phenotype")

        # get Protein variables
        protein_values = None
        if not isinstance(config.PROTEINS, type(None)):
            protein_values = list_node_variables(config.PROTEINS_META, config.PROTEINS, type="protein")

        # get Metabolite variables
        metabolite_values = None
        if not isinstance(config.METABOLITES, type(None)):
            metabolite_values = list_node_variables(config.METABOLITES, type="metabolite")

        # combine all data
        existing_values = [x for x in [phenotypes_values, protein_values, metabolite_values] if
                           not isinstance(x, type(None))]
        combined_vals = pd.concat(existing_values, axis=0)
        # create output dict whit type as key and identifier as value and return it
        values_dict = combined_vals.groupby('group').apply(lambda dd: list(dd.identifier)).to_dict()
        return JsonResponse(values_dict, safe=True)
