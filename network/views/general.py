import random

import pandas as pd
from django.http import JsonResponse, HttpResponse
from rest_framework import generics
from drf_spectacular.utils import extend_schema_view

from network.utils.db_utils import get_context
from network.schemas.general_schemas import *
from network.utils.utils import list_node_variables
from network.utils.color_utils import define_context_color
from django.conf import settings
from django.core.cache import cache
import logging

logger = logging.getLogger('network')

@extend_schema_view(get=variables_schema)
class GetVariablesView(generics.GenericAPIView):
    data_manager = None

    def get(self, request):
        pheno_meta, phenotypes = self.data_manager.get_df_copy(['pheno_meta', 'phenotypes'])
        proteins_meta, proteins = self.data_manager.get_df_copy(['proteins_meta', 'proteins'])
        metabolites = self.data_manager.get_df_copy('metabolites')

        def get_node_variables(meta, data, variable_type):
            return list_node_variables(meta, data, type=variable_type) if data is not None else None

        phenotypes_values = get_node_variables(pheno_meta, phenotypes, "phenotype")
        protein_values = get_node_variables(proteins_meta, proteins, "protein")
        metabolite_values = get_node_variables(metabolites, metabolites, "metabolite")

        if request.GET.get('contextValue') and request.user.is_authenticated:
            context = get_context(request.user, request.GET.get('contextValue'))
            phenotypes_values = phenotypes_values if 'phenomics' in context.params['layers'] else None
            protein_values = protein_values if 'proteomics' in context.params['layers'] else None
            metabolite_values = metabolite_values if 'metabolomics' in context.params['layers'] else None

        if 'all_variables' not in cache or settings.NO_CACHE:
            # Combine all data
            existing_values = [x for x in [phenotypes_values, protein_values, metabolite_values] if x is not None]

            # create output dict whit type as key and identifier as value and return it
            combined_vals = pd.concat(existing_values, axis=0)
            values_dict = combined_vals.groupby('group').apply(lambda dd: list(dd.identifier)).to_dict()
            if not settings.NO_CACHE:
                cache.set('all_variables', values_dict, timeout=None)
        else:
            logger.info(f"Cache hit: all_variables")
            values_dict = cache.get('all_variables')

        response = JsonResponse(values_dict, safe=True)
        keep_alive = 3600 * 24 * 7
        response['Cache-Control'] = f'max-age={keep_alive}, public'
        return response


class GetColorView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        if request.GET.get('base'):
            colors = [define_context_color(value=request.GET.get('value'), base_hue=request.GET.get('base'))]
        else:
            colors = []
            for i in range(5):
                colors.append(define_context_color(value=i))

        base = """
        <html>
            <head>
                <title>Color</title>
                <style>
                    .color-blob {
                        display: inline-block;
                        width: 20px;
                        height: 20px;
                        border-radius: 50%; /* Makes it a circle, remove this for a square */
                        margin-left: 10px;
                    }
                </style>
            </head>
            <body>
        """
        color_html = ""

        for i in range(5):
            color_html += f"""
            <p>Hue: {colors[i]['hue']}</p>
            <p>Base color: {colors[i]['color']} <span class="color-blob" style="background-color: {colors[i]['color']};"></span></p>
            <p>Light variant color: {colors[i]['lightVariant']} <span class="color-blob" style="background-color: {colors[i]['lightVariant']};"></span></p>
            <p>Dark variant color: {colors[i]['darkVariant']} <span class="color-blob" style="background-color: {colors[i]['darkVariant']};"></span></p>
            """

        end = """
        </body>
        </html>
        """

        # return html
        return HttpResponse(base + color_html + end)
