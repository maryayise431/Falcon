from django.urls import path

from . import views

app_name = "agent"

urlpatterns = [
    path("dashboard/", views.DeliveryAgentDashboardView.as_view(), name="dashboard"),
    path("inventory/", views.AgentInventoryView.as_view(), name="inventory"),
    path("deliveries/", views.AgentDeliveryListView.as_view(), name="deliveries"),
    path("deliveries/<str:ref>/", views.AgentDeliveryDetailView.as_view(), name="agent_detail"),
    path("deliveries/<str:ref>/pickup/", views.AgentPickupView.as_view(), name="pickup"),
    path("deliveries/<str:ref>/delivered/", views.AgentMarkDeliveredView.as_view(), name="mark_delivered"),
    path("deliveries/<str:ref>/failed/", views.AgentMarkFailedView.as_view(), name="mark_failed"),
    path("vendor-orders/", views.AgentVendorOrdersView.as_view(), name="vendor_orders"),
    path("reports/", views.AgentReportsView.as_view(), name="reports"),
]
