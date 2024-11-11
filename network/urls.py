from django.urls import path
from . import views

app_name = "network"
urlpatterns = [
    # ex: /network/api/variables
    path("api/variables/", views.GetVariablesView.as_view(), name="get_variables"),
    # ex: /network/api/table
    path("api/table/", views.GetTableView.as_view(), name="get_table"),
    path("api/plotData/", views.GetDataView.as_view(), name="get_plot_data"),
    # ex: /network/api/plotDataBarCount/?x=Food%20frequency:%20Sausages/ham%20(x0fd02)&c=Sex%20(x0_sex)
    path("api/plotDataBarCount/", views.GetDataBarCountView.as_view(), name="get_barcount_data"),
    path("api/plotDataBoxPlot/", views.GetDataBoxPlotView.as_view(), name="get_boxplot_data"),
    # ex: /network/api/plotDataHeatmap/?x=Sex%20(x0_sex)&y=Sniffin%20Stick%20%231%20(Orange)%20(x0ol01)
    path("api/plotDataHeatmap/", views.GetDataHeatmapView.as_view(), name="get_heatmap_data"),
    # ex: /network/api/getNetwork/?q=x0rd09&t=phenotype&l=10
    path("api/getNetwork/", views.GetNetworkView.as_view(), name="get_network"),
    # ex: /network/api/getAllExternals/?q=x0rd09
    path("api/getAllExternals/", views.GetAllExternalsView.as_view(), name="get_all_externals"),
    # ex: /network/api/getTypeaheadResults/?s=Bec
    path("api/getTypeaheadResults/", views.TypeaheadView.as_view(), name="get_typeahead"),
    path("api/filterContext", views.FilterUserContext.as_view(), name="filter_context"),
    path("api/createContext", views.CreateUserContext.as_view(), name="create_context"),
    path("api/contextStatus", views.ContextStatusView.as_view(), name="context_status"),

    path("api/register/", views.register, name="register"),
    path("api/login/", views.login_view, name="login"),
    path("api/logout/", views.logout_view, name="logout"),
    path("api/dashboard/", views.dashboard, name="dashboard"),

    path("api/password_reset/", auth_views.PasswordResetView.as_view(), name="admin_password_reset"),
    path("api/password_reset/done/", auth_views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("api/reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("api/reset/done/", auth_views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),

    #path('accounts/', include('allauth.urls')),
]
