from django.urls import path

from . import views

app_name = "customer"

urlpatterns = [
    path("dashboard/", views.CustomerDashboardView.as_view(), name="dashboard"),
    path("orders/", views.CustomerOrderListView.as_view(), name="orders"),
    path("history/", views.CustomerHistoryView.as_view(), name="history"),
    path("parcel/", views.CustomerParcelRedirectView.as_view(), name="parcel_redirect"),
]
