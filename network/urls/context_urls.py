from django.urls import path
import network.views.context as views
from django.apps import apps

config = apps.get_app_config('network')

urlpatterns = [
    path("api/retrieveContexts/", views.RetrieveContextsView.as_view(), name="retrieve_contexts"),
    path("api/createContext", views.CreateUserContext.as_view(data_manager=config.DATA_MANAGER), name="create_context"),
    path("api/filterContext", views.FilterUserContext.as_view(data_manager=config.DATA_MANAGER), name="filter_context"),
    path("api/contextStatus", views.ContextStatusView.as_view(), name="context_status"),
    path("api/deleteContext", views.DeleteUserContext.as_view(), name="delete_context"),
    path("api/singleVariableInfo", views.VariableInfoView.as_view(data_manager=config.DATA_MANAGER), name="variable_info"),
]
