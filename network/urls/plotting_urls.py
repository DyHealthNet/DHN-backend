from django.urls import path
import network.views.plotting as views

urlpatterns = [
    path("api/table/", views.GetTableView.as_view(), name="get_table"),
    path("api/plotData/", views.GetDataView.as_view(), name="get_plot_data"),
    path("api/plotDataBarCount/", views.GetDataBarCountView.as_view(), name="get_barcount_data"),
    path("api/plotDataBoxPlot/", views.GetDataBoxPlotView.as_view(), name="get_boxplot_data"),
    path("api/plotDataHeatmap/", views.GetDataHeatmapView.as_view(), name="get_heatmap_data"),
]
