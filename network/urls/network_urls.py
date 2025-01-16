from django.urls import path
import network.views.network as views

urlpatterns = [
    path("api/getNetwork/", views.GetNetworkView.as_view(), name="get_network"),
    path("api/getNetworkContext/", views.GetNetworkContextView.as_view(), name="get_network_context"),
    path("api/getGroupNetwork/", views.GetGroupNetworkView.as_view(), name="get_group_network"),
    path("api/getGroupNetworkContext/", views.GetGroupNetworkContextView.as_view(), name="get_group_network_context"),
    path("api/getAllExternals/", views.GetAllExternalsView.as_view(), name="get_all_externals"),
    path("api/getTypeaheadResults/", views.TypeaheadView.as_view(), name="get_typeahead"),
]
