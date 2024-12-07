from django.urls import path
import network.views.general as views

urlpatterns = [
    path("api/variables/", views.GetVariablesView.as_view(), name="get_variables"),
]
