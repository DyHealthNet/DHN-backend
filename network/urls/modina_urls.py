from django.urls import path
import network.views.modina as views
from django.apps import apps

config = apps.get_app_config('network')

urlpatterns = [
    path("api/createComparison", views.CreateComparisonView.as_view(data_manager=config.DATA_MANAGER), name="create_comparison"),
    path("api/comparisonStatus", views.ComparisonStatusView.as_view(), name="comparison_status"),
]
