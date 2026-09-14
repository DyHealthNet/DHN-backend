import random

import pandas as pd
from django.http import JsonResponse, HttpResponse
from rest_framework import generics
from drf_spectacular.utils import extend_schema_view

from network.schemas.general_schemas import *
from network.utils.utils import add_cache_header, build_group_values
from network.utils.color_utils import define_context_color, get_palette, rgb_to_hex
from django.conf import settings
from django.core.cache import cache
import logging

logger = logging.getLogger('network')


@extend_schema_view(get=variables_schema)
class GetVariablesView(generics.GenericAPIView):
    """Powers plot/context variable-selection dropdowns (PlotComponent, VariableSelector,
    LayerVariableSelector): just the type-bucketed identifier lists consumers select
    from, plus the layer/subgroup maps needed to group and label them. See
    GetVariableCatalogView (network/views/plotting.py) for the data-overview page's full
    per-variable metadata table - the two no longer share a response shape, only the
    build_group_values() they're built from."""
    data_manager = None

    def get(self, request):
        group_values, layers, layer_subgroups, has_context, context = build_group_values(self.data_manager, request)

        # Context-scoped responses get their own cache entry, capped at 30 days like
        # participants_context_{id} rather than forever -- unlike 'all_variables' this
        # key is per-context, so it's also explicitly invalidated on delete by
        # delete_context_tables() (network/contexts/contexts.py); the 30-day timeout is
        # just a backstop for that.
        cache_key = f'variables_context_{context.context_id}' if has_context else 'all_variables'
        cache_timeout = 3600 * 24 * 30 if has_context else None
        if cache_key not in cache or settings.NO_CACHE:
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
            available_layers = [
                group_name for group_name in layers
                if group_name in group_values and not group_values[group_name].empty
            ]
            if not available_layers:
                available_layers = ["All"]

            values_dict['variableLayers'] = variable_layers
            values_dict['availableLayers'] = available_layers
            values_dict['variableSubLayers'] = variable_sub_layers
            values_dict['layerSubLayers'] = {
                group_name: sorted(layer_subgroups[group_name].keys())
                for group_name in group_values
                if layer_subgroups.get(group_name)
            }

            response = JsonResponse(values_dict, safe=True)
            if not settings.NO_CACHE:
                response = add_cache_header(response, not has_context)
                cache.set(cache_key, response, timeout=cache_timeout)
        else:
            logger.info(f"Cache hit: {cache_key}")
            return cache.get(cache_key)

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
