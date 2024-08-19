from django.urls import path
from . import views

app_name = "network"
urlpatterns = [
    path("api/variables/", views.GetVariablesView.as_view(), name="get_variables"),
    # ex: /network/api/plotData
    path("api/plotData/", views.GetDataView.as_view(), name="get_plot_data"),
    # ex: /network/api/plotDataBoxPlot
    path("api/plotDataBoxPlot/",views.GetDataBoxPlotView.as_view(), name="get_boxplot_data"),
    # ex: /network/api/plotDataHeatmap
    path("api/plotDataHeatmap/", views.GetDataHeatmapView.as_view(), name="get_heatmap_data"),
    # ex: /network/api/getNetwork
    path("api/getNetwork/", views.GetNetworkView.as_view(), name="get_network"),
    # ex: /network/api/getNetwork
    path("api/getTypeaheadResults/", views.TypeaheadView.as_view(), name="get_typeahead"),
]
