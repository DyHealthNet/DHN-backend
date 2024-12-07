from django.urls import path
import network.views.authentication as views


urlpatterns = [
    path("api/register/", views.RegisterView.as_view(), name="register"),
    path("api/login/", views.LoginView.as_view(), name="login"),
    path("api/checklogin/", views.CheckLoginStatusView.as_view(), name="checklogin"),
    path("api/logout/", views.LogoutView.as_view(), name="logout"),

    # path("api/password_reset/", auth_views.PasswordResetView.as_view(), name="admin_password_reset"),
    # path("api/password_reset/done/", auth_views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    # path("api/reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    # path("api/reset/done/", auth_views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
]
