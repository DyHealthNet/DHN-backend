from django.urls import path
from . import views

app_name = "network"
urlpatterns = [
    # ex: /network/api/variables
    path("api/variables/", views.GetVariablesView.as_view(), name="get_variables"),
    # ex: /network/api/plotDataBoxPlot/?x=Pacemaker/implantable%20defibrillator%20(x0af11)&y=Sniffin%20Stick%20%231%20(Orange)%20(x0ol01)&c=Sex%20(x0_sex)
    path("api/plotData/", views.GetDataView.as_view(), name="get_plot_data"),
    # ex: /network/api/plotDataBarCount/?x=Food%20frequency:%20Sausages/ham%20(x0fd02)&c=Sex%20(x0_sex)
    path("api/plotDataBarCount/", views.GetDataBarCountView.as_view(), name="get_barcount_data"),
    # ex: /network/api/plotDataBoxPlot/?x=Time%20of%201st%20BP%20measurement,%20OMRON%20(x0bp08a)&y=Sniffin%20Stick%20%231%20(Orange)%20(x0ol01)&c=Sex%20(x0_sex)
    path("api/plotDataBoxPlot/",views.GetDataBoxPlotView.as_view(), name="get_boxplot_data"),
    # ex: /network/api/plotDataHeatmap/?x=Sex%20(x0_sex)&y=Sniffin%20Stick%20%231%20(Orange)%20(x0ol01)
    path("api/plotDataHeatmap/", views.GetDataHeatmapView.as_view(), name="get_heatmap_data"),
    # ex: /network/api/getNetwork/?q=x0rd09&t=phenotype&l=10
    path("api/getNetwork/", views.GetNetworkView.as_view(), name="get_network"),
    # ex: /network/api/getTypeaheadResults/?s=Bec
    path("api/getTypeaheadResults/", views.TypeaheadView.as_view(), name="get_typeahead"),
]
