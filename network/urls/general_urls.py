from django.urls import path
import network.views.general as views
from django.apps import apps

config = apps.get_app_config('network')

urlpatterns = [
    path("api/variables/", views.GetVariablesView.as_view(data_manager=config.DATA_MANAGER), name="get_variables"),
#TODO is this júnction still neededcalled anywhere
    path("api/colors", views.GetColorView.as_view(), name="get_colors"),
    path("api/networkConfig/", views.GetNetworkConfigView.as_view(), name="get_network_config"),
]
