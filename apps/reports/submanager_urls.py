from django.urls import path

from . import views

app_name = "submanager"

urlpatterns = [
    path("dashboard/", views.SubManagerDashboardView.as_view(), name="dashboard"),
]
