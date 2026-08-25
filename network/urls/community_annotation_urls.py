from django.urls import path
import network.views.community_annotation as views

urlpatterns = [
    path("api/runCommunityAnnotation", views.RunCommunityAnnotationView.as_view(), name="run_community_annotation"),
    path("api/runCommunityAnnotationStatus", views.CommunityAnnotationStatusView.as_view(), name="run_community_annotation_status"),
]
