from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from . import views

app_name = "network"
urlpatterns = [
    # ex: /network/
    path("", views.IndexView.as_view(), name="index"),
    # # ex: /network/5/
    path("<int:pk>/", views.DetailView.as_view(), name="detail"),
    # # ex: /network/5/detail_edge/
    path("<int:pk>/detail_edge/", views.Detail_EdgeView.as_view(), name="detail_edge"),
    # # ex: /network/variables
    path("variables/", views.getVariables, name="get_variables"),
    # # # ex: /network/plotData
    path("plotData/", views.getData, name="get_plot_data"),

# Unused for now/ #TODO:
    # ex: /network/5/results/
    path("<int:node_id>/results/", views.results, name="results"),
    # ex: /network/5_3/adding_edge/
    path("<int:node_id>_<int:node_id_2>/adding_edge/", views.adding_edge, name="adding_edge"),
]