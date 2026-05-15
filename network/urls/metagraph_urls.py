from django.urls import path
import network.views.metagraph as views

urlpatterns = [
    path("api/getCosmograph/", views.GetCosmographView.as_view(), name="get_cosmograph"),
    path("api/getLeidenMetagraph/", views.GetLeidenMetagraphView.as_view(), name="get_leiden_metagraph"),
]
