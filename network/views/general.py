import pandas as pd
from django.http import JsonResponse
from django.apps import apps
from rest_framework import generics
from drf_spectacular.utils import extend_schema_view

from network.utils.db_utils import get_context
from network.schemas.general_schemas import *
from network.utils.utils import list_node_variables

config = apps.get_app_config('network')


@extend_schema_view(
    get=variables_schema
)
class GetVariablesView(generics.GenericAPIView):

    @staticmethod
    def get(request):
        def get_node_variables(meta, data, variable_type):
            return list_node_variables(meta, data, type=variable_type) if data is not None else None

        phenotypes_values = get_node_variables(config.PHENO_META, config.PHENOTYPES, "phenotype")
        protein_values = get_node_variables(config.PROTEINS_META, config.PROTEINS, "protein")
        metabolite_values = get_node_variables(config.METABOLITES, config.METABOLITES, "metabolite")

        if request.GET.get('contextValue') and request.user.is_authenticated:
            context = get_context(request.user, request.GET.get('contextValue'))
            phenotypes_values = phenotypes_values if 'phenomics' in context.params['layers'] else None
            protein_values = protein_values if 'proteomics' in context.params['layers'] else None
            metabolite_values = metabolite_values if 'metabolomics' in context.params['layers'] else None

        # Combine all data
        existing_values = [x for x in [phenotypes_values, protein_values, metabolite_values] if x is not None]

        # create output dict whit type as key and identifier as value and return it
        combined_vals = pd.concat(existing_values, axis=0)
        values_dict = combined_vals.groupby('group').apply(lambda dd: list(dd.identifier)).to_dict()
        return JsonResponse(values_dict, safe=True)
