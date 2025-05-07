from django.urls import path
import network.views.plotting as views
from django.apps import apps

config = apps.get_app_config('network')

urlpatterns = [
    path("api/table/", views.GetTableView.as_view(data_manager=config.DATA_MANAGER), name="get_table"),
    path("api/plotDataLine/", views.GetDataLinePlotView.as_view(data_manager=config.DATA_MANAGER), name="get_plot_data"),
    path("api/plotDataDensity/", views.GetDataDensityPlotView.as_view(data_manager=config.DATA_MANAGER), name="get_density_data"),
    path("api/plotDataBarCount/", views.GetDataBarCountView.as_view(data_manager=config.DATA_MANAGER), name="get_barcount_data"),
    path("api/plotDataBoxPlot/", views.GetDataBoxPlotView.as_view(data_manager=config.DATA_MANAGER), name="get_boxplot_data"),
    path("api/plotDataHeatmap/", views.GetDataHeatmapView.as_view(data_manager=config.DATA_MANAGER), name="get_heatmap_data"),
    path("api/plotDataPieCount/", views.GetDataPieCountView.as_view(data_manager=config.DATA_MANAGER), name="get_piecount_data"),
]
