from django.urls import path
from . import views

app_name = "network"
urlpatterns = [
    # ex: /network/
    path("", views.IndexView.as_view(), name="index"),
    # ex: /network/node/1/
    path("node/<int:pk>/", views.Detail_NodeView.as_view(), name="detail_node"),
    # ex: /network/edge/1/
    path("edge/<int:pk>/", views.Detail_EdgeView.as_view(), name="detail_edge"),
    # ex: /network/api/variables
    path("api/variables/", views.GetVariablesView.as_view(), name="get_variables"),
    # ex: /network/api/plotData
    path("api/plotData/", views.GetDataView.as_view(), name="get_plot_data"),
    # ex: /network/api/plotDataBoxPlot
    path("api/plotDataBoxPlot/",views.GetDataBoxPlotView.as_view(), name="get_boxplot_data"),
    # ex: /network/api/getNetwork
    path("api/getNetwork/", views.GetNetworkView.as_view(), name="get_network"),
    # ex: /network/api/nodes
    path('api/nodes/', views.NodeListView.as_view(), name="node_list"),
    # ex: /network/api/nodes/1
    path('api/nodes/<int:pk>/', views.NodeDetailView.as_view(), name="node_edit"),
    # ex: /network/api/edges
    path('api/edges/', views.EdgeListView.as_view(), name="edge_list"),
    # ex: /network/api/edges/1
    path('api/edges/<int:pk>/', views.EdgeDetailView.as_view(), name="edge_edit"),


# Unused for now/ #TODO:
    # ex: /network/5/results/
    path("<int:node_id>/results/", views.results, name="results"),
]
