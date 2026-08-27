from django.urls import path

from . import views

app_name = "marketplace"

urlpatterns = [
    path("", views.MarketplaceHomeView.as_view(), name="home"),
    path("product/<slug:slug>/", views.ProductDetailView.as_view(), name="product_detail"),
    path("cart/", views.CartView.as_view(), name="cart"),
    path("checkout/", views.CheckoutView.as_view(), name="checkout"),
    path("order/<str:ref>/", views.OrderConfirmationView.as_view(), name="order_confirmation"),
    path("order/<str:ref>/cancel/", views.CancelOrderView.as_view(), name="cancel_order"),
    path("order/<str:ref>/pay/", views.CustomerPayOrderView.as_view(), name="customer_pay_order"),
    path("paystack/callback/", views.paystack_callback, name="paystack_callback"),
    path("manager/products/", views.ManagerProductListView.as_view(), name="manager_products"),
    path("manager/products/create/", views.ManagerProductCreateView.as_view(), name="manager_product_create"),
    path("manager/products/<int:pk>/edit/", views.ManagerProductUpdateView.as_view(), name="manager_product_edit"),
    path("manager/products/<int:pk>/delete/", views.ManagerProductDeleteView.as_view(), name="manager_product_delete"),
    path("manager/products/<int:pk>/publish/", views.ManagerProductPublishView.as_view(), name="manager_product_publish"),
    path("manager/orders/", views.ManagerOrdersView.as_view(), name="manager_orders"),
    path("manager/orders/<str:ref>/", views.ManagerOrderDetailView.as_view(), name="manager_order_detail"),
    path("manager/orders/<str:ref>/status/", views.ManagerOrderStatusView.as_view(), name="manager_order_status"),
    path("manager/orders/<str:ref>/delivery-fee/", views.ManagerSetDeliveryFeeView.as_view(), name="manager_set_delivery_fee"),
    path("manager/orders/<str:ref>/assign-agent/", views.ManagerAssignMarketplaceAgentView.as_view(), name="manager_assign_agent"),
    path("manager/orders/<str:ref>/dispatch/", views.ManagerDispatchMarketplaceView.as_view(), name="manager_dispatch"),
]
