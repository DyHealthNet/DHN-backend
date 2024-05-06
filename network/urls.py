from django.urls import path

from . import views

app_name = "network"
urlpatterns = [
    # ex: /network/
    path("", views.index, name="index"),
    # ex: /network/5/
    path("<int:node_id>/", views.detail, name="detail"),
    # ex: /network/5/detail_edge/
    path("<int:edge_id>/detail_edge/", views.detail_edge, name="detail_edge"),

# Unused for now/ #TODO:
    # ex: /network/5/results/
    path("<int:node_id>/results/", views.results, name="results"),
    # ex: /network/5_3/adding_edge/
    path("<int:node_id>_<int:node_id_2>/adding_edge/", views.adding_edge, name="adding_edge"),
]