from django.urls import path
import network.views.gemini as views

urlpatterns = [
    path("api/getGeminiLabel/", views.GetGeminiLabelView.as_view(), name="get_gemini_label"),
    path("api/getGeminiClusterLabels/", views.GetGeminiClusterLabelsView.as_view(), name="get_gemini_cluster_labels"),
]
