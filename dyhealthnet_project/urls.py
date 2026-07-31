"""
URL configuration for dyhealthnet_project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
# Added for OpenAPI
from drf_spectacular.views import SpectacularAPIView
from drf_spectacular.views import SpectacularRedocView, SpectacularSwaggerView

from network import views


urlpatterns = [
    path("network/", include('network.urls.network_urls')),
    path("metagraph/", include('network.urls.metagraph_urls')),
    path("gemini/", include('network.urls.gemini_urls')),
    path("context/", include('network.urls.context_urls')),
    path("modina/", include('network.urls.modina_urls')),
    path("plotting/", include('network.urls.plotting_urls')),
    path("auth/", include('network.urls.authentication_urls')),
    path("general/", include('network.urls.general_urls')),

    path("admin/", admin.site.urls),
    path('auth/api/', include('allauth.urls')),
    # Added for OpenAPI
    path("api/schema/", SpectacularAPIView.as_view(api_version='v1'), name="schema"),
    # Swagger UI:
    path("api/schema/swagger-ui/", SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    # Redoc UI:
    #path('api/schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]
