from django.urls import path

from . import views

app_name = "parcel"

urlpatterns = [
    path("send/", views.ParcelRequestView.as_view(), name="send"),
    path("history/", views.ParcelListView.as_view(), name="history"),
    path("paystack/callback/", views.parcel_paystack_callback, name="paystack_callback"),
    path("manager/", views.ManagerParcelListView.as_view(), name="manager_list"),
    path("manager/<str:ref>/", views.ManagerParcelDetailView.as_view(), name="manager_detail"),
    path("manager/<str:ref>/quote/", views.ManagerQuoteParcelView.as_view(), name="manager_quote"),
    path("manager/<str:ref>/assign/", views.ManagerAssignParcelAgentView.as_view(), name="manager_assign"),
    path("manager/<str:ref>/override/delivered/", views.ManagerParcelOverrideView.as_view(action_type="delivered"), name="manager_delivered"),
    path("manager/<str:ref>/override/failed/", views.ManagerParcelOverrideView.as_view(action_type="failed"), name="manager_failed"),
    path("<str:ref>/", views.ParcelDetailView.as_view(), name="detail"),
    path("<str:ref>/accept/", views.ParcelAcceptQuoteView.as_view(), name="accept_quote"),
    path("<str:ref>/cancel/", views.ParcelCancelView.as_view(), name="cancel"),
]
