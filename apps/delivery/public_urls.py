from django.urls import path

from . import views

app_name = "tracking"

urlpatterns = [
    path("", views.PublicTrackingView.as_view(), name="search"),
    path("<str:ref>/", views.PublicTrackingDetailView.as_view(), name="detail"),
]
