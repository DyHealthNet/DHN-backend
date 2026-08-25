from django.urls import path
import network.views.platform_authentication as views


urlpatterns = [
    path("api/login/", views.PlatformLoginView.as_view(), name="platform-login"),
    path("api/checkstatus/", views.PlatformCheckStatusView.as_view(), name="platform-checkstatus"),
]
