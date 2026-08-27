from django.urls import include, path

from . import views

app_name = "vendor"

urlpatterns = [
    path("api/banks/", views.api_banks, name="api_banks"),
    path("api/verify-bank/", views.api_verify_bank, name="api_verify_bank"),
    path("dashboard/", views.VendorDashboardView.as_view(), name="dashboard"),
    path("inventory/", views.VendorProductListView.as_view(), name="inventory"),
    path("inventory/add/", views.VendorProductCreateView.as_view(), name="inventory_add"),
    path("orders/", views.VendorOrderListView.as_view(), name="orders"),
    path("orders/create/", views.VendorOrderCreateView.as_view(), name="order_create"),
    path("orders/<str:ref>/", views.VendorOrderDetailView.as_view(), name="order_detail"),
    path("wallet/", views.VendorWalletView.as_view(), name="wallet"),
    path("wallet/withdraw/", views.VendorWithdrawalRequestView.as_view(), name="withdraw"),
    path("wallet/withdrawals/", views.VendorWithdrawalHistoryView.as_view(), name="withdrawals"),
    path("profile/", views.VendorProfileView.as_view(), name="profile"),
    path("profile/bank/", views.VendorBankAccountView.as_view(), name="bank"),
    path("manager/vendors/", views.ManagerVendorListView.as_view(), name="manager_vendors"),
    path("manager/product/<int:product_id>/", views.ManagerProductDetailView.as_view(), name="manager_product_detail"),
    path("manager/product/<int:product_id>/delete/", views.ManagerProductDeleteView.as_view(), name="manager_product_delete"),
    path("manager/vendors/<int:vendor_id>/inventory/", views.ManagerVendorProductsView.as_view(), name="manager_vendor_inventory"),
    path("manager/vendors/<int:vendor_id>/wallet/", views.ManagerVendorWalletView.as_view(), name="manager_vendor_wallet"),
    path("manager/vendors/<int:vendor_id>/wallet/deduct/", views.ManagerDeductWalletView.as_view(), name="manager_deduct_wallet"),
    path("manager/vendor-orders/", views.ManagerVendorOrderListView.as_view(), name="manager_vendor_orders"),
    path("manager/vendor-orders/create/", views.ManagerCreateVendorOrderView.as_view(), name="manager_vendor_order_create"),
    path("manager/vendor-orders/<str:ref>/", views.ManagerVendorOrderDetailView.as_view(), name="manager_vendor_order_detail"),
    path("manager/vendor-orders/<str:ref>/process/", views.ManagerProcessOrderView.as_view(), name="manager_order_process"),
    path("manager/vendor-orders/<str:ref>/approve/", views.ManagerApproveOrderView.as_view(), name="manager_order_approve"),
    path("manager/vendor-orders/<str:ref>/assign/", views.ManagerAssignAgentView.as_view(), name="manager_order_assign"),
    path("manager/vendor-orders/<str:ref>/dispatch/", views.ManagerDispatchOrderView.as_view(), name="manager_order_dispatch"),
    path("manager/vendor-orders/<str:ref>/cancel/", views.ManagerCancelOrderView.as_view(), name="manager_order_cancel"),
    path("manager/withdrawals/", views.ManagerWithdrawalListView.as_view(), name="manager_withdrawals"),
    path("manager/withdrawals/<int:pk>/approve/", views.ManagerApproveWithdrawalView.as_view(), name="manager_withdrawal_approve"),
    path("manager/withdrawals/<int:pk>/reject/", views.ManagerRejectWithdrawalView.as_view(), name="manager_withdrawal_reject"),
]
