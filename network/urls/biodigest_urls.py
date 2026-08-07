from django.urls import path
import network.views.biodigest_scoring as views

urlpatterns = [
    path("api/scoreClustering", views.ScoreClusteringView.as_view(), name="score_clustering"),
    path("api/scoreClusteringStatus", views.ScoreClusteringStatusView.as_view(), name="score_clustering_status"),
]
