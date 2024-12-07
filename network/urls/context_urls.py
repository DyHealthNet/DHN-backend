from django.urls import path
import network.views.context as views

urlpatterns = [
    path("api/retrieveContexts/", views.RetrieveContextsView.as_view(), name="retrieve_contexts"),
    path("api/filterContext", views.FilterUserContext.as_view(), name="filter_context"),
    path("api/createContext", views.CreateUserContext.as_view(), name="create_context"),
    path("api/contextStatus", views.ContextStatusView.as_view(), name="context_status"),
    path("api/deleteContext", views.DeleteUserContext.as_view(), name="delete_context"),
    path("api/singleVariableInfo", views.VariableInfoView.as_view(), name="variable_info"),
]
