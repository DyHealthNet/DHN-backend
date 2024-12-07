from django.urls import path
import network.views.network as views

urlpatterns = [
    path("api/getNetwork/", views.GetNetworkView.as_view(), name="get_network"),
    path("api/getAllExternals/", views.GetAllExternalsView.as_view(), name="get_all_externals"),
    path("api/getTypeaheadResults/", views.TypeaheadView.as_view(), name="get_typeahead"),
]
