from django.urls import path

from . import views

app_name = "vreports"

urlpatterns = [
    path("orders/", views.VendorOrdersReportView.as_view(), name="orders"),
    path("wallet/", views.VendorWalletReportView.as_view(), name="wallet"),
    path("settlements/", views.VendorSettlementReportView.as_view(), name="settlements"),
    path("withdrawals/", views.VendorWithdrawalReportView.as_view(), name="withdrawals"),
]
