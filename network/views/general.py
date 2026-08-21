import random

import pandas as pd
from django.http import JsonResponse, HttpResponse
from rest_framework import generics
from drf_spectacular.utils import extend_schema_view

from network.utils.db_utils import get_context
from network.schemas.general_schemas import *
from network.utils.utils import list_group_variables, add_cache_header
from network.utils.color_utils import define_context_color, get_palette, rgb_to_hex
from django.conf import settings
from django.core.cache import cache
import logging

logger = logging.getLogger('network')


@extend_schema_view(get=variables_schema)
class GetVariablesView(generics.GenericAPIView):
    data_manager = None

    def get(self, request):
        layers, group_data, group_meta, layer_subgroups = self.data_manager.get_df_copy(
            ['layers', 'group_data', 'group_meta', 'layer_subgroups']
        )
        has_context = request.GET.get('contextValue') and request.user.is_authenticated

        context_layers = None
        context_variables = None
        if has_context:
            context = get_context(request.user, request.GET.get('contextValue'))
            context_layers = context.params['layers']
            context_variables = context.params.get('variables')

        group_values = {}
        for group_name in layers:
            data = group_data.get(group_name)
            meta = group_meta.get(group_name)
            if data is None or meta is None:
                continue
            if context_layers is not None and group_name not in context_layers:
                continue
            values = list_group_variables(meta, data)
            if context_variables:
                values = values[values['identifier'].isin(context_variables)]
            group_values[group_name] = values

        if 'all_variables' not in cache or settings.NO_CACHE or has_context:
            # create output dict with type as key and identifier as value, plus an explicit
            # per-variable layer map so consumers don't need to infer layer from the identifier
            variable_layers = {}
            variable_sub_layers = {}
            for group_name, values in group_values.items():
                for identifier, subgroup in zip(values['identifier'], values['subgroup']):
                    variable_layers[identifier] = group_name
                    if pd.notna(subgroup):
                        variable_sub_layers[identifier] = subgroup

            if group_values:
                combined_vals = pd.concat(group_values.values(), axis=0)
                values_dict = combined_vals.groupby('group').apply(lambda dd: list(dd.identifier)).to_dict()
            else:
                values_dict = {}

            # ensure that all keys are present even if they are empty
            for key in ['binaryCategorical', 'continuous', 'nonbinaryCategorical']:
                if key not in values_dict:
                    values_dict[key] = []

            values_dict['variableLayers'] = variable_layers
            values_dict['availableLayers'] = list(group_values.keys())
            values_dict['variableSubLayers'] = variable_sub_layers
            values_dict['layerSubLayers'] = {
                group_name: sorted(layer_subgroups[group_name].keys())
                for group_name in group_values
                if layer_subgroups.get(group_name)
            }

            response = JsonResponse(values_dict, safe=True)
            if not settings.NO_CACHE and not has_context:
                response = add_cache_header(response, not has_context)
                cache.set('all_variables', response, timeout=None)
        else:
            logger.info(f"Cache hit: all_variables")
            return cache.get('all_variables')

        response = add_cache_header(response, not has_context)
        return response

#TODO is this júnction still needed
class GetColorView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        if request.GET.get('base'):
            colors = [define_context_color(value=request.GET.get('value'), base_hue=request.GET.get('base'))]

        elif request.GET.get('palette'):
            colors = get_palette(request.GET.get('palette'), n_colors=5)
            colors = [rgb_to_hex(col) for col in colors]
            colors = {'colors': colors}
            return JsonResponse(colors)
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


class GetNetworkConfigView(generics.GenericAPIView):
    """Exposes read-only network-computation config (currently just the multiple-
    testing correction used to precompute the static network's edges) so the
    frontend can show what was actually used instead of an editable toggle that
    doesn't affect anything."""
    @staticmethod
    def get(request):
        return JsonResponse({"correction": settings.MULTIPLE_TESTING})
